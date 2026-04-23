# Change Log

## 0.1.6

- **Fixed dashboard crash (`i.map is not a function`)** — list-returning MCP tools (`feature_list`, `log`, `linear_my_issues`, etc.) now come through as arrays again. FastMCP wraps non-dict returns in `{ "result": <list> }` to satisfy the spec's object-only `structuredContent`; the client now unwraps that convention before handing the value to callers.
- Features view and Worktrees view light up together after a reinit.

## 0.1.5

- **Fixed post-reinit crash** — the MCP client now reads `structuredContent` first (MCP 2025-06 spec) before falling back to text blocks. This prevents `{}` responses that caused *"Cannot read properties of undefined (reading 'length')"* after `Force Reinit Workspace`.
- Hardened every tree provider, the reinit toast, and the status bar against any missing or malformed fields from the MCP — each failure now logs a stack trace to the Canopy output channel instead of silently emptying the view.
- `refresh()` no longer throws synchronously when the status bar can't compute ahead/behind; errors are caught per-slice with traces.

## 0.1.4

- **Force Reinit Workspace** — `…` menu on the Features view (or the command palette) re-runs Canopy's repo/worktree discovery and overwrites `canopy.toml`. Useful after adding/removing repos or worktrees outside Canopy.
- **Preview Reinit (dry run)** — opens the would-be new `canopy.toml` in an editor tab without writing. Runs through the same modal confirmation as the real reinit.
- Backed by a new `workspace_reinit` MCP tool (Canopy now exposes 30 tools).

## 0.1.3

- **Features view now merges three data sources** — `features.json` (explicit features), `.canopy/worktrees/*` on disk (implicit worktrees), and `workspace_status.active_features` (multi-repo branches). Worktrees created outside `canopy feature create` (e.g. by an older Canopy or plain `git worktree add`) now appear in Features instead of being invisible.
- Resolver now scans `~/projects/*`, `~/src/*`, `~/code/*`, `~/Developer/*`, `~/dev/*`, `~/workspace/*` for any sibling checkout with a `.venv/bin/canopy-mcp`. Finds existing Canopy installs automatically — no more false *"can't start canopy-mcp"* when Canopy is already installed in a neighbouring project's venv.
- Last-ditch resolver fallback: asks system `python3` whether it can import `canopy`, and derives the `canopy-mcp` entry point from `sys.executable`.
- Also scans the extension's managed venv (`~/.canopy-vscode/venv/bin/canopy-mcp`) so post-install reconnects work without needing the configured setting.

## 0.1.2

- **Install Backend command**: one-click installer creates a managed venv at `~/.canopy-vscode/venv`, installs `canopy` from PyPI / a local checkout / a git URL, and points the extension at the new `canopy-mcp`. Triggered from the sidebar's *Install Canopy for me* button or from the error toast.
- Retry Connect re-reads the setting so a fresh install takes effect immediately.
- New `canopy.pythonPath` setting to pin the python3 used by the installer.

## 0.1.1

- Auto-resolve `canopy-mcp` via the user's login shell and common venv locations, so GUI-launched VSCode windows work without pre-setting PATH.
- Rewrote the sidebar welcome so it stops falsely saying "No Canopy workspace detected" when the real problem is a missing backend binary.
- Collapsed per-provider error toasts into a single up-front activation error with **Open Settings / Show Log** actions.
- New commands: `Canopy: Retry Connect`, `Canopy: Show Log`.

## 0.1.0 — Initial release

- Activity-bar entry with four sidebar sections: Features, Worktrees, Changes, Review Readiness
- Per-feature dashboard webview with branch state, Linear/GitHub status, recent commits, and overlap warnings
- "Create Feature" quick pick with Linear-issue autocomplete
- Status-bar items for active feature, repo count, and aggregate ahead/behind
- File watching on `.canopy/features.json` and worktree HEADs for live refresh
- All data flows through the existing `canopy-mcp` server over stdio
