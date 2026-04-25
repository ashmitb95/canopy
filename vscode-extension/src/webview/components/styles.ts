/**
 * Component CSS for the cockpit dashboard.
 *
 * References tokens via `var(--*)` only — never raw hex codes. Add new
 * components by appending their styles here. Theme swaps don't touch this file.
 *
 * Layout grammar:
 *   .bridge          — top bar
 *   .layout          — main grid (cockpit content + triage rail)
 *   .main            — main pane (focus tile, worktree row, branch ledger)
 *   .triage          — right rail
 *
 * Component grammar:
 *   .focus-tile      — canonical feature card
 *   .repo-row        — per-repo line inside a feature card
 *   .badge           — state / slot indicator pill
 *   .lamp-pill       — instrument-panel-style indicator (bridge bar)
 *   .theme-toggle    — settings-driven theme switcher
 */
export const componentCss = String.raw`
/* ── Bridge bar ────────────────────────────────────────────────── */
.bridge {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 11px 24px;
  background: var(--color-bg-elev);
  border-bottom: var(--shape-border-width) solid var(--color-border);
}
.bridge .insignia {
  display: flex; align-items: center; gap: 8px;
  font-weight: 600; font-size: var(--type-base-size);
}
.bridge .insignia .compass {
  width: 16px; height: 16px;
  border: 1.5px solid var(--color-fg-dim);
  border-radius: 50%;
  position: relative;
}
.bridge .insignia .compass::before,
.bridge .insignia .compass::after { content: ""; position: absolute; background: var(--color-fg-dim); }
.bridge .insignia .compass::before { top: 1px; bottom: 1px; left: 50%; width: 1px; transform: translateX(-50%); }
.bridge .insignia .compass::after  { left: 1px; right: 1px; top: 50%; height: 1px; transform: translateY(-50%); }

.bridge .station {
  color: var(--color-fg-muted);
  font-size: 12px;
  margin-left: 4px;
}
.bridge .station code { color: var(--color-fg); }
.bridge .spacer { flex: 1; }

.lamp-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 4px 11px;
  background: var(--color-bg-elev-2);
  border: var(--shape-border-width) solid var(--color-border-soft);
  border-radius: var(--shape-radius-sm);
  color: var(--color-fg-muted);
  font-size: 12px;
}
.lamp-pill .lamp {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--color-ok);
  box-shadow: 0 0 6px var(--color-ok);
}
.lamp-pill.warm .lamp { background: var(--color-warn); box-shadow: 0 0 6px var(--color-warn); }
.lamp-pill.cap .lamp  { background: var(--color-hot);  box-shadow: 0 0 6px var(--color-hot);  }
.lamp-pill .lamp.idle { background: var(--color-fg-dim); box-shadow: none; }
.lamp-pill strong { color: var(--color-fg); margin-left: 2px; font-weight: 500; }

.theme-toggle {
  display: inline-flex;
  border: var(--shape-border-width) solid var(--color-border-soft);
  border-radius: var(--shape-radius-sm);
  background: var(--color-bg-elev-2);
}
.theme-toggle button {
  background: none; border: none; cursor: pointer;
  padding: 5px 12px;
  font-size: 11px;
  color: var(--color-fg-muted);
  font-family: inherit;
  font-weight: 500;
}
.theme-toggle button + button { border-left: var(--shape-border-width) solid var(--color-border-soft); }
.theme-toggle button:hover { color: var(--color-fg); }
.theme-toggle button.active {
  background: var(--color-bg-elev-3);
  color: var(--color-fg);
}

/* ── Layout ──────────────────────────────────────────────────────── */
.layout {
  display: grid;
  grid-template-columns: 1fr 320px;
  height: calc(100vh - 42px);
}
.main {
  padding: 24px 32px 60px;
  overflow-y: auto;
}
.triage-rail {
  background: var(--color-bg-elev);
  border-left: var(--shape-border-width) solid var(--color-border-soft);
  overflow-y: auto;
}

/* ── Section heading ───────────────────────────────────────────── */
.section-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 0 0 12px;
  color: var(--color-fg-muted);
  font-size: 12px;
  font-weight: 500;
}
.section-head .count { color: var(--color-fg-dim); font-size: 11px; }
.section-head .hint  { color: var(--color-fg-dim); font-size: 11px; margin-left: auto; }
.main > .section-head:not(:first-child) { margin-top: 26px; }

/* ── Focus tile (canonical feature) ────────────────────────────── */
.focus-tile {
  background: var(--color-bg-elev);
  border: var(--shape-border-width) solid var(--color-border);
  border-left: 2px solid var(--color-ok);
  border-radius: var(--shape-radius);
  padding: 20px 22px;
}
.focus-tile.empty {
  border-left-color: var(--color-fg-dim);
  color: var(--color-fg-muted);
}
.focus-tile h2 {
  margin: 0 0 6px;
  font-size: 18px;
  font-weight: var(--type-headline-weight);
  letter-spacing: var(--type-headline-letter-spacing);
}
.focus-tile h2 .sub {
  color: var(--color-fg-muted);
  font-weight: 400;
  font-size: 13px;
  margin-left: 8px;
}
.focus-tile .meta-row {
  display: flex; gap: 8px; align-items: center;
  margin-bottom: 14px;
}

.badge {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11px;
  padding: 3px 9px;
  border-radius: 11px;
}
.badge.canonical          { color: var(--color-ok);   background: var(--color-ok-soft); }
.badge.worktree           { color: var(--color-warn); background: var(--color-warn-soft); }
.badge.branch             { color: var(--color-fg-dim); background: var(--color-bg-elev-2); }
.badge.state-needs_work       { color: var(--color-hot);    background: var(--color-hot-soft); }
.badge.state-in_progress      { color: var(--color-warn);   background: var(--color-warn-soft); }
.badge.state-ready_to_commit  { color: var(--color-accent); background: var(--color-accent-soft); }
.badge.state-ready_to_push    { color: var(--color-accent); background: var(--color-accent-soft); }
.badge.state-awaiting_review  { color: var(--color-fg-muted); background: var(--color-bg-elev-2); }
.badge.state-approved         { color: var(--color-ok);    background: var(--color-ok-soft); }
.badge.state-no_prs           { color: var(--color-fg-dim); background: var(--color-bg-elev-2); }
.badge.state-drifted          { color: var(--color-hot);    background: var(--color-hot-soft); }

.pill-link {
  color: var(--color-accent);
  text-decoration: none;
  font-size: 11px;
  padding: 2px 9px;
  background: var(--color-accent-soft);
  border-radius: 9px;
}
.pill-link:hover { text-decoration: underline; }

/* ── Per-repo strip (inside focus-tile or worktree-card) ────────── */
.repo-strip { display: grid; gap: 6px; margin-bottom: 14px; }
.repo-row {
  display: grid;
  grid-template-columns: 90px 1fr auto auto auto;
  gap: 14px;
  align-items: center;
  padding: 9px 12px;
  background: var(--color-bg);
  border: var(--shape-border-width) solid var(--color-border-soft);
  border-radius: var(--shape-radius-sm);
  font-size: 12px;
}
.repo-row .name { font-weight: 600; }
.repo-row .branch {
  color: var(--color-fg-muted);
  font-family: var(--font-mono);
  font-size: 11px;
}
.repo-row .dirty       { color: var(--color-warn); font-size: 11px; }
.repo-row .ahead       { color: var(--color-accent); font-size: 11px; }
.repo-row .pr {
  color: var(--color-accent);
  font-size: 11px;
  text-decoration: none;
}
.repo-row .pr:hover { text-decoration: underline; }
.repo-row .actionable { color: var(--color-hot); font-size: 11px; font-weight: 500; }

/* ── Buttons ────────────────────────────────────────────────────── */
.cta-row { display: flex; gap: 8px; flex-wrap: wrap; }
button.btn {
  background: var(--color-bg-elev-2);
  color: var(--color-fg);
  border: var(--shape-border-width) solid var(--color-border);
  border-radius: var(--shape-radius-sm);
  padding: 7px 14px;
  font-size: 12px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
}
button.btn:hover { background: var(--color-bg-elev-3); }
button.btn.primary {
  background: var(--color-accent);
  border-color: var(--color-accent);
  color: #fff;
}
button.btn.primary:hover { filter: brightness(1.08); }
button.btn .preview {
  color: var(--color-fg-muted);
  font-weight: 400;
  font-size: 11px;
  margin-left: 6px;
}
button.btn.primary .preview { color: rgba(255, 255, 255, 0.78); }
button.btn:disabled { opacity: 0.45; cursor: not-allowed; }

/* ── Empty state ───────────────────────────────────────────────── */
.empty-hint {
  color: var(--color-fg-muted);
  font-size: 13px;
  line-height: 1.6;
  padding: 6px 0;
}
.empty-hint .glyph {
  color: var(--color-accent);
  margin-right: 6px;
}

/* ── Loading state ─────────────────────────────────────────────── */
.skeleton {
  background: linear-gradient(
    90deg,
    var(--color-bg-elev) 0%,
    var(--color-bg-elev-2) 50%,
    var(--color-bg-elev) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.4s ease-in-out infinite;
  border-radius: var(--shape-radius-sm);
}
@keyframes shimmer {
  0% { background-position: 100% 0; }
  100% { background-position: -100% 0; }
}
`;
