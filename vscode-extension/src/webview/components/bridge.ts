import type { ThemeName } from "../themes";
import { listThemes } from "../themes";
import { escapeHtml } from "./util";

export type BridgeProps = {
  /** Workspace root path, displayed as inline code. */
  workspaceLabel: string;
  /** Currently-canonical feature name (null when nothing is in main). */
  canonicalFeature: string | null;
  /** Number of features currently in worktrees. */
  worktreeCount: number;
  /** Worktree slot cap from canopy.toml (default 2). */
  worktreeCap: number;
  /** Active theme — used to highlight the toggle. */
  activeTheme: ThemeName;
};

/**
 * The cockpit's top bar. Carries:
 *   - canopy insignia + workspace path
 *   - theme toggle (settings shortcut)
 *   - lamp pill: current canonical feature
 *   - lamp pill: worktree slot usage (warm tinted normally, hot when at cap)
 *
 * All click handlers go through `postMessage` to the panel (e.g.
 * `{ type: "setTheme", theme: "minimal" }`).
 */
export function renderBridge(props: BridgeProps): string {
  const { workspaceLabel, canonicalFeature, worktreeCount, worktreeCap, activeTheme } = props;

  const themes = listThemes();
  const themeButtons = themes
    .map(
      (t) =>
        `<button data-theme="${escapeHtml(t.id)}" class="${
          t.id === activeTheme ? "active" : ""
        }" title="${escapeHtml(t.description)}">${escapeHtml(t.name)}</button>`,
    )
    .join("");

  const canonicalPill = canonicalFeature
    ? `<span class="lamp-pill" title="Currently in main">
         <span class="lamp"></span>
         Main: <strong>${escapeHtml(canonicalFeature)}</strong>
       </span>`
    : `<span class="lamp-pill" title="Nothing currently in main">
         <span class="lamp idle"></span>
         Main: <strong>—</strong>
       </span>`;

  const atCap = worktreeCap > 0 && worktreeCount >= worktreeCap;
  const worktreePill = `<span class="lamp-pill ${atCap ? "cap" : "warm"}" title="Worktree slots in use vs cap from canopy.toml">
       <span class="lamp"></span>
       Worktrees: <strong>${worktreeCount} / ${worktreeCap || "∞"}</strong>
     </span>`;

  return `
<header class="bridge">
  <div class="insignia">
    <div class="compass" aria-hidden="true"></div>
    <span>Canopy</span>
  </div>
  <span class="station">workspace <code>${escapeHtml(workspaceLabel)}</code></span>
  <span class="spacer"></span>
  <span class="theme-toggle" role="group" aria-label="Theme">
    ${themeButtons}
  </span>
  ${canonicalPill}
  ${worktreePill}
</header>
`.trim();
}
