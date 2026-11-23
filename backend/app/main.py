import asyncio
import json
import os
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.models import (
    ComparativeAnalysisRequest,
    ComparativeAnalysisResponse,
    DockingRunRequest,
    DockingRunResponse,
    LigandPrepareRequest,
    LigandPrepareResponse,
    PocketDetectRequest,
    PocketDetectResponse,
    ProteinInspectResponse,
    ProteinPrepareRequest,
    ProteinPrepareResponse,
    RedockValidationRequest,
    RedockValidationResponse,
)
from app.utils import job_store

# Concurrency limiter to protect server RAM/CPU when many students dock simultaneously
MAX_CONCURRENT_DOCKS = int(os.getenv("MAX_CONCURRENT_DOCKS", "1"))
DOCKING_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOCKS)
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "3600"))  # 1 hour
BACKEND_DIR = Path(__file__).resolve().parent.parent


def _run_isolated_worker(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute scientific task in a short-lived subprocess so RAM returns to OS immediately."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        json.dump(payload, tmp)
        in_path = Path(tmp.name)
    out_path = Path(in_path.as_posix() + ".out.json")
    try:
        res = subprocess.run(
            [sys.executable, "-m", "app.worker", action, str(in_path)],
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
            timeout=240,
        )
        if res.returncode != 0:
            err = (res.stderr or res.stdout or f"Worker failed (exit code {res.returncode})").strip()
            if err.startswith("NOT_FOUND:"):
                raise FileNotFoundError(err[len("NOT_FOUND:"):].strip())
            if err.startswith("BAD_REQUEST:"):
                raise ValueError(err[len("BAD_REQUEST:"):].strip())
            if err.startswith("SERVER_ERROR:"):
                raise RuntimeError(err[len("SERVER_ERROR:"):].strip())
            raise RuntimeError(err)
        return json.loads(out_path.read_text(encoding="utf-8"))
    finally:
        in_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)


async def _periodic_session_cleanup():
    while True:
        try:
            job_store.cleanup_old_sessions(SESSION_TTL_SECONDS)
        except Exception:
            pass
        await asyncio.sleep(900)  # check every 15 minutes


@asynccontextmanager
async def lifespan(_app: FastAPI):
    job_store.cleanup_old_sessions(SESSION_TTL_SECONDS)
    cleanup_task = asyncio.create_task(_periodic_session_cleanup())
    try:
        yield
    finally:
        cleanup_task.cancel()


app = FastAPI(
    title="PocketLab API",
    description="All-in-One Molecular Docking, Interactive Preparation & Native-vs-Query Comparative Analysis API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class FetchPdbRequest(BaseModel):
    pdb_id: str


class PubChemLookupRequest(BaseModel):
    query: str


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "PocketLab"}


@app.post("/api/protein/fetch", response_model=ProteinInspectResponse)
async def fetch_protein(req: FetchPdbRequest):
    try:
        clean_id = req.pdb_id.strip().upper()
        if len(clean_id) != 4 or not clean_id.isalnum():
            raise ValueError(f"Invalid PDB ID '{req.pdb_id}'. Expected a 4-character alphanumeric code.")
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(f"https://files.rcsb.org/download/{clean_id}.pdb")
            if resp.status_code == 200:
                return await run_in_threadpool(
                    _run_isolated_worker, "protein_inspect", {"pdb_text": resp.text, "pdb_id": clean_id}
                )
            cif_resp = await client.get(f"https://files.rcsb.org/download/{clean_id}.cif")
            if cif_resp.status_code == 200:
                return await run_in_threadpool(
                    _run_isolated_worker, "protein_upload", {"raw_text": cif_resp.text, "is_cif": True}
                )
            raise ValueError(f"Could not fetch PDB or mmCIF for '{clean_id}' from RCSB.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch PDB: {e}")


@app.post("/api/protein/upload", response_model=ProteinInspectResponse)
async def upload_protein(file: UploadFile = File(...)):
    try:
        raw_bytes = await file.read()
        raw_text = raw_bytes.decode("utf-8", errors="ignore")
        fname = (file.filename or "").lower()
        is_cif = fname.endswith((".cif", ".mmcif")) or "_atom_site." in raw_text or raw_text.lstrip().startswith("data_")
        return await run_in_threadpool(
            _run_isolated_worker, "protein_upload", {"raw_text": raw_text, "is_cif": is_cif}
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse uploaded structure: {e}")


@app.post("/api/protein/prepare", response_model=ProteinPrepareResponse)
async def prepare_protein(req: ProteinPrepareRequest):
    try:
        return await run_in_threadpool(_run_isolated_worker, "protein_prepare", req.model_dump())
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Protein preparation failed: {e}")


@app.post("/api/ligand/pubchem")
async def lookup_pubchem(req: PubChemLookupRequest):
    try:
        q = req.query.strip()
        if not q:
            raise ValueError("Please enter a compound name or PubChem CID.")
        url = (
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{q}/property/CanonicalSMILES,Title/JSON"
            if q.isdigit()
            else f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{q}/property/CanonicalSMILES,Title/JSON"
        )
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise ValueError(f"Compound '{q}' not found on PubChem.")
            props = resp.json()["PropertyTable"]["Properties"][0]
            smiles = props.get("CanonicalSMILES") or props.get("ConnectivitySMILES")
            if not smiles:
                raise ValueError(f"No SMILES returned from PubChem for '{q}'.")
            return {"smiles": smiles, "name": props.get("Title") or q}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PubChem lookup failed: {e}")


@app.post("/api/ligand/prepare", response_model=LigandPrepareResponse)
async def prepare_ligand(req: LigandPrepareRequest):
    try:
        return await run_in_threadpool(_run_isolated_worker, "ligand_prepare", req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ligand preparation failed: {e}")


@app.post("/api/pocket/detect", response_model=PocketDetectResponse)
async def detect_pockets(req: PocketDetectRequest):
    try:
        return await run_in_threadpool(_run_isolated_worker, "pocket_detect", req.model_dump())
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pocket detection failed: {e}")


@app.post("/api/docking/validate", response_model=RedockValidationResponse)
async def validate_redocking(req: RedockValidationRequest):
    try:
        async with DOCKING_SEMAPHORE:
            return await run_in_threadpool(_run_isolated_worker, "docking_validate", req.model_dump())
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redocking validation failed: {e}")


@app.post("/api/docking/run", response_model=DockingRunResponse)
async def run_docking(req: DockingRunRequest):
    try:
        async with DOCKING_SEMAPHORE:
            return await run_in_threadpool(_run_isolated_worker, "docking_run", req.model_dump())
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Docking execution failed: {e}")


@app.post("/api/analysis/compare", response_model=ComparativeAnalysisResponse)
async def compare_results(req: ComparativeAnalysisRequest):
    try:
        return await run_in_threadpool(_run_isolated_worker, "analysis_compare", req.model_dump())
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Comparative analysis failed: {e}")


# Serve built frontend in production (Docker / SnapDeploy / VPS)
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend_dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
