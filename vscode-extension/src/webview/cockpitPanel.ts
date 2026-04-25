import * as vscode from "vscode";

import type { CanopyClient, FeatureStateResult } from "../canopyClient";
import { getTheme, renderThemeCss, type ThemeName } from "./themes";
import { componentCss } from "./components/styles";
import { renderBridge } from "./components/bridge";
import { renderFocusTile } from "./components/focusTile";
import { escapeHtml } from "./components/util";

/**
 * Workspace-scoped cockpit dashboard (Wave 7).
 *
 * One panel per workspace (singleton). Renders the canonical-slot model
 * end-to-end: bridge bar → focus tile (canonical) → worktrees → branches
 * → triage feed (rail). Phase B ships bridge + focus tile only; the rest
 * land in Phase C.
 *
 * Differs from the per-feature DashboardPanel in three ways:
 *   1. One panel for the whole workspace (not per feature).
 *   2. Driven by feature_state(canonical) + triage(), not feature_status.
 *   3. Theme-pluggable via canopy.dashboard.theme setting.
 */
export class CockpitPanel {
  private static instance: CockpitPanel | null = null;
  private readonly panel: vscode.WebviewPanel;
  private disposed = false;
  private themeName: ThemeName;
  private themeListener: vscode.Disposable;

  static show(context: vscode.ExtensionContext, client: CanopyClient): void {
    if (CockpitPanel.instance) {
      CockpitPanel.instance.panel.reveal(vscode.ViewColumn.Active);
      void CockpitPanel.instance.refresh();
      return;
    }
    CockpitPanel.instance = new CockpitPanel(context, client);
  }

  static refreshIfOpen(): void {
    if (CockpitPanel.instance) {
      void CockpitPanel.instance.refresh();
    }
  }

  private constructor(
    context: vscode.ExtensionContext,
    private readonly client: CanopyClient,
  ) {
    this.themeName = readThemeName();

    this.panel = vscode.window.createWebviewPanel(
      "canopy.cockpit",
      "Canopy",
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
      this.themeListener.dispose();
      CockpitPanel.instance = null;
    });

    // Re-render when the user changes the theme setting.
    this.themeListener = vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("canopy.dashboard.theme")) {
        this.themeName = readThemeName();
        void this.refresh();
      }
    });

    this.panel.webview.onDidReceiveMessage((msg: WebviewMessage) =>
      this.handleMessage(msg),
    );

    void this.refresh();
  }

  private async refresh(): Promise<void> {
    if (this.disposed) return;
    try {
      const html = await this.renderHtml();
      this.panel.webview.html = html;
    } catch (err) {
      this.panel.webview.html = this.renderError((err as Error).message);
    }
  }

  // ── Rendering ────────────────────────────────────────────────────

  private async renderHtml(): Promise<string> {
    const theme = getTheme(this.themeName);
    const themeCss = renderThemeCss(theme);

    const status = await this.client.workspaceStatus();
    const workspaceLabel = abbreviatePath(status.root);

    // Phase B: only canonical feature is wired. Worktree count + cap
    // come from triage when Phase C lands; for now we show 0 / cap or
    // pull from features with worktree_paths.
    const triage = await this.client.triage().catch(() => null);
    const canonicalFeature = triage?.canonical_feature ?? null;
    const worktreeCount = triage
      ? triage.features.filter(
          (f) => !f.is_canonical && f.physical_state === "warm",
        ).length
      : 0;
    const worktreeCap = readWorktreeCap();

    // Canonical feature state — drives the focus tile.
    let featureState: FeatureStateResult | null = null;
    let linearTitle: string | undefined;
    let linearUrl: string | undefined;
    if (canonicalFeature) {
      try {
        featureState = await this.client.featureState(canonicalFeature);
      } catch {
        featureState = null;
      }
      // Linear metadata sourced from the matching triage entry to avoid
      // an extra MCP roundtrip.
      const t = triage?.features.find((f) => f.feature === canonicalFeature);
      linearTitle = t?.linear_title;
      linearUrl = t?.linear_url;
    }

    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src ${this.panel.webview.cspSource}; img-src ${this.panel.webview.cspSource} data:;">
<title>Canopy</title>
<style>
${themeCss}

${componentCss}
</style>
</head>
<body>

${renderBridge({
  workspaceLabel,
  canonicalFeature,
  worktreeCount,
  worktreeCap,
  activeTheme: this.themeName,
})}

<div class="layout">
  <main class="main">
    <div class="section-head">
      Main <span class="count">${canonicalFeature ? "in focus" : "(empty)"}</span>
      <span class="hint">primary action sourced from feature_state.next_actions[0]</span>
    </div>
    ${renderFocusTile({ state: featureState, linearTitle, linearUrl })}

    <div class="section-head">
      Worktrees <span class="count">phase C</span>
      <span class="hint">linked worktrees · click to switch into main</span>
    </div>
    <div class="empty-hint"><span class="glyph">·</span>Worktree row lands in phase C of the rebuild.</div>

    <div class="section-head">
      Branches <span class="count">phase C</span>
      <span class="hint">no worktree · switching creates one</span>
    </div>
    <div class="empty-hint"><span class="glyph">·</span>Branch ledger lands in phase C.</div>
  </main>

  <aside class="triage-rail">
    <div class="empty-hint" style="padding: 18px;"><span class="glyph">·</span>Triage feed lands in phase C.</div>
  </aside>
</div>

<script>
  const vscode = acquireVsCodeApi();
  document.addEventListener('click', (ev) => {
    const el = ev.target.closest('[data-action], [data-theme]');
    if (!el) return;
    const theme = el.getAttribute('data-theme');
    if (theme) {
      vscode.postMessage({ type: 'setTheme', theme });
      return;
    }
    const action = el.getAttribute('data-action');
    if (action) {
      const args = el.getAttribute('data-args');
      vscode.postMessage({
        type: 'invokeAction',
        action,
        args: args ? JSON.parse(args) : {},
      });
    }
  });
</script>

</body>
</html>`;
  }

  private renderError(message: string): string {
    return `<!DOCTYPE html><html><body style="font-family: sans-serif; padding: 24px; color: #f85149;">
      <h2>Canopy dashboard failed to load</h2>
      <pre style="white-space: pre-wrap;">${escapeHtml(message)}</pre>
    </body></html>`;
  }

  // ── Message handling (browser → extension) ───────────────────────

  private async handleMessage(msg: WebviewMessage): Promise<void> {
    switch (msg.type) {
      case "setTheme": {
        const theme = msg.theme;
        if (theme === "navy" || theme === "minimal") {
          await vscode.workspace
            .getConfiguration()
            .update(
              "canopy.dashboard.theme",
              theme,
              vscode.ConfigurationTarget.Global,
            );
        }
        return;
      }
      case "invokeAction": {
        // Phase B placeholder: surface the action via a message so we
        // can verify wiring. Phase D wires the real CTAs through.
        void vscode.window.showInformationMessage(
          `Canopy action: ${msg.action} ${JSON.stringify(msg.args ?? {})}`,
        );
        return;
      }
      case "refresh":
        void this.refresh();
        return;
    }
  }
}

// ── Helpers ─────────────────────────────────────────────────────────

type WebviewMessage =
  | { type: "setTheme"; theme: string }
  | { type: "invokeAction"; action: string; args?: Record<string, unknown> }
  | { type: "refresh" };

function readThemeName(): ThemeName {
  const v = vscode.workspace
    .getConfiguration("canopy")
    .get<string>("dashboard.theme", "navy");
  return v === "minimal" ? "minimal" : "navy";
}

function readWorktreeCap(): number {
  // Until we expose canopy.toml's max_worktrees via MCP, default to the
  // documented cap (2). User overrides live in canopy.toml only.
  return 2;
}

function abbreviatePath(p: string): string {
  const home = process.env.HOME ?? process.env.USERPROFILE ?? "";
  if (home && p.startsWith(home)) return "~" + p.slice(home.length);
  return p;
}
