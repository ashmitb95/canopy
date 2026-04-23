import { execFile, execSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { promisify } from "node:util";
import * as vscode from "vscode";

const execFileAsync = promisify(execFile);

export const VENV_DIR = path.join(os.homedir(), ".canopy-vscode", "venv");
const PIP_BIN = path.join(VENV_DIR, "bin", "pip");
export const MCP_BIN = path.join(VENV_DIR, "bin", "canopy-mcp");
export const CANOPY_BIN = path.join(VENV_DIR, "bin", "canopy");

const GIT_URL = "git+https://github.com/ashmitb95/canopy.git";

/**
 * One-click Canopy backend installer.
 *
 *   1. Finds python3 (>= 3.10) via login shell.
 *   2. Creates a managed venv at ~/.canopy-vscode/venv.
 *   3. Installs canopy — editable from a detected local checkout if we can
 *      find one, otherwise `pip install git+https://github.com/...`.
 *   4. Saves the absolute canopy-mcp path to the extension setting so the
 *      extension uses it without needing a shell PATH.
 *
 * Returns the resolved canopy-mcp path if installation succeeded.
 */
export async function runInstallBackend(
  output: vscode.OutputChannel,
): Promise<string | null> {
  output.show(true);
  output.appendLine("[canopy] starting backend installer");

  const python = await findPython(output);
  if (!python) return null;

  const source = resolveSource();
  output.appendLine(`[canopy] install source: ${source.label}`);

  return await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "Canopy: installing backend",
      cancellable: false,
    },
    async (progress) => {
      try {
        progress.report({ message: "creating virtualenv" });
        fs.mkdirSync(path.dirname(VENV_DIR), { recursive: true });
        await runLogged(python, ["-m", "venv", VENV_DIR], output);

        progress.report({ message: "upgrading pip" });
        await runLogged(
          PIP_BIN,
          ["install", "--upgrade", "pip", "--quiet"],
          output,
        );

        progress.report({ message: `installing from ${source.label}` });
        await runLogged(PIP_BIN, ["install", ...source.pipArgs], output);

        if (!fs.existsSync(MCP_BIN)) {
          throw new Error(
            `installer finished but ${MCP_BIN} is missing — the installed package may not expose a canopy-mcp entry point.`,
          );
        }

        const cfg = vscode.workspace.getConfiguration("canopy");
        await cfg.update(
          "canopyMcpPath",
          MCP_BIN,
          vscode.ConfigurationTarget.Global,
        );
        output.appendLine(`[canopy] saved canopy.canopyMcpPath = ${MCP_BIN}`);

        void vscode.window.showInformationMessage(
          "Canopy backend installed. Reconnecting…",
        );
        return MCP_BIN;
      } catch (err) {
        const message = (err as Error).message;
        output.appendLine(`[canopy] install failed: ${message}`);
        void vscode.window.showErrorMessage(
          `Canopy install failed: ${message}. See Output panel for details.`,
        );
        return null;
      }
    },
  );
}

interface SourceChoice {
  label: string;
  pipArgs: string[];
}

function resolveSource(): SourceChoice {
  const localDir = detectLocalCheckout();
  if (localDir) {
    return { label: `local checkout (${localDir})`, pipArgs: ["-e", localDir] };
  }
  return { label: `GitHub (${GIT_URL})`, pipArgs: [GIT_URL] };
}

function detectLocalCheckout(): string | null {
  const candidates: string[] = [];
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    candidates.push(folder.uri.fsPath);
  }
  candidates.push(
    path.join(os.homedir(), "projects", "canopy"),
    path.join(os.homedir(), "src", "canopy"),
    path.join(os.homedir(), "code", "canopy"),
  );
  for (const dir of candidates) {
    if (
      fs.existsSync(path.join(dir, "pyproject.toml")) &&
      fs.existsSync(path.join(dir, "src", "canopy"))
    ) {
      return dir;
    }
  }
  return null;
}

async function findPython(
  output: vscode.OutputChannel,
): Promise<string | null> {
  const tried: string[] = [];

  const settingPython = vscode.workspace
    .getConfiguration("canopy")
    .get<string>("pythonPath");
  if (settingPython) {
    tried.push(settingPython);
    if (await isUsablePython(settingPython, output)) return settingPython;
  }

  const shellHit = resolveViaLoginShell("python3");
  if (shellHit) {
    tried.push(shellHit);
    if (await isUsablePython(shellHit, output)) return shellHit;
  }

  const fixed = [
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "/usr/bin/python3",
  ];
  for (const p of fixed) {
    if (fs.existsSync(p)) {
      tried.push(p);
      if (await isUsablePython(p, output)) return p;
    }
  }

  const picked = await vscode.window.showErrorMessage(
    `Canopy: no suitable python3 found (tried: ${tried.join(", ") || "nothing"}). Install Python 3.10+ and try again.`,
    "Open Download Page",
  );
  if (picked === "Open Download Page") {
    void vscode.env.openExternal(
      vscode.Uri.parse("https://www.python.org/downloads/"),
    );
  }
  return null;
}

async function isUsablePython(
  bin: string,
  output: vscode.OutputChannel,
): Promise<boolean> {
  try {
    const { stdout } = await execFileAsync(bin, [
      "-c",
      "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
    ]);
    const version = stdout.trim();
    const [maj, min] = version.split(".").map((n) => Number(n));
    if (maj >= 3 && min >= 10) {
      output.appendLine(`[canopy] using ${bin} (Python ${version})`);
      return true;
    }
    output.appendLine(`[canopy] rejecting ${bin} (Python ${version} < 3.10)`);
  } catch (err) {
    output.appendLine(`[canopy] could not run ${bin}: ${(err as Error).message}`);
  }
  return false;
}

function resolveViaLoginShell(binary: string): string | null {
  try {
    const shell = process.env.SHELL || "/bin/zsh";
    const stdout = execSync(`${shell} -ilc 'command -v ${binary}' 2>/dev/null`, {
      encoding: "utf8",
      timeout: 3000,
    });
    const line = stdout.trim().split("\n").pop() ?? "";
    if (line && path.isAbsolute(line) && fs.existsSync(line)) return line;
  } catch {
    // ignore
  }
  return null;
}

async function runLogged(
  bin: string,
  args: string[],
  output: vscode.OutputChannel,
): Promise<void> {
  output.appendLine(`$ ${bin} ${args.join(" ")}`);
  const { stdout, stderr } = await execFileAsync(bin, args, {
    maxBuffer: 20 * 1024 * 1024,
  });
  if (stdout.trim()) output.appendLine(stdout.trim());
  if (stderr.trim()) output.appendLine(stderr.trim());
}
