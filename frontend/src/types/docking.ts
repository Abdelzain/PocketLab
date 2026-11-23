export interface ChainInfo {
  chain_id: string;
  residue_count: number;
  atom_count: number;
}

export interface HeteroGroupInfo {
  id: string;
  resname: string;
  chain_id: string;
  resseq: number;
  atom_count: number;
  category: 'ligand' | 'cofactor' | 'ion' | 'solvent_artifact';
  formula_hint: string;
}

export interface ProteinInspectResponse {
  session_id: string;
  title: string;
  pdb_id?: string | null;
  chains: ChainInfo[];
  ligands: HeteroGroupInfo[];
  ions: HeteroGroupInfo[];
  water_count: number;
  raw_pdb: string;
}

export interface ProteinPrepareResponse {
  session_id: string;
  prepared_pdb: string;
  native_ligand_pdb?: string | null;
  native_ligand_id?: string | null;
  native_ligand_smiles?: string | null;
  atom_count: number;
  water_kept_count: number;
  ions_kept_count: number;
  warnings: string[];
}

export interface LigandProperties {
  molecular_formula: string;
  molecular_weight: number;
  clogp: number;
  tpsa: number;
  hbd: number;
  hba: number;
  rotatable_bonds: number;
  qed: number;
  lipinski_violations: number;
  pains_alerts: string[];
}

export interface LigandPrepareResponse {
  session_id: string;
  name: string;
  canonical_smiles: string;
  pdb_block: string;
  svg_2d: string;
  properties: LigandProperties;
}

export interface GridBox {
  center_x: number;
  center_y: number;
  center_z: number;
  size_x: number;
  size_y: number;
  size_z: number;
}

export interface PocketCandidate {
  pocket_id: number;
  label: string;
  source: 'native_ligand' | 'geometric_cavity';
  score: number;
  volume_est: number;
  box: GridBox;
  residues: string[];
}

export interface PocketDetectResponse {
  session_id: string;
  pockets: PocketCandidate[];
  recommended_box: GridBox;
}

export interface RedockValidationResponse {
  session_id: string;
  rmsd: number;
  passed: boolean;
  native_score: number;
  redocked_affinity: number;
  redocked_pdb: string;
  message: string;
}

export interface DockingPose {
  mode: number;
  affinity: number;
  rmsd_lb: number;
  rmsd_ub: number;
  pdb_block: string;
}

export interface DockingRunResponse {
  session_id: string;
  ligand_name: string;
  poses: DockingPose[];
  native_score?: number | null;
  box: GridBox;
  exhaustiveness: number;
}

export interface InteractionItem {
  interaction_type:
    | 'H-Bond'
    | 'Hydrophobic'
    | 'Pi-Stacking'
    | 'Salt Bridge'
    | 'Halogen Bond'
    | 'Metal Coordination';
  residue: string;
  resname: string;
  resseq: number;
  chain: string;
  distance: number;
  ligand_atom: string;
  protein_atom: string;
  ligand_coord?: number[];
  protein_coord?: number[];
  ligand_2d_coord?: number[];
}

export interface ResidueComparison {
  residue: string;
  status: 'retained' | 'gained' | 'lost';
  native_interactions: string[];
  query_interactions: string[];
  best_distance_native?: number | null;
  best_distance_query?: number | null;
}

export interface ComparativeAnalysisResponse {
  session_id: string;
  pose_mode: number;
  ligand_name: string;
  has_native_reference: boolean;
  query_affinity: number;
  native_score?: number | null;
  delta_affinity?: number | null;
  interaction_similarity_pct?: number | null;
  retained_count: number;
  gained_count: number;
  lost_count: number;
  native_interactions: InteractionItem[];
  query_interactions: InteractionItem[];
  residue_comparison: ResidueComparison[];
  key_findings: string[];
  diagram_ligand_svg?: string | null;
  summary_en: string;
  summary_ar: string;
}
