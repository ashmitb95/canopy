import { execSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

/**
 * Resolve the canopy-mcp executable.
 *
 * VSCode windows launched from the Dock/Finder don't inherit the shell PATH,
 * so `canopy-mcp` fails to spawn even when it works perfectly in the terminal.
 * This resolver falls back to a login-shell `which` and then to common venv
 * locations so the extension works out of the box for most users.
 */
export function resolveCanopyMcp(
  configuredPath: string,
  workspaceRoot: string | null,
): { path: string; resolvedVia: string } {
  // 1. Absolute path from settings — use as-is if it exists.
  if (path.isAbsolute(configuredPath) && fs.existsSync(configuredPath)) {
    return { path: configuredPath, resolvedVia: "settings (absolute)" };
  }

  // 2. If the configured path is a bare name (default "canopy-mcp"), try a login shell.
  if (configuredPath === "canopy-mcp" || !configuredPath.includes("/")) {
    const shellResolved = resolveViaLoginShell(configuredPath);
    if (shellResolved) return { path: shellResolved, resolvedVia: "login shell" };
  }

  // 3. Try common venv locations, relative to the workspace root first.
  const candidates: string[] = [];
  if (workspaceRoot) {
    candidates.push(
      path.join(workspaceRoot, ".venv", "bin", "canopy-mcp"),
      path.join(workspaceRoot, "venv", "bin", "canopy-mcp"),
    );
  }
  const home = os.homedir();
  // The extension's own managed venv (created by Canopy: Install Backend).
  candidates.push(path.join(home, ".canopy-vscode", "venv", "bin", "canopy-mcp"));
  // Home-dir conventions.
  candidates.push(
    path.join(home, ".venv", "bin", "canopy-mcp"),
    path.join(home, "venv", "bin", "canopy-mcp"),
    path.join(home, ".local", "bin", "canopy-mcp"),
    "/opt/homebrew/bin/canopy-mcp",
    "/usr/local/bin/canopy-mcp",
  );
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return { path: candidate, resolvedVia: `disk scan (${candidate})` };
    }
  }

  // 4. Scan common dev-project parents for *any* checkout that has
  //    .venv/bin/canopy-mcp. Keeps working when Canopy is installed into a
  //    sibling project's venv (the common case when `pip install -e .` was
  //    run from the canopy repo itself).
  const projectParents = [
    path.join(home, "projects"),
    path.join(home, "src"),
    path.join(home, "code"),
    path.join(home, "Developer"),
    path.join(home, "dev"),
    path.join(home, "workspace"),
  ];
  for (const parent of projectParents) {
    if (!fs.existsSync(parent)) continue;
    let children: string[];
    try {
      children = fs.readdirSync(parent);
    } catch {
      continue;
    }
    for (const child of children) {
      const candidate = path.join(parent, child, ".venv", "bin", "canopy-mcp");
      if (fs.existsSync(candidate)) {
        return {
          path: candidate,
          resolvedVia: `sibling project scan (${candidate})`,
        };
      }
    }
  }

  // 5. Last-ditch: ask a system python which canopy-mcp *would* be.
  const viaPython = resolveViaPython();
  if (viaPython) return { path: viaPython, resolvedVia: "python -m canopy" };

  // 6. Give up — caller surfaces the ENOENT with a helpful toast.
  return { path: configuredPath, resolvedVia: "unresolved (PATH fallback)" };
}

function resolveViaPython(): string | null {
  const pythons = [
    process.env.SHELL ? resolveViaLoginShell("python3") : null,
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "/usr/bin/python3",
  ].filter((p): p is string => !!p && fs.existsSync(p));
  for (const py of pythons) {
    try {
      // Ask Python where the canopy package lives; derive the canopy-mcp entry.
      const stdout = execSync(
        `${py} -c "import canopy, os, sys; base = os.path.dirname(os.path.dirname(sys.executable)); mcp = os.path.join(base, 'bin', 'canopy-mcp'); print(mcp if os.path.exists(mcp) else '')"`,
        { encoding: "utf8", timeout: 3000 },
      ).trim();
      if (stdout && fs.existsSync(stdout)) return stdout;
    } catch {
      // canopy not importable by this python — try the next one
    }
  }
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
    if (line && path.isAbsolute(line) && fs.existsSync(line)) {
      return line;
    }
  } catch {
    // shell missing or command not found — fall through
  }
  return null;
}
