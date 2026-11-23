"""
Short-lived subprocess worker for heavy scientific operations (RDKit, SciPy, BioPython).
Running each heavy call in an isolated worker ensures 100% of its RAM (~200 MB) is
immediately returned to the OS so the main FastAPI process stays ~45 MB on 512 MB hosts.
"""
import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("Usage: python -m app.worker <action> <payload_json_path>")

    action = sys.argv[1]
    payload_path = Path(sys.argv[2])
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    if action == "protein_inspect":
        from app.services import protein_service
        res = protein_service.inspect_pdb_text(payload["pdb_text"], pdb_id=payload.get("pdb_id"))
    elif action == "protein_upload":
        from app.services import protein_service
        raw_text = payload["raw_text"]
        if payload.get("is_cif"):
            raw_text = protein_service.mmcif_to_pdb(raw_text)
        if "ATOM" not in raw_text:
            raise ValueError("Uploaded file does not appear to be a valid PDB or mmCIF (.cif) structure.")
        res = protein_service.inspect_pdb_text(raw_text, pdb_id=None)
    elif action == "protein_prepare":
        from app.models import ProteinPrepareRequest
        from app.services import protein_service
        res = protein_service.prepare_protein(ProteinPrepareRequest(**payload))
    elif action == "ligand_prepare":
        from app.models import LigandPrepareRequest
        from app.services import ligand_service
        res = ligand_service.prepare_ligand(LigandPrepareRequest(**payload))
    elif action == "pocket_detect":
        from app.models import PocketDetectRequest
        from app.services import pocket_service
        res = pocket_service.detect_pockets(PocketDetectRequest(**payload))
    elif action == "docking_validate":
        from app.models import RedockValidationRequest
        from app.services import docking_service
        res = docking_service.run_redocking_validation(RedockValidationRequest(**payload))
    elif action == "docking_run":
        from app.models import DockingRunRequest
        from app.services import docking_service
        res = docking_service.run_docking(DockingRunRequest(**payload))
    elif action == "docking_inputs":
        from app.services import docking_service
        res = docking_service.get_docking_inputs(payload["session_id"])
    elif action == "docking_ingest":
        from app.models import DockingIngestRequest
        from app.services import docking_service
        res = docking_service.ingest_browser_docking(DockingIngestRequest(**payload))
    elif action == "docking_ingest_redock":
        from app.models import RedockIngestRequest
        from app.services import docking_service
        res = docking_service.ingest_browser_redock(RedockIngestRequest(**payload))
    elif action == "analysis_compare":
        from app.models import ComparativeAnalysisRequest
        from app.services import analysis_service
        res = analysis_service.run_comparative_analysis(ComparativeAnalysisRequest(**payload))
    else:
        raise ValueError(f"Unknown worker action: {action}")

    out_path = Path(payload_path.as_posix() + ".out.json")
    out_path.write_text(res.model_dump_json(), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        sys.stderr.write(f"NOT_FOUND:{exc}\n")
        sys.exit(44)
    except ValueError as exc:
        sys.stderr.write(f"BAD_REQUEST:{exc}\n")
        sys.exit(40)
    except Exception as exc:
        sys.stderr.write(f"SERVER_ERROR:{exc}\n")
        sys.exit(50)
