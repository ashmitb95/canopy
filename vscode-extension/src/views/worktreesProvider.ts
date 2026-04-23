import * as vscode from "vscode";

import { CanopyClient } from "../canopyClient";
import { WorktreeRepoInfo } from "../types";

type Node = WorktreeFeatureNode | WorktreeRepoNode;

class WorktreeFeatureNode {
  constructor(
    public readonly featureName: string,
    public readonly repos: Record<string, WorktreeRepoInfo>,
  ) {}
  readonly kind = "feature" as const;
}

class WorktreeRepoNode {
  constructor(
    public readonly featureName: string,
    public readonly repoName: string,
    public readonly info: WorktreeRepoInfo,
  ) {}
  readonly kind = "repo" as const;
}

export class WorktreesProvider implements vscode.TreeDataProvider<Node> {
  private readonly _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  /** Latest "active / max" pair, surfaced via getViewBadge from extension.ts. */
  budgetLabel = "";

  constructor(private readonly client: CanopyClient) {}

  refresh(): void {
    this._onDidChange.fire();
  }

  getTreeItem(element: Node): vscode.TreeItem {
    if (element.kind === "feature") {
      const item = new vscode.TreeItem(
        element.featureName,
        vscode.TreeItemCollapsibleState.Expanded,
      );
      item.contextValue = "worktree.feature";
      item.iconPath = new vscode.ThemeIcon("folder");
      const repoCount = Object.keys(element.repos).length;
      item.description = `${repoCount} worktree${repoCount === 1 ? "" : "s"}`;
      return item;
    }

    const item = new vscode.TreeItem(
      element.repoName,
      vscode.TreeItemCollapsibleState.None,
    );
    item.contextValue = "worktree.repo";
    item.iconPath = new vscode.ThemeIcon("repo");
    const parts: string[] = [];
    if (element.info.ahead) parts.push(`↑${element.info.ahead}`);
    if (element.info.behind) parts.push(`↓${element.info.behind}`);
    if (element.info.dirty_count) parts.push(`${element.info.dirty_count} dirty`);
    item.description = parts.join(" · ") || element.info.branch;
    item.tooltip = element.info.path;
    item.resourceUri = vscode.Uri.file(element.info.path);
    item.command = {
      command: "vscode.openFolder",
      title: "Open worktree in new window",
      arguments: [vscode.Uri.file(element.info.path), { forceNewWindow: true }],
    };
    return item;
  }

  async getChildren(element?: Node): Promise<Node[]> {
    if (!element) {
      try {
        const [info, config] = await Promise.all([
          this.client.worktreeInfo().catch(() => null),
          this.client.workspaceConfig().catch(() => null),
        ]);
        const featureMap =
          info && info.features && typeof info.features === "object"
            ? info.features
            : {};
        const featureCount = Object.keys(featureMap).length;
        const max = config?.max_worktrees ?? 0;
        this.budgetLabel = max > 0 ? `${featureCount} / ${max}` : `${featureCount}`;
        return Object.entries(featureMap).map(([name, payload]) => {
          const repos =
            payload && typeof payload === "object" && payload.repos && typeof payload.repos === "object"
              ? payload.repos
              : {};
          return new WorktreeFeatureNode(name, repos);
        });
      } catch (err) {
        console.error("[canopy] worktreesProvider.getChildren failed", err);
        return [];
      }
    }
    if (element.kind === "feature") {
      return Object.entries(element.repos).map(
        ([repo, info]) => new WorktreeRepoNode(element.featureName, repo, info),
      );
    }
    return [];
  }
}
