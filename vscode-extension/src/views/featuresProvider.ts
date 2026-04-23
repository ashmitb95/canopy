import * as vscode from "vscode";

import { CanopyClient } from "../canopyClient";
import { FeatureLane, RepoState, WorktreeInfo } from "../types";

type Node = FeatureNode | RepoUnderFeatureNode;

class FeatureNode {
  constructor(public readonly lane: FeatureLane, public readonly isActive: boolean) {}
  readonly kind = "feature" as const;
}

class RepoUnderFeatureNode {
  constructor(
    public readonly featureName: string,
    public readonly repoName: string,
    public readonly state: RepoState,
  ) {}
  readonly kind = "repo" as const;
}

/**
 * Top-level FEATURES tree. One row per lane in features.json plus expand-to-repos.
 * Click a feature → opens the dashboard webview. Right-click for switch / done.
 */
export class FeaturesProvider implements vscode.TreeDataProvider<Node> {
  private readonly _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  constructor(
    private readonly client: CanopyClient,
    private readonly getActiveFeature: () => string | null,
  ) {}

  refresh(): void {
    this._onDidChange.fire();
  }

  getTreeItem(element: Node): vscode.TreeItem {
    if (element.kind === "feature") {
      const lane = element.lane;
      const item = new vscode.TreeItem(
        lane.name,
        vscode.TreeItemCollapsibleState.Collapsed,
      );
      item.contextValue = "feature";
      item.iconPath = featureIcon(lane, element.isActive);
      item.description = featureDescription(lane, element.isActive);
      item.tooltip = featureTooltip(lane);
      item.command = {
        command: "canopy.openDashboard",
        title: "Open dashboard",
        arguments: [lane.name],
      };
      return item;
    }

    const repoItem = new vscode.TreeItem(
      element.repoName,
      vscode.TreeItemCollapsibleState.None,
    );
    repoItem.contextValue = "feature.repo";
    repoItem.iconPath = new vscode.ThemeIcon("repo");
    const ahead = element.state.ahead ?? 0;
    const behind = element.state.behind ?? 0;
    const files = element.state.changed_file_count ?? 0;
    const parts: string[] = [];
    if (ahead) parts.push(`↑${ahead}`);
    if (behind) parts.push(`↓${behind}`);
    if (files) parts.push(`${files} file${files === 1 ? "" : "s"}`);
    if (element.state.dirty) parts.push("dirty");
    repoItem.description = parts.join(" · ");
    if (element.state.worktree_path) {
      repoItem.command = {
        command: "vscode.openFolder",
        title: "Open worktree",
        arguments: [vscode.Uri.file(element.state.worktree_path), { forceNewWindow: true }],
      };
    }
    return repoItem;
  }

  async getChildren(element?: Node): Promise<Node[]> {
    if (!element) {
      try {
        // Merge three sources so the Features list shows *every* detected
        // feature — not just ones explicitly created via `canopy feature create`:
        //
        //   1. features.json (authoritative metadata — Linear links, status)
        //   2. .canopy/worktrees/* on disk (implicit when worktrees were added
        //      manually or from an older Canopy)
        //   3. workspace_status.active_features (branches living in 2+ repos
        //      with no worktree yet)
        const [features, worktreeInfo, ws] = await Promise.all([
          this.client.featureList().catch(() => [] as FeatureLane[]),
          this.client
            .worktreeInfo()
            .catch(() => ({ features: {}, repos: {} } as WorktreeInfo)),
          this.client
            .workspaceStatus()
            .catch(() => ({ active_features: [] as string[] } as unknown as {
              active_features: string[];
            })),
        ]);

        const byName = new Map<string, FeatureLane>();
        for (const lane of Array.isArray(features) ? features : []) {
          if (lane && typeof lane === "object" && typeof lane.name === "string") {
            byName.set(lane.name, {
              ...lane,
              repos: Array.isArray(lane.repos) ? lane.repos : [],
              repo_states:
                lane.repo_states && typeof lane.repo_states === "object"
                  ? lane.repo_states
                  : {},
            });
          }
        }

        const featureMap =
          worktreeInfo && worktreeInfo.features && typeof worktreeInfo.features === "object"
            ? worktreeInfo.features
            : {};
        for (const [name, wt] of Object.entries(featureMap)) {
          if (byName.has(name)) continue;
          const repos =
            wt && typeof wt === "object" && wt.repos && typeof wt.repos === "object"
              ? wt.repos
              : {};
          const repo_states: Record<string, RepoState> = {};
          for (const [repo, info] of Object.entries(repos)) {
            const i = info ?? ({} as Record<string, unknown>);
            repo_states[repo] = {
              has_branch: true,
              ahead: (i as { ahead?: number }).ahead ?? 0,
              behind: (i as { behind?: number }).behind ?? 0,
              dirty: (i as { dirty?: boolean }).dirty ?? false,
              changed_file_count: (i as { dirty_count?: number }).dirty_count ?? 0,
              default_branch: (i as { default_branch?: string }).default_branch ?? "",
              worktree_path: (i as { path?: string }).path,
            };
          }
          byName.set(name, {
            name,
            repos: Object.keys(repos),
            created_at: "",
            status: "active",
            repo_states,
          });
        }

        const activeFeatures =
          ws && Array.isArray((ws as { active_features?: string[] }).active_features)
            ? (ws as { active_features: string[] }).active_features
            : [];
        for (const name of activeFeatures) {
          if (byName.has(name)) continue;
          byName.set(name, {
            name,
            repos: [],
            created_at: "",
            status: "active",
            repo_states: {},
          });
        }

        const active = this.getActiveFeature();
        return Array.from(byName.values()).map(
          (lane) => new FeatureNode(lane, lane.name === active),
        );
      } catch (err) {
        // Surface the stack so users can share it from the Canopy output channel.
        console.error("[canopy] featuresProvider.getChildren failed", err);
        return [];
      }
    }
    if (element.kind === "feature") {
      return element.lane.repos.map(
        (repo) =>
          new RepoUnderFeatureNode(
            element.lane.name,
            repo,
            element.lane.repo_states?.[repo] ?? { has_branch: false },
          ),
      );
    }
    return [];
  }
}

function featureIcon(lane: FeatureLane, isActive: boolean): vscode.ThemeIcon {
  if (isActive) {
    return new vscode.ThemeIcon(
      "circle-filled",
      new vscode.ThemeColor("charts.green"),
    );
  }
  if (lane.status === "active") {
    return new vscode.ThemeIcon(
      "circle-filled",
      new vscode.ThemeColor("charts.yellow"),
    );
  }
  return new vscode.ThemeIcon(
    "circle-outline",
    new vscode.ThemeColor("descriptionForeground"),
  );
}

function featureDescription(lane: FeatureLane, isActive: boolean): string {
  const parts: string[] = [];
  if (isActive) parts.push("ACTIVE");
  if (lane.linear_issue) parts.push(lane.linear_issue);
  if (lane.status && lane.status !== "active") parts.push(lane.status);
  parts.push(`${lane.repos.length} repo${lane.repos.length === 1 ? "" : "s"}`);
  return parts.join(" · ");
}

function featureTooltip(lane: FeatureLane): vscode.MarkdownString {
  const md = new vscode.MarkdownString(undefined, true);
  md.isTrusted = true;
  md.appendMarkdown(`**${lane.name}** — ${lane.status}\n\n`);
  if (lane.linear_title) {
    md.appendMarkdown(`*${lane.linear_issue}* — ${lane.linear_title}\n\n`);
  }
  md.appendMarkdown(`Repos: ${lane.repos.join(", ")}\n\n`);
  if (lane.created_at) md.appendMarkdown(`Created: ${lane.created_at}\n`);
  return md;
}
