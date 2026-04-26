import * as vscode from "vscode";

import { CanopyClient } from "../canopyClient";
import { LinearIssue } from "../types";

type Kind =
  | "section-active"
  | "section-features"
  | "section-linear"
  | "active-feature"
  | "active-repo"
  | "feature"
  | "linear-issue"
  | "empty";

export interface CanopyNode {
  kind: Kind;
  label: string;
  description?: string;
  tooltip?: string;
  contextValue?: string;
  iconId?: string;
  iconColor?: vscode.ThemeColor;
  command?: vscode.Command;
  collapsibleState?: vscode.TreeItemCollapsibleState;

  featureName?: string;
  repoName?: string;
  worktreePath?: string;
  linearIssue?: LinearIssue;
}

export class CanopyTreeProvider implements vscode.TreeDataProvider<CanopyNode> {
  private readonly _onDidChange = new vscode.EventEmitter<CanopyNode | undefined>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  private linearCount = 0;
  private featureCount = 0;

  constructor(
    private readonly client: CanopyClient,
    private readonly getActiveFeature: () => string | null,
  ) {}

  refresh(): void {
    this._onDidChange.fire(undefined);
  }

  getTreeItem(node: CanopyNode): vscode.TreeItem {
    const item = new vscode.TreeItem(node.label, node.collapsibleState);
    if (node.description !== undefined) item.description = node.description;
    if (node.tooltip !== undefined) item.tooltip = node.tooltip;
    if (node.contextValue !== undefined) item.contextValue = node.contextValue;
    if (node.command !== undefined) item.command = node.command;
    if (node.iconId !== undefined) {
      item.iconPath = node.iconColor
        ? new vscode.ThemeIcon(node.iconId, node.iconColor)
        : new vscode.ThemeIcon(node.iconId);
    }
    return item;
  }

  async getChildren(parent?: CanopyNode): Promise<CanopyNode[]> {
    if (!parent) {
      return [
        {
          kind: "section-active",
          label: "ACTIVE",
          collapsibleState: vscode.TreeItemCollapsibleState.Expanded,
          contextValue: "section",
        },
        {
          kind: "section-features",
          label: "FEATURES",
          description: this.featureCount ? `${this.featureCount}` : undefined,
          collapsibleState: vscode.TreeItemCollapsibleState.Expanded,
          contextValue: "section",
        },
        {
          kind: "section-linear",
          label: "LINEAR INBOX",
          description: this.linearCount ? `${this.linearCount} todos` : undefined,
          collapsibleState: vscode.TreeItemCollapsibleState.Collapsed,
          contextValue: "section",
        },
      ];
    }

    switch (parent.kind) {
      case "section-active":
        return this.activeChildren();
      case "section-features":
        return this.featureChildren();
      case "section-linear":
        return this.linearChildren();
      case "active-feature":
        return this.activeRepoChildren(parent.featureName!);
      default:
        return [];
    }
  }

  private async activeChildren(): Promise<CanopyNode[]> {
    const active = this.getActiveFeature();
    if (!active) {
      return [
        {
          kind: "empty",
          label: "(no active feature)",
          tooltip: "Use Canopy: Switch to Feature to set one",
          collapsibleState: vscode.TreeItemCollapsibleState.None,
        },
      ];
    }
    let lane;
    try {
      lane = await this.client.featureStatus(active);
    } catch (err) {
      return [
        {
          kind: "empty",
          label: `error: ${(err as Error).message}`,
          collapsibleState: vscode.TreeItemCollapsibleState.None,
        },
      ];
    }
    const dirty = Object.values(lane.repo_states).reduce(
      (n, s) => n + (s.changed_file_count ?? 0),
      0,
    );
    const ahead = Object.values(lane.repo_states).reduce(
      (n, s) => n + (s.ahead ?? 0),
      0,
    );
    const desc =
      lane.linear_issue
        ? `${lane.linear_issue} · ↑${ahead} · ${dirty} dirty`
        : `↑${ahead} · ${dirty} dirty`;
    return [
      {
        kind: "active-feature",
        label: active,
        description: desc,
        tooltip: lane.linear_title ?? undefined,
        contextValue: "feature",
        iconId: "circle-filled",
        iconColor: new vscode.ThemeColor("charts.green"),
        collapsibleState: vscode.TreeItemCollapsibleState.Expanded,
        featureName: active,
        command: {
          command: "canopy.openDashboard",
          title: "Open dashboard",
          arguments: [active],
        },
      },
    ];
  }

  private async activeRepoChildren(feature: string): Promise<CanopyNode[]> {
    let lane;
    try {
      lane = await this.client.featureStatus(feature);
    } catch {
      return [];
    }
    return Object.entries(lane.repo_states).map(([repo, state]) => {
      const ahead = state.ahead ?? 0;
      const dirty = state.changed_file_count ?? 0;
      const parts: string[] = [];
      if (ahead) parts.push(`↑${ahead}`);
      if (dirty) parts.push(`${dirty} dirty`);
      const desc = parts.join(" · ") || "clean";
      return {
        kind: "active-repo",
        label: repo,
        description: desc,
        contextValue: "feature.repo",
        iconId: "repo",
        collapsibleState: vscode.TreeItemCollapsibleState.None,
        featureName: feature,
        repoName: repo,
        worktreePath: state.worktree_path ?? undefined,
        command: state.worktree_path
          ? {
              command: "vscode.openFolder",
              title: "Open worktree",
              arguments: [vscode.Uri.file(state.worktree_path), { forceNewWindow: false }],
            }
          : undefined,
      };
    });
  }

  private async featureChildren(): Promise<CanopyNode[]> {
    let features;
    try {
      features = await this.client.featureList();
    } catch (err) {
      return [
        {
          kind: "empty",
          label: `error: ${(err as Error).message}`,
          collapsibleState: vscode.TreeItemCollapsibleState.None,
        },
      ];
    }
    const active = this.getActiveFeature();
    const visible = features.filter((f: { name: string }) => f.name !== active);
    this.featureCount = visible.length;
    if (!visible.length) {
      return [
        {
          kind: "empty",
          label: active ? "(no other features)" : "(no features yet)",
          collapsibleState: vscode.TreeItemCollapsibleState.None,
        },
      ];
    }
    return visible.map((f: { name: string; repos: string[]; linear_issue?: string | null }) => {
      const linear = f.linear_issue ? ` · ${f.linear_issue}` : "";
      return {
        kind: "feature",
        label: f.name,
        description: `${f.repos.length} repo${f.repos.length === 1 ? "" : "s"}${linear}`,
        contextValue: "feature",
        iconId: "circle-outline",
        collapsibleState: vscode.TreeItemCollapsibleState.None,
        featureName: f.name,
        command: {
          command: "canopy.openDashboard",
          title: "Open dashboard",
          arguments: [f.name],
        },
      };
    });
  }

  private async linearChildren(): Promise<CanopyNode[]> {
    let issues: LinearIssue[];
    try {
      issues = await this.client.linearMyIssues(25);
    } catch (err) {
      return [
        {
          kind: "empty",
          label: `Linear unavailable: ${(err as Error).message}`,
          collapsibleState: vscode.TreeItemCollapsibleState.None,
        },
      ];
    }
    const todos = issues.filter((i) => i.state.toLowerCase() === "todo");
    this.linearCount = todos.length;
    if (!todos.length) {
      return [
        {
          kind: "empty",
          label: "(inbox empty)",
          collapsibleState: vscode.TreeItemCollapsibleState.None,
        },
      ];
    }
    return todos.map((i) => ({
      kind: "linear-issue" as const,
      label: i.identifier,
      description: i.title,
      tooltip: `${i.identifier} · ${i.state}\n${i.title}`,
      contextValue: "linear.issue",
      iconId: "issues",
      collapsibleState: vscode.TreeItemCollapsibleState.None,
      linearIssue: i,
      command: {
        command: "canopy.createFeatureFromIssue",
        title: "Start feature from this issue",
        arguments: [i],
      },
    }));
  }
}
