import React, { useEffect, useState } from 'react';
import {
  Box,
  CheckCircle2,
  Crosshair,
  Loader2,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react';
import { api } from '../api/client';
import { isWebinaSupported, parseLocalAffinity, runWebinaInBrowser } from '../utils/webinaRunner';
import type {
  GridBox,
  PocketCandidate,
  RedockValidationResponse,
} from '../types/docking';

interface ActiveSiteStepProps {
  sessionId: string;
  hasNativeLigand: boolean;
  gridBox: GridBox | null;
  pockets: PocketCandidate[];
  validation: RedockValidationResponse | null;
  onPocketsDetected: (pockets: PocketCandidate[], box: GridBox) => void;
  onBoxChange: (box: GridBox) => void;
  onValidated: (res: RedockValidationResponse) => void;
  onNext: () => void;
}

export const ActiveSiteStep: React.FC<ActiveSiteStepProps> = ({
  sessionId,
  hasNativeLigand,
  gridBox,
  pockets,
  validation,
  onPocketsDetected,
  onBoxChange,
  onValidated,
  onNext,
}) => {
  const [detecting, setDetecting] = useState(false);
  const [validating, setValidating] = useState(false);
  const [padding, setPadding] = useState(6.0);
  const [error, setError] = useState<string | null>(null);

  const runDetection = async (pad = padding) => {
    setDetecting(true);
    setError(null);
    try {
      const res = await api.detectPockets(sessionId, pad);
      onPocketsDetected(res.pockets, res.recommended_box);
    } catch (err: any) {
      setError(err.message || 'Pocket detection failed');
    } finally {
      setDetecting(false);
    }
  };

  useEffect(() => {
    if (pockets.length === 0 && !gridBox) {
      runDetection(6.0);
    }
  }, [sessionId]);

  const handleValidate = async () => {
    if (!gridBox) return;
    setValidating(true);
    setError(null);
    try {
      if (isWebinaSupported()) {
        const inputs = await api.getDockingInputs(sessionId);
        if (!inputs.native_ligand_pdbqt) {
          throw new Error('Native co-crystallized ligand PDBQT is not available for this session.');
        }
        let nativeScore: number | null = null;
        try {
          const scoreRun = await runWebinaInBrowser(
            { box: gridBox, localOnly: true, cpu: 1 },
            inputs.receptor_pdbqt,
            inputs.native_ligand_pdbqt
          );
          nativeScore = parseLocalAffinity(scoreRun.stdout);
        } catch {
          // ignore local_only score error
        }
        const redockRun = await runWebinaInBrowser(
          { box: gridBox, exhaustiveness: 8, numModes: 5 },
          inputs.receptor_pdbqt,
          inputs.native_ligand_pdbqt
        );
        const res = await api.ingestRedock({
          session_id: sessionId,
          redocked_pdbqt: redockRun.outPdbqt,
          stdout: redockRun.stdout,
          native_score: nativeScore,
        });
        onValidated(res);
      } else {
        const res = await api.validateRedocking(sessionId, gridBox, 8);
        onValidated(res);
      }
    } catch (err: any) {
      setError(err.message || 'Redocking validation failed');
    } finally {
      setValidating(false);
    }
  };

  const updateField = (field: keyof GridBox, val: number) => {
    if (!gridBox || Number.isNaN(val)) return;
    onBoxChange({ ...gridBox, [field]: val });
  };

  return (
    <div className="space-y-4">
      <div className="card-glass p-4 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <Crosshair className="w-4 h-4 text-cyan-400" />
            3. Active Site Detection & Grid Box
          </h2>
          <button
            onClick={() => runDetection(padding)}
            disabled={detecting}
            className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs text-slate-200 inline-flex items-center gap-1.5"
          >
            {detecting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Box className="w-3.5 h-3.5" />}
            Re-Detect Pockets
          </button>
        </div>

        {error && (
          <div className="p-2.5 rounded-lg bg-rose-500/15 border border-rose-500/40 text-rose-200 text-xs">
            {error}
          </div>
        )}

        {/* Detected Pockets List */}
        {pockets.length > 0 && (
          <div className="space-y-2">
            <label className="text-xs font-medium text-slate-300 block">
              Detected Binding Pockets (click to snap Grid Box)
            </label>
            <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
              {pockets.map((p) => {
                const isSelected =
                  gridBox &&
                  Math.abs(gridBox.center_x - p.box.center_x) < 0.1 &&
                  Math.abs(gridBox.center_y - p.box.center_y) < 0.1;
                return (
                  <button
                    key={p.pocket_id}
                    onClick={() => onBoxChange(p.box)}
                    className={`w-full text-left p-2.5 rounded-lg border transition ${
                      isSelected
                        ? 'bg-cyan-500/15 border-cyan-400/60 text-white'
                        : 'bg-slate-950/70 border-slate-800 text-slate-300 hover:border-slate-700'
                    }`}
                  >
                    <div className="flex items-center justify-between text-xs font-semibold">
                      <span>{p.label}</span>
                      <span className="font-mono text-[11px] text-emerald-300">
                        Score {p.score.toFixed(2)} • {p.volume_est} Å³
                      </span>
                    </div>
                    {p.residues.length > 0 && (
                      <div className="text-[11px] text-slate-400 mt-1 truncate">
                        Key residues: {p.residues.slice(0, 8).join(', ')}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Fine-tune Grid Box Sliders */}
        {gridBox && (
          <div className="grid grid-cols-2 gap-3 pt-2 border-t border-slate-800">
            <div className="space-y-2">
              <div className="text-xs font-medium text-slate-300">Box Center (Å)</div>
              {(['center_x', 'center_y', 'center_z'] as const).map((k) => (
                <div key={k} className="flex items-center gap-2">
                  <span className="text-[11px] font-mono text-slate-400 w-6 uppercase">
                    {k.slice(-1)}
                  </span>
                  <input
                    type="number"
                    step="0.5"
                    value={gridBox[k]}
                    onChange={(e) => updateField(k, parseFloat(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs font-mono text-cyan-200"
                  />
                </div>
              ))}
            </div>
            <div className="space-y-2">
              <div className="text-xs font-medium text-slate-300">Box Size (Å)</div>
              {(['size_x', 'size_y', 'size_z'] as const).map((k) => (
                <div key={k} className="flex items-center gap-2">
                  <span className="text-[11px] font-mono text-slate-400 w-6 uppercase">
                    {k.slice(-1)}
                  </span>
                  <input
                    type="range"
                    min="12"
                    max="36"
                    step="1"
                    value={gridBox[k]}
                    onChange={(e) => updateField(k, parseFloat(e.target.value))}
                    className="flex-1 accent-cyan-500"
                  />
                  <span className="text-xs font-mono text-white w-8 text-right">
                    {gridBox[k]}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 1-Click Redocking Validation Gatekeeper */}
        {hasNativeLigand && gridBox && (
          <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/30 space-y-2.5">
            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="text-xs font-semibold text-amber-200">
                  Protocol Validation (1-Click Redocking RMSD)
                </div>
                <div className="text-[11px] text-amber-200/75">
                  Re-dock the original co-crystallized ligand to verify accuracy (RMSD ≤ 2.0 Å).
                </div>
              </div>
              <button
                onClick={handleValidate}
                disabled={validating}
                className="px-3.5 py-2 rounded-lg bg-amber-400 hover:bg-amber-300 text-slate-950 font-semibold text-xs transition shrink-0 inline-flex items-center gap-1.5 disabled:opacity-50"
              >
                {validating && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                Validate Protocol
              </button>
            </div>

            {validation && (
              <div
                className={`p-2.5 rounded-lg border text-xs flex items-start gap-2 ${
                  validation.passed
                    ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-200'
                    : 'bg-rose-500/15 border-rose-500/40 text-rose-200'
                }`}
              >
                {validation.passed ? (
                  <ShieldCheck className="w-4 h-4 shrink-0 mt-0.5 text-emerald-400" />
                ) : (
                  <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5 text-rose-400" />
                )}
                <div className="space-y-0.5">
                  <div className="font-semibold">
                    Symmetry-Corrected RMSD: {validation.rmsd.toFixed(2)} Å • Redocked Affinity:{' '}
                    {validation.redocked_affinity.toFixed(2)} kcal/mol
                  </div>
                  <div className="text-[11px] opacity-90">{validation.message}</div>
                </div>
              </div>
            )}
          </div>
        )}

        <div className="flex justify-end pt-1">
          <button
            onClick={onNext}
            disabled={!gridBox}
            className="py-2.5 px-5 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold text-sm transition disabled:opacity-50 inline-flex items-center gap-2"
          >
            <CheckCircle2 className="w-4 h-4" />
            Proceed to Docking →
          </button>
        </div>
      </div>
    </div>
  );
};
