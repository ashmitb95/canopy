import * as vscode from "vscode";

import { CanopyClient } from "./canopyClient";

/**
 * Three left-aligned status bar items mirroring mockup screen 1:
 *   ⛺ <feature> · ⑂ <N> repos · ↑N ↓N
 *
 * Cheap to refresh (one workspace_context + one worktree_info call), so we
 * recompute on every refresh tick.
 */
export class StatusBarManager implements vscode.Disposable {
  private readonly featureItem: vscode.StatusBarItem;
  private readonly reposItem: vscode.StatusBarItem;
  private readonly aheadItem: vscode.StatusBarItem;
  activeFeature: string | null = null;

  constructor(private readonly client: CanopyClient) {
    this.featureItem = vscode.window.createStatusBarItem(
      "canopy.feature",
      vscode.StatusBarAlignment.Left,
      100,
    );
    this.featureItem.text = "$(rocket) Canopy";
    this.featureItem.tooltip = "Canopy: open feature dashboard";
    this.featureItem.command = {
      command: "canopy.openDashboardForActive",
      title: "Open active dashboard",
    };

    this.reposItem = vscode.window.createStatusBarItem(
      "canopy.repos",
      vscode.StatusBarAlignment.Left,
      99,
    );
    this.reposItem.command = "canopy.refresh";

    this.aheadItem = vscode.window.createStatusBarItem(
      "canopy.ahead",
      vscode.StatusBarAlignment.Left,
      98,
    );
  }

  dispose(): void {
    this.featureItem.dispose();
    this.reposItem.dispose();
    this.aheadItem.dispose();
  }

  async refresh(): Promise<void> {
    let feature: string | null = null;
    try {
      const ctx = await this.client.workspaceContext();
      feature = ctx.feature;
    } catch {
      // canopy-mcp not running yet
    }
    this.activeFeature = feature;

    if (feature) {
      this.featureItem.text = `$(rocket) ${feature}`;
      this.featureItem.show();
    } else {
      this.featureItem.text = "$(rocket) Canopy";
      this.featureItem.show();
    }

    try {
      const info = await this.client.worktreeInfo();
      const featureBlock =
        feature && info?.features && typeof info.features === "object"
          ? info.features[feature]
          : null;
      const repoMap =
        featureBlock && typeof featureBlock === "object" && featureBlock.repos && typeof featureBlock.repos === "object"
          ? featureBlock.repos
          : null;
      if (repoMap) {
        const repos = Object.values(repoMap);
        this.reposItem.text = `$(repo) ${repos.length} repo${repos.length === 1 ? "" : "s"}`;
        this.reposItem.show();
        const ahead = repos.reduce((s, r) => s + ((r as { ahead?: number })?.ahead ?? 0), 0);
        const behind = repos.reduce((s, r) => s + ((r as { behind?: number })?.behind ?? 0), 0);
        this.aheadItem.text = `$(arrow-up)${ahead} $(arrow-down)${behind}`;
        this.aheadItem.show();
      } else {
        this.reposItem.hide();
        this.aheadItem.hide();
      }
    } catch {
      this.reposItem.hide();
      this.aheadItem.hide();
    }
  }
}
