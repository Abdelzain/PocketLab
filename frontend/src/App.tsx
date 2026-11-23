import React, { useState } from 'react';
import { Atom } from 'lucide-react';
import { api } from './api/client';
import { ActiveSiteStep } from './components/ActiveSiteStep';
import { AnalysisStep } from './components/AnalysisStep';
import { DockingStep } from './components/DockingStep';
import { LigandStep } from './components/LigandStep';
import { ProteinStep } from './components/ProteinStep';
import { Stepper } from './components/Stepper';
import { Viewer3D } from './components/Viewer3D';
import type {
  ComparativeAnalysisResponse,
  DockingRunResponse,
  GridBox,
  LigandPrepareResponse,
  PocketCandidate,
  ProteinInspectResponse,
  ProteinPrepareResponse,
  RedockValidationResponse,
} from './types/docking';

export default function App() {
  const [step, setStep] = useState(1);

  const [inspected, setInspected] = useState<ProteinInspectResponse | null>(null);
  const [preparedProtein, setPreparedProtein] = useState<ProteinPrepareResponse | null>(null);
  const [preparedLigand, setPreparedLigand] = useState<LigandPrepareResponse | null>(null);

  const [pockets, setPockets] = useState<PocketCandidate[]>([]);
  const [gridBox, setGridBox] = useState<GridBox | null>(null);
  const [validation, setValidation] = useState<RedockValidationResponse | null>(null);

  const [dockingResult, setDockingResult] = useState<DockingRunResponse | null>(null);
  const [selectedPoseMode, setSelectedPoseMode] = useState(1);

  const [analysis, setAnalysis] = useState<ComparativeAnalysisResponse | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  const maxUnlockedStep = dockingResult
    ? 5
    : gridBox
    ? 4
    : preparedLigand
    ? 3
    : preparedProtein
    ? 2
    : 1;

  const currentPosePdb =
    dockingResult?.poses.find((p) => p.mode === selectedPoseMode)?.pdb_block || null;

  const handleAnalyzePose = async (mode: number) => {
    if (!inspected) return;
    setStep(5);
    setAnalyzing(true);
    try {
      const res = await api.compareResults(inspected.session_id, mode);
      setAnalysis(res);
    } catch (err) {
      console.error(err);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleDownloadReport = () => {
    if (!analysis || !inspected) return;
    const lines = [
      `# PocketLab Comparative Molecular Docking Report`,
      ``,
      `- **Target Protein:** ${inspected.pdb_id || 'Uploaded PDB'} — ${inspected.title}`,
      `- **Query Ligand:** ${analysis.ligand_name}`,
      `- **Selected Pose:** Mode #${analysis.pose_mode}`,
      `- **Query Binding Affinity:** ${analysis.query_affinity.toFixed(2)} kcal/mol`,
      `- **Original Co-Crystallized Ligand Score:** ${
        analysis.native_score !== null && analysis.native_score !== undefined
          ? `${analysis.native_score.toFixed(2)} kcal/mol`
          : 'N/A'
      }`,
      `- **Interaction Fingerprint Similarity:** ${
        analysis.interaction_similarity_pct !== null &&
        analysis.interaction_similarity_pct !== undefined
          ? `${analysis.interaction_similarity_pct.toFixed(1)}%`
          : 'N/A'
      }`,
      validation
        ? `- **Redocking Protocol Validation:** RMSD = ${validation.rmsd.toFixed(2)} Å (${
            validation.passed ? 'PASSED' : 'WARNING'
          })`
        : '',
      gridBox
        ? `- **Grid Box:** Center (${gridBox.center_x}, ${gridBox.center_y}, ${gridBox.center_z}) | Size (${gridBox.size_x} × ${gridBox.size_y} × ${gridBox.size_z} Å)`
        : '',
      ``,
      `## Executive Summary`,
      analysis.summary_en,
      ``,
      `## Residue-by-Residue Comparison`,
      `| Residue | Status | Original Ligand | Query Ligand |`,
      `| :--- | :--- | :--- | :--- |`,
      ...analysis.residue_comparison.map(
        (r) =>
          `| ${r.residue} | ${r.status.toUpperCase()} | ${
            r.native_interactions.join(', ') || '—'
          } | ${r.query_interactions.join(', ') || '—'} |`
      ),
    ];

    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `PocketLab_Report_${analysis.ligand_name.replace(/\s+/g, '_')}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Header */}
      <header className="border-b border-slate-800/80 bg-slate-950/90 backdrop-blur sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-500 to-emerald-500 flex items-center justify-center text-slate-950 shadow-lg shadow-cyan-500/20">
              <Atom className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-base font-bold tracking-tight text-white leading-none">
                PocketLab
              </h1>
              <p className="text-[11px] text-slate-400 mt-0.5">
                All-in-One Molecular Docking & Native-Ligand Benchmarking Workbench
              </p>
            </div>
          </div>
          {inspected && (
            <div className="hidden sm:flex items-center gap-2 text-xs text-slate-400">
              <span className="px-2.5 py-1 rounded-full bg-slate-900 border border-slate-800 font-mono text-cyan-300">
                Session: {inspected.session_id}
              </span>
            </div>
          )}
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl w-full mx-auto px-4 py-5 space-y-5 flex-1">
        <Stepper
          currentStep={step}
          maxUnlockedStep={maxUnlockedStep}
          onSelectStep={setStep}
        />

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
          {/* Left Panel: Active Step Controls */}
          <div className="lg:col-span-6 space-y-4">
            {step === 1 && (
              <ProteinStep
                inspected={inspected}
                prepared={preparedProtein}
                onInspected={(data) => {
                  setInspected(data);
                  setPreparedProtein(null);
                  setPreparedLigand(null);
                  setPockets([]);
                  setGridBox(null);
                  setValidation(null);
                  setDockingResult(null);
                  setAnalysis(null);
                }}
                onPrepared={(data) => setPreparedProtein(data)}
                onNext={() => setStep(2)}
              />
            )}

            {step === 2 && inspected && (
              <LigandStep
                sessionId={inspected.session_id}
                nativeLigandSmiles={preparedProtein?.native_ligand_smiles}
                preparedLigand={preparedLigand}
                onPrepared={(data) => setPreparedLigand(data)}
                onNext={() => setStep(3)}
              />
            )}

            {step === 3 && inspected && (
              <ActiveSiteStep
                sessionId={inspected.session_id}
                hasNativeLigand={Boolean(preparedProtein?.native_ligand_pdb)}
                gridBox={gridBox}
                pockets={pockets}
                validation={validation}
                onPocketsDetected={(list, box) => {
                  setPockets(list);
                  setGridBox(box);
                }}
                onBoxChange={(box) => setGridBox(box)}
                onValidated={(res) => setValidation(res)}
                onNext={() => setStep(4)}
              />
            )}

            {step === 4 && inspected && gridBox && (
              <DockingStep
                sessionId={inspected.session_id}
                gridBox={gridBox}
                dockingResult={dockingResult}
                selectedPoseMode={selectedPoseMode}
                onDockingComplete={(res) => {
                  setDockingResult(res);
                  setSelectedPoseMode(1);
                }}
                onSelectPose={(mode) => setSelectedPoseMode(mode)}
                onAnalyzePose={handleAnalyzePose}
              />
            )}

            {step === 5 && (
              <AnalysisStep
                analysis={analysis}
                ligandSvg2d={preparedLigand?.svg_2d}
                loading={analyzing}
                onDownloadReport={handleDownloadReport}
              />
            )}
          </div>

          {/* Right Panel: Always-Live Interactive 3D Viewport */}
          <div className="lg:col-span-6 lg:sticky lg:top-20">
            <Viewer3D
              proteinPdb={preparedProtein?.prepared_pdb || inspected?.raw_pdb}
              nativeLigandPdb={preparedProtein?.native_ligand_pdb}
              dockedLigandPdb={step >= 4 ? currentPosePdb : null}
              redockedLigandPdb={step === 3 ? validation?.redocked_pdb : null}
              gridBox={step === 3 || step === 4 ? gridBox : null}
              residueComparison={step === 5 ? analysis?.residue_comparison : undefined}
              interactions={step === 5 ? analysis?.query_interactions : undefined}
              height="560px"
            />
          </div>
        </div>
      </main>
    </div>
  );
}
