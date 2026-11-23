import type {
  ComparativeAnalysisResponse,
  DockingRunResponse,
  GridBox,
  LigandPrepareResponse,
  PocketDetectResponse,
  ProteinInspectResponse,
  ProteinPrepareResponse,
  RedockValidationResponse,
} from '../types/docking';

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (data?.detail) detail = data.detail;
    } catch {
      // ignore json parse error
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  fetchProtein(pdb_id: string): Promise<ProteinInspectResponse> {
    return request('/api/protein/fetch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pdb_id }),
    });
  },

  uploadProtein(file: File): Promise<ProteinInspectResponse> {
    const form = new FormData();
    form.append('file', file);
    return request('/api/protein/upload', {
      method: 'POST',
      body: form,
    });
  },

  prepareProtein(payload: {
    session_id: string;
    keep_chains: string[];
    remove_waters: boolean;
    keep_waters_within_angstrom?: number | null;
    keep_ions: string[];
    extract_native_ligand_id?: string | null;
    add_hydrogens: boolean;
    ph: number;
  }): Promise<ProteinPrepareResponse> {
    return request('/api/protein/prepare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },

  lookupPubChem(query: string): Promise<{ smiles: string; name: string }> {
    return request('/api/ligand/pubchem', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });
  },

  prepareLigand(payload: {
    session_id: string;
    name: string;
    smiles?: string | null;
    molblock?: string | null;
    minimize: boolean;
  }): Promise<LigandPrepareResponse> {
    return request('/api/ligand/prepare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },

  detectPockets(session_id: string, padding = 6.0): Promise<PocketDetectResponse> {
    return request('/api/pocket/detect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id, padding }),
    });
  },

  validateRedocking(
    session_id: string,
    box: GridBox,
    exhaustiveness = 8
  ): Promise<RedockValidationResponse> {
    return request('/api/docking/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id, box, exhaustiveness }),
    });
  },

  getDockingInputs(session_id: string): Promise<{
    session_id: string;
    ligand_name: string;
    receptor_pdbqt: string;
    query_ligand_pdbqt?: string | null;
    native_ligand_pdbqt?: string | null;
  }> {
    return request(`/api/docking/inputs/${encodeURIComponent(session_id)}`);
  },

  ingestDocking(payload: {
    session_id: string;
    poses_pdbqt: string;
    stdout: string;
    box: GridBox;
    exhaustiveness: number;
    native_score?: number | null;
  }): Promise<DockingRunResponse> {
    return request('/api/docking/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },

  ingestRedock(payload: {
    session_id: string;
    redocked_pdbqt: string;
    stdout: string;
    native_score?: number | null;
  }): Promise<RedockValidationResponse> {
    return request('/api/docking/ingest-redock', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },

  runDocking(
    session_id: string,
    box: GridBox,
    exhaustiveness = 8,
    num_modes = 9
  ): Promise<DockingRunResponse> {
    return request('/api/docking/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id, box, exhaustiveness, num_modes }),
    });
  },

  compareResults(session_id: string, pose_mode: number): Promise<ComparativeAnalysisResponse> {
    return request('/api/analysis/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id, pose_mode }),
    });
  },
};
