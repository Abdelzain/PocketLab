# PocketLab — All-in-One Molecular Docking & Comparative Analysis Platform

**PocketLab** is a unified, browser-based molecular docking workbench designed to eliminate multi-tool fragmentation. It guides researchers through:

1. **Interactive Protein Editor & Preparation** — Fetch by PDB ID or upload `.pdb`, inspect in 3D, toggle chains/waters/cofactors/ions, extract the native co-crystallized ligand as a benchmark reference, and prepare for docking.
2. **2D-to-3D Ligand Studio** — Draw/edit ligands interactively in 2D or import via SMILES/PubChem/SDF, inspect live medicinal chemistry properties (MW, LogP, TPSA, HBD/HBA, Lipinski, QED), and generate energy-minimized 3D conformers.
3. **Smart Active-Site Detection & 1-Click Redocking Validation** — Auto-detect the binding grid box from the native ligand (or geometric cavity detection for apo structures) and validate the protocol with symmetry-corrected Redocking RMSD (<= 2.0 A).
4. **Molecular Docking Engine** — Run AutoDock Vina with transparent, reproducible parameters.
5. **Deep Native-vs-Query Comparative Analysis** — Compare your docked ligand side-by-side against the original co-crystallized ligand: retained, gained, and lost residue interactions (H-bonds, hydrophobic contacts, pi-stacking, salt bridges), interaction similarity score, 3D pose overlay, and an auto-generated scientific summary.

## Quick Start (Local Development)

### Backend
```bash
conda env create -f backend/environment.yml
conda activate pocketlab
uvicorn app.main:app --app-dir backend --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Cloud Deployment (Zero/Low Cost)
A production `Dockerfile` is included in the repository root for deployment on **Hugging Face Spaces (Free Tier)** or any **$6/mo VPS** (Hetzner / DigitalOcean / Railway).
