import React, { useMemo, useRef } from 'react';
import { Download } from 'lucide-react';
import type { InteractionItem, ResidueComparison } from '../types/docking';

export const INTERACTION_COLORS: Record<string, { hex: string; bg: string; label: string }> = {
  'H-Bond': { hex: '#10b981', bg: '#ecfdf5', label: 'Hydrogen Bond' },
  Hydrophobic: { hex: '#f59e0b', bg: '#fffbeb', label: 'Hydrophobic' },
  'Pi-Stacking': { hex: '#d946ef', bg: '#fdf4ff', label: 'Pi-Stacking' },
  'Salt Bridge': { hex: '#f43f5e', bg: '#fff1f2', label: 'Salt Bridge' },
  'Halogen Bond': { hex: '#06b6d4', bg: '#ecfeff', label: 'Halogen Bond' },
  'Metal Coordination': { hex: '#8b5cf6', bg: '#f5f3ff', label: 'Metal Coord.' },
};

interface InteractionDiagram2DProps {
  ligandName: string;
  ligandSvg2d?: string | null;
  interactions: InteractionItem[];
  residueComparison?: ResidueComparison[];
}

export const InteractionDiagram2D: React.FC<InteractionDiagram2DProps> = ({
  ligandName,
  ligandSvg2d,
  interactions,
  residueComparison,
}) => {
  const svgRef = useRef<SVGSVGElement | null>(null);

  const statusMap = useMemo(() => {
    const map: Record<string, 'retained' | 'gained' | 'lost'> = {};
    residueComparison?.forEach((rc) => {
      map[rc.residue] = rc.status;
    });
    return map;
  }, [residueComparison]);

  const width = 820;
  const height = 560;
  const cx = width / 2;
  const cy = height / 2;

  // RDKit diagram_ligand_svg is rendered at exact 440 x 280 coordinate space
  const molW = 440;
  const molH = 280;
  const offsetX = (width - molW) / 2;
  const offsetY = (height - molH) / 2;

  // Outer ellipse for amino acid residue circles
  const rx = 335;
  const ry = 225;

  // Extract inner SVG markup from RDKit SVG (strips outer <svg> and background <rect> so lines stay crisp)
  const innerLigandSvg = useMemo(() => {
    if (!ligandSvg2d) return null;
    const match = ligandSvg2d.match(/<svg[^>]*>([\s\S]*?)<\/svg>/i);
    if (!match) return null;
    return match[1].replace(/<rect[^>]*style='opacity:1\.0;fill:#FFFFFF[^>]*\/>/i, '');
  }, [ligandSvg2d]);

  // Deduplicate by residue and compute smart non-overlapping radial angles aligned to each atom's exact 2D position
  const placedItems = useMemo(() => {
    const seen = new Set<string>();
    const unique: InteractionItem[] = [];
    for (const item of interactions) {
      if (!seen.has(item.residue)) {
        seen.add(item.residue);
        unique.push(item);
      }
    }
    const items = unique.slice(0, 18);
    if (items.length === 0) return [];

    // Compute exact anchor point (ax, ay) on the 2D chemical structure + ideal radial angle
    const withAngles = items.map((item, idx) => {
      const hasExact = item.ligand_2d_coord && item.ligand_2d_coord.length === 2;
      const ax = hasExact ? offsetX + item.ligand_2d_coord![0] : cx;
      const ay = hasExact ? offsetY + item.ligand_2d_coord![1] : cy;
      let idealAngle = hasExact
        ? Math.atan2((ay - cy) / ry, (ax - cx) / rx)
        : (2 * Math.PI * idx) / items.length - Math.PI / 2;
      if (idealAngle < 0) idealAngle += 2 * Math.PI;
      return { item, ax, ay, hasExact, angle: idealAngle };
    });

    // Sort by ideal angle and relax angular spacing so residue circles never collide
    withAngles.sort((a, b) => a.angle - b.angle);
    const n = withAngles.length;
    const minSep = Math.min((2 * Math.PI) / n, 0.36); // ~20.6 degrees minimum separation

    for (let iter = 0; iter < 24; iter++) {
      for (let i = 0; i < n; i++) {
        const next = (i + 1) % n;
        let diff = withAngles[next].angle - withAngles[i].angle;
        if (next === 0) diff += 2 * Math.PI;
        if (diff < minSep) {
          const push = (minSep - diff) / 2 + 0.002;
          withAngles[i].angle = (withAngles[i].angle - push + 2 * Math.PI) % (2 * Math.PI);
          withAngles[next].angle = (withAngles[next].angle + push) % (2 * Math.PI);
        }
      }
    }

    return withAngles.map((entry) => {
      const nx = cx + rx * Math.cos(entry.angle);
      const ny = cy + ry * Math.sin(entry.angle);
      // Stop dashed line cleanly at the outer rim of the 30px residue circle
      const dx = nx - entry.ax;
      const dy = ny - entry.ay;
      const len = Math.hypot(dx, dy) || 1;
      const lineEndX = nx - (dx / len) * 32;
      const lineEndY = ny - (dy / len) * 32;
      // Place distance pill 68% of the way toward the residue so it never covers the ligand atoms
      const pillX = entry.ax + (lineEndX - entry.ax) * 0.68;
      const pillY = entry.ay + (lineEndY - entry.ay) * 0.68;
      return {
        ...entry,
        nx,
        ny,
        lineEndX,
        lineEndY,
        pillX,
        pillY,
      };
    });
  }, [interactions, cx, cy, rx, ry, offsetX, offsetY]);

  const handleDownloadSvg = () => {
    if (!svgRef.current) return;
    const serializer = new XMLSerializer();
    const source = serializer.serializeToString(svgRef.current);
    const blob = new Blob([source], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `PocketLab_2D_Interactions_${ligandName.replace(/\s+/g, '_')}.svg`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const activeTypes = Array.from(new Set(placedItems.map((p) => p.item.interaction_type)));

  return (
    <div className="card-glass p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-white">
            2D Protein–Ligand Interaction Diagram (Atom-Exact)
          </h3>
          <p className="text-[11px] text-slate-400">
            Dashed lines connect each residue directly to the exact interacting ligand atom or aromatic ring
          </p>
        </div>
        <button
          onClick={handleDownloadSvg}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-medium text-slate-100 transition"
        >
          <Download className="w-3.5 h-3.5 text-cyan-400" />
          Download SVG
        </button>
      </div>

      <div className="rounded-xl overflow-hidden border border-slate-700 bg-white">
        <svg
          ref={svgRef}
          xmlns="http://www.w3.org/2000/svg"
          viewBox={`0 0 ${width} ${height}`}
          className="w-full h-auto block"
        >
          <rect width={width} height={height} fill="#ffffff" />

          {/* Central RDKit 2D Ligand Depiction (exact 440x280 pixel space) */}
          <g transform={`translate(${offsetX}, ${offsetY})`}>
            {innerLigandSvg ? (
              <g dangerouslySetInnerHTML={{ __html: innerLigandSvg }} />
            ) : (
              <g>
                <rect
                  x={80}
                  y={75}
                  width={280}
                  height={130}
                  rx={16}
                  fill="#ecfeff"
                  stroke="#06b6d4"
                  strokeWidth={2}
                />
                <text
                  x={220}
                  y={145}
                  textAnchor="middle"
                  fontSize="18"
                  fontWeight="700"
                  fill="#0f172a"
                >
                  {ligandName}
                </text>
              </g>
            )}
          </g>

          {/* Atom-Exact Dashed Interaction Lines + Anchor Dots + Distance Pills */}
          {placedItems.map(({ item, ax, ay, lineEndX, lineEndY, pillX, pillY }) => {
            const style = INTERACTION_COLORS[item.interaction_type] || INTERACTION_COLORS.Hydrophobic;
            return (
              <g key={`bond-${item.residue}`}>
                <line
                  x1={ax}
                  y1={ay}
                  x2={lineEndX}
                  y2={lineEndY}
                  stroke={style.hex}
                  strokeWidth={2}
                  strokeDasharray={item.interaction_type === 'H-Bond' ? '6 4' : '4 4'}
                  strokeLinecap="round"
                />
                {/* Exact atom / ring anchor dot on the ligand structure */}
                <circle
                  cx={ax}
                  cy={ay}
                  r={4.2}
                  fill={style.hex}
                  stroke="#ffffff"
                  strokeWidth={1.4}
                />
                {/* Distance label pill */}
                <rect
                  x={pillX - 20}
                  y={pillY - 8.5}
                  width={40}
                  height={16.5}
                  rx={8}
                  fill="#ffffff"
                  stroke={style.hex}
                  strokeWidth={1.1}
                />
                <text
                  x={pillX}
                  y={pillY + 3}
                  textAnchor="middle"
                  fontSize="9"
                  fontFamily="Inter, sans-serif"
                  fontWeight="600"
                  fill="#0f172a"
                >
                  {item.distance.toFixed(2)} Å
                </text>
              </g>
            );
          })}

          {/* Radial Amino Acid Residue Nodes */}
          {placedItems.map(({ item, nx, ny }) => {
            const style = INTERACTION_COLORS[item.interaction_type] || INTERACTION_COLORS.Hydrophobic;
            const compStatus = statusMap[item.residue];

            return (
              <g key={`node-${item.residue}`} transform={`translate(${nx}, ${ny})`}>
                <circle r={30} fill={style.bg} stroke={style.hex} strokeWidth={2.5} />
                <text
                  y={-3}
                  textAnchor="middle"
                  fontSize="11"
                  fontWeight="700"
                  fontFamily="Inter, sans-serif"
                  fill="#0f172a"
                >
                  {item.resname}
                </text>
                <text
                  y={10}
                  textAnchor="middle"
                  fontSize="10"
                  fontWeight="600"
                  fontFamily="JetBrains Mono, monospace"
                  fill="#334155"
                >
                  {item.chain}:{item.resseq}
                </text>
                {compStatus && (
                  <g transform="translate(21, -21)">
                    <circle
                      r={8}
                      fill={compStatus === 'retained' ? '#10b981' : '#06b6d4'}
                      stroke="#ffffff"
                      strokeWidth={1.5}
                    />
                    <text
                      y={3}
                      textAnchor="middle"
                      fontSize="9"
                      fontWeight="700"
                      fill="#ffffff"
                    >
                      {compStatus === 'retained' ? '✓' : '+'}
                    </text>
                  </g>
                )}
              </g>
            );
          })}
        </svg>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-300 pt-1">
        {(activeTypes.length > 0 ? activeTypes : Object.keys(INTERACTION_COLORS)).map((t) => {
          const st = INTERACTION_COLORS[t] || INTERACTION_COLORS.Hydrophobic;
          return (
            <span key={t} className="inline-flex items-center gap-1.5">
              <span
                className="w-4 h-0 border-t-2 border-dashed inline-block"
                style={{ borderColor: st.hex }}
              />
              <span>{st.label}</span>
            </span>
          );
        })}
        <span className="ml-auto text-slate-400">
          ✓ Retained vs. Original • + Gained New Contact
        </span>
      </div>
    </div>
  );
};
