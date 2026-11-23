import React, { useState } from 'react';
import {
  CheckCircle2,
  Download,
  Droplets,
  FlaskConical,
  Loader2,
  Settings2,
  Upload,
} from 'lucide-react';
import { api } from '../api/client';
import type { ProteinInspectResponse, ProteinPrepareResponse } from '../types/docking';

interface ProteinStepProps {
  inspected: ProteinInspectResponse | null;
  prepared: ProteinPrepareResponse | null;
  onInspected: (data: ProteinInspectResponse) => void;
  onPrepared: (data: ProteinPrepareResponse) => void;
  onNext: () => void;
}

const EXAMPLE_PDBS = [
  { id: '1IEP', label: '1IEP (ABL Kinase + Imatinib)' },
  { id: '1M17', label: '1M17 (EGFR + Erlotinib)' },
  { id: '6LU7', label: '6LU7 (SARS-CoV-2 Mpro)' },
];

export const ProteinStep: React.FC<ProteinStepProps> = ({
  inspected,
  prepared,
  onInspected,
  onPrepared,
  onNext,
}) => {
  const [pdbId, setPdbId] = useState('1IEP');
  const [loading, setLoading] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedChains, setSelectedChains] = useState<string[]>([]);
  const [selectedNativeId, setSelectedNativeId] = useState<string>('');
  const [selectedIons, setSelectedIons] = useState<string[]>([]);
  const [removeWaters, setRemoveWaters] = useState(true);
  const [keepNearWaters, setKeepNearWaters] = useState(false);
  const [waterRadius, setWaterRadius] = useState(4.5);
  const [addHydrogens, setAddHydrogens] = useState(true);
  const [ph, setPh] = useState(7.4);

  const applyDefaultsFromInspect = (data: ProteinInspectResponse) => {
    setSelectedChains(data.chains.length > 0 ? [data.chains[0].chain_id] : []);
    const primaryLig = data.ligands.find((l) => l.category === 'ligand') || data.ligands[0];
    setSelectedNativeId(primaryLig ? primaryLig.id : '');
    setSelectedIons(
      data.ions.filter((i) => i.category === 'ion').map((i) => i.id)
    );
  };

  const handleFetch = async (idToFetch?: string) => {
    const target = (idToFetch || pdbId).trim();
    if (!target) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.fetchProtein(target);
      onInspected(data);
      applyDefaultsFromInspect(data);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch PDB');
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.uploadProtein(file);
      onInspected(data);
      applyDefaultsFromInspect(data);
    } catch (err: any) {
      setError(err.message || 'Upload failed');
    } finally {
      setLoading(false);
    }
  };

  const toggleChain = (chainId: string) => {
    setSelectedChains((prev) =>
      prev.includes(chainId) ? prev.filter((c) => c !== chainId) : [...prev, chainId]
    );
  };

  const toggleIon = (id: string) => {
    setSelectedIons((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]
    );
  };

  const handlePrepare = async () => {
    if (!inspected) return;
    if (selectedChains.length === 0) {
      setError('Please select at least one protein chain.');
      return;
    }
    setPreparing(true);
    setError(null);
    try {
      const res = await api.prepareProtein({
        session_id: inspected.session_id,
        keep_chains: selectedChains,
        remove_waters: removeWaters,
        keep_waters_within_angstrom: removeWaters && keepNearWaters ? waterRadius : null,
        keep_ions: selectedIons,
        extract_native_ligand_id: selectedNativeId || null,
        add_hydrogens: addHydrogens,
        ph,
      });
      onPrepared(res);
    } catch (err: any) {
      setError(err.message || 'Preparation failed');
    } finally {
      setPreparing(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Load Protein Card */}
      <div className="card-glass p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <Download className="w-4 h-4 text-cyan-400" />
            1. Load Target Protein
          </h2>
          <label className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 cursor-pointer transition">
            <Upload className="w-3.5 h-3.5" />
            Upload .PDB / .CIF
            <input type="file" accept=".pdb,.ent,.cif,.mmcif" onChange={handleUpload} className="hidden" />
          </label>
        </div>

        <div className="flex gap-2">
          <input
            type="text"
            value={pdbId}
            onChange={(e) => setPdbId(e.target.value.toUpperCase())}
            placeholder="PDB ID (e.g. 1IEP)"
            className="flex-1 bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-cyan-500"
          />
          <button
            onClick={() => handleFetch()}
            disabled={loading}
            className="px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold text-sm transition disabled:opacity-50 inline-flex items-center gap-2"
          >
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            Fetch PDB
          </button>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {EXAMPLE_PDBS.map((ex) => (
            <button
              key={ex.id}
              onClick={() => {
                setPdbId(ex.id);
                handleFetch(ex.id);
              }}
              className="text-[11px] px-2.5 py-1 rounded-md bg-slate-800/80 hover:bg-slate-700 text-slate-300 border border-slate-700/70 transition"
            >
              {ex.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-rose-500/15 border border-rose-500/40 text-rose-200 text-xs">
          {error}
        </div>
      )}

      {/* Interactive Protein Editor */}
      {inspected && (
        <div className="card-glass p-4 space-y-4">
          <div className="border-b border-slate-800 pb-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                <Settings2 className="w-4 h-4 text-emerald-400" />
                Interactive Protein Editor & Prep
              </h3>
              <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-800 text-cyan-300">
                {inspected.pdb_id || 'Custom PDB'}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1 line-clamp-2">{inspected.title}</p>
          </div>

          {/* Chains */}
          <div>
            <label className="text-xs font-medium text-slate-300 block mb-1.5">
              Protein Chains to Keep
            </label>
            <div className="flex flex-wrap gap-2">
              {inspected.chains.map((ch) => {
                const active = selectedChains.includes(ch.chain_id);
                return (
                  <button
                    key={ch.chain_id}
                    onClick={() => toggleChain(ch.chain_id)}
                    className={`px-3 py-1.5 rounded-lg text-xs border transition ${
                      active
                        ? 'bg-cyan-500/20 border-cyan-400 text-cyan-100 font-semibold'
                        : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
                    }`}
                  >
                    Chain {ch.chain_id}{' '}
                    <span className="opacity-70">({ch.residue_count} res)</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Native Co-crystallized Ligand Extraction */}
          <div>
            <label className="text-xs font-medium text-amber-300 flex items-center gap-1.5 mb-1.5">
              <FlaskConical className="w-3.5 h-3.5" />
              Extract Original (Co-Crystallized) Ligand as Reference Benchmark
            </label>
            <select
              value={selectedNativeId}
              onChange={(e) => setSelectedNativeId(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 focus:outline-none focus:border-amber-400"
            >
              <option value="">None (Apo structure — detect pockets automatically)</option>
              {inspected.ligands.map((lig) => (
                <option key={lig.id} value={lig.id}>
                  {lig.resname} — Chain {lig.chain_id} #{lig.resseq} ({lig.atom_count} atoms,{' '}
                  {lig.category})
                </option>
              ))}
            </select>
          </div>

          {/* Waters & Ions */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
            <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-slate-300 flex items-center gap-1.5">
                  <Droplets className="w-3.5 h-3.5 text-sky-400" />
                  Waters ({inspected.water_count})
                </span>
                <label className="inline-flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={removeWaters}
                    onChange={(e) => setRemoveWaters(e.target.checked)}
                    className="rounded border-slate-600 bg-slate-800 text-cyan-500"
                  />
                  Remove
                </label>
              </div>
              {removeWaters && selectedNativeId && (
                <label className="flex items-center gap-2 text-[11px] text-slate-400 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={keepNearWaters}
                    onChange={(e) => setKeepNearWaters(e.target.checked)}
                    className="rounded border-slate-600 bg-slate-800 text-cyan-500"
                  />
                  Keep catalytic waters ≤
                  <input
                    type="number"
                    step="0.5"
                    min="2.5"
                    max="8"
                    value={waterRadius}
                    onChange={(e) => setWaterRadius(parseFloat(e.target.value) || 4.5)}
                    className="w-12 bg-slate-900 border border-slate-700 rounded px-1 py-0.5 text-center text-slate-200"
                  />
                  Å
                </label>
              )}
            </div>

            <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-slate-300">Protonation (pH)</span>
                <label className="inline-flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={addHydrogens}
                    onChange={(e) => setAddHydrogens(e.target.checked)}
                    className="rounded border-slate-600 bg-slate-800 text-cyan-500"
                  />
                  Fix & Add H
                </label>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min="4.0"
                  max="10.0"
                  step="0.2"
                  value={ph}
                  onChange={(e) => setPh(parseFloat(e.target.value))}
                  className="flex-1 accent-cyan-500"
                />
                <span className="text-xs font-mono text-cyan-300 w-10 text-right">
                  {ph.toFixed(1)}
                </span>
              </div>
            </div>
          </div>

          {/* Ions / Cofactors */}
          {inspected.ions.length > 0 && (
            <div>
              <label className="text-xs font-medium text-slate-300 block mb-1.5">
                Metal Ions & Cofactors (click to retain)
              </label>
              <div className="flex flex-wrap gap-1.5">
                {inspected.ions.map((ion) => {
                  const active = selectedIons.includes(ion.id);
                  return (
                    <button
                      key={ion.id}
                      onClick={() => toggleIon(ion.id)}
                      className={`px-2.5 py-1 rounded-md text-[11px] border transition ${
                        active
                          ? 'bg-emerald-500/20 border-emerald-400 text-emerald-200'
                          : 'bg-slate-950 border-slate-800 text-slate-400'
                      }`}
                    >
                      {ion.resname} ({ion.chain_id}:{ion.resseq})
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Action */}
          <div className="flex items-center gap-2 pt-2">
            <button
              onClick={handlePrepare}
              disabled={preparing}
              className="flex-1 py-2.5 px-4 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold text-sm transition disabled:opacity-50 inline-flex items-center justify-center gap-2"
            >
              {preparing && <Loader2 className="w-4 h-4 animate-spin" />}
              Prepare Receptor & Extract Reference
            </button>
            {prepared && (
              <button
                onClick={onNext}
                className="py-2.5 px-4 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold text-sm transition"
              >
                Next: Ligand →
              </button>
            )}
          </div>

          {prepared && (
            <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-xs text-emerald-200 space-y-1">
              <div className="flex items-center gap-1.5 font-semibold">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                Receptor Ready ({prepared.atom_count} atoms, {prepared.water_kept_count} waters,{' '}
                {prepared.ions_kept_count} ions)
              </div>
              {prepared.native_ligand_id && (
                <div className="text-amber-300">
                  Original Reference Ligand Extracted: <span className="font-mono">{prepared.native_ligand_id}</span>
                </div>
              )}
              {prepared.warnings.map((w, idx) => (
                <div key={idx} className="text-[11px] text-amber-200/80">
                  Note: {w}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
