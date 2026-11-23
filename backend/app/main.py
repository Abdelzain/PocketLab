import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
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
from app.services import (
    analysis_service,
    docking_service,
    ligand_service,
    pocket_service,
    protein_service,
)
from app.utils import job_store

# Concurrency limiter to protect server RAM/CPU when many students dock simultaneously
MAX_CONCURRENT_DOCKS = int(os.getenv("MAX_CONCURRENT_DOCKS", "2"))
DOCKING_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOCKS)
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "3600"))  # 1 hour


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
        pdb_text = await protein_service.fetch_pdb_from_rcsb(req.pdb_id)
        return protein_service.inspect_pdb_text(pdb_text, pdb_id=req.pdb_id.strip().upper())
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
        if is_cif:
            pdb_text = protein_service.mmcif_to_pdb(raw_text)
        else:
            pdb_text = raw_text
        if "ATOM" not in pdb_text:
            raise ValueError("Uploaded file does not appear to be a valid PDB or mmCIF (.cif) structure.")
        return protein_service.inspect_pdb_text(pdb_text, pdb_id=None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse uploaded structure: {e}")


@app.post("/api/protein/prepare", response_model=ProteinPrepareResponse)
def prepare_protein(req: ProteinPrepareRequest):
    try:
        return protein_service.prepare_protein(req)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Protein preparation failed: {e}")


@app.post("/api/ligand/pubchem")
async def lookup_pubchem(req: PubChemLookupRequest):
    try:
        smiles, title = await ligand_service.fetch_smiles_from_pubchem(req.query)
        return {"smiles": smiles, "name": title}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PubChem lookup failed: {e}")


@app.post("/api/ligand/prepare", response_model=LigandPrepareResponse)
def prepare_ligand(req: LigandPrepareRequest):
    try:
        return ligand_service.prepare_ligand(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ligand preparation failed: {e}")


@app.post("/api/pocket/detect", response_model=PocketDetectResponse)
def detect_pockets(req: PocketDetectRequest):
    try:
        return pocket_service.detect_pockets(req)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pocket detection failed: {e}")


@app.post("/api/docking/validate", response_model=RedockValidationResponse)
async def validate_redocking(req: RedockValidationRequest):
    try:
        async with DOCKING_SEMAPHORE:
            return await run_in_threadpool(docking_service.run_redocking_validation, req)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redocking validation failed: {e}")


@app.post("/api/docking/run", response_model=DockingRunResponse)
async def run_docking(req: DockingRunRequest):
    try:
        async with DOCKING_SEMAPHORE:
            return await run_in_threadpool(docking_service.run_docking, req)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Docking execution failed: {e}")


@app.post("/api/analysis/compare", response_model=ComparativeAnalysisResponse)
def compare_results(req: ComparativeAnalysisRequest):
    try:
        return analysis_service.run_comparative_analysis(req)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Comparative analysis failed: {e}")


# Serve built frontend in production (Docker / Hugging Face Spaces)
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend_dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
