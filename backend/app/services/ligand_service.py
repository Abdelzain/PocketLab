import shutil
import subprocess
from typing import List, Optional, Tuple
import httpx
from rdkit import Chem
from rdkit.Chem import AllChem, Descriptors, FilterCatalog, QED, rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D

from app.models import LigandPrepareRequest, LigandPrepareResponse, LigandProperties
from app.utils import job_store


async def fetch_smiles_from_pubchem(query: str) -> Tuple[str, str]:
    q = query.strip()
    if not q:
        raise ValueError("Please enter a compound name or PubChem CID.")

    if q.isdigit():
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{q}/property/CanonicalSMILES,Title/JSON"
    else:
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{q}/property/CanonicalSMILES,Title/JSON"

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise ValueError(f"Compound '{q}' not found on PubChem.")
        data = resp.json()
        props = data["PropertyTable"]["Properties"][0]
        smiles = props.get("CanonicalSMILES") or props.get("ConnectivitySMILES")
        title = props.get("Title") or q
        if not smiles:
            raise ValueError(f"No SMILES returned from PubChem for '{q}'.")
        return smiles, title


def _compute_pains(mol: Chem.Mol) -> List[str]:
    params = FilterCatalog.FilterCatalogParams()
    params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS)
    catalog = FilterCatalog.FilterCatalog(params)
    matches = catalog.GetMatches(mol)
    return [m.GetDescription() for m in matches]


def _render_2d_svg(mol: Chem.Mol) -> str:
    mol_2d = Chem.RemoveHs(Chem.Mol(mol))
    AllChem.Compute2DCoords(mol_2d)
    drawer = rdMolDraw2D.MolDraw2DSVG(360, 240)
    opts = drawer.drawOptions()
    opts.clearBackground = False
    drawer.DrawMolecule(mol_2d)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


def _write_ligand_pdbqt(mol_3d: Chem.Mol, pdbqt_path: str, sdf_path: str) -> None:
    # 1. Preferred: Meeko (native AutoDock Vina ligand prep)
    try:
        from meeko import MoleculePreparation, PDBQTWriterLegacy

        preparator = MoleculePreparation()
        mol_setups = preparator.prepare(mol_3d)
        pdbqt_str, is_ok, err = PDBQTWriterLegacy.write_string(mol_setups[0])
        if is_ok and pdbqt_str:
            with open(pdbqt_path, "w", encoding="utf-8") as fh:
                fh.write(pdbqt_str)
            return
    except Exception:
        pass

    # 2. Fallback: OpenBabel CLI
    obabel_exe = shutil.which("obabel")
    if obabel_exe:
        res = subprocess.run(
            [obabel_exe, sdf_path, "-O", pdbqt_path, "--partialcharge", "gasteiger"],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            return

    # 3. Fallback: OpenBabel Python API
    try:
        from openbabel import openbabel as ob

        conv = ob.OBConversion()
        conv.SetInAndOutFormats("sdf", "pdbqt")
        ob_mol = ob.OBMol()
        conv.ReadFile(ob_mol, sdf_path)
        conv.WriteFile(ob_mol, pdbqt_path)
        return
    except Exception as exc:
        raise RuntimeError(f"Could not convert ligand to PDBQT via Meeko or OpenBabel: {exc}")


def prepare_ligand(req: LigandPrepareRequest) -> LigandPrepareResponse:
    mol: Optional[Chem.Mol] = None
    if req.molblock and req.molblock.strip():
        mol = Chem.MolFromMolBlock(req.molblock, sanitize=True, removeHs=False)
    elif req.smiles and req.smiles.strip():
        mol = Chem.MolFromSmiles(req.smiles.strip())
    else:
        raise ValueError("Please provide a valid SMILES string or 2D drawn structure.")

    if mol is None:
        raise ValueError("Invalid chemical structure. Please check the SMILES or drawn molecule.")

    canonical_smiles = Chem.MolToSmiles(Chem.RemoveHs(mol), canonical=True)

    # Calculate physicochemical properties on neutral/sanitized form
    mol_no_h = Chem.RemoveHs(mol)
    mw = round(float(Descriptors.MolWt(mol_no_h)), 2)
    clogp = round(float(Descriptors.MolLogP(mol_no_h)), 2)
    tpsa = round(float(Descriptors.TPSA(mol_no_h)), 2)
    hbd = int(rdMolDescriptors.CalcNumHBD(mol_no_h))
    hba = int(rdMolDescriptors.CalcNumHBA(mol_no_h))
    rot_bonds = int(rdMolDescriptors.CalcNumRotatableBonds(mol_no_h))
    qed_score = round(float(QED.qed(mol_no_h)), 3)
    formula = rdMolDescriptors.CalcMolFormula(mol_no_h)
    pains = _compute_pains(mol_no_h)

    lipinski = sum([mw > 500, clogp > 5, hbd > 5, hba > 10])
    svg_2d = _render_2d_svg(mol_no_h)

    # Generate 3D conformer + MMFF94 minimization
    mol_3d = Chem.AddHs(mol_no_h)
    params = AllChem.ETKDGv3()
    params.randomSeed = 42
    embed_status = AllChem.EmbedMolecule(mol_3d, params)
    if embed_status != 0:
        embed_status = AllChem.EmbedMolecule(mol_3d, useRandomCoords=True, randomSeed=42)
        if embed_status != 0:
            raise ValueError("Failed to generate 3D conformer for this ligand.")

    if req.minimize:
        try:
            if AllChem.MMFFHasAllMoleculeParams(mol_3d):
                AllChem.MMFFOptimizeMolecule(mol_3d, maxIters=500)
            else:
                AllChem.UFFOptimizeMolecule(mol_3d, maxIters=500)
        except Exception:
            pass

    pdb_block = Chem.MolToPDBBlock(mol_3d)
    sdf_block = Chem.MolToMolBlock(mol_3d)

    job_store.save_text(req.session_id, "query_ligand.pdb", pdb_block)
    sdf_path = job_store.save_text(req.session_id, "query_ligand.sdf", sdf_block)
    pdbqt_path = job_store.get_file_path(req.session_id, "query_ligand.pdbqt")

    _write_ligand_pdbqt(mol_3d, str(pdbqt_path), str(sdf_path))

    job_store.save_meta(
        req.session_id,
        {
            "ligand_name": req.name or "Query Ligand",
            "ligand_smiles": canonical_smiles,
        },
    )

    return LigandPrepareResponse(
        session_id=req.session_id,
        name=req.name or "Query Ligand",
        canonical_smiles=canonical_smiles,
        pdb_block=pdb_block,
        svg_2d=svg_2d,
        properties=LigandProperties(
            molecular_formula=formula,
            molecular_weight=mw,
            clogp=clogp,
            tpsa=tpsa,
            hbd=hbd,
            hba=hba,
            rotatable_bonds=rot_bonds,
            qed=qed_score,
            lipinski_violations=lipinski,
            pains_alerts=pains,
        ),
    )
