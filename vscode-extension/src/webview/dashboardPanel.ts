import * as vscode from "vscode";

import { CanopyClient } from "../canopyClient";
import {
  FeatureDiff,
  FeatureLane,
  LinearIssue,
  LogEntry,
  PreflightResult,
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
  preflight: PreflightResult | null;
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
  private lastPreflight: PreflightResult | null = null;

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
          case "runPreflight": {
            const result = await client.preflight();
            this.lastPreflight = result;
            const passed = result.all_passed
              ? "all repos passed"
              : "see Output for failures";
            void vscode.window.showInformationMessage(
              `Canopy preflight: ${passed}`,
            );
            await this.refresh();
            return;
          }
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
          case "pickLinear":
            await this.pickLinearIssue();
            return;
          case "startClaudeWorkflow":
            await this.startClaudeWorkflow();
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

  private async pickLinearIssue(): Promise<void> {
    let issues: LinearIssue[];
    try {
      issues = await this.client.linearMyIssues(50);
    } catch (err) {
      void vscode.window.showErrorMessage(
        `Canopy: couldn't fetch Linear issues — ${(err as Error).message}`,
      );
      return;
    }
    if (!issues.length) {
      void vscode.window.showInformationMessage(
        "Canopy: no Linear issues found (check that Linear MCP is configured).",
      );
      return;
    }
    const picked = await vscode.window.showQuickPick(
      issues.map((i) => ({
        label: i.identifier,
        description: i.title,
        detail: i.state,
        issue: i,
      })),
      { placeHolder: "Pick a Linear issue to link to this lane" },
    );
    if (!picked) return;
    try {
      await this.client.featureLinkLinear(
        this.featureName,
        picked.issue.identifier,
      );
      void vscode.window.showInformationMessage(
        `Canopy: linked ${picked.issue.identifier} to ${this.featureName}`,
      );
      await this.refresh();
    } catch (err) {
      void vscode.window.showErrorMessage(
        `Canopy: couldn't link issue — ${(err as Error).message}`,
      );
    }
  }

  private async startClaudeWorkflow(): Promise<void> {
    const payload = await this.fetch();
    await launchClaudeWorkflow(payload);
  }

  private fetch(): Promise<DashboardPayload> {
    return fetchDashboardPayload(this.client, this.featureName, this.lastPreflight);
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
  const { lane, diff, status, comments, log, preflight } = p;
  const linearPill = lane.linear_issue
    ? `<span class="pill linear">${escapeHtml(lane.linear_issue)}</span>`
    : "";

  const prCount = status
    ? Object.values(status.repos).filter((r) => r.pr).length
    : 0;
  const prPill = prCount
    ? `<span class="pill pr">${prCount} PR${prCount === 1 ? "" : "s"}</span>`
    : "";

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
        <div class="btn-row">
          <button class="secondary" data-action="pickLinear">Pick from my Linear issues</button>
        </div>
      </section>`;

  const reviewSection = renderReviewSection(status, comments);
  const preflightSection = renderPreflightSection(preflight);

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
        ${reviewSection}
        ${preflightSection}
        <div class="btn-row">
          <button data-action="startClaudeWorkflow">Start workflow with Claude</button>
        </div>
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

export async function launchClaudeWorkflow(p: DashboardPayload): Promise<void> {
  const prompt = buildClaudePrompt(p);
  const uri = vscode.Uri.parse(
    `vscode://anthropic.claude-code/open?prompt=${encodeURIComponent(prompt)}`,
  );
  const opened = await vscode.env.openExternal(uri);
  if (!opened) {
    await vscode.env.clipboard.writeText(prompt);
    void vscode.window.showInformationMessage(
      "Canopy: Claude Code isn't installed — prompt copied to clipboard instead.",
    );
  }
}

export async function fetchDashboardPayload(
  client: CanopyClient,
  feature: string,
  preflight: PreflightResult | null = null,
): Promise<DashboardPayload> {
  const lane = await client.featureStatus(feature);
  const [diff, status, comments, log] = await Promise.all([
    client.featureDiff(feature).catch(() => null),
    client.reviewStatus(feature).catch(() => null),
    client.reviewComments(feature).catch(() => null),
    client.log(10, feature).catch(() => [] as LogEntry[]),
  ]);
  return {
    feature,
    lane,
    diff,
    status,
    comments,
    log,
    preflight,
  };
}

function buildClaudePrompt(p: DashboardPayload): string {
  const lines: string[] = [];
  lines.push(
    `I'm working on feature \`${p.feature}\` in a Canopy workspace.`,
    "",
  );
  if (p.lane.linear_issue) {
    lines.push(
      `Linear: ${p.lane.linear_issue}${p.lane.linear_title ? ` — ${p.lane.linear_title}` : ""}${p.lane.linear_url ? ` (${p.lane.linear_url})` : ""}`,
      "",
    );
  }
  const worktreePaths = Object.entries(p.lane.repo_states)
    .map(([repo, state]) => (state.worktree_path ? `  - ${repo}: ${state.worktree_path}` : null))
    .filter((s): s is string => s !== null);
  if (worktreePaths.length) {
    lines.push("Worktrees:", ...worktreePaths, "");
  }

  if (p.status) {
    lines.push("Pull requests:");
    for (const [repo, info] of Object.entries(p.status.repos)) {
      if (info.pr) {
        const unresolved =
          p.comments?.repos?.[repo]?.comments?.length ?? 0;
        lines.push(
          `  - ${repo}: PR #${info.pr.number} — ${info.pr.title} (${info.pr.url}) · ${unresolved} unresolved comment${unresolved === 1 ? "" : "s"}`,
        );
      } else {
        lines.push(`  - ${repo}: no PR yet`);
      }
    }
    lines.push("");
  }

  if (p.comments && p.comments.total_comments > 0) {
    lines.push("Unresolved PR review comments:");
    for (const [repo, info] of Object.entries(p.comments.repos)) {
      if (!info.comments.length) continue;
      lines.push(`  ${repo} — PR #${info.pr_number}:`);
      for (const c of info.comments) {
        const body = c.body.replace(/\s+/g, " ").trim();
        const truncated = body.length > 240 ? body.slice(0, 237) + "…" : body;
        lines.push(
          `    - ${c.path}:${c.line} (${c.author}): "${truncated}"`,
        );
      }
    }
    lines.push("");
  }

  if (p.preflight) {
    const verdict = p.preflight.all_passed
      ? "all repos passed pre-commit hooks and are staged"
      : "one or more repos failed pre-commit";
    lines.push(`Latest preflight: ${verdict}.`);
    for (const [repo, r] of Object.entries(p.preflight.results)) {
      const hooksOk = r.hooks?.passed !== false;
      lines.push(
        `  - ${repo}: ${r.dirty_count} dirty file${r.dirty_count === 1 ? "" : "s"}, hooks ${hooksOk ? "OK" : "FAILED"}`,
      );
      if (!hooksOk && r.hooks?.output) {
        const snippet = r.hooks.output.trim().split("\n").slice(-10).join("\n");
        lines.push("    hook output tail:", ...snippet.split("\n").map((l) => `      ${l}`));
      }
    }
    lines.push("");
  }

  lines.push(
    "Workflow: address the unresolved review comments above in the worktrees listed.",
  );
  if (p.preflight && !p.preflight.all_passed) {
    lines.push(
      "Preflight has already run and some hooks failed — start by fixing those before continuing on the comments.",
    );
  } else if (p.preflight && p.preflight.all_passed) {
    lines.push(
      "Preflight is green right now. After applying comment fixes, re-run preflight to confirm nothing regressed.",
    );
  } else {
    lines.push(
      "After making changes, run `canopy preflight` from the worktree (or click \"Run preflight\" in the Canopy dashboard) to stage all changes and run pre-commit hooks.",
    );
  }
  return lines.join("\n");
}

function renderReviewSection(
  status: ReviewStatus | null,
  comments: ReviewComments | null,
): string {
  if (!status) {
    return `<p class="muted">Review data unavailable. Ensure GitHub MCP is configured in <code>.canopy/mcps.json</code> or <code>.mcp.json</code>.</p>`;
  }
  const repoBlocks = Object.entries(status.repos).map(([repo, info]) => {
    if (!info.pr) {
      return `
        <div class="review-repo">
          <div class="review-repo-head">
            <span class="dot dot-orange"></span>${escapeHtml(repo)}
            <span class="muted"> — no PR yet</span>
          </div>
        </div>`;
    }
    const repoComments = comments?.repos?.[repo]?.comments ?? [];
    const commentList = repoComments.length
      ? `<ul class="comment-list">${repoComments
          .map((c) => {
            const body = c.body.replace(/\s+/g, " ").trim();
            const truncated = body.length > 220 ? body.slice(0, 217) + "…" : body;
            return `
              <li>
                <a href="#" data-link="${escapeAttr(c.url)}" class="comment-loc">${escapeHtml(c.path)}:${c.line}</a>
                <span class="comment-author muted">${escapeHtml(c.author)}</span>
                <div class="comment-body">${escapeHtml(truncated)}</div>
              </li>`;
          })
          .join("")}</ul>`
      : `<p class="muted small">No unresolved comments.</p>`;
    return `
      <div class="review-repo">
        <div class="review-repo-head">
          <span class="dot dot-orange"></span>${escapeHtml(repo)}
          <a href="#" data-link="${escapeAttr(info.pr.url)}">PR #${info.pr.number}</a>
          <span class="muted">— ${escapeHtml(info.pr.title)}</span>
          <span class="review-count">${repoComments.length} comment${repoComments.length === 1 ? "" : "s"}</span>
        </div>
        ${commentList}
      </div>`;
  });
  return repoBlocks.join("") || `<p class="muted">No repos in this feature.</p>`;
}

function renderPreflightSection(preflight: PreflightResult | null): string {
  if (!preflight) return "";
  const banner = preflight.all_passed
    ? `<div class="preflight-banner ok">✓ Preflight passed — all repos staged, hooks OK.</div>`
    : `<div class="preflight-banner fail">⚠ Preflight failed — see output for details.</div>`;
  const rows = Object.entries(preflight.results)
    .map(([repo, r]) => {
      const ok = r.hooks?.passed !== false;
      const status = ok ? "ok" : "fail";
      return `<div class="preflight-row ${status}">
        <span class="dot dot-orange"></span>${escapeHtml(repo)}
        <span class="muted">${r.dirty_count} dirty · ${ok ? "hooks ok" : "hooks failed"}</span>
      </div>`;
    })
    .join("");
  return `${banner}${rows}`;
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
  .review-repo { padding: 10px 0; border-bottom: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.15)); }
  .review-repo:last-child { border-bottom: none; }
  .review-repo-head { display: flex; align-items: center; gap: 8px; font-size: 13px; margin-bottom: 6px; flex-wrap: wrap; }
  .review-repo-head a { color: var(--vscode-textLink-foreground); text-decoration: none; font-weight: 600; }
  .review-repo-head a:hover { text-decoration: underline; }
  .review-count { margin-left: auto; color: var(--vscode-descriptionForeground); font-size: 11px; }
  .comment-list { list-style: none; padding: 0 0 0 18px; margin: 6px 0 0; }
  .comment-list li { padding: 6px 0; border-top: 1px dashed var(--vscode-panel-border, rgba(128,128,128,0.12)); font-size: 12px; }
  .comment-list li:first-child { border-top: none; }
  .comment-loc { color: var(--vscode-textLink-foreground); text-decoration: none; font-family: var(--vscode-editor-font-family, ui-monospace, Menlo, monospace); font-size: 11px; }
  .comment-loc:hover { text-decoration: underline; }
  .comment-author { margin-left: 8px; font-size: 11px; }
  .comment-body { margin-top: 3px; color: var(--vscode-foreground); white-space: pre-wrap; }
  .small { font-size: 11px; padding-left: 18px; }
  .preflight-banner { padding: 8px 12px; border-radius: 4px; margin: 10px 0 6px; font-size: 12px; }
  .preflight-banner.ok { background: rgba(46, 160, 67, 0.12); border: 1px solid var(--vscode-charts-green, #4ec9b0); }
  .preflight-banner.fail { background: rgba(220, 53, 69, 0.12); border: 1px solid var(--vscode-charts-red, #f48771); }
  .preflight-row { display: flex; align-items: center; gap: 8px; font-size: 12px; padding: 4px 0; }
  .preflight-row.fail { color: var(--vscode-errorForeground); }
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
