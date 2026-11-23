import React, { useEffect, useRef, useState } from 'react';
import { Eye, Layers, RotateCcw, Tag } from 'lucide-react';
import type { GridBox, InteractionItem, ResidueComparison } from '../types/docking';
import { INTERACTION_COLORS } from './InteractionDiagram2D';

declare global {
  interface Window {
    $3Dmol?: any;
  }
}

// Kyte-Doolittle hydropathy scale (-4.5 very hydrophilic/polar to +4.5 very hydrophobic)
const KYTE_DOOLITTLE: Record<string, number> = {
  ILE: 4.5,
  VAL: 4.2,
  LEU: 3.8,
  PHE: 2.8,
  CYS: 2.5,
  MET: 1.9,
  ALA: 1.8,
  GLY: -0.4,
  THR: -0.7,
  SER: -0.8,
  TRP: -0.9,
  TYR: -1.3,
  PRO: -1.6,
  HIS: -3.2,
  GLU: -3.5,
  GLN: -3.5,
  ASP: -3.5,
  ASN: -3.5,
  LYS: -3.9,
  ARG: -4.5,
};

function hydropathyToHex(atom: any): string {
  const resn = (atom?.resn || '').toUpperCase();
  const kd = KYTE_DOOLITTLE[resn];
  if (kd === undefined) return '#cbd5e1'; // neutral fallback
  if (kd >= 2.5) return '#ea580c'; // Strongly hydrophobic (deep orange)
  if (kd >= 1.0) return '#f59e0b'; // Moderately hydrophobic (amber/gold)
  if (kd >= -1.0) return '#e2e8f0'; // Neutral / amphipathic (light off-white)
  if (kd >= -3.2) return '#38bdf8'; // Polar / hydrophilic (sky cyan)
  return '#2563eb'; // Strongly polar / charged (rich blue)
}

interface Viewer3DProps {
  proteinPdb?: string | null;
  nativeLigandPdb?: string | null;
  dockedLigandPdb?: string | null;
  redockedLigandPdb?: string | null;
  gridBox?: GridBox | null;
  residueComparison?: ResidueComparison[];
  interactions?: InteractionItem[];
  height?: string;
}

export const Viewer3D: React.FC<Viewer3DProps> = ({
  proteinPdb,
  nativeLigandPdb,
  dockedLigandPdb,
  redockedLigandPdb,
  gridBox,
  residueComparison,
  interactions,
  height = '480px',
}) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<any>(null);
  const [showSurface, setShowSurface] = useState(false);
  const [showNative, setShowNative] = useState(true);
  const [showDocked, setShowDocked] = useState(true);
  const [showInteractions3D, setShowInteractions3D] = useState(true);

  useEffect(() => {
    if (!containerRef.current || !window.$3Dmol) return;

    if (!viewerRef.current) {
      viewerRef.current = window.$3Dmol.createViewer(containerRef.current, {
        backgroundColor: '#020617',
      });
    }

    try {
      const viewer = viewerRef.current;
      viewer.clear();

      if (proteinPdb) {
        const protModel = viewer.addModel(proteinPdb, 'pdb');
        protModel.setStyle(
          { hetflag: false },
          { cartoon: { color: 'spectrum', opacity: showSurface ? 0.45 : 0.88 } }
        );
        // Show remaining hetero atoms (e.g. ions / cofactors) as spheres/sticks
        protModel.setStyle(
          { hetflag: true },
          {
            stick: { colorscheme: 'Jmol', radius: 0.2 },
            sphere: { radius: 0.45, colorscheme: 'Jmol' },
          }
        );

        // Hydrophobicity & Polarity colored Solvent-Excluded Surface (SES)
        if (showSurface) {
          viewer.addSurface(
            window.$3Dmol.SurfaceType.SES,
            {
              opacity: 0.78,
              colorfunc: hydropathyToHex,
            },
            { model: protModel, hetflag: false }
          );
        }

        // Highlight interacting residues in comparative analysis
        if (residueComparison && residueComparison.length > 0) {
          residueComparison.forEach((rc) => {
            const match = rc.residue.match(/([A-Z0-9]+?)(\d+)\s*\(([^)]+)\)/);
            if (!match) return;
            const resi = parseInt(match[2], 10);
            const chain = match[3];
            const color =
              rc.status === 'retained'
                ? '#10b981'
                : rc.status === 'gained'
                ? '#06b6d4'
                : '#f43f5e';
            viewer.addStyle(
              { model: protModel, chain, resi },
              { stick: { color, radius: 0.18 } }
            );
          });
        }
      }

      let focusTarget: any = null;

      if (nativeLigandPdb && showNative) {
        const natModel = viewer.addModel(nativeLigandPdb, 'pdb');
        natModel.setStyle(
          {},
          { stick: { colorscheme: 'yellowCarbon', radius: 0.24 } }
        );
        focusTarget = { model: natModel };
      }

      if (redockedLigandPdb) {
        const redockModel = viewer.addModel(redockedLigandPdb, 'pdb');
        redockModel.setStyle(
          {},
          { stick: { colorscheme: 'magentaCarbon', radius: 0.2 } }
        );
        focusTarget = { model: redockModel };
      }

      if (dockedLigandPdb && showDocked) {
        const dockModel = viewer.addModel(dockedLigandPdb, 'pdb');
        dockModel.setStyle(
          {},
          { stick: { colorscheme: 'cyanCarbon', radius: 0.26 } }
        );
        focusTarget = { model: dockModel };
      }

      // 3D Color-coded Dashed Interaction Lines + Amino Acid Name & Number Labels
      if (showInteractions3D && interactions && interactions.length > 0) {
        const labeledResidues = new Set<string>();
        interactions.forEach((item) => {
          const style =
            INTERACTION_COLORS[item.interaction_type] || INTERACTION_COLORS.Hydrophobic;
          if (
            item.ligand_coord &&
            item.ligand_coord.length === 3 &&
            item.protein_coord &&
            item.protein_coord.length === 3
          ) {
            viewer.addCylinder({
              start: {
                x: item.ligand_coord[0],
                y: item.ligand_coord[1],
                z: item.ligand_coord[2],
              },
              end: {
                x: item.protein_coord[0],
                y: item.protein_coord[1],
                z: item.protein_coord[2],
              },
              radius: 0.055,
              dashed: true,
              dashLength: 0.22,
              gapLength: 0.16,
              color: style.hex,
              fromCap: 1,
              toCap: 1,
            });

            if (!labeledResidues.has(item.residue)) {
              labeledResidues.add(item.residue);
              viewer.addLabel(`${item.resname}${item.resseq}`, {
                position: {
                  x: item.protein_coord[0],
                  y: item.protein_coord[1],
                  z: item.protein_coord[2],
                },
                fontSize: 11,
                fontColor: '#f8fafc',
                backgroundColor: '#0f172a',
                backgroundOpacity: 0.82,
                borderColor: style.hex,
                borderThickness: 1.2,
                inFront: true,
              });
            }
          }
        });
      }

      if (gridBox) {
        viewer.addBox({
          center: { x: gridBox.center_x, y: gridBox.center_y, z: gridBox.center_z },
          dimensions: { w: gridBox.size_x, h: gridBox.size_y, d: gridBox.size_z },
          color: '#22d3ee',
          wireframe: true,
          opacity: 0.85,
        });
      }

      if (focusTarget) {
        viewer.zoomTo(focusTarget, 450);
      } else if (proteinPdb) {
        viewer.zoomTo();
      }
      viewer.render();
    } catch (err) {
      console.error('3Dmol render error:', err);
    }
  }, [
    proteinPdb,
    nativeLigandPdb,
    dockedLigandPdb,
    redockedLigandPdb,
    gridBox,
    residueComparison,
    interactions,
    showSurface,
    showNative,
    showDocked,
    showInteractions3D,
  ]);

  const handleResetView = () => {
    if (!viewerRef.current) return;
    viewerRef.current.zoomTo();
    viewerRef.current.render();
  };

  const activeInteractionTypes = interactions
    ? Array.from(new Set(interactions.map((i) => i.interaction_type)))
    : [];

  return (
    <div className="card-glass overflow-hidden flex flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 border-b border-slate-800 bg-slate-900/90">
        <div className="flex items-center gap-2 text-xs font-medium text-slate-300">
          <Eye className="w-4 h-4 text-cyan-400" />
          <span>Interactive 3D Viewport</span>
          {nativeLigandPdb && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30">
              <span className="w-2 h-2 rounded-full bg-amber-400" /> Original
            </span>
          )}
          {dockedLigandPdb && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
              <span className="w-2 h-2 rounded-full bg-cyan-400" /> Docked
            </span>
          )}
          {redockedLigandPdb && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-fuchsia-500/15 text-fuchsia-300 border border-fuchsia-500/30">
              <span className="w-2 h-2 rounded-full bg-fuchsia-400" /> Redocked
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {nativeLigandPdb && (
            <button
              onClick={() => setShowNative((v) => !v)}
              className={`px-2 py-1 text-xs rounded-md border transition ${
                showNative
                  ? 'bg-amber-500/20 border-amber-500/40 text-amber-200'
                  : 'bg-slate-800 border-slate-700 text-slate-400'
              }`}
            >
              Original
            </button>
          )}
          {dockedLigandPdb && (
            <button
              onClick={() => setShowDocked((v) => !v)}
              className={`px-2 py-1 text-xs rounded-md border transition ${
                showDocked
                  ? 'bg-cyan-500/20 border-cyan-500/40 text-cyan-200'
                  : 'bg-slate-800 border-slate-700 text-slate-400'
              }`}
            >
              Docked
            </button>
          )}
          {interactions && interactions.length > 0 && (
            <button
              onClick={() => setShowInteractions3D((v) => !v)}
              className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded-md border transition ${
                showInteractions3D
                  ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-200'
                  : 'bg-slate-800 border-slate-700 text-slate-400'
              }`}
            >
              <Tag className="w-3.5 h-3.5" /> 3D Labels & Lines
            </button>
          )}
          <button
            onClick={() => setShowSurface((v) => !v)}
            className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded-md border transition ${
              showSurface
                ? 'bg-orange-500/20 border-orange-500/40 text-orange-200'
                : 'bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700'
            }`}
          >
            <Layers className="w-3.5 h-3.5" /> Surface
          </button>
          <button
            onClick={handleResetView}
            className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded-md bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700 transition"
          >
            <RotateCcw className="w-3.5 h-3.5" /> Reset
          </button>
        </div>
      </div>

      {/* Surface Hydrophobicity / Polarity Color Scale Bar */}
      {showSurface && (
        <div className="px-4 py-1.5 border-b border-slate-800 bg-slate-950/90 flex items-center justify-between gap-3 text-[11px]">
          <span className="text-slate-400 font-medium">Surface Polarity / Hydrophobicity:</span>
          <div className="flex items-center gap-2 flex-1 max-w-xs">
            <span className="text-blue-400 font-medium">Polar</span>
            <div
              className="h-2 flex-1 rounded-full"
              style={{
                background:
                  'linear-gradient(90deg, #2563eb 0%, #38bdf8 25%, #e2e8f0 50%, #f59e0b 75%, #ea580c 100%)',
              }}
            />
            <span className="text-orange-400 font-medium">Hydrophobic</span>
          </div>
        </div>
      )}

      {/* 3D Interaction Dashed-Line Color Legend */}
      {showInteractions3D && activeInteractionTypes.length > 0 && (
        <div className="px-4 py-1.5 border-b border-slate-800 bg-slate-950/80 flex flex-wrap items-center gap-3 text-[11px] text-slate-300">
          <span className="text-slate-400 font-medium">3D Bonds:</span>
          {activeInteractionTypes.map((type) => {
            const st = INTERACTION_COLORS[type] || INTERACTION_COLORS.Hydrophobic;
            return (
              <span key={type} className="inline-flex items-center gap-1.5">
                <span
                  className="w-3.5 h-0 border-t-2 border-dashed inline-block"
                  style={{ borderColor: st.hex }}
                />
                <span>{st.label}</span>
              </span>
            );
          })}
        </div>
      )}

      <div className="relative w-full" style={{ height }}>
        <div ref={containerRef} className="w-full h-full" />
        {!proteinPdb && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-500 text-sm pointer-events-none">
            <p className="font-medium text-slate-400">No 3D structure loaded yet</p>
            <p className="text-xs mt-1">
              Fetch a PDB ID (e.g. 1IEP, 6LU7, 1M17) or upload a .pdb file to start
            </p>
          </div>
        )}
      </div>
    </div>
  );
};
