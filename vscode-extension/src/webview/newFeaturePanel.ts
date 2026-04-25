import * as vscode from "vscode";

import type { CanopyClient } from "../canopyClient";
import { getTheme, renderThemeCss, type ThemeName } from "./themes";
import { componentCss } from "./components/styles";
import { renderBridge } from "./components/bridge";
import {
  renderNewFeatureForm,
  slugifyTitle,
  type NewFeatureLinearIssue,
  type NewFeatureRepo,
} from "./components/newFeatureForm";
import { CockpitPanel } from "./cockpitPanel";

/**
 * "Spin up a new feature" panel — Linear inbox + repo picker + slot
 * picker. Singleton like the cockpit. Closes on successful create.
 */
export class NewFeaturePanel {
  private static instance: NewFeaturePanel | null = null;
  private readonly panel: vscode.WebviewPanel;
  private themeName: ThemeName;
  private themeListener: vscode.Disposable;

  // Form state lives in the panel (not the webview) so refresh keeps
  // the user's selections and we can validate before issuing the call.
  private selectedKey: string | null = null;
  private nameSuggestion = "";
  private slot: "main" | "worktree" = "worktree";
  private repoChecked = new Map<string, boolean>();

  static show(context: vscode.ExtensionContext, client: CanopyClient): void {
    if (NewFeaturePanel.instance) {
      NewFeaturePanel.instance.panel.reveal(vscode.ViewColumn.Active);
      return;
    }
    NewFeaturePanel.instance = new NewFeaturePanel(context, client);
  }

  private constructor(
    context: vscode.ExtensionContext,
    private readonly client: CanopyClient,
  ) {
    this.themeName = readThemeName();
    this.panel = vscode.window.createWebviewPanel(
      "canopy.newFeature",
      "Canopy — New feature",
      vscode.ViewColumn.Active,
      { enableScripts: true, retainContextWhenHidden: true },
    );
    this.panel.iconPath = vscode.Uri.joinPath(
      context.extensionUri,
      "media",
      "canopy-icon.svg",
    );
    this.panel.onDidDispose(() => {
      this.themeListener.dispose();
      NewFeaturePanel.instance = null;
    });
    this.themeListener = vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("canopy.dashboard.theme")) {
        this.themeName = readThemeName();
        void this.refresh();
      }
    });
    this.panel.webview.onDidReceiveMessage((m) => this.handleMessage(m));
    void this.refresh();
  }

  private async refresh(): Promise<void> {
    try {
      const html = await this.renderHtml();
      this.panel.webview.html = html;
    } catch (err) {
      this.panel.webview.html = `<html><body style="color:#f85149; padding:24px; font-family:sans-serif;"><h2>Canopy: failed to load</h2><pre>${(err as Error).message}</pre></body></html>`;
    }
  }

  private async renderHtml(): Promise<string> {
    const theme = getTheme(this.themeName);
    const themeCss = renderThemeCss(theme);

    const status = await this.client.workspaceStatus();
    const workspaceLabel = abbreviatePath(status.root);

    // Linear inbox + the set of features already in canopy (so we can
    // disable issues whose lane already exists).
    const [issuesRaw, lanes] = await Promise.all([
      this.client.linearMyIssues(40).catch(() => []),
      this.client.featureList().catch(() => []),
    ]);
    const linkedLinearIds = new Set(
      lanes
        .map((l) => (l as { linear_issue?: string }).linear_issue ?? "")
        .filter((s) => s.length > 0)
        .map((s) => s.toUpperCase()),
    );
    const issues: NewFeatureLinearIssue[] = (issuesRaw as Array<{ identifier: string; title: string; state: string; url: string }>).map((i) => ({
      identifier: i.identifier,
      title: i.title,
      state: i.state,
      url: i.url,
      alreadyInCanopy: linkedLinearIds.has(i.identifier.toUpperCase()),
    }));

    // Default selection: first non-already-in-canopy issue.
    if (this.selectedKey === null) {
      const first = issues.find((i) => !i.alreadyInCanopy);
      if (first) {
        this.selectedKey = first.identifier;
        this.nameSuggestion = slugifyTitle(first.title);
      }
    }
    const selected = issues.find((i) => i.identifier === this.selectedKey) ?? null;

    // Repo list (all repos in workspace, all checked by default)
    const repos: NewFeatureRepo[] = status.repos.map((raw) => {
      const r = raw as { name?: unknown; current_branch?: unknown; is_dirty?: unknown };
      const name = String(r.name ?? "");
      const branch = String(r.current_branch ?? "?");
      const dirty = Boolean(r.is_dirty);
      if (!this.repoChecked.has(name)) this.repoChecked.set(name, true);
      return {
        name,
        status: `${branch} · ${dirty ? "dirty" : "clean"}`,
        defaultChecked: this.repoChecked.get(name),
      };
    });

    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src ${this.panel.webview.cspSource}; img-src ${this.panel.webview.cspSource} data:;">
<title>Canopy — New feature</title>
<style>
${themeCss}

${componentCss}
</style>
</head>
<body>

${renderBridge({
  workspaceLabel,
  canonicalFeature: null,
  worktreeCount: 0,
  worktreeCap: 0,
  activeTheme: this.themeName,
})}

${renderNewFeatureForm({
  issues,
  selected,
  repos,
  nameSuggestion: this.nameSuggestion,
  defaultSlot: this.slot,
})}

<script>
  const vscode = acquireVsCodeApi();
  document.addEventListener('click', (ev) => {
    // Theme toggle
    const themeBtn = ev.target.closest('[data-theme]');
    if (themeBtn) {
      vscode.postMessage({ type: 'setTheme', theme: themeBtn.getAttribute('data-theme') });
      return;
    }
    // Slot toggle
    const slotBtn = ev.target.closest('[data-slot]');
    if (slotBtn) {
      const slot = slotBtn.getAttribute('data-slot');
      vscode.postMessage({ type: 'setSlot', slot });
      return;
    }
    // Repo checkbox
    const repoRow = ev.target.closest('[data-repo]');
    if (repoRow) {
      const repo = repoRow.getAttribute('data-repo');
      vscode.postMessage({ type: 'toggleRepo', repo });
      return;
    }
    // Action button
    const actBtn = ev.target.closest('[data-action]');
    if (actBtn) {
      const action = actBtn.getAttribute('data-action');
      const args = actBtn.getAttribute('data-args');
      // For createLane, also collect the current name input value.
      const extras = action === 'createLane'
        ? { issue: actBtn.getAttribute('data-issue'), name: document.getElementById('feature-name')?.value }
        : {};
      vscode.postMessage({
        type: 'invokeAction',
        action,
        args: { ...(args ? JSON.parse(args) : {}), ...extras },
      });
    }
  });
</script>

</body>
</html>`;
  }

  private async handleMessage(msg: NewFeatureMessage): Promise<void> {
    switch (msg.type) {
      case "setTheme": {
        if (msg.theme === "navy" || msg.theme === "minimal") {
          await vscode.workspace
            .getConfiguration()
            .update(
              "canopy.dashboard.theme",
              msg.theme,
              vscode.ConfigurationTarget.Global,
            );
        }
        return;
      }
      case "setSlot":
        this.slot = msg.slot === "main" ? "main" : "worktree";
        await this.refresh();
        return;
      case "toggleRepo":
        this.repoChecked.set(msg.repo, !(this.repoChecked.get(msg.repo) ?? true));
        await this.refresh();
        return;
      case "invokeAction":
        await this.handleAction(msg.action, msg.args ?? {});
        return;
    }
  }

  private async handleAction(action: string, args: Record<string, unknown>): Promise<void> {
    switch (action) {
      case "selectLinearIssue": {
        const id = args.identifier as string;
        this.selectedKey = id;
        // Re-fetch to get the latest title and re-derive name suggestion
        try {
          const issue = await this.client.linearGetIssue(id);
          this.nameSuggestion = slugifyTitle(issue.title);
        } catch {
          // Linear fetch failed; keep prior suggestion
        }
        await this.refresh();
        return;
      }
      case "repoQuick": {
        const pick = args.pick as "all" | "none";
        const status = await this.client.workspaceStatus();
        for (const raw of status.repos) {
          const name = String((raw as { name?: unknown }).name ?? "");
          if (name) this.repoChecked.set(name, pick === "all");
        }
        await this.refresh();
        return;
      }
      case "cancelNewFeature":
        this.panel.dispose();
        return;
      case "createLane":
        await this.createLane(args.issue as string, args.name as string);
        return;
    }
  }

  private async createLane(issueId: string, nameSuffix: string): Promise<void> {
    const featureName = `${issueId}-${nameSuffix.trim() || "feature"}`;
    const repos = Array.from(this.repoChecked.entries())
      .filter(([, checked]) => checked)
      .map(([name]) => name);

    if (repos.length === 0) {
      void vscode.window.showWarningMessage(
        "Canopy: pick at least one repo before creating the lane.",
      );
      return;
    }

    try {
      if (this.slot === "worktree") {
        await this.client.worktreeCreate({
          name: featureName,
          issue: issueId,
          repos,
        });
      } else {
        // Switch into main directly: feature_create + switch
        await this.client.featureCreate({ name: featureName, repos });
        await this.client.switchFeature({ feature: featureName });
      }
      void vscode.window.showInformationMessage(
        `Canopy: created lane ${featureName} (${this.slot === "worktree" ? "worktree" : "in main"}).`,
      );
      this.panel.dispose();
      CockpitPanel.refreshIfOpen();
    } catch (err) {
      void vscode.window.showErrorMessage(
        `Canopy: create lane failed — ${(err as Error).message}`,
      );
    }
  }
}

type NewFeatureMessage =
  | { type: "setTheme"; theme: string }
  | { type: "setSlot"; slot: string }
  | { type: "toggleRepo"; repo: string }
  | { type: "invokeAction"; action: string; args?: Record<string, unknown> };

function readThemeName(): ThemeName {
  const v = vscode.workspace
    .getConfiguration("canopy")
    .get<string>("dashboard.theme", "navy");
  return v === "minimal" ? "minimal" : "navy";
}

function abbreviatePath(p: string): string {
  const home = process.env.HOME ?? process.env.USERPROFILE ?? "";
  if (home && p.startsWith(home)) return "~" + p.slice(home.length);
  return p;
}
