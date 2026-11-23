import io
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple
import numpy as np
from Bio.PDB import PDBParser

from app.models import (
    ComparativeAnalysisRequest,
    ComparativeAnalysisResponse,
    InteractionItem,
    ResidueComparison,
)
from app.utils import job_store

AROMATIC_RESIDUES = {"PHE", "TYR", "TRP", "HIS"}
POS_CHARGED_RESIDUES = {"ARG", "LYS", "HIS"}
NEG_CHARGED_RESIDUES = {"ASP", "GLU"}
METAL_ELEMENTS = {"ZN", "MG", "CA", "FE", "MN", "CU", "CO", "NI"}
HALOGEN_ELEMENTS = {"CL", "BR", "I"}
POLAR_ELEMENTS = {"N", "O", "F", "S"}


def _parse_atoms(pdb_text: str):
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("s", io.StringIO(pdb_text))
    model = next(structure.get_models())
    atoms = []
    for chain in model.get_chains():
        for res in chain.get_residues():
            resname = res.get_resname().strip().upper()
            resseq = int(res.id[1])
            for atom in res.get_atoms():
                el = (atom.element or atom.get_name()[0]).strip().upper()
                if el == "H":
                    continue
                atoms.append(
                    {
                        "chain": chain.id,
                        "resname": resname,
                        "resseq": resseq,
                        "residue": f"{resname}{resseq} ({chain.id})",
                        "name": atom.get_name().strip(),
                        "element": el,
                        "coord": np.array(atom.get_coord(), dtype=float),
                    }
                )
    return atoms


def _detect_ligand_aromatic_centroids(lig_pdb: str) -> List[np.ndarray]:
    """Use RDKit to locate exact aromatic ring centroids in the ligand."""
    centroids: List[np.ndarray] = []
    try:
        from rdkit import Chem

        mol = Chem.MolFromPDBBlock(lig_pdb, sanitize=True, removeHs=True)
        if mol is None:
            return centroids
        conf = mol.GetConformer()
        for ring in mol.GetRingInfo().AtomRings():
            if all(mol.GetAtomWithIdx(i).GetIsAromatic() for i in ring):
                pts = np.array([list(conf.GetAtomPosition(i)) for i in ring], dtype=float)
                centroids.append(pts.mean(axis=0))
    except Exception:
        pass
    return centroids


def _detect_protein_aromatic_rings(prot_atoms) -> List[Tuple[str, str, int, str, np.ndarray]]:
    rings = []
    by_res = defaultdict(list)
    for a in prot_atoms:
        if a["resname"] in AROMATIC_RESIDUES and a["name"] not in {"N", "CA", "C", "O", "CB"}:
            by_res[(a["residue"], a["resname"], a["resseq"], a["chain"])].append(a["coord"])
    for (residue, resname, resseq, chain), coords in by_res.items():
        if len(coords) >= 5:
            rings.append((residue, resname, resseq, chain, np.mean(coords, axis=0)))
    return rings


def _build_2d_diagram_mapping(
    query_pdb: str, query_sdf: Optional[str] = None
) -> Tuple[Optional[str], List[Tuple[np.ndarray, Tuple[float, float]]], List[Tuple[np.ndarray, Tuple[float, float]]]]:
    """
    Generate a 440x280 RDKit 2D SVG of the docked ligand and return exact 3D->2D pixel
    mappings for every heavy atom and aromatic ring centroid.
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
        from rdkit.Chem.Draw import rdMolDraw2D

        mol_3d = None
        # 1a. Best (works in slim Docker too): OpenBabel CLI perceives bond orders & aromaticity from 3D PDB
        import shutil
        import subprocess
        obabel_exe = shutil.which("obabel")
        if obabel_exe:
            try:
                res = subprocess.run(
                    [obabel_exe, "-ipdb", "-omol"],
                    input=query_pdb,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if res.returncode == 0 and res.stdout.strip():
                    mol_3d = Chem.MolFromMolBlock(res.stdout, sanitize=True, removeHs=True)
            except Exception:
                mol_3d = None

        # 1b. OpenBabel Python API (pybel)
        if mol_3d is None:
            try:
                from openbabel import pybel

                ob_mol = pybel.readstring("pdb", query_pdb)
                mol_block = ob_mol.write("mol")
                mol_3d = Chem.MolFromMolBlock(mol_block, sanitize=True, removeHs=True)
            except Exception:
                mol_3d = None

        # 2. Fallback: RDKit PDB + template bond orders from query_ligand.sdf
        if mol_3d is None:
            raw_mol = Chem.MolFromPDBBlock(query_pdb, sanitize=False, removeHs=True)
            if raw_mol is not None and query_sdf:
                tmpl = Chem.MolFromMolBlock(query_sdf, sanitize=True, removeHs=True)
                if tmpl is not None:
                    try:
                        mol_3d = AllChem.AssignBondOrdersFromTemplate(tmpl, raw_mol)
                    except Exception:
                        mol_3d = raw_mol
            else:
                mol_3d = raw_mol

        if mol_3d is None or mol_3d.GetNumConformers() == 0:
            return None, [], []

        conf3d = mol_3d.GetConformer()
        atom_3d_coords = [
            np.array(list(conf3d.GetAtomPosition(i)), dtype=float)
            for i in range(mol_3d.GetNumAtoms())
        ]

        # Compute aromatic ring 3D centroids before overwriting conformer with 2D coords
        aromatic_rings: List[Tuple[List[int], np.ndarray]] = []
        try:
            for ring in mol_3d.GetRingInfo().AtomRings():
                if all(mol_3d.GetAtomWithIdx(i).GetIsAromatic() for i in ring):
                    pts = np.array([atom_3d_coords[i] for i in ring], dtype=float)
                    aromatic_rings.append((list(ring), pts.mean(axis=0)))
        except Exception:
            pass

        mol_2d = Chem.Mol(mol_3d)
        AllChem.Compute2DCoords(mol_2d)

        drawer = rdMolDraw2D.MolDraw2DSVG(440, 280)
        opts = drawer.drawOptions()
        opts.clearBackground = False
        opts.padding = 0.08
        drawer.DrawMolecule(mol_2d)
        drawer.FinishDrawing()
        svg_text = drawer.GetDrawingText()

        atom_map: List[Tuple[np.ndarray, Tuple[float, float]]] = []
        for i in range(mol_2d.GetNumAtoms()):
            pt = drawer.GetDrawCoords(i)
            atom_map.append((atom_3d_coords[i], (round(float(pt.x), 2), round(float(pt.y), 2))))

        ring_map: List[Tuple[np.ndarray, Tuple[float, float]]] = []
        for ring_indices, cent_3d in aromatic_rings:
            pts_2d = [drawer.GetDrawCoords(i) for i in ring_indices]
            cx_2d = round(float(np.mean([p.x for p in pts_2d])), 2)
            cy_2d = round(float(np.mean([p.y for p in pts_2d])), 2)
            ring_map.append((cent_3d, (cx_2d, cy_2d)))

        return svg_text, atom_map, ring_map
    except Exception:
        return None, [], []


def _attach_2d_coords(
    interactions: List[InteractionItem],
    atom_map: List[Tuple[np.ndarray, Tuple[float, float]]],
    ring_map: List[Tuple[np.ndarray, Tuple[float, float]]],
) -> None:
    if not atom_map:
        return
    atom_xyzs = np.array([a[0] for a in atom_map], dtype=float)
    ring_xyzs = np.array([r[0] for r in ring_map], dtype=float) if ring_map else None

    for item in interactions:
        if not item.ligand_coord or len(item.ligand_coord) != 3:
            continue
        target = np.array(item.ligand_coord, dtype=float)
        if item.interaction_type == "Pi-Stacking" and ring_xyzs is not None and len(ring_xyzs) > 0:
            idx = int(np.argmin(np.linalg.norm(ring_xyzs - target, axis=1)))
            px, py = ring_map[idx][1]
            item.ligand_2d_coord = [px, py]
        else:
            idx = int(np.argmin(np.linalg.norm(atom_xyzs - target, axis=1)))
            px, py = atom_map[idx][1]
            item.ligand_2d_coord = [px, py]


def profile_interactions(receptor_pdb: str, ligand_pdb: str) -> List[InteractionItem]:
    """PLIP-compatible geometric non-covalent interaction profiler."""
    prot_atoms = _parse_atoms(receptor_pdb)
    lig_atoms = _parse_atoms(ligand_pdb)
    if not prot_atoms or not lig_atoms:
        return []

    prot_coords = np.array([a["coord"] for a in prot_atoms])
    lig_coords = np.array([a["coord"] for a in lig_atoms])

    # Pre-filter protein atoms within 6.0 A of any ligand atom for speed
    dists_all = np.linalg.norm(prot_coords[:, None, :] - lig_coords[None, :, :], axis=-1)
    min_d_per_prot = dists_all.min(axis=1)
    near_indices = np.where(min_d_per_prot <= 6.0)[0]

    best_per_pair: Dict[Tuple[str, str], InteractionItem] = {}

    def _record(item: InteractionItem):
        key = (item.residue, item.interaction_type)
        if key not in best_per_pair or item.distance < best_per_pair[key].distance:
            best_per_pair[key] = item

    for pi in near_indices:
        pa = prot_atoms[pi]
        for li, la in enumerate(lig_atoms):
            d = float(dists_all[pi, li])
            if d > 5.5:
                continue

            l_xyz = [round(float(x), 3) for x in la["coord"]]
            p_xyz = [round(float(x), 3) for x in pa["coord"]]

            # 1. Metal Coordination (<= 2.8 A)
            if pa["element"] in METAL_ELEMENTS and la["element"] in POLAR_ELEMENTS and d <= 2.8:
                _record(
                    InteractionItem(
                        interaction_type="Metal Coordination",
                        residue=pa["residue"],
                        resname=pa["resname"],
                        resseq=pa["resseq"],
                        chain=pa["chain"],
                        distance=round(d, 2),
                        ligand_atom=la["name"],
                        protein_atom=pa["name"],
                        ligand_coord=l_xyz,
                        protein_coord=p_xyz,
                    )
                )
                continue

            # 2. Salt Bridge (charged protein sidechain + polar ligand atom <= 4.0 A)
            if (
                (pa["resname"] in POS_CHARGED_RESIDUES and pa["element"] == "N" and la["element"] == "O")
                or (pa["resname"] in NEG_CHARGED_RESIDUES and pa["element"] == "O" and la["element"] == "N")
            ) and pa["name"] not in {"N", "O"} and d <= 4.0:
                _record(
                    InteractionItem(
                        interaction_type="Salt Bridge",
                        residue=pa["residue"],
                        resname=pa["resname"],
                        resseq=pa["resseq"],
                        chain=pa["chain"],
                        distance=round(d, 2),
                        ligand_atom=la["name"],
                        protein_atom=pa["name"],
                        ligand_coord=l_xyz,
                        protein_coord=p_xyz,
                    )
                )

            # 3. Hydrogen Bond (N/O/F/S to N/O/F <= 3.5 A)
            if pa["element"] in {"N", "O", "S"} and la["element"] in {"N", "O", "F"} and d <= 3.5:
                _record(
                    InteractionItem(
                        interaction_type="H-Bond",
                        residue=pa["residue"],
                        resname=pa["resname"],
                        resseq=pa["resseq"],
                        chain=pa["chain"],
                        distance=round(d, 2),
                        ligand_atom=la["name"],
                        protein_atom=pa["name"],
                        ligand_coord=l_xyz,
                        protein_coord=p_xyz,
                    )
                )

            # 4. Halogen Bond (Cl/Br/I to O/N/S <= 3.8 A)
            if la["element"] in HALOGEN_ELEMENTS and pa["element"] in {"O", "N", "S"} and d <= 3.8:
                _record(
                    InteractionItem(
                        interaction_type="Halogen Bond",
                        residue=pa["residue"],
                        resname=pa["resname"],
                        resseq=pa["resseq"],
                        chain=pa["chain"],
                        distance=round(d, 2),
                        ligand_atom=la["name"],
                        protein_atom=pa["name"],
                        ligand_coord=l_xyz,
                        protein_coord=p_xyz,
                    )
                )

            # 5. Hydrophobic Contact (C to C <= 4.0 A)
            if pa["element"] == "C" and la["element"] == "C" and d <= 4.0:
                _record(
                    InteractionItem(
                        interaction_type="Hydrophobic",
                        residue=pa["residue"],
                        resname=pa["resname"],
                        resseq=pa["resseq"],
                        chain=pa["chain"],
                        distance=round(d, 2),
                        ligand_atom=la["name"],
                        protein_atom=pa["name"],
                        ligand_coord=l_xyz,
                        protein_coord=p_xyz,
                    )
                )

    # 6. Pi-Stacking (aromatic ring centroid to centroid <= 5.5 A)
    lig_rings = _detect_ligand_aromatic_centroids(ligand_pdb)
    if lig_rings:
        prot_rings = _detect_protein_aromatic_rings([prot_atoms[i] for i in near_indices])
        for residue, resname, resseq, chain, p_cent in prot_rings:
            for idx, l_cent in enumerate(lig_rings, start=1):
                d = float(np.linalg.norm(p_cent - l_cent))
                if d <= 5.5:
                    _record(
                        InteractionItem(
                            interaction_type="Pi-Stacking",
                            residue=residue,
                            resname=resname,
                            resseq=resseq,
                            chain=chain,
                            distance=round(d, 2),
                            ligand_atom=f"Ring{idx}",
                            protein_atom="AromRing",
                            ligand_coord=[round(float(x), 3) for x in l_cent],
                            protein_coord=[round(float(x), 3) for x in p_cent],
                        )
                    )

    results = list(best_per_pair.values())
    priority = {
        "H-Bond": 0,
        "Salt Bridge": 1,
        "Metal Coordination": 2,
        "Pi-Stacking": 3,
        "Halogen Bond": 4,
        "Hydrophobic": 5,
    }
    results.sort(key=lambda x: (priority.get(x.interaction_type, 9), x.distance))
    return results


def run_comparative_analysis(req: ComparativeAnalysisRequest) -> ComparativeAnalysisResponse:
    receptor_pdb = job_store.read_text(req.session_id, "receptor_prepared.pdb")
    query_pdb = job_store.read_text(req.session_id, f"docked_pose_{req.pose_mode}.pdb")
    native_pdb = job_store.read_text(req.session_id, "native_ligand.pdb")

    if not receptor_pdb or not query_pdb:
        raise FileNotFoundError("Docking results not found for this session/pose.")

    meta = job_store.load_meta(req.session_id)
    ligand_name = meta.get("ligand_name", "Query Ligand")
    poses_aff = meta.get("poses_affinities", {})
    query_affinity = float(poses_aff.get(str(req.pose_mode), 0.0))
    native_score: Optional[float] = meta.get("native_score")

    query_interactions = profile_interactions(receptor_pdb, query_pdb)
    native_interactions = profile_interactions(receptor_pdb, native_pdb) if native_pdb else []

    query_sdf = job_store.read_text(req.session_id, "query_ligand.sdf")
    diagram_svg, atom_map_2d, ring_map_2d = _build_2d_diagram_mapping(query_pdb, query_sdf)
    _attach_2d_coords(query_interactions, atom_map_2d, ring_map_2d)

    if not native_pdb:
        hbonds = [i for i in query_interactions if i.interaction_type == "H-Bond"]
        h_res = ", ".join(i.residue for i in hbonds[:4]) or "none detected"
        summary_en = (
            f"{ligand_name} (Pose #{req.pose_mode}) achieved a predicted binding affinity of {query_affinity:.2f} kcal/mol, "
            f"forming {len(query_interactions)} total non-covalent interactions including {len(hbonds)} hydrogen bonds ({h_res}). "
            f"No co-crystallized reference ligand was selected for side-by-side benchmarking."
        )
        summary_ar = (
            f"المركب {ligand_name} (الوضعية #{req.pose_mode}) حقق طاقة ارتباط متوقعة {query_affinity:.2f} kcal/mol، "
            f"وكوّن إجمالي {len(query_interactions)} تفاعل غير تساهمي منها {len(hbonds)} روابط هيدروجينية مع ({h_res}). "
            f"لم يتم تحديد Original Ligand للمقارنة المرجعية."
        )
        return ComparativeAnalysisResponse(
            session_id=req.session_id,
            pose_mode=req.pose_mode,
            ligand_name=ligand_name,
            has_native_reference=False,
            query_affinity=query_affinity,
            native_score=None,
            delta_affinity=None,
            interaction_similarity_pct=None,
            query_interactions=query_interactions,
            key_findings=[
                f"Predicted Binding Affinity: {query_affinity:.2f} kcal/mol",
                f"Total Non-Covalent Contacts: {len(query_interactions)} ({len(hbonds)} H-Bonds)",
            ],
            diagram_ligand_svg=diagram_svg,
            summary_en=summary_en,
            summary_ar=summary_ar,
        )

    # Build Residue-by-Residue Comparison Matrix
    native_by_res: Dict[str, List[InteractionItem]] = defaultdict(list)
    query_by_res: Dict[str, List[InteractionItem]] = defaultdict(list)
    for item in native_interactions:
        native_by_res[item.residue].append(item)
    for item in query_interactions:
        query_by_res[item.residue].append(item)

    all_residues = sorted(set(native_by_res.keys()) | set(query_by_res.keys()))
    comparison: List[ResidueComparison] = []
    retained_res, gained_res, lost_res = [], [], []

    for res in all_residues:
        n_items = native_by_res.get(res, [])
        q_items = query_by_res.get(res, [])
        n_types = sorted({i.interaction_type for i in n_items})
        q_types = sorted({i.interaction_type for i in q_items})
        n_min = min((i.distance for i in n_items), default=None)
        q_min = min((i.distance for i in q_items), default=None)

        if n_items and q_items:
            status = "retained"
            retained_res.append(res)
        elif q_items:
            status = "gained"
            gained_res.append(res)
        else:
            status = "lost"
            lost_res.append(res)

        comparison.append(
            ResidueComparison(
                residue=res,
                status=status,
                native_interactions=n_types,
                query_interactions=q_types,
                best_distance_native=n_min,
                best_distance_query=q_min,
            )
        )

    # Sort: retained first, then gained, then lost
    status_order = {"retained": 0, "gained": 1, "lost": 2}
    comparison.sort(key=lambda c: (status_order[c.status], c.residue))

    # Tanimoto Interaction Fingerprint Similarity on (residue, interaction_type) pairs
    native_fp: Set[Tuple[str, str]] = {(i.residue, i.interaction_type) for i in native_interactions}
    query_fp: Set[Tuple[str, str]] = {(i.residue, i.interaction_type) for i in query_interactions}
    union_len = len(native_fp | query_fp)
    sim_pct = round((len(native_fp & query_fp) / union_len) * 100.0, 1) if union_len else 0.0

    delta_aff = round(query_affinity - native_score, 2) if native_score is not None else None

    # Generate Actionable Findings & Scientific Summaries
    findings: List[str] = []
    if delta_aff is not None:
        if delta_aff <= -0.5:
            findings.append(
                f"Stronger predicted affinity than native ligand by {abs(delta_aff):.2f} kcal/mol ({query_affinity:.2f} vs {native_score:.2f} kcal/mol)."
            )
        elif delta_aff >= 0.5:
            findings.append(
                f"Weaker predicted affinity than native ligand by {delta_aff:.2f} kcal/mol ({query_affinity:.2f} vs {native_score:.2f} kcal/mol)."
            )
        else:
            findings.append(
                f"Comparable predicted affinity to native ligand ({query_affinity:.2f} vs {native_score:.2f} kcal/mol; Δ = {delta_aff:+.2f})."
            )

    findings.append(
        f"Interaction Fingerprint Overlap: {sim_pct:.1f}% ({len(retained_res)} retained, {len(gained_res)} gained, {len(lost_res)} lost binding-site residues)."
    )

    q_hbonds = [i for i in query_interactions if i.interaction_type == "H-Bond"]
    n_hbonds = [i for i in native_interactions if i.interaction_type == "H-Bond"]
    findings.append(
        f"Hydrogen Bonds: {len(q_hbonds)} in query vs {len(n_hbonds)} in native ligand."
    )

    ret_str = ", ".join(retained_res[:4]) if retained_res else "none"
    gain_str = ", ".join(gained_res[:4]) if gained_res else "none"
    lost_str = ", ".join(lost_res[:4]) if lost_res else "none"

    aff_phrase_en = (
        f"outperforming the native co-crystallized ligand by {abs(delta_aff):.2f} kcal/mol ({query_affinity:.2f} vs {native_score:.2f} kcal/mol)"
        if delta_aff is not None and delta_aff < -0.2
        else (
            f"showing comparable binding affinity to the native ligand ({query_affinity:.2f} vs {native_score:.2f} kcal/mol)"
            if delta_aff is not None and abs(delta_aff) <= 0.2
            else (
                f"with slightly weaker predicted affinity than the native ligand ({query_affinity:.2f} vs {native_score:.2f} kcal/mol)"
                if delta_aff is not None
                else f"with a predicted Vina binding affinity of {query_affinity:.2f} kcal/mol"
            )
        )
    )

    summary_en = (
        f"In Pose #{req.pose_mode}, {ligand_name} binds within the active site {aff_phrase_en}. "
        f"It achieves a {sim_pct:.1f}% interaction fingerprint similarity with the native ligand, "
        f"retaining key contacts with {len(retained_res)} residues ({ret_str}), "
        f"gaining {len(gained_res)} new interactions ({gain_str}), and losing {len(lost_res)} native contacts ({lost_str})."
    )

    aff_phrase_ar = (
        f"متفوقاً على الـ Original Ligand بمقدار {abs(delta_aff):.2f} kcal/mol ({query_affinity:.2f} مقابل {native_score:.2f} kcal/mol)"
        if delta_aff is not None and delta_aff < -0.2
        else (
            f"بطاقة ارتباط مقاربة جداً للـ Original Ligand ({query_affinity:.2f} مقابل {native_score:.2f} kcal/mol)"
            if delta_aff is not None and abs(delta_aff) <= 0.2
            else (
                f"بطاقة ارتباط أقل قليلاً من الـ Original Ligand ({query_affinity:.2f} مقابل {native_score:.2f} kcal/mol)"
                if delta_aff is not None
                else f"بطاقة ارتباط متوقعة {query_affinity:.2f} kcal/mol"
            )
        )
    )

    summary_ar = (
        f"في الوضعية #{req.pose_mode}، ارتبط المركب {ligand_name} داخل الموقع النشط {aff_phrase_ar}. "
        f"حقق المركب نسبة تشابه في البصمة التفاعلية قدرها {sim_pct:.1f}% مقارنة بالمركب الأصلي؛ "
        f"حيث حافظ على التفاعل مع {len(retained_res)} أحماض أمينية أساسية ({ret_str})، "
        f"واكتسب {len(gained_res)} تفاعلات جديدة ({gain_str})، بينما فقد {len(lost_res)} تفاعلات كانت موجودة في الأصلي ({lost_str})."
    )

    return ComparativeAnalysisResponse(
        session_id=req.session_id,
        pose_mode=req.pose_mode,
        ligand_name=ligand_name,
        has_native_reference=True,
        query_affinity=query_affinity,
        native_score=native_score,
        delta_affinity=delta_aff,
        interaction_similarity_pct=sim_pct,
        retained_count=len(retained_res),
        gained_count=len(gained_res),
        lost_count=len(lost_res),
        native_interactions=native_interactions,
        query_interactions=query_interactions,
        residue_comparison=comparison,
        key_findings=findings,
        diagram_ligand_svg=diagram_svg,
        summary_en=summary_en,
        summary_ar=summary_ar,
    )
