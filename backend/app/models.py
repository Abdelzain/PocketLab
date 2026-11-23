from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class ChainInfo(BaseModel):
    chain_id: str
    residue_count: int
    atom_count: int


class HeteroGroupInfo(BaseModel):
    id: str  # e.g. "A:STI:501"
    resname: str
    chain_id: str
    resseq: int
    atom_count: int
    category: Literal["ligand", "cofactor", "ion", "solvent_artifact"]
    formula_hint: str = ""


class ProteinInspectResponse(BaseModel):
    session_id: str
    title: str
    pdb_id: Optional[str] = None
    chains: List[ChainInfo]
    ligands: List[HeteroGroupInfo]
    ions: List[HeteroGroupInfo]
    water_count: int
    raw_pdb: str


class ProteinPrepareRequest(BaseModel):
    session_id: str
    keep_chains: List[str]
    remove_waters: bool = True
    keep_waters_within_angstrom: Optional[float] = None
    keep_ions: List[str] = Field(default_factory=list)  # list of HeteroGroupInfo.id
    extract_native_ligand_id: Optional[str] = None      # HeteroGroupInfo.id
    add_hydrogens: bool = True
    ph: float = 7.4


class ProteinPrepareResponse(BaseModel):
    session_id: str
    prepared_pdb: str
    native_ligand_pdb: Optional[str] = None
    native_ligand_id: Optional[str] = None
    native_ligand_smiles: Optional[str] = None
    atom_count: int
    water_kept_count: int
    ions_kept_count: int
    warnings: List[str] = Field(default_factory=list)


class LigandProperties(BaseModel):
    molecular_formula: str
    molecular_weight: float
    clogp: float
    tpsa: float
    hbd: int
    hba: int
    rotatable_bonds: int
    qed: float
    lipinski_violations: int
    pains_alerts: List[str] = Field(default_factory=list)


class LigandPrepareRequest(BaseModel):
    session_id: str
    name: str = "Query Ligand"
    smiles: Optional[str] = None
    molblock: Optional[str] = None
    minimize: bool = True


class LigandPrepareResponse(BaseModel):
    session_id: str
    name: str
    canonical_smiles: str
    pdb_block: str
    svg_2d: str
    properties: LigandProperties


class GridBox(BaseModel):
    center_x: float
    center_y: float
    center_z: float
    size_x: float = 20.0
    size_y: float = 20.0
    size_z: float = 20.0


class PocketCandidate(BaseModel):
    pocket_id: int
    label: str
    source: Literal["native_ligand", "geometric_cavity"]
    score: float
    volume_est: float
    box: GridBox
    residues: List[str] = Field(default_factory=list)


class PocketDetectRequest(BaseModel):
    session_id: str
    padding: float = 6.0


class PocketDetectResponse(BaseModel):
    session_id: str
    pockets: List[PocketCandidate]
    recommended_box: GridBox


class RedockValidationRequest(BaseModel):
    session_id: str
    box: GridBox
    exhaustiveness: int = 8


class RedockValidationResponse(BaseModel):
    session_id: str
    rmsd: float
    passed: bool
    native_score: float
    redocked_affinity: float
    redocked_pdb: str
    message: str


class DockingRunRequest(BaseModel):
    session_id: str
    box: GridBox
    exhaustiveness: int = 8
    num_modes: int = 9


class DockingPose(BaseModel):
    mode: int
    affinity: float
    rmsd_lb: float
    rmsd_ub: float
    pdb_block: str


class DockingRunResponse(BaseModel):
    session_id: str
    ligand_name: str
    poses: List[DockingPose]
    native_score: Optional[float] = None
    box: GridBox
    exhaustiveness: int


class DockingInputsResponse(BaseModel):
    session_id: str
    ligand_name: str
    receptor_pdbqt: str
    query_ligand_pdbqt: Optional[str] = None
    native_ligand_pdbqt: Optional[str] = None


class DockingIngestRequest(BaseModel):
    session_id: str
    poses_pdbqt: str
    stdout: str = ""
    box: GridBox
    exhaustiveness: int = 8
    native_score: Optional[float] = None


class RedockIngestRequest(BaseModel):
    session_id: str
    redocked_pdbqt: str
    stdout: str = ""
    native_score: Optional[float] = None


class InteractionItem(BaseModel):
    interaction_type: Literal[
        "H-Bond",
        "Hydrophobic",
        "Pi-Stacking",
        "Salt Bridge",
        "Halogen Bond",
        "Metal Coordination",
    ]
    residue: str  # e.g., "ASP123 (A)"
    resname: str
    resseq: int
    chain: str
    distance: float
    ligand_atom: str
    protein_atom: str
    ligand_coord: List[float] = Field(default_factory=list)
    protein_coord: List[float] = Field(default_factory=list)
    ligand_2d_coord: List[float] = Field(default_factory=list)


class ResidueComparison(BaseModel):
    residue: str
    status: Literal["retained", "gained", "lost"]
    native_interactions: List[str]
    query_interactions: List[str]
    best_distance_native: Optional[float] = None
    best_distance_query: Optional[float] = None


class ComparativeAnalysisRequest(BaseModel):
    session_id: str
    pose_mode: int = 1


class ComparativeAnalysisResponse(BaseModel):
    session_id: str
    pose_mode: int
    ligand_name: str
    has_native_reference: bool
    query_affinity: float
    native_score: Optional[float] = None
    delta_affinity: Optional[float] = None
    interaction_similarity_pct: Optional[float] = None
    retained_count: int = 0
    gained_count: int = 0
    lost_count: int = 0
    native_interactions: List[InteractionItem] = Field(default_factory=list)
    query_interactions: List[InteractionItem] = Field(default_factory=list)
    residue_comparison: List[ResidueComparison] = Field(default_factory=list)
    key_findings: List[str] = Field(default_factory=list)
    diagram_ligand_svg: Optional[str] = None
    summary_en: str
    summary_ar: str
