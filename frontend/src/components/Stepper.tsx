import React from 'react';
import { Check } from 'lucide-react';

export interface StepItem {
  id: number;
  title: string;
  subtitle: string;
}

export const STEPS: StepItem[] = [
  { id: 1, title: 'Protein Prep', subtitle: 'Edit & Extract Native' },
  { id: 2, title: 'Ligand Studio', subtitle: 'Draw & Optimize 3D' },
  { id: 3, title: 'Active Site', subtitle: 'Grid Box & RMSD' },
  { id: 4, title: 'Docking', subtitle: 'AutoDock Vina' },
  { id: 5, title: 'Deep Analysis', subtitle: 'vs. Original Ligand' },
];

interface StepperProps {
  currentStep: number;
  maxUnlockedStep: number;
  onSelectStep: (step: number) => void;
}

export const Stepper: React.FC<StepperProps> = ({
  currentStep,
  maxUnlockedStep,
  onSelectStep,
}) => {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
      {STEPS.map((step) => {
        const isActive = step.id === currentStep;
        const isDone = step.id < currentStep;
        const isUnlocked = step.id <= maxUnlockedStep;
        return (
          <button
            key={step.id}
            disabled={!isUnlocked}
            onClick={() => onSelectStep(step.id)}
            className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl border text-left transition ${
              isActive
                ? 'bg-cyan-500/15 border-cyan-400/60 text-white shadow-md shadow-cyan-950/40'
                : isDone
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-100 hover:bg-emerald-500/15'
                : isUnlocked
                ? 'bg-slate-900/70 border-slate-800 text-slate-300 hover:border-slate-700'
                : 'bg-slate-900/30 border-slate-800/60 text-slate-600 cursor-not-allowed'
            }`}
          >
            <div
              className={`w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold shrink-0 ${
                isActive
                  ? 'bg-cyan-500 text-slate-950'
                  : isDone
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                  : 'bg-slate-800 text-slate-400'
              }`}
            >
              {isDone ? <Check className="w-4 h-4" /> : step.id}
            </div>
            <div className="min-w-0">
              <div className="text-xs font-semibold truncate">{step.title}</div>
              <div className="text-[11px] text-slate-400 truncate">{step.subtitle}</div>
            </div>
          </button>
        );
      })}
    </div>
  );
};
