import React, { useState } from 'react';
import { BarChart3, Cpu, Loader2, Play, Sparkles } from 'lucide-react';
import { api } from '../api/client';
import { isWebinaSupported, parseLocalAffinity, runWebinaInBrowser } from '../utils/webinaRunner';
import type { DockingRunResponse, GridBox } from '../types/docking';

interface DockingStepProps {
  sessionId: string;
  gridBox: GridBox;
  dockingResult: DockingRunResponse | null;
  selectedPoseMode: number;
  onDockingComplete: (res: DockingRunResponse) => void;
  onSelectPose: (mode: number) => void;
  onAnalyzePose: (mode: number) => void;
}

export const DockingStep: React.FC<DockingStepProps> = ({
  sessionId,
  gridBox,
  dockingResult,
  selectedPoseMode,
  onDockingComplete,
  onSelectPose,
  onAnalyzePose,
}) => {
  const [exhaustiveness, setExhaustiveness] = useState(8);
  const [numModes, setNumModes] = useState(9);
  const [running, setRunning] = useState(false);
  const [statusText, setStatusText] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleRun = async () => {
    setRunning(true);
    setError(null);
    try {
      if (isWebinaSupported()) {
        setStatusText('Loading prepared PDBQT structures...');
        const inputs = await api.getDockingInputs(sessionId);
        if (!inputs.query_ligand_pdbqt) {
          throw new Error('Prepared query ligand not found. Complete Step 2 first.');
        }

        let nativeScore: number | null = null;
        if (inputs.native_ligand_pdbqt) {
          setStatusText('Scoring original co-crystallized ligand in-browser...');
          try {
            const nativeRun = await runWebinaInBrowser(
              { box: gridBox, localOnly: true, cpu: 1 },
              inputs.receptor_pdbqt,
              inputs.native_ligand_pdbqt
            );
            nativeScore = parseLocalAffinity(nativeRun.stdout);
          } catch {
            // optional native local score
          }
        }

        setStatusText('Running AutoDock Vina locally in your browser (WebAssembly)...');
        const dockRun = await runWebinaInBrowser(
          { box: gridBox, exhaustiveness, numModes },
          inputs.receptor_pdbqt,
          inputs.query_ligand_pdbqt
        );

        setStatusText('Processing poses & saving results...');
        const res = await api.ingestDocking({
          session_id: sessionId,
          poses_pdbqt: dockRun.outPdbqt,
          stdout: dockRun.stdout,
          box: gridBox,
          exhaustiveness,
          native_score: nativeScore,
        });
        onDockingComplete(res);
      } else {
        setStatusText('Running AutoDock Vina on server...');
        const res = await api.runDocking(sessionId, gridBox, exhaustiveness, numModes);
        onDockingComplete(res);
      }
    } catch (err: any) {
      setError(err.message || 'Docking execution failed');
    } finally {
      setRunning(false);
      setStatusText('');
    }
  };

  return (
    <div className="space-y-4">
      <div className="card-glass p-4 space-y-4">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <Play className="w-4 h-4 text-cyan-400" />
            4. Run Molecular Docking (AutoDock Vina)
          </h2>
          {isWebinaSupported() && (
            <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-300">
              <Cpu className="w-3 h-3" /> In-Browser WASM Engine
            </span>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-1.5">
            <div className="flex justify-between text-xs">
              <span className="text-slate-400">Exhaustiveness</span>
              <span className="font-mono text-cyan-300">{exhaustiveness}</span>
            </div>
            <input
              type="range"
              min="4"
              max="32"
              step="4"
              value={exhaustiveness}
              onChange={(e) => setExhaustiveness(parseInt(e.target.value, 10))}
              className="w-full accent-cyan-500"
            />
            <div className="text-[10px] text-slate-500">
              8 = Standard (fast), 16–32 = Publication accuracy
            </div>
          </div>

          <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-1.5">
            <div className="flex justify-between text-xs">
              <span className="text-slate-400">Binding Modes</span>
              <span className="font-mono text-cyan-300">{numModes}</span>
            </div>
            <input
              type="range"
              min="3"
              max="15"
              step="1"
              value={numModes}
              onChange={(e) => setNumModes(parseInt(e.target.value, 10))}
              className="w-full accent-cyan-500"
            />
            <div className="text-[10px] text-slate-500">
              Top ranked binding conformations returned
            </div>
          </div>
        </div>

        {error && (
          <div className="p-2.5 rounded-lg bg-rose-500/15 border border-rose-500/40 text-rose-200 text-xs">
            {error}
          </div>
        )}

        <button
          onClick={handleRun}
          disabled={running}
          className="w-full py-3 px-4 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 hover:from-cyan-400 hover:to-emerald-400 text-slate-950 font-bold text-sm transition disabled:opacity-50 inline-flex items-center justify-center gap-2 shadow-lg shadow-cyan-950/40"
        >
          {running ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              {statusText || 'Running AutoDock Vina...'}
            </>
          ) : (
            <>
              <Sparkles className="w-4 h-4" />
              Launch Molecular Docking Study
            </>
          )}
        </button>
      </div>

      {/* Results Table */}
      {dockingResult && (
        <div className="card-glass p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-white">
              Ranked Poses — {dockingResult.ligand_name}
            </h3>
            {dockingResult.native_score !== null && dockingResult.native_score !== undefined && (
              <span className="text-xs px-2.5 py-1 rounded-full bg-amber-500/15 border border-amber-500/40 text-amber-200 font-mono">
                Original Ligand Score: {dockingResult.native_score.toFixed(2)} kcal/mol
              </span>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400">
                  <th className="py-2 px-2">Mode</th>
                  <th className="py-2 px-2">Affinity (kcal/mol)</th>
                  <th className="py-2 px-2">vs Original</th>
                  <th className="py-2 px-2">RMSD l.b.</th>
                  <th className="py-2 px-2 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {dockingResult.poses.map((pose) => {
                  const active = pose.mode === selectedPoseMode;
                  const delta =
                    dockingResult.native_score !== null &&
                    dockingResult.native_score !== undefined
                      ? pose.affinity - dockingResult.native_score
                      : null;
                  return (
                    <tr
                      key={pose.mode}
                      onClick={() => onSelectPose(pose.mode)}
                      className={`border-b border-slate-800/60 cursor-pointer transition ${
                        active ? 'bg-cyan-500/15' : 'hover:bg-slate-800/40'
                      }`}
                    >
                      <td className="py-2 px-2 font-mono font-semibold text-white">
                        #{pose.mode}
                      </td>
                      <td className="py-2 px-2 font-mono font-bold text-cyan-300">
                        {pose.affinity.toFixed(2)}
                      </td>
                      <td className="py-2 px-2 font-mono">
                        {delta !== null ? (
                          <span
                            className={
                              delta <= 0 ? 'text-emerald-400 font-semibold' : 'text-rose-400'
                            }
                          >
                            {delta > 0 ? `+${delta.toFixed(2)}` : delta.toFixed(2)}
                          </span>
                        ) : (
                          <span className="text-slate-500">—</span>
                        )}
                      </td>
                      <td className="py-2 px-2 font-mono text-slate-400">
                        {pose.rmsd_lb.toFixed(2)} Å
                      </td>
                      <td className="py-2 px-2 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectPose(pose.mode);
                            onAnalyzePose(pose.mode);
                          }}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 text-emerald-200 font-medium transition"
                        >
                          <BarChart3 className="w-3.5 h-3.5" />
                          Deep Analysis
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
