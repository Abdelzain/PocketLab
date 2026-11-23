import React, { useState } from 'react';
import {
  Award,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  MinusCircle,
  Network,
  PlusCircle,
  Table2,
} from 'lucide-react';
import type { ComparativeAnalysisResponse } from '../types/docking';
import { InteractionDiagram2D } from './InteractionDiagram2D';

interface AnalysisStepProps {
  analysis: ComparativeAnalysisResponse | null;
  ligandSvg2d?: string | null;
  loading: boolean;
  onDownloadReport: () => void;
}

export const AnalysisStep: React.FC<AnalysisStepProps> = ({
  analysis,
  ligandSvg2d,
  loading,
  onDownloadReport,
}) => {
  const [viewMode, setViewMode] = useState<'summary' | 'diagram2d'>('summary');

  if (loading) {
    return (
      <div className="card-glass p-10 flex flex-col items-center justify-center gap-3 text-slate-300">
        <Loader2 className="w-7 h-7 animate-spin text-cyan-400" />
        <p className="text-sm font-medium">
          Profiling non-covalent interactions & benchmarking against Original Ligand...
        </p>
      </div>
    );
  }

  if (!analysis) {
    return (
      <div className="card-glass p-8 text-center text-slate-400 text-sm">
        Run docking and select a pose to view the deep comparative analysis.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* KPI Metrics Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        <div className="card-glass p-3">
          <div className="text-[11px] text-slate-400">Query Affinity</div>
          <div className="text-lg font-mono font-bold text-cyan-300 mt-0.5">
            {analysis.query_affinity.toFixed(2)}{' '}
            <span className="text-[11px] font-normal text-slate-400">kcal/mol</span>
          </div>
        </div>

        <div className="card-glass p-3">
          <div className="text-[11px] text-slate-400">Original Ligand</div>
          <div className="text-lg font-mono font-bold text-amber-300 mt-0.5">
            {analysis.native_score !== null && analysis.native_score !== undefined
              ? `${analysis.native_score.toFixed(2)}`
              : 'N/A'}{' '}
            {analysis.native_score !== null && analysis.native_score !== undefined && (
              <span className="text-[11px] font-normal text-slate-400">kcal/mol</span>
            )}
          </div>
        </div>

        <div className="card-glass p-3">
          <div className="text-[11px] text-slate-400">Δ Affinity (New − Orig)</div>
          <div
            className={`text-lg font-mono font-bold mt-0.5 ${
              analysis.delta_affinity !== null &&
              analysis.delta_affinity !== undefined &&
              analysis.delta_affinity <= 0
                ? 'text-emerald-400'
                : 'text-rose-400'
            }`}
          >
            {analysis.delta_affinity !== null && analysis.delta_affinity !== undefined
              ? `${analysis.delta_affinity > 0 ? '+' : ''}${analysis.delta_affinity.toFixed(2)}`
              : '—'}
          </div>
        </div>

        <div className="card-glass p-3">
          <div className="text-[11px] text-slate-400">Interaction Overlap</div>
          <div className="text-lg font-mono font-bold text-emerald-300 mt-0.5">
            {analysis.interaction_similarity_pct !== null &&
            analysis.interaction_similarity_pct !== undefined
              ? `${analysis.interaction_similarity_pct.toFixed(1)}%`
              : '—'}
          </div>
        </div>
      </div>

      {/* View Switcher: Summary & Matrix vs 2D Interaction Diagram */}
      <div className="flex items-center justify-between gap-2">
        <div className="inline-flex p-1 rounded-xl bg-slate-900 border border-slate-800">
          <button
            onClick={() => setViewMode('summary')}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              viewMode === 'summary'
                ? 'bg-cyan-500 text-slate-950'
                : 'text-slate-300 hover:text-white'
            }`}
          >
            <Table2 className="w-3.5 h-3.5" />
            Summary & Matrix
          </button>
          <button
            onClick={() => setViewMode('diagram2d')}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              viewMode === 'diagram2d'
                ? 'bg-emerald-500 text-slate-950'
                : 'text-slate-300 hover:text-white'
            }`}
          >
            <Network className="w-3.5 h-3.5" />
            2D Interaction Diagram
          </button>
        </div>

        <button
          onClick={onDownloadReport}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold text-xs transition"
        >
          <Download className="w-3.5 h-3.5" />
          Export Report (.md)
        </button>
      </div>

      {viewMode === 'diagram2d' ? (
        <InteractionDiagram2D
          ligandName={analysis.ligand_name}
          ligandSvg2d={analysis.diagram_ligand_svg || ligandSvg2d}
          interactions={analysis.query_interactions}
          residueComparison={analysis.residue_comparison}
        />
      ) : (
        <>
          {/* Executive Summary Card (English only) */}
          <div className="card-glass p-4 space-y-3">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <Award className="w-4 h-4 text-emerald-400" />
              Comparative Scientific Summary (Pose #{analysis.pose_mode})
            </h3>

            <p className="text-xs leading-relaxed text-slate-200 bg-slate-950/70 p-3.5 rounded-lg border border-slate-800">
              {analysis.summary_en}
            </p>

            {analysis.key_findings.length > 0 && (
              <ul className="space-y-1.5 pt-1">
                {analysis.key_findings.map((f, i) => (
                  <li key={i} className="text-xs text-slate-300 flex items-start gap-2">
                    <FileText className="w-3.5 h-3.5 text-cyan-400 shrink-0 mt-0.5" />
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Residue-by-Residue Comparison Matrix */}
          {analysis.has_native_reference && (
            <div className="card-glass p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-white">
                  Residue-by-Residue Comparison Matrix
                </h3>
                <div className="flex items-center gap-2 text-[11px]">
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                    <CheckCircle2 className="w-3 h-3" /> Retained ({analysis.retained_count})
                  </span>
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
                    <PlusCircle className="w-3 h-3" /> Gained ({analysis.gained_count})
                  </span>
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-rose-500/15 text-rose-300 border border-rose-500/30">
                    <MinusCircle className="w-3 h-3" /> Lost ({analysis.lost_count})
                  </span>
                </div>
              </div>

              <div className="overflow-x-auto max-h-72 overflow-y-auto">
                <table className="w-full text-xs text-left border-collapse">
                  <thead className="sticky top-0 bg-slate-900">
                    <tr className="border-b border-slate-800 text-slate-400">
                      <th className="py-2 px-2">Residue</th>
                      <th className="py-2 px-2">Status</th>
                      <th className="py-2 px-2">Original Ligand</th>
                      <th className="py-2 px-2">Your Ligand</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysis.residue_comparison.map((row) => (
                      <tr key={row.residue} className="border-b border-slate-800/50">
                        <td className="py-2 px-2 font-mono font-semibold text-slate-100">
                          {row.residue}
                        </td>
                        <td className="py-2 px-2">
                          <span
                            className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase ${
                              row.status === 'retained'
                                ? 'bg-emerald-500/20 text-emerald-300'
                                : row.status === 'gained'
                                ? 'bg-cyan-500/20 text-cyan-300'
                                : 'bg-rose-500/20 text-rose-300'
                            }`}
                          >
                            {row.status}
                          </span>
                        </td>
                        <td className="py-2 px-2 text-amber-200/90">
                          {row.native_interactions.length > 0
                            ? `${row.native_interactions.join(', ')}${
                                typeof row.best_distance_native === 'number'
                                  ? ` (${row.best_distance_native.toFixed(2)} Å)`
                                  : ''
                              }`
                            : '—'}
                        </td>
                        <td className="py-2 px-2 text-cyan-200">
                          {row.query_interactions.length > 0
                            ? `${row.query_interactions.join(', ')}${
                                typeof row.best_distance_query === 'number'
                                  ? ` (${row.best_distance_query.toFixed(2)} Å)`
                                  : ''
                              }`
                            : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};
