import io
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import httpx
import numpy as np
from Bio.PDB import MMCIFParser, PDBIO, PDBParser, Select

from app.models import (
    ChainInfo,
    HeteroGroupInfo,
    ProteinInspectResponse,
    ProteinPrepareRequest,
    ProteinPrepareResponse,
)
from app.utils import job_store

WATER_RESNAMES = {"HOH", "WAT", "DOD", "H2O"}
ION_RESNAMES = {
    "ZN", "MG", "CA", "FE", "FE2", "MN", "CU", "NA", "K", "CL", "BR", "IOD",
    "CO", "NI", "CD", "HG", "SR", "BA", "CS", "LI", "RB",
}
COFACTOR_RESNAMES = {
    "HEM", "HEC", "NAD", "NAP", "NDP", "NAI", "FAD", "FMN", "ATP", "ADP",
    "AMP", "GTP", "GDP", "GMP", "SAM", "SAH", "PLP", "COA", "ACO", "TPP",
    "BTN", "B12", "FOL", "THF",
}
SOLVENT_ARTIFACTS = {
    "EDO", "GOL", "SO4", "PO4", "DMS", "DMSO", "PEG", "PGE", "MPD", "ACT",
    "ACE", "TRS", "MES", "HEP", "EPE", "CIT", "FMT", "BME", "IPA", "EOH",
    "MOH", "ACY", "NO3", "UNX", "UNL",
}


def mmcif_to_pdb(cif_text: str) -> str:
    """Convert mmCIF (.cif) text into standard PDB format (handling multi-char chain IDs safely)."""
    parser = MMCIFParser(QUIET=True)
    structure = parser.get_structure("protein", io.StringIO(cif_text))
    model = next(structure.get_models())

    # Legacy PDB format only supports 1-character chain IDs
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuvwxyz"
    used_ids = {c.id for c in model.get_chains() if len(c.id) == 1}
    free_iter = iter([ch for ch in alphabet if ch not in used_ids])
    for chain in list(model.get_chains()):
        if len(chain.id) != 1:
            try:
                chain.id = next(free_iter)
            except StopIteration:
                chain.id = chain.id[0]

    # Truncate residue names >3 chars if any (PDB spec allows 3 chars)
    for chain in model.get_chains():
        for res in chain.get_residues():
            if len(res.resname.strip()) > 3:
                res.resname = res.resname.strip()[:3]

    # Preserve title from _struct.title if present
    title_line = ""
    for line in cif_text.splitlines():
        if line.startswith("_struct.title"):
            t = line[len("_struct.title"):].strip().strip("'\"")
            if t:
                title_line = f"TITLE     {t[:70]}\n"
            break

    out_buf = io.StringIO()
    pdbio = PDBIO()
    pdbio.set_structure(model)
    pdbio.save(out_buf)
    return title_line + out_buf.getvalue()


async def fetch_pdb_from_rcsb(pdb_id: str) -> str:
    clean_id = pdb_id.strip().upper()
    if len(clean_id) != 4 or not clean_id.isalnum():
        raise ValueError(f"Invalid PDB ID '{pdb_id}'. Expected a 4-character alphanumeric code (e.g. 1IEP, 6LU7).")
    pdb_url = f"https://files.rcsb.org/download/{clean_id}.pdb"
    cif_url = f"https://files.rcsb.org/download/{clean_id}.cif"
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.get(pdb_url)
        if resp.status_code == 200:
            return resp.text
        # Automatic fallback to mmCIF (.cif) when Legacy PDB is unavailable on RCSB
        cif_resp = await client.get(cif_url)
        if cif_resp.status_code == 200:
            return mmcif_to_pdb(cif_resp.text)
        raise ValueError(
            f"Could not fetch PDB or mmCIF for '{clean_id}' from RCSB (HTTP {resp.status_code} / {cif_resp.status_code})."
        )


def _extract_title(pdb_text: str, fallback: str = "Uploaded Structure") -> str:
    title_lines = []
    for line in pdb_text.splitlines():
        if line.startswith("TITLE"):
            title_lines.append(line[10:].strip())
    return " ".join(title_lines).strip() or fallback


def inspect_pdb_text(pdb_text: str, pdb_id: Optional[str] = None) -> ProteinInspectResponse:
    session_id = job_store.create_session()
    job_store.save_text(session_id, "raw.pdb", pdb_text)

    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("protein", io.StringIO(pdb_text))
    model = next(structure.get_models())

    chains: List[ChainInfo] = []
    ligands: List[HeteroGroupInfo] = []
    ions: List[HeteroGroupInfo] = []
    water_count = 0

    for chain in model.get_chains():
        std_res = 0
        std_atoms = 0
        for residue in chain.get_residues():
            hetflag, resseq, _ = residue.id
            resname = residue.get_resname().strip().upper()
            atoms = list(residue.get_atoms())

            if hetflag == " ":
                std_res += 1
                std_atoms += len(atoms)
            elif resname in WATER_RESNAMES or hetflag == "W":
                water_count += 1
            else:
                group_id = f"{chain.id}:{resname}:{resseq}"
                elem_counts: Dict[str, int] = {}
                for a in atoms:
                    el = (a.element or a.get_name()[0]).strip().upper()
                    elem_counts[el] = elem_counts.get(el, 0) + 1
                formula = "".join(f"{k}{v if v > 1 else ''}" for k, v in sorted(elem_counts.items()))

                if resname in ION_RESNAMES:
                    ions.append(
                        HeteroGroupInfo(
                            id=group_id,
                            resname=resname,
                            chain_id=chain.id,
                            resseq=resseq,
                            atom_count=len(atoms),
                            category="ion",
                            formula_hint=formula,
                        )
                    )
                elif resname in COFACTOR_RESNAMES:
                    ions.append(
                        HeteroGroupInfo(
                            id=group_id,
                            resname=resname,
                            chain_id=chain.id,
                            resseq=resseq,
                            atom_count=len(atoms),
                            category="cofactor",
                            formula_hint=formula,
                        )
                    )
                    ligands.append(
                        HeteroGroupInfo(
                            id=group_id,
                            resname=resname,
                            chain_id=chain.id,
                            resseq=resseq,
                            atom_count=len(atoms),
                            category="cofactor",
                            formula_hint=formula,
                        )
                    )
                elif resname in SOLVENT_ARTIFACTS:
                    ligands.append(
                        HeteroGroupInfo(
                            id=group_id,
                            resname=resname,
                            chain_id=chain.id,
                            resseq=resseq,
                            atom_count=len(atoms),
                            category="solvent_artifact",
                            formula_hint=formula,
                        )
                    )
                else:
                    ligands.append(
                        HeteroGroupInfo(
                            id=group_id,
                            resname=resname,
                            chain_id=chain.id,
                            resseq=resseq,
                            atom_count=len(atoms),
                            category="ligand",
                            formula_hint=formula,
                        )
                    )

        if std_res > 0:
            chains.append(ChainInfo(chain_id=chain.id, residue_count=std_res, atom_count=std_atoms))

    # Sort ligands so true drug-like ligands appear first (largest atom count first)
    priority = {"ligand": 0, "cofactor": 1, "solvent_artifact": 2, "ion": 3}
    ligands.sort(key=lambda x: (priority.get(x.category, 9), -x.atom_count))

    title = _extract_title(pdb_text, fallback=f"PDB {pdb_id}" if pdb_id else "Uploaded Protein")
    job_store.save_meta(session_id, {"title": title, "pdb_id": pdb_id})

    return ProteinInspectResponse(
        session_id=session_id,
        title=title,
        pdb_id=pdb_id,
        chains=chains,
        ligands=ligands,
        ions=ions,
        water_count=water_count,
        raw_pdb=pdb_text,
    )


def _pdb_to_smiles(pdb_text: str) -> Optional[str]:
    # 1. OpenBabel CLI perceives bond orders & aromaticity from 3D PDB geometry accurately
    obabel_exe = shutil.which("obabel")
    if obabel_exe:
        try:
            res = subprocess.run(
                [obabel_exe, "-ipdb", "-ocan"],
                input=pdb_text,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip().split()[0]
        except Exception:
            pass
    # 2. OpenBabel Python API (pybel)
    try:
        from openbabel import pybel
        mol = pybel.readstring("pdb", pdb_text)
        can = mol.write("can").strip().split()[0]
        if can:
            return can
    except Exception:
        pass
    # 3. RDKit fallback
    try:
        from rdkit import Chem
        mol = Chem.MolFromPDBBlock(pdb_text, sanitize=True, removeHs=True)
        if mol is not None:
            return Chem.MolToSmiles(mol, canonical=True)
    except Exception:
        pass
    return None


def _sanitize_receptor_pdbqt(pdbqt_path: str) -> None:
    """Ensure rigid receptor PDBQT has no ligand tree tags and uses valid AutoDock metal types."""
    metal_fix = {"ZN": "Zn", "MG": "Mg", "CA": "Ca", "FE": "Fe", "MN": "Mn", "CU": "Cu"}
    p = Path(pdbqt_path)
    if not p.exists():
        return
    clean_lines = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith(("ROOT", "ENDROOT", "BRANCH", "ENDBRANCH", "TORSDOF")):
            continue
        if line.startswith(("ATOM  ", "HETATM")) and len(line) >= 77:
            ad_type = line[77:79].strip()
            if ad_type.upper() in metal_fix:
                fixed = metal_fix[ad_type.upper()]
                line = line[:77] + f"{fixed:<2s}" + line[79:]
        clean_lines.append(line)
    p.write_text("\n".join(clean_lines) + "\n", encoding="utf-8")


def _convert_receptor_to_pdbqt(pdb_path: str, pdbqt_path: str, ph: float = 7.4) -> Tuple[bool, Optional[str]]:
    def _has_valid_output() -> bool:
        p = Path(pdbqt_path)
        return p.exists() and p.stat().st_size > 100

    # 1. Try OpenBabel CLI (with Gasteiger charges, then retry without Gasteiger for metalloproteins like Zn2+)
    obabel_exe = shutil.which("obabel")
    if obabel_exe:
        for extra_args in (["--partialcharge", "gasteiger"], []):
            cmd = [obabel_exe, pdb_path, "-O", pdbqt_path, "-xr", "-p", str(ph), *extra_args]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0 and _has_valid_output():
                _sanitize_receptor_pdbqt(pdbqt_path)
                return True, None

    # 2. Try OpenBabel Python API (pybel)
    try:
        from openbabel import openbabel as ob
        conv = ob.OBConversion()
        conv.SetInAndOutFormats("pdb", "pdbqt")
        conv.AddOption("r", ob.OBConversion.OUTOPTIONS)  # rigid receptor
        mol = ob.OBMol()
        conv.ReadFile(mol, pdb_path)
        mol.AddHydrogens(False, True, ph)
        conv.WriteFile(mol, pdbqt_path)
        if _has_valid_output():
            _sanitize_receptor_pdbqt(pdbqt_path)
            return True, None
    except Exception as exc:
        return False, f"OpenBabel PDBQT conversion unavailable ({exc}); using fallback writer."

    return False, "OpenBabel produced empty PDBQT (likely due to metal ion); using fallback writer."


def _write_fallback_pdbqt(pdb_text: str, pdbqt_path: str) -> None:
    """Minimal AutoDock PDBQT writer fallback if OpenBabel is absent."""
    ad_type_map = {
        "C": "C ", "N": "NA", "O": "OA", "S": "SA", "H": "HD",
        "P": "P ", "F": "F ", "CL": "Cl", "BR": "Br", "I": "I ",
        "ZN": "Zn", "MG": "Mg", "CA": "Ca", "FE": "Fe", "MN": "Mn",
    }
    out_lines = []
    for line in pdb_text.splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            padded = line.ljust(80)
            elem = padded[76:78].strip().upper() or padded[12:16].strip()[0].upper()
            ad_type = ad_type_map.get(elem, elem[:2].ljust(2))
            pdbqt_line = f"{padded[:54]}  1.00  0.00    +0.000 {ad_type}\n"
            out_lines.append(pdbqt_line)
    with open(pdbqt_path, "w", encoding="utf-8") as fh:
        fh.writelines(out_lines)


def prepare_protein(req: ProteinPrepareRequest) -> ProteinPrepareResponse:
    raw_pdb = job_store.read_text(req.session_id, "raw.pdb")
    if not raw_pdb:
        raise FileNotFoundError("Raw PDB not found for this session.")

    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("protein", io.StringIO(raw_pdb))
    model = next(structure.get_models())

    keep_chains = set(req.keep_chains)
    keep_ions = set(req.keep_ions)
    native_id = req.extract_native_ligand_id
    warnings: List[str] = []

    # 1. Extract native ligand coordinates if requested
    native_coords: List[np.ndarray] = []
    native_pdb: Optional[str] = None
    native_smiles: Optional[str] = None

    if native_id:
        class NativeLigandSelect(Select):
            def accept_residue(self, residue):
                hetflag, resseq, _ = residue.id
                resname = residue.get_resname().strip().upper()
                gid = f"{residue.get_parent().id}:{resname}:{resseq}"
                return gid == native_id

        for chain in model.get_chains():
            for res in chain.get_residues():
                hetflag, resseq, _ = res.id
                resname = res.get_resname().strip().upper()
                if f"{chain.id}:{resname}:{resseq}" == native_id:
                    for atom in res.get_atoms():
                        native_coords.append(atom.get_coord())

        if native_coords:
            io_buf = io.StringIO()
            pdbio = PDBIO()
            pdbio.set_structure(model)
            pdbio.save(io_buf, NativeLigandSelect())
            native_pdb = io_buf.getvalue()
            job_store.save_text(req.session_id, "native_ligand.pdb", native_pdb)
            native_smiles = _pdb_to_smiles(native_pdb)
        else:
            warnings.append(f"Selected native ligand '{native_id}' was not found in structure.")

    native_coords_arr = np.array(native_coords) if native_coords else None

    # 2. Filter receptor structure
    water_kept = 0
    ions_kept = 0
    atom_count = 0

    class ReceptorSelect(Select):
        def accept_chain(self, chain):
            return chain.id in keep_chains

        def accept_residue(self, residue):
            nonlocal water_kept, ions_kept
            hetflag, resseq, _ = residue.id
            resname = residue.get_resname().strip().upper()
            gid = f"{residue.get_parent().id}:{resname}:{resseq}"

            if gid == native_id:
                return False

            if hetflag == " ":
                return True

            if resname in WATER_RESNAMES or hetflag == "W":
                if not req.remove_waters:
                    water_kept += 1
                    return True
                if req.keep_waters_within_angstrom and native_coords_arr is not None:
                    for atom in residue.get_atoms():
                        dists = np.linalg.norm(native_coords_arr - atom.get_coord(), axis=1)
                        if float(np.min(dists)) <= req.keep_waters_within_angstrom:
                            water_kept += 1
                            return True
                return False

            if gid in keep_ions:
                ions_kept += 1
                return True

            return False

    rec_buf = io.StringIO()
    pdbio = PDBIO()
    pdbio.set_structure(model)
    pdbio.save(rec_buf, ReceptorSelect())
    cleaned_pdb = rec_buf.getvalue()

    # 3. Optional PDBFixer for missing atoms & hydrogens
    prepared_pdb = cleaned_pdb
    if req.add_hydrogens:
        try:
            from pdbfixer import PDBFixer
            from openmm.app import PDBFile

            fixer = PDBFixer(pdbfile=io.StringIO(cleaned_pdb))
            fixer.findMissingResidues()
            fixer.missingResidues = {}  # avoid hallucinating long missing loops
            fixer.findNonstandardResidues()
            fixer.replaceNonstandardResidues()
            fixer.findMissingAtoms()
            fixer.addMissingAtoms()
            fixer.addMissingHydrogens(req.ph)
            out_io = io.StringIO()
            PDBFile.writeFile(fixer.topology, fixer.positions, out_io, keepIds=True)
            prepared_pdb = out_io.getvalue()
        except Exception as exc:
            warnings.append(f"PDBFixer step skipped ({exc}); using cleaned structure directly.")

    for line in prepared_pdb.splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            atom_count += 1

    rec_pdb_path = job_store.save_text(req.session_id, "receptor_prepared.pdb", prepared_pdb)
    rec_pdbqt_path = job_store.get_file_path(req.session_id, "receptor.pdbqt")

    ok, conv_warn = _convert_receptor_to_pdbqt(str(rec_pdb_path), str(rec_pdbqt_path), ph=req.ph)
    if not ok:
        if conv_warn:
            warnings.append(conv_warn)
        _write_fallback_pdbqt(prepared_pdb, str(rec_pdbqt_path))

    job_store.save_meta(
        req.session_id,
        {
            "prepared": True,
            "native_ligand_id": native_id,
            "native_ligand_smiles": native_smiles,
            "ph": req.ph,
            "keep_chains": req.keep_chains,
        },
    )

    return ProteinPrepareResponse(
        session_id=req.session_id,
        prepared_pdb=prepared_pdb,
        native_ligand_pdb=native_pdb,
        native_ligand_id=native_id,
        native_ligand_smiles=native_smiles,
        atom_count=atom_count,
        water_kept_count=water_kept,
        ions_kept_count=ions_kept,
        warnings=warnings,
    )
