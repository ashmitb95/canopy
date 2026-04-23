import * as path from "node:path";
import * as vscode from "vscode";

import { CanopyClient } from "../canopyClient";
import { FeatureChange } from "../types";

type Node = ChangesRepoNode | ChangeFileNode | EmptyNode;

class ChangesRepoNode {
  constructor(
    public readonly repoName: string,
    public readonly repoPath: string,
    public readonly changes: FeatureChange[],
  ) {}
  readonly kind = "repo" as const;
}

class ChangeFileNode {
  constructor(
    public readonly repoPath: string,
    public readonly change: FeatureChange,
  ) {}
  readonly kind = "file" as const;
}

class EmptyNode {
  constructor(public readonly message: string) {}
  readonly kind = "empty" as const;
}

export class ChangesProvider implements vscode.TreeDataProvider<Node> {
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
    if (element.kind === "empty") {
      const item = new vscode.TreeItem(element.message);
      item.iconPath = new vscode.ThemeIcon("info");
      return item;
    }

    if (element.kind === "repo") {
      const item = new vscode.TreeItem(
        element.repoName,
        vscode.TreeItemCollapsibleState.Expanded,
      );
      item.contextValue = "changes.repo";
      item.iconPath = new vscode.ThemeIcon("repo");
      const n = element.changes.length;
      item.description = `${n} change${n === 1 ? "" : "s"}`;
      item.tooltip = element.repoPath;
      return item;
    }

    const filePath = path.join(element.repoPath, element.change.path);
    const item = new vscode.TreeItem(
      path.basename(element.change.path),
      vscode.TreeItemCollapsibleState.None,
    );
    item.description = element.change.path;
    item.contextValue = "changes.file";
    item.tooltip = `${describeStatus(element.change.status)} — ${element.change.path}`;
    item.iconPath = statusIcon(element.change.status);
    item.resourceUri = vscode.Uri.file(filePath);
    if (element.change.status !== "D") {
      item.command = {
        command: "vscode.open",
        title: "Open file",
        arguments: [vscode.Uri.file(filePath)],
      };
    }
    return item;
  }

  async getChildren(element?: Node): Promise<Node[]> {
    if (!element) {
      const active = this.getActiveFeature();
      if (!active) {
        return [
          new EmptyNode(
            "Open a feature's worktree (or run Canopy: Switch to Feature) to see its changes.",
          ),
        ];
      }
      try {
        const result = await this.client.featureChanges(active);
        const nodes: Node[] = [];
        for (const [repoName, payload] of Object.entries(result.repos)) {
          if (!payload.has_branch) continue;
          if (!payload.changes.length) continue;
          nodes.push(
            new ChangesRepoNode(repoName, payload.path, payload.changes),
          );
        }
        if (!nodes.length) {
          return [new EmptyNode(`No changes in ${active}.`)];
        }
        return nodes;
      } catch (err) {
        return [
          new EmptyNode(
            `Failed to load changes — ${(err as Error).message}`,
          ),
        ];
      }
    }
    if (element.kind === "repo") {
      return element.changes.map((c) => new ChangeFileNode(element.repoPath, c));
    }
    return [];
  }
}

function statusIcon(status: string): vscode.ThemeIcon {
  switch (status) {
    case "M":
      return new vscode.ThemeIcon(
        "diff-modified",
        new vscode.ThemeColor("gitDecoration.modifiedResourceForeground"),
      );
    case "A":
      return new vscode.ThemeIcon(
        "diff-added",
        new vscode.ThemeColor("gitDecoration.addedResourceForeground"),
      );
    case "D":
      return new vscode.ThemeIcon(
        "diff-removed",
        new vscode.ThemeColor("gitDecoration.deletedResourceForeground"),
      );
    case "R":
      return new vscode.ThemeIcon(
        "diff-renamed",
        new vscode.ThemeColor("gitDecoration.renamedResourceForeground"),
      );
    case "?":
      return new vscode.ThemeIcon(
        "question",
        new vscode.ThemeColor("gitDecoration.untrackedResourceForeground"),
      );
    default:
      return new vscode.ThemeIcon("circle-outline");
  }
}

function describeStatus(status: string): string {
  switch (status) {
    case "M":
      return "Modified";
    case "A":
      return "Added";
    case "D":
      return "Deleted";
    case "R":
      return "Renamed";
    case "C":
      return "Copied";
    case "T":
      return "Type changed";
    case "?":
      return "Untracked";
    default:
      return status;
  }
}
