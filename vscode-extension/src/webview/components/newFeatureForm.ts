import { escapeHtml } from "./util";

export type NewFeatureLinearIssue = {
  identifier: string;
  title: string;
  state: string;
  url: string;
  /** Existing canopy lanes that already reference this issue. Disables it. */
  alreadyInCanopy?: boolean;
};

export type NewFeatureRepo = {
  name: string;
  /** Free-text status hint shown to the right of the repo (e.g. "main · clean"). */
  status?: string;
  /** Pre-checked when true. */
  defaultChecked?: boolean;
};

export type NewFeatureFormProps = {
  /** Linear issues for the left-rail inbox. May be empty when Linear isn't configured. */
  issues: NewFeatureLinearIssue[];
  /** Selected issue (the rest of the form refers to it). */
  selected: NewFeatureLinearIssue | null;
  /** All repos in the workspace. */
  repos: NewFeatureRepo[];
  /**
   * Initial feature-name suffix (after `<KEY>/`). Derived from the
   * issue title slug; the user can edit it.
   */
  nameSuggestion: string;
  /** Default slot mode: "main" promotes to canonical; "worktree" creates only. */
  defaultSlot?: "main" | "worktree";
};

/**
 * Renders the entire new-feature panel HTML body (everything between
 * the bridge bar and a fresh `<div id="modal-host">`). The panel
 * reuses the cockpit's bridge + theme machinery; this body slots in
 * place of the cockpit's main grid.
 */
export function renderNewFeatureForm(props: NewFeatureFormProps): string {
  const { issues, selected, repos, nameSuggestion, defaultSlot = "worktree" } = props;

  return `
<div class="new-feature-layout">

  <!-- Linear inbox -->
  <aside class="new-feature-inbox">
    <h3>Linear inbox <span class="count">${issues.length} open</span></h3>
    ${issues.length === 0 ? renderInboxEmpty() : issues.map((i) => renderInboxItem(i, selected?.identifier)).join("\n")}
  </aside>

  <!-- Form -->
  <main class="new-feature-form">
    ${selected ? renderForm(selected, repos, nameSuggestion, defaultSlot) : renderFormEmpty()}
  </main>

</div>`.trim();
}

function renderInboxItem(issue: NewFeatureLinearIssue, selectedKey?: string): string {
  const cls = [
    "issue",
    issue.identifier === selectedKey ? "selected" : "",
    issue.alreadyInCanopy ? "in-canopy" : "",
  ]
    .filter(Boolean)
    .join(" ");

  // Disable click on already-in-canopy issues so the user doesn't try
  // to create a duplicate lane.
  const onClick = issue.alreadyInCanopy
    ? ""
    : `data-action="selectLinearIssue" data-args='${escapeHtml(JSON.stringify({ identifier: issue.identifier }))}'`;

  return `
<div class="${cls}" ${onClick}>
  <div class="key">${escapeHtml(issue.identifier)}</div>
  <div class="title">${escapeHtml(issue.title)}</div>
</div>`;
}

function renderInboxEmpty(): string {
  return `
<div class="empty-hint" style="padding: 12px 18px;">
  <span class="glyph">·</span>No open issues from Linear.
  Either Linear isn't configured (add a <code>linear</code> entry to
  <code>.canopy/mcps.json</code>), or your assigned issues are all closed.
</div>`;
}

function renderFormEmpty(): string {
  return `
<div class="empty-hint" style="padding: 24px 0;">
  <span class="glyph">·</span>Pick an issue from the Linear inbox on the left.
</div>`;
}

function renderForm(
  selected: NewFeatureLinearIssue,
  repos: NewFeatureRepo[],
  nameSuggestion: string,
  defaultSlot: "main" | "worktree",
): string {
  const repoRows = repos.map((r) => renderRepoRow(r)).join("\n");
  const checkedCount = repos.filter((r) => r.defaultChecked !== false).length;

  return `
<div class="crumb">Dashboard · <span class="here">New feature</span></div>

<div class="selected-issue">
  <span class="key">${escapeHtml(selected.identifier)}</span>
  <span class="title">${escapeHtml(selected.title)}</span>
  ${selected.url ? `<a href="${escapeHtml(selected.url)}" class="pill-link">View in Linear ↗</a>` : ""}
</div>

<div class="field">
  <label class="field-label">Name</label>
  <div class="input-group">
    <span class="prefix">${escapeHtml(selected.identifier)}/</span>
    <input class="text-input" id="feature-name" value="${escapeHtml(nameSuggestion)}" />
  </div>
</div>

<div class="field">
  <label class="field-label">Repos</label>
  <div class="repos">${repoRows}</div>
  <div class="repo-quick">
    <button data-action="repoQuick" data-args='${escapeHtml(JSON.stringify({ pick: "all" }))}'>All</button>
    <button data-action="repoQuick" data-args='${escapeHtml(JSON.stringify({ pick: "none" }))}'>None</button>
    <span class="summary" id="repo-summary">${checkedCount} of ${repos.length} selected</span>
  </div>
</div>

<div class="field">
  <label class="field-label">Initial slot</label>
  <div class="slot-toggle">
    <button data-slot="main" class="${defaultSlot === "main" ? "active" : ""}">Switch into main</button>
    <button data-slot="worktree" class="${defaultSlot === "worktree" ? "active" : ""}">Open as worktree</button>
  </div>
</div>

<div class="preview">
  <span class="glyph">→</span>
  Creates branch <strong id="preview-branch">${escapeHtml(selected.identifier)}-${escapeHtml(nameSuggestion)}</strong>
  in the selected repos; ${defaultSlot === "main" ? "switches into main" : "opens as worktrees"}.
</div>

<div class="actions">
  <button class="btn ghost" data-action="cancelNewFeature">Cancel</button>
  <span style="flex:1"></span>
  <button class="btn primary" data-action="createLane" data-issue="${escapeHtml(selected.identifier)}">Create lane</button>
</div>`;
}

function renderRepoRow(r: NewFeatureRepo): string {
  const checked = r.defaultChecked !== false;
  return `
<div class="repo ${checked ? "checked" : ""}" data-repo="${escapeHtml(r.name)}">
  <div class="check"></div>
  <div class="name">${escapeHtml(r.name)}</div>
  <div class="status">${escapeHtml(r.status ?? "")}</div>
</div>`;
}

/** Slugify a Linear issue title into a feature-name suffix. */
export function slugifyTitle(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}
