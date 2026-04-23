import { execFile, execSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { promisify } from "node:util";
import * as vscode from "vscode";

import { CANOPY_BIN, runInstallBackend } from "./installBackend";

const execFileAsync = promisify(execFile);

export async function runSetupWizard(
  output: vscode.OutputChannel,
): Promise<void> {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    void vscode.window.showErrorMessage(
      "Canopy setup: open a folder first, then run Initialize Canopy here.",
    );
    return;
  }
  const cwd = folder.uri.fsPath;

  let canopyBin = locateCanopyBin();
  if (!canopyBin) {
    const choice = await vscode.window.showInformationMessage(
      "Canopy backend isn't installed yet. Install it now?",
      { modal: true },
      "Install",
    );
    if (choice !== "Install") return;
    const mcpPath = await runInstallBackend(output);
    if (!mcpPath) return;
    canopyBin = CANOPY_BIN;
  }

  output.appendLine(`[canopy] running '${canopyBin} init' in ${cwd}`);
  output.show(true);

  const ok = await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "Canopy: initializing workspace",
      cancellable: false,
    },
    async () => {
      try {
        const { stdout, stderr } = await execFileAsync(canopyBin!, ["init"], {
          cwd,
          maxBuffer: 20 * 1024 * 1024,
        });
        if (stdout.trim()) output.appendLine(stdout.trim());
        if (stderr.trim()) output.appendLine(stderr.trim());
        return true;
      } catch (err) {
        const message = (err as Error).message;
        output.appendLine(`[canopy] init failed: ${message}`);
        void vscode.window.showErrorMessage(
          `Canopy init failed: ${message}. See Output panel for details.`,
        );
        return false;
      }
    },
  );
  if (!ok) return;

  if (!fs.existsSync(path.join(cwd, "canopy.toml"))) {
    void vscode.window.showErrorMessage(
      "Canopy init ran but no canopy.toml was written. See Output panel.",
    );
    return;
  }

  const pick = await vscode.window.showInformationMessage(
    "Canopy workspace initialized. Reload window to activate the sidebar?",
    "Reload Window",
    "Later",
  );
  if (pick === "Reload Window") {
    await vscode.commands.executeCommand("workbench.action.reloadWindow");
  }
}

function locateCanopyBin(): string | null {
  if (fs.existsSync(CANOPY_BIN)) return CANOPY_BIN;
  const shellHit = resolveViaLoginShell("canopy");
  if (shellHit) return shellHit;
  return null;
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
