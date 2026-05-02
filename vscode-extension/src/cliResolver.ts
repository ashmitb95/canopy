/**
 * Resolve the absolute path to the `canopy` CLI binary.
 *
 * VSCode windows launched from Dock/Finder/Spotlight don't inherit the shell's
 * PATH — they get a minimal `/usr/bin:/bin`. So `child_process.execFile("canopy", …)`
 * fails with ENOENT even when `canopy` works perfectly in the terminal. This
 * resolver tries (in order):
 *
 *   1. The user's `canopy.cliPath` setting if it's an existing absolute path.
 *   2. A login-shell `command -v canopy` — picks up wherever the user actually
 *      installed it (pipx, brew, asdf, mise, custom $PATH).
 *   3. A scan of common install dirs (workspace `.venv`, pipx, brew, /usr/local).
 *   4. Give up and return the configured name with `resolvedVia: "unresolved"`
 *      so the caller can surface a "couldn't find canopy" error with the search
 *      paths that were tried.
 *
 * Returns the resolved path + a short string explaining how it was found
 * (useful for the extension's "Show Log" output channel).
 *
 * Design source: matches the pattern in
 * `AgathaCrystal/canopy@extension-rewrite:vscode-extension/src/cliResolver.ts`,
 * rewritten in our voice with workspace `.canopy/venv` and pipx as additional
 * scan candidates.
 */
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export interface CliResolution {
  /** Absolute path attempted (may not exist if `resolvedVia === "unresolved"`). */
  path: string;
  /** Short human label of the resolution method — for logging. */
  resolvedVia:
    | "settings"
    | "login-shell"
    | "disk-scan"
    | "unresolved";
  /** Paths tried, in order. Useful for the "couldn't find canopy" error. */
  tried: string[];
}

const LOGIN_SHELL_TIMEOUT_MS = 3000;

export function resolveCanopyCli(
  configuredPath: string,
  workspaceRoot: string | null,
): CliResolution {
  const tried: string[] = [];

  // 1. Absolute path from settings — use as-is if it exists.
  if (path.isAbsolute(configuredPath)) {
    tried.push(configuredPath);
    if (fs.existsSync(configuredPath)) {
      return { path: configuredPath, resolvedVia: "settings", tried };
    }
  }

  // 2. Bare name (e.g. "canopy") — try a login shell so we pick up the user's
  //    actual install location regardless of how VSCode was launched.
  if (!configuredPath.includes("/")) {
    const shellResolved = resolveViaLoginShell(configuredPath);
    if (shellResolved) {
      tried.push(shellResolved);
      return { path: shellResolved, resolvedVia: "login-shell", tried };
    }
  }

  // 3. Disk scan of common install locations.
  for (const candidate of diskCandidates(configuredPath, workspaceRoot)) {
    tried.push(candidate);
    if (fs.existsSync(candidate)) {
      return { path: candidate, resolvedVia: "disk-scan", tried };
    }
  }

  // 4. Give up. Caller surfaces the ENOENT with `tried` so the user can see
  //    where we looked.
  return { path: configuredPath, resolvedVia: "unresolved", tried };
}

function resolveViaLoginShell(binary: string): string | null {
  const shell = process.env.SHELL || "/bin/zsh";
  try {
    // `-ilc` runs an interactive login shell that sources the user's profile,
    // so we get the same PATH the user sees in their terminal. `command -v`
    // is portable across bash/zsh/fish (vs `which`).
    const stdout = execFileSync(
      shell,
      ["-ilc", `command -v ${binary} 2>/dev/null`],
      { encoding: "utf8", timeout: LOGIN_SHELL_TIMEOUT_MS },
    );
    // Login shells often print MOTD / shell init noise. The path is on the
    // last non-empty line.
    const line = stdout.split("\n").map((s) => s.trim()).filter(Boolean).pop() ?? "";
    if (line && path.isAbsolute(line) && fs.existsSync(line)) {
      return line;
    }
  } catch {
    // Shell missing, command not found, or timeout — fall through silently.
  }
  return null;
}

function diskCandidates(
  binaryName: string,
  workspaceRoot: string | null,
): string[] {
  const name = binaryName.includes("/") ? path.basename(binaryName) : binaryName;
  const home = os.homedir();
  const candidates: string[] = [];

  // Workspace-scoped install (canopy's own convention for managed venvs).
  if (workspaceRoot) {
    candidates.push(path.join(workspaceRoot, ".venv", "bin", name));
    candidates.push(path.join(workspaceRoot, ".canopy", "venv", "bin", name));
  }

  // Per-user install locations.
  candidates.push(
    path.join(home, ".local", "bin", name),
    path.join(home, ".local", "pipx", "venvs", "canopy", "bin", name),
    path.join(home, ".canopy-vscode", "venv", "bin", name),
  );

  // System-wide install locations.
  candidates.push(
    "/opt/homebrew/bin/" + name,
    "/usr/local/bin/" + name,
    "/usr/bin/" + name,
  );

  return candidates;
}
