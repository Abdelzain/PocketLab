import io
from typing import List
import numpy as np
from Bio.PDB import PDBParser
from scipy.spatial import cKDTree
from scipy.ndimage import label

from app.models import GridBox, PocketCandidate, PocketDetectRequest, PocketDetectResponse
from app.utils import job_store


def _nearby_residues(receptor_pdb: str, center: np.ndarray, radius: float = 6.0) -> List[str]:
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("rec", io.StringIO(receptor_pdb))
    model = next(structure.get_models())
    found = []
    seen = set()
    for chain in model.get_chains():
        for res in chain.get_residues():
            if res.id[0] != " ":
                continue
            for atom in res.get_atoms():
                if float(np.linalg.norm(atom.get_coord() - center)) <= radius:
                    label_str = f"{res.get_resname().strip()}{res.id[1]} ({chain.id})"
                    if label_str not in seen:
                        seen.add(label_str)
                        found.append(label_str)
                    break
    return found[:25]


def _box_from_native_ligand(native_pdb: str, receptor_pdb: str, padding: float) -> PocketCandidate:
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("lig", io.StringIO(native_pdb))
    coords = np.array([a.get_coord() for a in structure.get_atoms() if a.element != "H"])
    if len(coords) == 0:
        coords = np.array([a.get_coord() for a in structure.get_atoms()])

    min_c = coords.min(axis=0)
    max_c = coords.max(axis=0)
    center = (min_c + max_c) / 2.0
    span = (max_c - min_c) + 2.0 * padding
    size = np.clip(span, 16.0, 32.0)

    box = GridBox(
        center_x=round(float(center[0]), 2),
        center_y=round(float(center[1]), 2),
        center_z=round(float(center[2]), 2),
        size_x=round(float(size[0]), 1),
        size_y=round(float(size[1]), 1),
        size_z=round(float(size[2]), 1),
    )
    residues = _nearby_residues(receptor_pdb, center, radius=float(max(span) / 2.0))
    vol = round(float(np.prod(max_c - min_c + 4.0)), 1)

    return PocketCandidate(
        pocket_id=1,
        label="Co-Crystallized Active Site (Native Ligand)",
        source="native_ligand",
        score=0.99,
        volume_est=vol,
        box=box,
        residues=residues,
    )


def _detect_geometric_cavities(receptor_pdb: str, max_pockets: int = 5) -> List[PocketCandidate]:
    """Fast pure-NumPy/SciPy buried-cavity detector for Apo / AlphaFold structures."""
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("rec", io.StringIO(receptor_pdb))
    coords = np.array([a.get_coord() for a in structure.get_atoms() if a.element != "H"])
    if len(coords) == 0:
        raise ValueError("Prepared receptor has no heavy atoms.")

    tree = cKDTree(coords)
    min_c = coords.min(axis=0) - 2.0
    max_c = coords.max(axis=0) + 2.0
    step = 2.5

    xs = np.arange(min_c[0], max_c[0], step)
    ys = np.arange(min_c[1], max_c[1], step)
    zs = np.arange(min_c[2], max_c[2], step)
    grid = np.stack(np.meshgrid(xs, ys, zs, indexing="ij"), axis=-1)
    pts = grid.reshape(-1, 3)

    # Points that are free of steric clashes (> 2.8 A) yet close to protein (< 5.5 A)
    d_near, _ = tree.query(pts, k=1)
    free_mask = (d_near >= 2.8) & (d_near <= 5.5)

    # Buriedness: count protein atoms within 9.5 A
    buried_mask = np.zeros(len(pts), dtype=bool)
    free_indices = np.where(free_mask)[0]
    if len(free_indices) > 0:
        counts = tree.query_ball_point(pts[free_indices], r=9.5, return_length=True)
        buried_mask[free_indices] = counts >= 28

    mask_3d = buried_mask.reshape(grid.shape[:3])
    labeled, num_features = label(mask_3d)

    candidates: List[PocketCandidate] = []
    voxel_vol = step ** 3
    for comp_id in range(1, num_features + 1):
        idxs = np.argwhere(labeled == comp_id)
        if len(idxs) < 6:
            continue
        comp_pts = grid[idxs[:, 0], idxs[:, 1], idxs[:, 2]]
        center = comp_pts.mean(axis=0)
        span = (comp_pts.max(axis=0) - comp_pts.min(axis=0)) + 10.0
        size = np.clip(span, 18.0, 30.0)
        vol = round(float(len(idxs) * voxel_vol), 1)
        score = round(min(0.95, 0.40 + len(idxs) / 120.0), 2)

        box = GridBox(
            center_x=round(float(center[0]), 2),
            center_y=round(float(center[1]), 2),
            center_z=round(float(center[2]), 2),
            size_x=round(float(size[0]), 1),
            size_y=round(float(size[1]), 1),
            size_z=round(float(size[2]), 1),
        )
        candidates.append(
            PocketCandidate(
                pocket_id=comp_id,
                label=f"Predicted Pocket #{comp_id}",
                source="geometric_cavity",
                score=score,
                volume_est=vol,
                box=box,
                residues=_nearby_residues(receptor_pdb, center, radius=7.0),
            )
        )

    candidates.sort(key=lambda p: (-p.volume_est, -p.score))
    candidates = candidates[:max_pockets]
    for i, c in enumerate(candidates, start=1):
        c.pocket_id = i
        c.label = f"Predicted Pocket #{i}"

    if not candidates:
        center = coords.mean(axis=0)
        box = GridBox(
            center_x=round(float(center[0]), 2),
            center_y=round(float(center[1]), 2),
            center_z=round(float(center[2]), 2),
            size_x=24.0,
            size_y=24.0,
            size_z=24.0,
        )
        candidates.append(
            PocketCandidate(
                pocket_id=1,
                label="Global Protein Center (Fallback)",
                source="geometric_cavity",
                score=0.5,
                volume_est=0.0,
                box=box,
                residues=_nearby_residues(receptor_pdb, center, radius=8.0),
            )
        )

    return candidates


def detect_pockets(req: PocketDetectRequest) -> PocketDetectResponse:
    receptor_pdb = job_store.read_text(req.session_id, "receptor_prepared.pdb")
    if not receptor_pdb:
        raise FileNotFoundError("Please prepare the protein first (Step 1).")

    native_pdb = job_store.read_text(req.session_id, "native_ligand.pdb")
    pockets: List[PocketCandidate] = []

    if native_pdb:
        pockets.append(_box_from_native_ligand(native_pdb, receptor_pdb, req.padding))

    # Also compute top geometric cavities as secondary options
    try:
        cavities = _detect_geometric_cavities(receptor_pdb, max_pockets=4 if native_pdb else 5)
        start_idx = len(pockets) + 1
        for offset, cav in enumerate(cavities):
            cav.pocket_id = start_idx + offset
            pockets.append(cav)
    except Exception:
        if not pockets:
            raise

    return PocketDetectResponse(
        session_id=req.session_id,
        pockets=pockets,
        recommended_box=pockets[0].box,
    )
