import * as vscode from "vscode";

import { CanopyClient } from "../canopyClient";
import { LinearIssue } from "../types";

type Node = StateGroupNode | IssueNode;

const TODO_STATES = new Set(["todo", "unstarted", "to do", "backlog-todo"]);
const IN_PROGRESS_STATES = new Set([
  "in progress",
  "in-progress",
  "started",
  "doing",
]);

class StateGroupNode {
  readonly kind = "group" as const;
  constructor(
    public readonly title: string,
    public readonly issues: LinearIssue[],
  ) {}
}

class IssueNode {
  readonly kind = "issue" as const;
  constructor(public readonly issue: LinearIssue) {}
}

/**
 * Top-level LINEAR ISSUES tree. Shows issues assigned to the user in Todo
 * or In Progress state. Click an issue to start a new feature lane from it.
 *
 * When Linear MCP isn't configured, the view falls back to the welcome
 * content declared in package.json (contributes.viewsWelcome).
 */
export class LinearIssuesProvider implements vscode.TreeDataProvider<Node> {
  private readonly _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  constructor(private readonly client: CanopyClient) {}

  refresh(): void {
    this._onDidChange.fire();
  }

  getTreeItem(element: Node): vscode.TreeItem {
    if (element.kind === "group") {
      const item = new vscode.TreeItem(
        element.title,
        vscode.TreeItemCollapsibleState.Expanded,
      );
      item.contextValue = "linear.group";
      item.description = `${element.issues.length} issue${element.issues.length === 1 ? "" : "s"}`;
      return item;
    }

    const issue = element.issue;
    const item = new vscode.TreeItem(
      issue.identifier,
      vscode.TreeItemCollapsibleState.None,
    );
    item.description = issue.title;
    item.contextValue = "linear.issue";
    item.iconPath = new vscode.ThemeIcon(
      "issue-opened",
      new vscode.ThemeColor(
        isInProgress(issue.state) ? "charts.blue" : "charts.yellow",
      ),
    );
    item.tooltip = new vscode.MarkdownString(
      `**${issue.identifier}** — ${issue.title}\n\nState: ${issue.state || "unknown"}${issue.url ? `\n\n[Open in Linear](${issue.url})` : ""}`,
    );
    item.command = {
      command: "canopy.createFeatureFromIssue",
      title: "Create feature lane from issue",
      arguments: [issue],
    };
    return item;
  }

  async getChildren(element?: Node): Promise<Node[]> {
    if (element?.kind === "group") {
      return element.issues.map((issue) => new IssueNode(issue));
    }
    if (element) return [];

    let issues: LinearIssue[];
    try {
      issues = await this.client.linearMyIssues(50);
    } catch {
      return [];
    }

    const todo: LinearIssue[] = [];
    const inProgress: LinearIssue[] = [];
    for (const issue of issues) {
      if (isInProgress(issue.state)) {
        inProgress.push(issue);
      } else if (isTodo(issue.state)) {
        todo.push(issue);
      }
    }

    const groups: Node[] = [];
    if (todo.length) groups.push(new StateGroupNode("Todo", todo));
    if (inProgress.length)
      groups.push(new StateGroupNode("In Progress", inProgress));
    return groups;
  }
}

function isTodo(state: string): boolean {
  return TODO_STATES.has((state || "").toLowerCase().trim());
}

function isInProgress(state: string): boolean {
  return IN_PROGRESS_STATES.has((state || "").toLowerCase().trim());
}
