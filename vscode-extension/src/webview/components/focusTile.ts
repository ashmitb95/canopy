import type { FeatureStateResult } from "../../canopyClient";
import { escapeHtml, cx } from "./util";

export type FocusTileProps = {
  /** featureState() result for the canonical feature, or null when nothing is in main. */
  state: FeatureStateResult | null;
  /** Optional Linear issue subtitle (linear_title). */
  linearTitle?: string;
  /** Optional Linear issue URL — renders as a pill link if present. */
  linearUrl?: string;
};

/**
 * The cockpit's centerpiece: the canonical feature card.
 *
 * Shows the feature name, state badge, per-repo strip, and a CTA row
 * sourced from `state.next_actions` — primary CTA is `next_actions[0]`,
 * up to 3 more secondaries follow. Fallbacks for empty / no-canonical
 * cases keep the dashboard usable on a fresh workspace.
 */
export function renderFocusTile(props: FocusTileProps): string {
  const { state, linearTitle, linearUrl } = props;

  if (!state) {
    return renderEmpty();
  }

  const stateLabel = STATE_LABELS[state.state] ?? state.state;
  const linearPill =
    linearUrl && linearUrl.startsWith("http")
      ? `<a class="pill-link" href="${escapeHtml(linearUrl)}">${escapeHtml(stripLinearKey(linearTitle ?? "") || "Linear")} ↗</a>`
      : "";

  const reposHtml = renderRepoStrip(state);
  const ctasHtml = renderCtas(state);

  return `
<div class="focus-tile">
  <h2>
    ${escapeHtml(state.feature)}
    ${linearTitle ? `<span class="sub">${escapeHtml(linearTitle)}</span>` : ""}
  </h2>
  <div class="meta-row">
    <span class="badge canonical" title="In the main checkout">● in main</span>
    <span class="badge state-${escapeHtml(state.state)}">${escapeHtml(stateLabel)}</span>
    ${linearPill}
  </div>
  ${reposHtml}
  <div class="cta-row">
    ${ctasHtml}
  </div>
</div>
`.trim();
}

function renderRepoStrip(state: FeatureStateResult): string {
  // Walk dirty_repos + ahead_repos + review_decisions to enumerate per repo.
  // The summary shape is loosely typed; pull what's there, gracefully skip what isn't.
  const summary = state.summary ?? {};
  const expected: Record<string, string> = (summary.alignment?.expected as Record<string, string>) ?? {};
  const repos = Object.keys(expected);
  if (repos.length === 0) {
    return `<div class="empty-hint"><span class="glyph">·</span>No repos resolved for this feature lane.</div>`;
  }

  const dirtyRepos = new Set<string>(summary.dirty_repos ?? []);
  const aheadByRepo: Record<string, number> = (summary.ahead_repos as Record<string, number>) ?? {};
  const decisionByRepo: Record<string, string> = (summary.review_decisions as Record<string, string>) ?? {};

  const rows = repos
    .map((repo) => {
      const branch = expected[repo];
      const dirty = dirtyRepos.has(repo);
      const ahead = aheadByRepo[repo] ?? 0;
      const decision = decisionByRepo[repo] ?? "";

      return `
<div class="repo-row">
  <span class="name">${escapeHtml(repo)}</span>
  <span class="branch">${escapeHtml(branch)}</span>
  ${dirty ? `<span class="dirty">dirty</span>` : `<span class="dirty" style="visibility:hidden">·</span>`}
  ${ahead > 0 ? `<span class="ahead">${ahead} ahead</span>` : `<span class="ahead" style="visibility:hidden">·</span>`}
  ${decision ? `<span class="actionable" title="Review decision">${escapeHtml(decision)}</span>` : `<span style="visibility:hidden">·</span>`}
</div>`;
    })
    .join("\n");

  return `<div class="repo-strip">${rows}</div>`;
}

function renderCtas(state: FeatureStateResult): string {
  const next = state.next_actions ?? [];
  if (next.length === 0) {
    return `<button class="btn" disabled>No next actions</button>`;
  }

  return next
    .slice(0, 4)
    .map((a, i) => {
      const cls = cx("btn", i === 0 && "primary");
      const label = escapeHtml(a.label ?? a.action);
      const preview = a.preview
        ? `<span class="preview">${escapeHtml(a.preview)}</span>`
        : "";
      return `<button class="${cls}" data-action="${escapeHtml(a.action)}" data-args='${escapeHtml(
        JSON.stringify(a.args ?? {}),
      )}'>${label}${preview}</button>`;
    })
    .join("\n");
}

function renderEmpty(): string {
  return `
<div class="focus-tile empty">
  <h2>No feature in main</h2>
  <div class="empty-hint">
    <span class="glyph">·</span>Pick a feature from the triage rail to switch into main, or
    <a href="#" data-action="newFeature" style="color: var(--color-accent);">spin up a new one from Linear</a>.
  </div>
</div>
`.trim();
}

function stripLinearKey(title: string): string {
  // "SIN-12: Add /search endpoint" → "SIN-12"
  const m = /^([A-Z]+-\d+)/.exec(title);
  return m ? m[1] : title;
}

const STATE_LABELS: Record<string, string> = {
  drifted: "drifted",
  needs_work: "needs work",
  in_progress: "in progress",
  ready_to_commit: "ready to commit",
  ready_to_push: "ready to push",
  awaiting_review: "awaiting review",
  approved: "approved",
  no_prs: "no PRs",
};
