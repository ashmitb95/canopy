import * as vscode from "vscode";

import { CanopyClient } from "../canopyClient";
import {
  FeatureDiff,
  FeatureLane,
  LogEntry,
  ReviewComments,
  ReviewStatus,
} from "../types";

interface DashboardPayload {
  feature: string;
  lane: FeatureLane;
  diff: FeatureDiff | null;
  status: ReviewStatus | null;
  comments: ReviewComments | null;
  log: LogEntry[];
  mergeIssues: string[];
  preflightAllPassed: boolean | null;
}

const PANELS = new Map<string, DashboardPanel>();

/**
 * Per-feature dashboard webview. One panel per feature; reveal if already open.
 * HTML adapted from mockups/canopy-vscode.html (screen 2) with hardcoded colors
 * swapped out for VSCode CSS variables so it themes automatically.
 */
export class DashboardPanel {
  private readonly panel: vscode.WebviewPanel;
  private disposed = false;

  static show(
    context: vscode.ExtensionContext,
    client: CanopyClient,
    featureName: string,
  ) {
    const existing = PANELS.get(featureName);
    if (existing) {
      existing.panel.reveal(vscode.ViewColumn.Active);
      void existing.refresh();
      return;
    }
    const panel = new DashboardPanel(context, client, featureName);
    PANELS.set(featureName, panel);
  }

  private constructor(
    context: vscode.ExtensionContext,
    private readonly client: CanopyClient,
    private readonly featureName: string,
  ) {
    this.panel = vscode.window.createWebviewPanel(
      "canopy.dashboard",
      `● ${featureName} — dashboard`,
      vscode.ViewColumn.Active,
      { enableScripts: true, retainContextWhenHidden: true },
    );
    this.panel.iconPath = vscode.Uri.joinPath(
      context.extensionUri,
      "media",
      "canopy-icon.svg",
    );

    this.panel.onDidDispose(() => {
      this.disposed = true;
      PANELS.delete(featureName);
    });

    this.panel.webview.onDidReceiveMessage(async (msg: { type: string; url?: string }) => {
      try {
        switch (msg.type) {
          case "refresh":
            await this.refresh();
            return;
          case "runPreflight":
            await client.preflight();
            void vscode.window.showInformationMessage("Canopy: preflight complete");
            await this.refresh();
            return;
          case "syncAll": {
            const result = await client.sync("rebase");
            const failures = Object.entries(result.results).filter(
              ([, v]) => v !== "ok",
            );
            if (failures.length) {
              void vscode.window.showWarningMessage(
                `Canopy sync: ${failures.length} repo${failures.length === 1 ? "" : "s"} failed`,
              );
            } else {
              void vscode.window.showInformationMessage("Canopy: all repos synced");
            }
            await this.refresh();
            return;
          }
          case "open":
            if (msg.url) {
              void vscode.env.openExternal(vscode.Uri.parse(msg.url));
            }
            return;
        }
      } catch (err) {
        void vscode.window.showErrorMessage(
          `Canopy dashboard: ${(err as Error).message}`,
        );
      }
    });

    void this.refresh();
  }

  async refresh(): Promise<void> {
    if (this.disposed) return;
    try {
      const payload = await this.fetch();
      this.panel.webview.html = renderHtml(payload);
    } catch (err) {
      this.panel.webview.html = renderError((err as Error).message);
    }
  }

  private async fetch(): Promise<DashboardPayload> {
    const lane = await this.client.featureStatus(this.featureName);
    const [diff, status, comments, log, merge] = await Promise.all([
      this.client.featureDiff(this.featureName).catch(() => null),
      this.client.reviewStatus(this.featureName).catch(() => null),
      this.client.reviewComments(this.featureName).catch(() => null),
      this.client.log(10, this.featureName).catch(() => [] as LogEntry[]),
      this.client.featureMergeReadiness(this.featureName).catch(() => null),
    ]);
    return {
      feature: this.featureName,
      lane,
      diff,
      status,
      comments,
      log,
      mergeIssues: merge?.issues ?? [],
      preflightAllPassed: null,
    };
  }
}

function renderError(message: string): string {
  return baseHtml(`
    <main>
      <h1>Canopy dashboard</h1>
      <p class="error">Failed to load dashboard: ${escapeHtml(message)}</p>
    </main>
  `);
}

function renderHtml(p: DashboardPayload): string {
  const { lane, diff, status, comments, log, mergeIssues } = p;
  const linearPill = lane.linear_issue
    ? `<span class="pill linear">${escapeHtml(lane.linear_issue)}</span>`
    : "";

  const prInfo = firstPr(status);
  const prPill = prInfo
    ? `<span class="pill pr">PR #${prInfo.number}</span>`
    : "";

  const overlapIssues = mergeIssues.filter((i) =>
    i.toLowerCase().startsWith("type overlap"),
  );

  const branchRows = Object.entries(lane.repo_states)
    .map(([repo, state]) => {
      const ahead = state.ahead ?? 0;
      const behind = state.behind ?? 0;
      const changed = state.changed_file_count ?? 0;
      const meta = `↑${ahead} ↓${behind} · ${changed} changed`;
      return `
        <div class="row">
          <div class="left"><span class="dot dot-orange"></span>${escapeHtml(repo)}</div>
          <div class="right mono">${escapeHtml(meta)}</div>
        </div>`;
    })
    .join("");

  const linearCard = lane.linear_issue
    ? `
      <section class="card">
        <h3>Linear · ${escapeHtml(lane.linear_issue)}</h3>
        ${row("Title", lane.linear_title || "—")}
        ${row("URL", lane.linear_url ? `<a href="#" data-link="${escapeAttr(lane.linear_url)}">${escapeHtml(lane.linear_url)}</a>` : "—", true)}
      </section>`
    : `
      <section class="card">
        <h3>Linear</h3>
        <p class="muted">No Linear issue linked.</p>
      </section>`;

  const reviewRows: string[] = [];
  if (status && prInfo) {
    reviewRows.push(
      row(
        "Pull request",
        `<a href="#" data-link="${escapeAttr(prInfo.url)}">#${prInfo.number} — ${escapeHtml(prInfo.title)}</a>`,
        true,
      ),
    );
  } else {
    reviewRows.push(row("Pull request", "no PR open"));
  }
  reviewRows.push(
    row(
      "Unresolved comments",
      comments ? String(comments.total_comments) : "n/a",
    ),
  );
  reviewRows.push(
    row(
      "File overlap",
      overlapIssues.length
        ? `${overlapIssues.length} warning${overlapIssues.length === 1 ? "" : "s"}`
        : "none",
    ),
  );

  const overlapBox = overlapIssues.length
    ? `<div class="warn-box">⚠ ${overlapIssues
        .map((i) => escapeHtml(i))
        .join("<br>")}</div>`
    : "";

  const commitRows = log
    .map(
      (c) => `
      <div class="commit">
        <span class="sha">${escapeHtml(c.short_sha)}</span>
        <span class="msg">[${escapeHtml(c.repo)}] ${escapeHtml(c.subject)}</span>
        <span class="when">${escapeHtml(c.date.split("T")[0])}</span>
      </div>`,
    )
    .join("") || `<p class="muted">No commits yet.</p>`;

  const totalsLine = diff
    ? `${diff.summary.total_files_changed} files · +${diff.summary.total_insertions} −${diff.summary.total_deletions}`
    : "";

  return baseHtml(`
    <main>
      <h1>
        <span class="dot dot-green"></span>${escapeHtml(lane.name)}
        ${linearPill}${prPill}
      </h1>
      <p class="subhead">
        ${lane.repos.length} repo${lane.repos.length === 1 ? "" : "s"}
        ${lane.created_at ? "· created " + escapeHtml(lane.created_at.split("T")[0]) : ""}
        ${totalsLine ? "· " + escapeHtml(totalsLine) : ""}
      </p>

      <div class="grid-2">
        <section class="card">
          <h3>Branches <span class="mono muted">git status</span></h3>
          ${branchRows || `<p class="muted">No branches yet.</p>`}
          <div class="btn-row">
            <button data-action="syncAll">Sync all</button>
            <button class="secondary" data-action="runPreflight">Run preflight</button>
          </div>
        </section>
        ${linearCard}
      </div>

      <section class="card">
        <h3>Review readiness</h3>
        ${reviewRows.join("")}
        ${overlapBox}
      </section>

      <section class="card">
        <h3>Recent commits <span class="mono muted">across all worktrees</span></h3>
        ${commitRows}
      </section>
    </main>
  `);
}

function row(left: string, right: string, allowHtml = false): string {
  const r = allowHtml ? right : escapeHtml(right);
  return `
    <div class="row">
      <div class="left">${escapeHtml(left)}</div>
      <div class="right">${r}</div>
    </div>`;
}

function firstPr(
  status: ReviewStatus | null,
): { number: number; url: string; title: string } | null {
  if (!status) return null;
  for (const repo of Object.values(status.repos)) {
    if (repo.pr) return repo.pr;
  }
  return null;
}

function baseHtml(body: string): string {
  return `<!doctype html>
<html><head>
<meta charset="utf-8">
<style>
  body { font: 13px/1.45 var(--vscode-font-family); color: var(--vscode-foreground); background: var(--vscode-editor-background); margin: 0; padding: 24px 32px; }
  main { max-width: 880px; margin: 0 auto; }
  h1 { margin: 0 0 4px; font-size: 22px; font-weight: 600; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .subhead { color: var(--vscode-descriptionForeground); font-size: 13px; margin-bottom: 24px; }
  .muted { color: var(--vscode-descriptionForeground); }
  .mono { font-family: var(--vscode-editor-font-family, ui-monospace, Menlo, monospace); font-size: 12px; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
  @media (max-width: 720px) { .grid-2 { grid-template-columns: 1fr; } }
  .card { background: var(--vscode-sideBar-background); border: 1px solid var(--vscode-panel-border, transparent); border-radius: 6px; padding: 14px 16px; margin-bottom: 16px; }
  .card h3 { margin: 0 0 10px; font-size: 12px; text-transform: uppercase; letter-spacing: .6px; color: var(--vscode-descriptionForeground); font-weight: 700; display: flex; align-items: center; justify-content: space-between; }
  .row { display: flex; align-items: center; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.2)); font-size: 13px; }
  .row:last-child { border-bottom: none; }
  .left { display: flex; gap: 10px; align-items: center; }
  .right { color: var(--vscode-descriptionForeground); font-size: 12px; }
  .right a { color: var(--vscode-textLink-foreground); text-decoration: none; }
  .right a:hover { text-decoration: underline; }
  .pill { display: inline-block; padding: 0 8px; border-radius: 8px; font-size: 10px; line-height: 16px; font-weight: 600; }
  .pill.linear { background: #5e6ad2; color: white; }
  .pill.pr { background: #6f42c1; color: white; }
  .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .dot-green { background: var(--vscode-charts-green, #4ec9b0); }
  .dot-orange { background: var(--vscode-charts-orange, #ce9178); }
  .commit { display: grid; grid-template-columns: 70px 1fr auto; gap: 12px; padding: 6px 0; border-bottom: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.2)); font-size: 12px; }
  .commit:last-child { border-bottom: none; }
  .sha { color: var(--vscode-charts-yellow, #dcdcaa); font-family: var(--vscode-editor-font-family, ui-monospace, Menlo, monospace); }
  .msg { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .when { color: var(--vscode-descriptionForeground); }
  .warn-box { background: rgba(220, 170, 0, 0.12); border: 1px solid var(--vscode-charts-yellow, #dcdcaa); border-radius: 4px; padding: 10px 12px; color: var(--vscode-foreground); font-size: 12px; margin-top: 8px; }
  .btn-row { display: flex; gap: 8px; margin-top: 12px; }
  button { padding: 6px 12px; background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; border-radius: 3px; cursor: pointer; font-size: 12px; font-family: inherit; }
  button:hover { background: var(--vscode-button-hoverBackground); }
  button.secondary { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); }
  button.secondary:hover { background: var(--vscode-button-secondaryHoverBackground); }
  .error { color: var(--vscode-errorForeground); }
</style>
</head><body>
${body}
<script>
  const vscode = acquireVsCodeApi();
  document.addEventListener('click', (e) => {
    const t = e.target;
    if (!(t instanceof HTMLElement)) return;
    const action = t.getAttribute('data-action');
    if (action) { vscode.postMessage({ type: action }); return; }
    const link = t.getAttribute('data-link');
    if (link) { e.preventDefault(); vscode.postMessage({ type: 'open', url: link }); }
  });
</script>
</body></html>`;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(s: string): string {
  return escapeHtml(s);
}
