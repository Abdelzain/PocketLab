import io
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple
import numpy as np
from Bio.PDB import PDBParser
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import cdist

VINA_CPU_THREADS = int(os.getenv("VINA_CPU_THREADS", "1"))
SMINA_LOW_RAM = os.getenv("SMINA_LOW_RAM", "0") == "1"

from app.models import (
    DockingPose,
    DockingRunRequest,
    DockingRunResponse,
    GridBox,
    RedockValidationRequest,
    RedockValidationResponse,
)
from app.utils import job_store


def _pdbqt_to_pdb_models(pdbqt_text: str) -> List[str]:
    """Split multi-model PDBQT output into clean single-model PDB blocks with unique atom names."""
    models: List[str] = []
    current: List[str] = []
    elem_counters: dict[str, int] = {}

    def _clean_line(line: str) -> str:
        atom_name = line[12:16].strip()
        parts = line.split()
        ad_type = parts[-1].strip() if parts else ""
        elem_map = {
            "OA": "O", "NA": "N", "SA": "S", "HD": "H", "A": "C",
            "C": "C", "N": "N", "O": "O", "S": "S", "P": "P",
            "F": "F", "Cl": "CL", "CL": "CL", "Br": "BR", "BR": "BR", "I": "I",
        }
        elem = elem_map.get(ad_type, "".join(c for c in atom_name if c.isalpha())[:2].upper())
        if len(elem) == 2 and elem not in {"CL", "BR", "ZN", "MG", "CA", "FE", "MN", "CU", "NA"}:
            elem = elem[0]
        elem_counters[elem] = elem_counters.get(elem, 0) + 1
        uniq_name = f"{elem}{elem_counters[elem]}"[:4]
        uniq_field = f" {uniq_name:<3s}" if len(uniq_name) < 4 else f"{uniq_name:<4s}"
        prefix = line[:12] + uniq_field + line[16:54].ljust(38)
        return f"{prefix}  1.00  0.00          {elem:>2s}"

    for line in pdbqt_text.splitlines():
        if line.startswith("MODEL"):
            current = []
            elem_counters = {}
        elif line.startswith("ENDMDL"):
            if current:
                current.append("END")
                models.append("\n".join(current) + "\n")
                current = []
                elem_counters = {}
        elif line.startswith(("ATOM  ", "HETATM")):
            current.append(_clean_line(line))

    if current:
        current.append("END")
        models.append("\n".join(current) + "\n")

    return models


def _prepare_native_pdbqt(session_id: str) -> str:
    native_pdb = job_store.read_text(session_id, "native_ligand.pdb")
    if not native_pdb:
        raise FileNotFoundError("No native co-crystallized ligand was extracted in Step 1.")

    native_pdb_path = job_store.get_file_path(session_id, "native_ligand.pdb")
    native_pdbqt_path = job_store.get_file_path(session_id, "native_ligand.pdbqt")

    # 1. Try OpenBabel CLI
    obabel_exe = shutil.which("obabel")
    if obabel_exe:
        res = subprocess.run(
            [obabel_exe, str(native_pdb_path), "-O", str(native_pdbqt_path), "-h", "--partialcharge", "gasteiger"],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0 and native_pdbqt_path.exists():
            return str(native_pdbqt_path)

    # 2. Try OpenBabel Python API
    try:
        from openbabel import openbabel as ob

        conv = ob.OBConversion()
        conv.SetInAndOutFormats("pdb", "pdbqt")
        mol = ob.OBMol()
        conv.ReadFile(mol, str(native_pdb_path))
        mol.AddHydrogens()
        conv.WriteFile(mol, str(native_pdbqt_path))
        return str(native_pdbqt_path)
    except Exception:
        pass

    # 3. Try RDKit + Meeko
    try:
        from rdkit import Chem
        from meeko import MoleculePreparation, PDBQTWriterLegacy

        mol = Chem.MolFromPDBBlock(native_pdb, sanitize=False, removeHs=False)
        if mol is not None:
            mol = Chem.AddHs(mol, addCoords=True)
            preparator = MoleculePreparation()
            setups = preparator.prepare(mol)
            pdbqt_str, is_ok, _ = PDBQTWriterLegacy.write_string(setups[0])
            if is_ok and pdbqt_str:
                native_pdbqt_path.write_text(pdbqt_str, encoding="utf-8")
                return str(native_pdbqt_path)
    except Exception as exc:
        raise RuntimeError(f"Could not prepare native ligand PDBQT: {exc}")

    raise RuntimeError("Failed to prepare native ligand PDBQT.")


def _heavy_atoms_from_pdb(pdb_text: str) -> Tuple[List[str], np.ndarray]:
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("mol", io.StringIO(pdb_text))
    elems: List[str] = []
    coords: List[np.ndarray] = []
    for atom in structure.get_atoms():
        el = (atom.element or atom.get_name()[0]).strip().upper()
        if el == "H":
            continue
        elems.append(el)
        coords.append(atom.get_coord())
    return elems, np.array(coords, dtype=float)


def compute_symmetry_rmsd(ref_pdb: str, probe_pdb: str) -> float:
    """Symmetry-aware heavy-atom RMSD (RDKit isomorphism first, Hungarian element-match fallback)."""
    try:
        from rdkit import Chem
        from rdkit.Chem import rdMolAlign

        m_ref = Chem.MolFromPDBBlock(ref_pdb, sanitize=True, removeHs=True)
        m_prb = Chem.MolFromPDBBlock(probe_pdb, sanitize=True, removeHs=True)
        if m_ref is not None and m_prb is not None and m_ref.GetNumAtoms() == m_prb.GetNumAtoms():
            rmsd = rdMolAlign.CalcRMS(m_prb, m_ref)
            return round(float(rmsd), 3)
    except Exception:
        pass

    # Fallback: element-grouped Hungarian optimal assignment (in-place, no superposition)
    ref_el, ref_xyz = _heavy_atoms_from_pdb(ref_pdb)
    prb_el, prb_xyz = _heavy_atoms_from_pdb(probe_pdb)
    if len(ref_xyz) == 0 or len(prb_xyz) == 0:
        return 99.9

    sq_dists: List[float] = []
    unique_elems = set(ref_el) & set(prb_el)
    for el in unique_elems:
        r_idx = [i for i, e in enumerate(ref_el) if e == el]
        p_idx = [i for i, e in enumerate(prb_el) if e == el]
        cost = cdist(ref_xyz[r_idx], prb_xyz[p_idx], metric="sqeuclidean")
        row_ind, col_ind = linear_sum_assignment(cost)
        sq_dists.extend(cost[row_ind, col_ind].tolist())

    if not sq_dists:
        return 99.9
    return round(float(np.sqrt(np.mean(sq_dists))), 3)


def _find_vina_binary() -> Optional[str]:
    local_bin = Path(__file__).resolve().parent.parent.parent / "bin" / "vina.exe"
    if local_bin.exists():
        return str(local_bin)
    local_unix = Path(__file__).resolve().parent.parent.parent / "bin" / "vina"
    if local_unix.exists():
        return str(local_unix)
    return shutil.which("vina")


def _parse_vina_cli_table(stdout: str) -> List[Tuple[float, float, float]]:
    energies: List[Tuple[float, float, float]] = []
    for line in stdout.splitlines():
        m = re.match(r"^\s*(\d+)\s+(-?\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)", line)
        if m:
            energies.append(
                (round(float(m.group(2)), 2), round(float(m.group(3)), 2), round(float(m.group(4)), 2))
            )
    return energies


def _run_vina_engine(
    receptor_pdbqt: str,
    ligand_pdbqt: str,
    box: GridBox,
    exhaustiveness: int = 8,
    num_modes: int = 9,
) -> Tuple[List[Tuple[float, float, float]], str, float]:
    """Run AutoDock Vina via Python binding (Linux/Docker) or CLI binary (Windows/Linux)."""
    try:
        from vina import Vina

        v = Vina(sf_name="vina", cpu=VINA_CPU_THREADS, verbosity=0)
        v.set_receptor(receptor_pdbqt)
        v.set_ligand_from_file(ligand_pdbqt)
        v.compute_vina_maps(
            center=[box.center_x, box.center_y, box.center_z],
            box_size=[box.size_x, box.size_y, box.size_z],
        )
        init_score = float(v.score()[0])
        v.dock(exhaustiveness=exhaustiveness, n_poses=num_modes)
        energies = v.energies(n_poses=num_modes)
        poses_pdbqt = v.poses(n_poses=num_modes)
        energy_tuples = [(round(float(e[0]), 2), round(float(e[1]), 2), round(float(e[2]), 2)) for e in energies]
        return energy_tuples, poses_pdbqt, round(init_score, 2)
    except ImportError:
        pass

    vina_bin = _find_vina_binary()
    if not vina_bin:
        raise RuntimeError(
            "AutoDock Vina engine not found. Install the 'vina' Python package or place vina.exe in backend/bin/."
        )

    with tempfile.NamedTemporaryFile(suffix=".pdbqt", delete=False) as tmp_out:
        out_path = Path(tmp_out.name)

    try:
        cmd = [
            vina_bin,
            "--receptor", receptor_pdbqt,
            "--ligand", ligand_pdbqt,
            "--center_x", str(box.center_x),
            "--center_y", str(box.center_y),
            "--center_z", str(box.center_z),
            "--size_x", str(min(box.size_x, 22.0) if SMINA_LOW_RAM else box.size_x),
            "--size_y", str(min(box.size_y, 22.0) if SMINA_LOW_RAM else box.size_y),
            "--size_z", str(min(box.size_z, 22.0) if SMINA_LOW_RAM else box.size_z),
            "--exhaustiveness", str(min(exhaustiveness, 8) if SMINA_LOW_RAM else exhaustiveness),
            "--num_modes", str(num_modes),
            "--cpu", str(VINA_CPU_THREADS),
            "--out", str(out_path),
        ]
        if SMINA_LOW_RAM:
            cmd.extend(["--approximation", "linear", "--factor", "10"])
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(
                f"AutoDock Vina CLI failed (exit code {res.returncode}): {res.stderr or res.stdout}"
            )

        energies = _parse_vina_cli_table(res.stdout)
        poses_pdbqt = out_path.read_text(encoding="utf-8")
        if not energies:
            # Parse REMARK VINA RESULT lines from PDBQT output
            for line in poses_pdbqt.splitlines():
                if line.startswith("REMARK VINA RESULT:"):
                    parts = line.split(":")[1].split()
                    if len(parts) >= 3:
                        energies.append((round(float(parts[0]), 2), round(float(parts[1]), 2), round(float(parts[2]), 2)))
        init_score = energies[0][0] if energies else 0.0
        return energies, poses_pdbqt, init_score
    finally:
        if out_path.exists():
            out_path.unlink(missing_ok=True)


def _score_native_in_place(session_id: str, box: GridBox) -> Optional[float]:
    try:
        rec_pdbqt = str(job_store.get_file_path(session_id, "receptor.pdbqt"))
        nat_pdbqt = _prepare_native_pdbqt(session_id)
        try:
            from vina import Vina

            v = Vina(sf_name="vina", verbosity=0)
            v.set_receptor(rec_pdbqt)
            v.set_ligand_from_file(nat_pdbqt)
            v.compute_vina_maps(
                center=[box.center_x, box.center_y, box.center_z],
                box_size=[box.size_x, box.size_y, box.size_z],
            )
            opt_score = float(v.optimize()[0])
            return round(opt_score, 2)
        except ImportError:
            vina_bin = _find_vina_binary()
            if not vina_bin:
                return None
            local_cmd = [
                vina_bin,
                "--receptor", rec_pdbqt,
                "--ligand", nat_pdbqt,
                "--center_x", str(box.center_x),
                "--center_y", str(box.center_y),
                "--center_z", str(box.center_z),
                "--size_x", str(min(box.size_x, 22.0) if SMINA_LOW_RAM else box.size_x),
                "--size_y", str(min(box.size_y, 22.0) if SMINA_LOW_RAM else box.size_y),
                "--size_z", str(min(box.size_z, 22.0) if SMINA_LOW_RAM else box.size_z),
                "--cpu", str(VINA_CPU_THREADS),
                "--local_only",
            ]
            if SMINA_LOW_RAM:
                local_cmd.extend(["--approximation", "linear", "--factor", "10"])
            res = subprocess.run(local_cmd, capture_output=True, text=True)
            for line in res.stdout.splitlines():
                m = re.search(r"(?:Affinity|Estimated Free Energy of Binding)\s*:\s*(-?\d+\.\d+)", line)
                if m:
                    return round(float(m.group(1)), 2)
            return None
    except Exception:
        return None


def run_redocking_validation(req: RedockValidationRequest) -> RedockValidationResponse:
    rec_pdbqt = job_store.get_file_path(req.session_id, "receptor.pdbqt")
    if not rec_pdbqt.exists():
        raise FileNotFoundError("Prepared receptor not found. Complete Step 1 first.")

    nat_pdb = job_store.read_text(req.session_id, "native_ligand.pdb")
    if not nat_pdb:
        raise FileNotFoundError("No native co-crystallized ligand available for redocking validation.")

    nat_pdbqt = _prepare_native_pdbqt(req.session_id)
    energies, poses_pdbqt, init_score = _run_vina_engine(
        receptor_pdbqt=str(rec_pdbqt),
        ligand_pdbqt=nat_pdbqt,
        box=req.box,
        exhaustiveness=req.exhaustiveness,
        num_modes=5,
    )
    models = _pdbqt_to_pdb_models(poses_pdbqt)
    if not models:
        raise RuntimeError("Vina produced no poses during redocking validation.")

    best_pose_pdb = models[0]
    rmsd = compute_symmetry_rmsd(nat_pdb, best_pose_pdb)
    passed = rmsd <= 2.0
    redocked_affinity = energies[0][0]

    job_store.save_text(req.session_id, "redocked_native.pdb", best_pose_pdb)
    job_store.save_meta(
        req.session_id,
        {
            "redock_rmsd": rmsd,
            "redock_passed": passed,
            "native_score": redocked_affinity,
        },
    )

    msg = (
        f"Validation PASSED: Redocked pose reproduces the experimental crystal pose with RMSD = {rmsd:.2f} Å (≤ 2.0 Å)."
        if passed
        else f"Validation WARNING: Redocked RMSD is {rmsd:.2f} Å (> 2.0 Å). Consider adjusting grid box size/center or checking protonation/waters."
    )

    return RedockValidationResponse(
        session_id=req.session_id,
        rmsd=rmsd,
        passed=passed,
        native_score=init_score,
        redocked_affinity=redocked_affinity,
        redocked_pdb=best_pose_pdb,
        message=msg,
    )


def run_docking(req: DockingRunRequest) -> DockingRunResponse:
    rec_pdbqt = job_store.get_file_path(req.session_id, "receptor.pdbqt")
    lig_pdbqt = job_store.get_file_path(req.session_id, "query_ligand.pdbqt")

    if not rec_pdbqt.exists():
        raise FileNotFoundError("Prepared receptor not found. Complete Step 1 first.")
    if not lig_pdbqt.exists():
        raise FileNotFoundError("Prepared query ligand not found. Complete Step 2 first.")

    energies, poses_pdbqt, _ = _run_vina_engine(
        receptor_pdbqt=str(rec_pdbqt),
        ligand_pdbqt=str(lig_pdbqt),
        box=req.box,
        exhaustiveness=req.exhaustiveness,
        num_modes=req.num_modes,
    )
    models = _pdbqt_to_pdb_models(poses_pdbqt)

    poses: List[DockingPose] = []
    for idx, (energy, pdb_block) in enumerate(zip(energies, models), start=1):
        job_store.save_text(req.session_id, f"docked_pose_{idx}.pdb", pdb_block)
        poses.append(
            DockingPose(
                mode=idx,
                affinity=energy[0],
                rmsd_lb=energy[1],
                rmsd_ub=energy[2],
                pdb_block=pdb_block,
            )
        )

    meta = job_store.load_meta(req.session_id)
    native_score = meta.get("native_score")
    if native_score is None and job_store.read_text(req.session_id, "native_ligand.pdb"):
        native_score = _score_native_in_place(req.session_id, req.box)

    job_store.save_meta(
        req.session_id,
        {
            "native_score": native_score,
            "poses_affinities": {str(p.mode): p.affinity for p in poses},
            "last_box": req.box.model_dump(),
            "last_exhaustiveness": req.exhaustiveness,
        },
    )

    return DockingRunResponse(
        session_id=req.session_id,
        ligand_name=meta.get("ligand_name", "Query Ligand"),
        poses=poses,
        native_score=native_score,
        box=req.box,
        exhaustiveness=req.exhaustiveness,
    )
