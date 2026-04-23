import * as vscode from "vscode";

import { CanopyClient } from "../canopyClient";

interface ReviewRow {
  feature: string;
  light: "green" | "yellow" | "red";
  summary: string;
  url?: string;
}

class ReviewNode {
  constructor(public readonly row: ReviewRow) {}
}

/**
 * Per-feature traffic-light row backed by review_status + review_comments.
 * Cached for the lifetime of one refresh cycle to avoid N round trips on every
 * VSCode tree expansion.
 */
export class ReviewProvider implements vscode.TreeDataProvider<ReviewNode> {
  private readonly _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  constructor(private readonly client: CanopyClient) {}

  refresh(): void {
    this._onDidChange.fire();
  }

  getTreeItem(element: ReviewNode): vscode.TreeItem {
    const item = new vscode.TreeItem(
      element.row.feature,
      vscode.TreeItemCollapsibleState.None,
    );
    item.iconPath = lightIcon(element.row.light);
    item.description = element.row.summary;
    if (element.row.url) {
      item.command = {
        command: "vscode.open",
        title: "Open PR",
        arguments: [vscode.Uri.parse(element.row.url)],
      };
      item.tooltip = element.row.url;
    }
    return item;
  }

  async getChildren(element?: ReviewNode): Promise<ReviewNode[]> {
    if (element) return [];
    try {
      const features = await this.client.featureList();
      const rows = await Promise.all(
        features
          .filter((l) => l.status === "active")
          .map((l) => this.computeRow(l.name)),
      );
      return rows.map((r) => new ReviewNode(r));
    } catch {
      return [];
    }
  }

  private async computeRow(name: string): Promise<ReviewRow> {
    let status: Awaited<ReturnType<CanopyClient["reviewStatus"]>> | null = null;
    let comments: Awaited<ReturnType<CanopyClient["reviewComments"]>> | null = null;
    let mergeReady: Awaited<
      ReturnType<CanopyClient["featureMergeReadiness"]>
    > | null = null;

    try {
      status = await this.client.reviewStatus(name);
    } catch {
      // GitHub MCP not configured, treat as no PR
    }
    try {
      comments = await this.client.reviewComments(name);
    } catch {
      // ignore
    }
    try {
      mergeReady = await this.client.featureMergeReadiness(name);
    } catch {
      // ignore
    }

    const unresolved = comments?.total_comments ?? 0;
    const overlap = (mergeReady?.issues ?? []).filter((i) =>
      i.toLowerCase().startsWith("type overlap"),
    ).length;
    const hasPr = !!status?.has_prs;
    let light: ReviewRow["light"] = "yellow";
    const parts: string[] = [];

    if (overlap > 0) {
      light = "red";
      parts.push(`${overlap} overlap warning${overlap === 1 ? "" : "s"}`);
    } else if (hasPr && unresolved === 0) {
      light = "green";
      parts.push("PR · ready");
    } else if (hasPr) {
      light = "yellow";
      parts.push(
        `${unresolved} unresolved comment${unresolved === 1 ? "" : "s"}`,
      );
    } else {
      light = "yellow";
      parts.push("no PR yet");
    }

    let prUrl: string | undefined;
    if (status) {
      for (const repo of Object.values(status.repos)) {
        if (repo.pr?.url) {
          parts.push(`#${repo.pr.number}`);
          prUrl = repo.pr.url;
          break;
        }
      }
    }

    return { feature: name, light, summary: parts.join(" · "), url: prUrl };
  }
}

function lightIcon(light: ReviewRow["light"]): vscode.ThemeIcon {
  const map = {
    green: "charts.green",
    yellow: "charts.yellow",
    red: "charts.red",
  } as const;
  return new vscode.ThemeIcon(
    "circle-filled",
    new vscode.ThemeColor(map[light]),
  );
}
