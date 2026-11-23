import type { GridBox } from '../types/docking';

export interface WebinaRunOptions {
  box: GridBox;
  exhaustiveness?: number;
  numModes?: number;
  localOnly?: boolean;
  cpu?: number;
}

export interface WebinaRunResult {
  outPdbqt: string;
  stdout: string;
  stderr: string;
}

export function isWebinaSupported(): boolean {
  return typeof WebAssembly === 'object' && typeof SharedArrayBuffer !== 'undefined';
}

export function parseLocalAffinity(stdout: string): number | null {
  const m = stdout.match(/(?:Affinity|Estimated Free Energy of Binding)\s*:\s*(-?\d+\.\d+)/i);
  return m ? Math.round(parseFloat(m[1]) * 100) / 100 : null;
}

export async function runWebinaInBrowser(
  options: WebinaRunOptions,
  receptorPdbqt: string,
  ligandPdbqt: string
): Promise<WebinaRunResult> {
  if (!isWebinaSupported()) {
    throw new Error(
      'In-browser WebAssembly multi-threading (SharedArrayBuffer) is not enabled in this browser context.'
    );
  }

  // Dynamic runtime import from /webina/vina.js (served from public/webina/)
  const modUrl = '/webina/vina.js';
  const mod: any = await import(/* @vite-ignore */ modUrl);
  const WEBINA_MODULE = mod.default;

  return new Promise<WebinaRunResult>((resolve, reject) => {
    let initializedObj: any = null;
    let stdout = '';
    let stderr = '';
    let settled = false;

    const finishErr = (msg: string) => {
      if (settled) return;
      settled = true;
      reject(new Error(msg));
    };

    const finishOk = (outPdbqt: string) => {
      if (settled) return;
      settled = true;
      resolve({ outPdbqt, stdout, stderr });
    };

    try {
      const webinaMod = new WEBINA_MODULE({
        noInitialRun: true,
        locateFile: (path: string) => `/webina/${path}`,
        preRun: [
          function (instance: any) {
            instance.FS.writeFile('/receptor.pdbqt', receptorPdbqt);
            instance.FS.writeFile('/ligand.pdbqt', ligandPdbqt);
            initializedObj = instance;
          },
        ],
        print: (text: string) => {
          stdout += text + '\n';
        },
        printErr: (text: string) => {
          stderr += text + '\n';
        },
        onExit: (code: number) => {
          if (code !== 0) {
            finishErr(`AutoDock Vina WASM exited with code ${code}: ${stderr || stdout}`);
            return;
          }
          try {
            let outTxt = '';
            if (!options.localOnly && initializedObj?.FS) {
              outTxt = initializedObj.FS.readFile('/ligand_out.pdbqt', { encoding: 'utf8' });
            }
            finishOk(outTxt);
          } catch (e: any) {
            finishErr(`Failed to read docking output from Webina: ${e?.message || e}`);
          }
        },
        onAbort: (what: any) => {
          finishErr(`AutoDock Vina WASM aborted: ${what}`);
        },
      });

      webinaMod.ready
        .then((instance: any) => {
          const defaultCpu = Math.min(4, Math.max(1, (navigator.hardwareConcurrency || 2) - 1));
          const cpu = options.cpu ?? defaultCpu;
          const args: string[] = [
            '--receptor',
            '/receptor.pdbqt',
            '--ligand',
            '/ligand.pdbqt',
            '--center_x',
            String(options.box.center_x),
            '--center_y',
            String(options.box.center_y),
            '--center_z',
            String(options.box.center_z),
            '--size_x',
            String(options.box.size_x),
            '--size_y',
            String(options.box.size_y),
            '--size_z',
            String(options.box.size_z),
            '--cpu',
            String(cpu),
          ];

          if (options.localOnly) {
            args.push('--local_only');
          } else {
            args.push(
              '--exhaustiveness',
              String(options.exhaustiveness ?? 8),
              '--num_modes',
              String(options.numModes ?? 9),
              '--out',
              '/ligand_out.pdbqt'
            );
          }

          instance.callMain(args);
        })
        .catch((err: any) => {
          finishErr(`Failed to initialize AutoDock Vina WASM: ${err?.message || err}`);
        });
    } catch (err: any) {
      finishErr(`Webina startup error: ${err?.message || err}`);
    }
  });
}
