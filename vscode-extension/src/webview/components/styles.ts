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

/* ── Standby row (warm worktree cards) ──────────────────────────── */
.standby-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.standby-card {
  background: var(--color-bg-elev);
  border: var(--shape-border-width) solid var(--color-border-soft);
  border-left: 2px solid var(--color-warn);
  border-radius: var(--shape-radius);
  padding: 14px 16px;
}
.standby-card .meta-row {
  display: flex; gap: 8px; align-items: center;
  margin-bottom: 8px;
}
.standby-card h3 {
  margin: 0 0 6px;
  font-size: 14px;
  font-weight: var(--type-headline-weight);
}
.standby-card .summary {
  color: var(--color-fg-muted);
  font-size: 11px;
  margin-bottom: 10px;
}
.standby-card .actions { display: flex; gap: 6px; }
.standby-card button.btn { padding: 4px 10px; font-size: 11px; }

/* ── Cold ledger (branch-only features) ────────────────────────── */
.cold-ledger {
  background: var(--color-bg-elev);
  border: var(--shape-border-width) solid var(--color-border-soft);
  border-radius: var(--shape-radius);
  overflow: hidden;
}
.cold-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 14px;
  align-items: center;
  padding: 9px 14px;
  border-top: var(--shape-border-width) solid var(--color-border-soft);
  font-size: 12px;
}
.cold-row:first-child { border-top: none; }
.cold-row:hover { background: var(--color-bg-elev-2); }
.cold-row .name { font-weight: 500; }
.cold-row .name .badge { margin-left: 8px; }
.cold-row .meta-info { color: var(--color-fg-dim); font-size: 11px; }
.cold-row button.btn { padding: 3px 10px; font-size: 11px; background: none; }
.cold-row button.btn:hover { background: var(--color-bg-elev-2); }

/* ── Triage feed (right rail) ──────────────────────────────────── */
.triage-rail-body { padding: 0; }
.triage-rail-body h3 {
  margin: 0; padding: 14px 18px 12px;
  font-size: 12px;
  color: var(--color-fg-dim);
  font-weight: 600;
  border-bottom: var(--shape-border-width) solid var(--color-border-soft);
  display: flex; align-items: baseline;
}
.triage-rail-body h3 .total {
  margin-left: auto;
  font-weight: 400;
  font-size: 11px;
  color: var(--color-fg-muted);
}
.triage-item {
  padding: 11px 18px;
  border-bottom: var(--shape-border-width) solid var(--color-border-soft);
  cursor: pointer;
}
.triage-item:hover { background: var(--color-bg-elev-2); }
.triage-item.focused { background: var(--color-bg-elev-2); }
.triage-item .priority-row {
  display: flex; align-items: center; gap: 8px; margin-bottom: 4px;
}
.triage-item .priority {
  font-size: 10px; font-weight: 600; letter-spacing: 0.04em;
}
.triage-item .priority.changes_requested,
.triage-item .priority.review_required_with_bot_comments {
  color: var(--color-hot);
}
.triage-item .priority.review_required { color: var(--color-accent); }
.triage-item .priority.approved        { color: var(--color-ok); }
.triage-item .canonical-tag {
  color: var(--color-ok); font-size: 10px; margin-left: auto;
}
.triage-item .feature-name { font-size: 12px; font-weight: 500; }
.triage-item .secondary {
  color: var(--color-fg-muted); font-size: 11px; margin-top: 3px;
}

/* ── Modal (cap-reached + future BlockerErrors) ────────────────── */
.modal-veil {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex; align-items: flex-start; justify-content: center;
  padding-top: 90px;
  z-index: 50;
}
.modal {
  width: 640px; max-width: 92vw;
  background: var(--color-bg-elev);
  border: var(--shape-border-width) solid var(--color-border);
  border-top: 3px solid var(--color-warn);
  border-radius: var(--shape-radius);
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.65);
  overflow: hidden;
}
.modal-head {
  padding: 18px 22px 12px;
  display: flex;
  gap: 14px;
  align-items: flex-start;
}
.modal-glyph {
  width: 32px; height: 32px;
  border-radius: 50%;
  background: var(--color-warn-soft);
  color: var(--color-warn);
  display: flex; align-items: center; justify-content: center;
  font-weight: 700;
  flex-shrink: 0;
}
.modal-title {
  font-size: 15px;
  font-weight: var(--type-headline-weight);
  color: var(--color-fg);
}
.modal-code {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-fg-dim);
  margin-top: 2px;
}
.modal-close {
  margin-left: auto;
  background: none; border: none; color: var(--color-fg-dim);
  font-size: 22px; line-height: 1; cursor: pointer;
  padding: 0 4px;
}
.modal-close:hover { color: var(--color-fg); }
.modal-body {
  padding: 0 22px 16px;
  color: var(--color-fg-muted);
}
.modal-body .what {
  color: var(--color-fg);
  margin-bottom: 12px;
  font-size: 13px;
  line-height: 1.5;
}
.state-snapshot {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 4px 14px;
  padding: 10px 14px;
  background: var(--color-bg-elev-2);
  border-radius: var(--shape-radius-sm);
  font-size: 12px;
}
.state-snapshot .label { color: var(--color-fg-dim); font-weight: 500; }
.state-snapshot .value { color: var(--color-fg); font-family: var(--font-mono); font-size: 11px; }

.actions-list {
  border-top: var(--shape-border-width) solid var(--color-border-soft);
  background: var(--color-bg);
}
.action-choice {
  display: grid;
  grid-template-columns: 24px 1fr auto;
  gap: 14px; align-items: center;
  padding: 13px 22px;
  border-bottom: var(--shape-border-width) solid var(--color-border-soft);
  cursor: pointer;
}
.action-choice:last-child { border-bottom: none; }
.action-choice:hover { background: var(--color-bg-elev-2); }
.action-choice.recommended { background: var(--color-bg-elev-2); }
.action-choice .num {
  color: var(--color-fg-dim);
  font-family: var(--font-mono);
  font-size: 12px;
  text-align: center;
}
.action-choice .title {
  color: var(--color-fg); font-weight: 500; margin-bottom: 3px;
  font-size: 13px;
}
.action-choice .title .recommended-tag {
  color: var(--color-ok);
  font-size: 10px; font-weight: 600;
  margin-left: 8px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.action-choice .preview {
  color: var(--color-fg-muted); font-size: 12px; line-height: 1.45;
}
.action-choice .safe {
  font-size: 10px; padding: 2px 8px; border-radius: 8px;
  color: var(--color-ok); background: var(--color-ok-soft);
  text-transform: uppercase; letter-spacing: 0.04em; font-weight: 600;
}
.action-choice .safe.unsafe { color: var(--color-warn); background: var(--color-warn-soft); }

.modal-foot {
  display: flex; gap: 8px; padding: 12px 22px 16px;
  background: var(--color-bg);
  justify-content: flex-end;
}
.btn.ghost {
  background: none; color: var(--color-fg-muted); border-color: transparent;
}
.btn.ghost:hover { color: var(--color-fg); background: var(--color-bg-elev-2); }

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
