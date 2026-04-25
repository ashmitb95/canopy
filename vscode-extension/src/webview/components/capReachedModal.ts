import type { SwitchBlocker, FixAction } from "../../canopyClient";
import { escapeHtml } from "./util";

/**
 * Cap-reached modal — rendered when `switch` returns
 * `BlockerError(code='worktree_cap_reached')`. The user sees the three
 * fix actions (wind-down, evict by name, raise cap) and picks one;
 * clicking re-issues `switch` with the chosen flag.
 *
 * The HTML is injected into a `<div id="modal-host">` placeholder in
 * the cockpit body via webview.postMessage. CSS lives in styles.ts.
 */
export function renderCapReachedModal(blocker: SwitchBlocker, originalTarget: string): string {
  const fixes = blocker.fix_actions ?? [];
  const expected = blocker.expected as Record<string, unknown> | undefined;
  const actual = blocker.actual as Record<string, unknown> | undefined;

  const cap = expected?.warm_slot_cap ?? "?";
  const warmNow = (actual?.warm_now as string[] | undefined) ?? [];

  const choices = fixes.map((fa, i) => renderChoice(fa, i, originalTarget)).join("\n");

  return `
<div class="modal-veil" data-modal-veil>
  <div class="modal cap-reached">
    <div class="modal-head">
      <div class="modal-glyph">!</div>
      <div>
        <div class="modal-title">Switching to ${escapeHtml(originalTarget)} would exceed the worktree cap.</div>
        <div class="modal-code">BlockerError · ${escapeHtml(blocker.code)}</div>
      </div>
      <button class="modal-close" data-modal-close title="Cancel">×</button>
    </div>

    <div class="modal-body">
      <div class="what">${escapeHtml(blocker.what)}</div>
      <div class="state-snapshot">
        <span class="label">in worktree now</span>
        <span class="value">${escapeHtml(warmNow.join(", ") || "(none)")}</span>
        <span class="label">cap (max_worktrees)</span>
        <span class="value">${escapeHtml(String(cap))}</span>
        <span class="label">switching to</span>
        <span class="value">${escapeHtml(originalTarget)}</span>
      </div>
    </div>

    <div class="actions-list">
      ${choices || `<div class="empty-hint" style="padding: 14px 24px;"><span class="glyph">·</span>No fix actions returned by canopy. Cancel and try a different switch.</div>`}
    </div>

    <div class="modal-foot">
      <button class="btn ghost" data-modal-close>Cancel</button>
    </div>
  </div>
</div>`.trim();
}

function renderChoice(fa: FixAction, index: number, originalTarget: string): string {
  const safeBadge = fa.safe
    ? `<span class="safe">SAFE</span>`
    : `<span class="safe unsafe">REQUIRES&nbsp;CONFIRM</span>`;

  // Recommend the first one with `safe: false` (typically wind-down /
  // hibernate) — it's least destructive in the cap-reached scenario.
  const recommended = index === 0;

  // Translate the action name into a user-friendly title using fa.preview
  // when available, otherwise a derived label.
  const title = inferTitle(fa, originalTarget);
  const preview = fa.preview ?? "";

  // The fix-action `args` carries everything the dashboard needs to
  // re-issue the call. We re-dispatch through the same invokeAction
  // path; "switch" + new args will trigger the operation.
  return `
<div class="action-choice ${recommended ? "recommended" : ""}" data-action="${escapeHtml(fa.action)}" data-args='${escapeHtml(JSON.stringify(fa.args ?? {}))}'>
  <div class="num">${index + 1}.</div>
  <div>
    <div class="title">
      ${escapeHtml(title)}
      ${recommended ? `<span class="recommended-tag">recommended</span>` : ""}
    </div>
    ${preview ? `<div class="preview">${escapeHtml(preview)}</div>` : ""}
  </div>
  ${safeBadge}
</div>`;
}

function inferTitle(fa: FixAction, target: string): string {
  // Prefer concrete copy from preview when it's there. Otherwise infer
  // a friendly label from action name + args.
  if (fa.preview && fa.preview.length < 80) return fa.preview;

  switch (fa.action) {
    case "switch": {
      const args = fa.args as Record<string, unknown>;
      if (args.release_current) {
        return `Hibernate the current focus instead — keep both worktrees intact`;
      }
      if (args.evict) {
        return `Evict ${args.evict} to branch only (auto-stash if dirty)`;
      }
      return `Retry switch to ${target}`;
    }
    case "workspace_config": {
      const newCap = (fa.args as Record<string, unknown>).max_worktrees;
      return `Raise the worktree cap to ${newCap}`;
    }
    default:
      return fa.action;
  }
}
