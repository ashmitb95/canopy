import type { TriageFeature } from "../../canopyClient";
import { escapeHtml } from "./util";

export type BranchLedgerProps = {
  /** Features that exist as branches but have no worktree (physical_state="cold"). */
  features: TriageFeature[];
  /**
   * Name of the LRU warm feature that would be evicted if the user switches
   * a cold feature into main while the worktree cap is full. Null if cap
   * has room. Drives the "Switch (evicts X)" button text.
   */
  evictionCandidate: string | null;
};

/**
 * Cold ledger — compact list of branches with no worktree. Switching one
 * warms it (and evicts the LRU warm if cap full). The button text is
 * explicit about that consequence so the user isn't surprised.
 */
export function renderBranchLedger(props: BranchLedgerProps): string {
  const { features, evictionCandidate } = props;

  if (features.length === 0) {
    return `<div class="empty-hint"><span class="glyph">·</span>No branch-only features. Every tracked feature is in main or a worktree.</div>`;
  }

  const rows = features.map((f) => renderRow(f, evictionCandidate)).join("\n");
  return `<div class="cold-ledger">${rows}</div>`;
}

function renderRow(f: TriageFeature, evict: string | null): string {
  const switchBtnLabel = evict
    ? `Switch (evicts ${escapeHtml(evict)})`
    : "Switch";
  const args = evict
    ? { feature: f.feature, evict }
    : { feature: f.feature };

  const meta: string[] = [];
  const repoNames = Object.keys(f.repos).join(" + ") || "no PRs";
  meta.push(repoNames);
  const totalActionable = Object.values(f.repos).reduce(
    (sum, r) => sum + (r.actionable_count ?? 0),
    0,
  );
  if (totalActionable > 0) meta.push(`${totalActionable} actionable thread${totalActionable === 1 ? "" : "s"}`);

  return `
<div class="cold-row">
  <span class="name">
    ${escapeHtml(f.feature)}
    ${prioritySubBadge(f.priority)}
  </span>
  <span class="meta-info">${meta.join(" · ")}</span>
  <button class="btn" data-action="switch" data-args='${escapeHtml(JSON.stringify(args))}'>${switchBtnLabel}</button>
</div>`;
}

function prioritySubBadge(priority: string): string {
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
