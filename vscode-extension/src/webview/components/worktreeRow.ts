import type { TriageFeature } from "../../canopyClient";
import { escapeHtml } from "./util";

export type WorktreeRowProps = {
  /** Features currently in worktrees (is_canonical=false && physical_state="warm"). */
  features: TriageFeature[];
};

/**
 * Standby row — small card per warm worktree with switch + open-IDE actions.
 *
 * Click "Switch into main" → posts `{ type: "invokeAction", action: "switch",
 * args: { feature, release_current: false } }`. Phase D wires it through.
 */
export function renderWorktreeRow(props: WorktreeRowProps): string {
  const { features } = props;
  if (features.length === 0) {
    return `<div class="empty-hint"><span class="glyph">·</span>No features in worktrees right now. Switching into a branch creates one.</div>`;
  }

  const cards = features.map(renderCard).join("\n");
  return `<div class="standby-row">${cards}</div>`;
}

function renderCard(f: TriageFeature): string {
  const repoSummaries = Object.entries(f.repos)
    .map(([repo, info]) => {
      const bits: string[] = [escapeHtml(repo)];
      if (info.pr_number) bits.push(`PR #${info.pr_number}`);
      if (info.actionable_count > 0) bits.push(`${info.actionable_count} actionable`);
      return bits.join(" · ");
    })
    .join(" — ");

  const linearPill =
    f.linear_url && f.linear_url.startsWith("http")
      ? `<a class="pill-link" href="${escapeHtml(f.linear_url)}">${escapeHtml(f.linear_issue || "Linear")} ↗</a>`
      : "";

  return `
<div class="standby-card">
  <h3>${escapeHtml(f.feature)}</h3>
  <div class="meta-row">
    <span class="badge worktree" title="In a linked worktree">● worktree</span>
    ${prioritySubBadge(f.priority)}
    ${linearPill}
  </div>
  <div class="summary">${repoSummaries || "<em>no PRs</em>"}</div>
  <div class="actions">
    <button class="btn primary" data-action="switch" data-args='${escapeHtml(JSON.stringify({ feature: f.feature }))}'>Switch into main</button>
    <button class="btn" data-action="openInIde" data-args='${escapeHtml(JSON.stringify({ feature: f.feature }))}'>Open IDE</button>
  </div>
</div>`;
}

function prioritySubBadge(priority: string): string {
  // Reuse state-* badge styling for priority pills inside warm cards —
  // visually distinct without needing new tokens.
  switch (priority) {
    case "changes_requested":
      return `<span class="badge state-needs_work">changes requested</span>`;
    case "review_required_with_bot_comments":
      return `<span class="badge state-needs_work">bot review</span>`;
    case "review_required":
      return `<span class="badge state-awaiting_review">review required</span>`;
    case "approved":
      return `<span class="badge state-approved">approved</span>`;
    default:
      return "";
  }
}
