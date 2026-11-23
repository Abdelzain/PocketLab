import React, { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Loader2,
  PencilRuler,
  Search,
  Sparkles,
} from 'lucide-react';
import { api } from '../api/client';
import type { LigandPrepareResponse } from '../types/docking';

declare global {
  interface Window {
    JSApplet?: any;
    jsmeOnLoad?: () => void;
  }
}

interface LigandStepProps {
  sessionId: string;
  nativeLigandSmiles?: string | null;
  preparedLigand: LigandPrepareResponse | null;
  onPrepared: (data: LigandPrepareResponse) => void;
  onNext: () => void;
}

export const LigandStep: React.FC<LigandStepProps> = ({
  sessionId,
  nativeLigandSmiles,
  preparedLigand,
  onPrepared,
  onNext,
}) => {
  const [name, setName] = useState('Candidate-1');
  const [smiles, setSmiles] = useState(
    nativeLigandSmiles || 'Cc1ccc(NC(=O)c2ccc(CN3CCN(C)CC3)cc2)cc1Nc1nccc(-c2cccnc2)n1'
  );
  const [pubchemQuery, setPubchemQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sketcherReady, setSketcherReady] = useState(false);

  const jsmeContainerId = 'pocketlab-jsme-container';
  const jsmeAppletRef = useRef<any>(null);

  useEffect(() => {
    const mountJsme = () => {
      if (!window.JSApplet || jsmeAppletRef.current) return;
      const el = document.getElementById(jsmeContainerId);
      if (!el) return;
      try {
        const applet = new window.JSApplet.JSME(jsmeContainerId, '100%', '290px', {
          options: 'oldlook,star',
        });
        applet.setCallBack('AfterStructureModified', () => {
          const drawnSmiles = applet.smiles();
          if (drawnSmiles) setSmiles(drawnSmiles);
        });
        jsmeAppletRef.current = applet;
        setSketcherReady(true);
      } catch {
        // fallback if CDN is blocked offline
      }
    };

    if (window.JSApplet) {
      mountJsme();
    } else {
      window.jsmeOnLoad = mountJsme;
      const timer = setInterval(() => {
        if (window.JSApplet) {
          mountJsme();
          clearInterval(timer);
        }
      }, 400);
      return () => clearInterval(timer);
    }
  }, []);

  const handlePubChemSearch = async () => {
    if (!pubchemQuery.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const res = await api.lookupPubChem(pubchemQuery.trim());
      setSmiles(res.smiles);
      setName(res.name);
    } catch (err: any) {
      setError(err.message || 'PubChem lookup failed');
    } finally {
      setSearching(false);
    }
  };

  const handleLoadNative = () => {
    if (!nativeLigandSmiles) return;
    setSmiles(nativeLigandSmiles);
    setName('Modified-Native-Analog');
  };

  const handlePrepare = async () => {
    setPreparing(true);
    setError(null);
    try {
      let molblock: string | null = null;
      if (jsmeAppletRef.current) {
        const mb = jsmeAppletRef.current.molFile();
        if (mb && mb.includes('V2000') && mb.split('\n').length > 6) {
          molblock = mb;
        }
      }
      const res = await api.prepareLigand({
        session_id: sessionId,
        name: name.trim() || 'Query Ligand',
        smiles: smiles.trim() || null,
        molblock: smiles.trim() ? null : molblock,
        minimize: true,
      });
      onPrepared(res);
    } catch (err: any) {
      setError(err.message || 'Failed to prepare ligand');
    } finally {
      setPreparing(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Input & Sketcher Card */}
      <div className="card-glass p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <PencilRuler className="w-4 h-4 text-cyan-400" />
            2. Draw or Import Ligand
          </h2>
          {nativeLigandSmiles && (
            <button
              onClick={handleLoadNative}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/40 text-amber-200 text-xs transition"
            >
              <Copy className="w-3.5 h-3.5" />
              Copy Native Ligand SMILES
            </button>
          )}
        </div>

        {/* PubChem quick search */}
        <div className="flex gap-2">
          <input
            type="text"
            value={pubchemQuery}
            onChange={(e) => setPubchemQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handlePubChemSearch()}
            placeholder="Search PubChem by drug name or CID (e.g. Nilotinib, Dasatinib, Aspirin)..."
            className="flex-1 bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-500"
          />
          <button
            onClick={handlePubChemSearch}
            disabled={searching}
            className="px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-medium text-slate-200 inline-flex items-center gap-1.5"
          >
            {searching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
            PubChem
          </button>
        </div>

        {/* Embedded 2D JSME Sketcher */}
        <div className="rounded-lg overflow-hidden border border-slate-700 bg-white">
          <div id={jsmeContainerId} className="w-full min-h-[290px]" />
          {!sketcherReady && (
            <div className="p-2 text-center text-[11px] text-slate-600 bg-slate-100">
              Loading 2D Molecule Sketcher... (You can also enter SMILES directly below)
            </div>
          )}
        </div>

        {/* Ligand Name & SMILES */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ligand Name"
            className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-500"
          />
          <input
            type="text"
            value={smiles}
            onChange={(e) => setSmiles(e.target.value)}
            placeholder="SMILES string"
            className="sm:col-span-2 bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs font-mono text-cyan-200 focus:outline-none focus:border-cyan-500"
          />
        </div>

        {error && (
          <div className="p-2.5 rounded-lg bg-rose-500/15 border border-rose-500/40 text-rose-200 text-xs">
            {error}
          </div>
        )}

        <div className="flex items-center gap-2">
          <button
            onClick={handlePrepare}
            disabled={preparing}
            className="flex-1 py-2.5 px-4 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold text-sm transition disabled:opacity-50 inline-flex items-center justify-center gap-2"
          >
            {preparing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            Generate 3D Conformer & Optimize (MMFF94)
          </button>
          {preparedLigand && (
            <button
              onClick={onNext}
              className="py-2.5 px-4 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold text-sm transition"
            >
              Next: Active Site →
            </button>
          )}
        </div>
      </div>

      {/* Live Medicinal Chemistry Properties Card */}
      {preparedLigand && (
        <div className="card-glass p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-emerald-300 flex items-center gap-1.5">
              <CheckCircle2 className="w-4 h-4" />
              Ligand Prepared: {preparedLigand.name} ({preparedLigand.properties.molecular_formula})
            </h3>
            <span
              className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${
                preparedLigand.properties.lipinski_violations === 0
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                  : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
              }`}
            >
              Lipinski Violations: {preparedLigand.properties.lipinski_violations}
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 items-center">
            <div
              className="bg-white rounded-lg p-2 flex items-center justify-center border border-slate-700"
              dangerouslySetInnerHTML={{ __html: preparedLigand.svg_2d }}
            />
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="p-2 rounded-lg bg-slate-950 border border-slate-800">
                <div className="text-slate-400 text-[11px]">Mol. Weight</div>
                <div className="font-mono font-semibold text-white">
                  {preparedLigand.properties.molecular_weight} Da
                </div>
              </div>
              <div className="p-2 rounded-lg bg-slate-950 border border-slate-800">
                <div className="text-slate-400 text-[11px]">cLogP</div>
                <div className="font-mono font-semibold text-white">
                  {preparedLigand.properties.clogp}
                </div>
              </div>
              <div className="p-2 rounded-lg bg-slate-950 border border-slate-800">
                <div className="text-slate-400 text-[11px]">TPSA</div>
                <div className="font-mono font-semibold text-white">
                  {preparedLigand.properties.tpsa} Å²
                </div>
              </div>
              <div className="p-2 rounded-lg bg-slate-950 border border-slate-800">
                <div className="text-slate-400 text-[11px]">QED Score</div>
                <div className="font-mono font-semibold text-cyan-300">
                  {preparedLigand.properties.qed}
                </div>
              </div>
              <div className="p-2 rounded-lg bg-slate-950 border border-slate-800">
                <div className="text-slate-400 text-[11px]">HBD / HBA</div>
                <div className="font-mono font-semibold text-white">
                  {preparedLigand.properties.hbd} / {preparedLigand.properties.hba}
                </div>
              </div>
              <div className="p-2 rounded-lg bg-slate-950 border border-slate-800">
                <div className="text-slate-400 text-[11px]">Rot. Bonds</div>
                <div className="font-mono font-semibold text-white">
                  {preparedLigand.properties.rotatable_bonds}
                </div>
              </div>
            </div>
          </div>

          {preparedLigand.properties.pains_alerts.length > 0 && (
            <div className="p-2.5 rounded-lg bg-amber-500/15 border border-amber-500/40 text-amber-200 text-xs flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <div>
                <strong>PAINS Structural Alert:</strong>{' '}
                {preparedLigand.properties.pains_alerts.join(', ')}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
