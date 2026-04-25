import type { TriageResult, TriageFeature } from "../../canopyClient";
import { escapeHtml } from "./util";

export type TriageFeedProps = {
  triage: TriageResult | null;
};

/**
 * Right-rail prioritized feed: "what should be your focus" vs the
 * "what is your focus" main pane. Bridge between the two is the
 * `switch` button each row exposes implicitly (clicking the row opens
 * the focused-feature drilldown — phase D).
 */
export function renderTriageFeed(props: TriageFeedProps): string {
  const { triage } = props;
  if (!triage) {
    return `
<div class="triage-rail-body">
  <h3>Triage</h3>
  <div class="empty-hint" style="padding: 18px;">
    <span class="glyph">·</span>Couldn't load triage — is GitHub configured?
  </div>
</div>`;
  }

  if (triage.features.length === 0) {
    return `
<div class="triage-rail-body">
  <h3>Triage <span class="total">all clear</span></h3>
  <div class="empty-hint" style="padding: 18px;">
    <span class="glyph">·</span>No features needing attention right now.
  </div>
</div>`;
  }

  const items = triage.features.map((f) => renderItem(f, triage.canonical_feature)).join("\n");
  return `
<div class="triage-rail-body">
  <h3>Triage <span class="total">${triage.features.length} feature${triage.features.length === 1 ? "" : "s"}</span></h3>
  ${items}
</div>`;
}

function renderItem(f: TriageFeature, canonical: string | null): string {
  const isFocused = f.feature === canonical;
  const totalActionable = Object.values(f.repos).reduce(
    (sum, r) => sum + (r.actionable_count ?? 0),
    0,
  );

  const secondaryParts: string[] = [];
  if (totalActionable > 0) {
    secondaryParts.push(
      `${totalActionable} actionable thread${totalActionable === 1 ? "" : "s"}`,
    );
  }
  switch (f.physical_state) {
    case "canonical":
      // suppressed: the focused-tag below already says it
      break;
    case "warm":
      secondaryParts.push("in worktree");
      break;
    case "cold":
      secondaryParts.push("branch only");
      break;
    case "mixed":
      secondaryParts.push("mixed slot");
      break;
  }

  const secondary = secondaryParts.join(" · ") || "&nbsp;";

  return `
<div class="triage-item${isFocused ? " focused" : ""}" data-action="openCockpitForFeature" data-args='${escapeHtml(JSON.stringify({ feature: f.feature }))}'>
  <div class="priority-row">
    <span class="priority ${escapeHtml(f.priority)}">${PRIORITY_LABEL[f.priority] ?? f.priority}</span>
    ${isFocused ? `<span class="canonical-tag">● focused</span>` : ""}
  </div>
  <div class="feature-name">${escapeHtml(f.feature)}</div>
  <div class="secondary">${secondary}</div>
</div>`;
}

const PRIORITY_LABEL: Record<string, string> = {
  changes_requested: "changes requested",
  review_required_with_bot_comments: "bot review",
  review_required: "review required",
  approved: "approved",
  unknown: "—",
};
