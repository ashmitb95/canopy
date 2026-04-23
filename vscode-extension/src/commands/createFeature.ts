import * as vscode from "vscode";

import { CanopyClient } from "../canopyClient";
import { LinearIssue } from "../types";

interface PickItem extends vscode.QuickPickItem {
  itemKind: "linear" | "custom";
  issue?: LinearIssue;
}

/**
 * Linear-aware Create Feature flow.
 *
 *   1. Open a quick pick prefilled with `linear_my_issues()` results.
 *   2. Selecting an issue auto-suggests `<id>-<slug>` and creates a worktree.
 *   3. Falling through with a custom name opens a multi-select repo picker.
 *
 * Empty Linear list (or unconfigured) → still works as a freeform name input.
 */
export async function runCreateFeature(client: CanopyClient): Promise<string | null> {
  const issues = await client.linearMyIssues().catch(() => [] as LinearIssue[]);

  const items: PickItem[] = issues.map((i) => ({
    itemKind: "linear",
    issue: i,
    label: `$(link-external) ${i.identifier} — ${i.title}`,
    description: i.state,
    detail: `Auto-name: ${slugify(i.identifier, i.title)}`,
  }));

  const picked = await new Promise<PickItem | null>((resolve) => {
    const qp = vscode.window.createQuickPick<PickItem>();
    qp.placeholder = issues.length
      ? "Pick a Linear issue, or type a custom feature name…"
      : "Type a feature name (Linear MCP not configured)";
    qp.matchOnDescription = true;
    qp.matchOnDetail = true;
    const sentinel: PickItem = {
      itemKind: "custom",
      label: "$(add) Create feature with custom name",
    };
    qp.items = items.length ? [...items, sentinel] : [sentinel];

    qp.onDidChangeValue((value) => {
      const trimmed = value.trim();
      if (!trimmed) {
        qp.items = items.length ? [...items, sentinel] : [sentinel];
        return;
      }
      const dynamic: PickItem = {
        itemKind: "custom",
        label: `$(add) Create custom feature “${trimmed}”`,
        detail: "Press Enter to use this name and pick repos manually",
      };
      qp.items = items.length ? [dynamic, ...items] : [dynamic];
    });

    qp.onDidAccept(() => {
      const choice = qp.selectedItems[0] ?? null;
      qp.hide();
      resolve(choice);
    });
    qp.onDidHide(() => {
      qp.dispose();
      resolve(null);
    });
    qp.show();
  });

  if (!picked) return null;

  if (picked.itemKind === "linear" && picked.issue) {
    const suggested = slugify(picked.issue.identifier, picked.issue.title);
    const name = await vscode.window.showInputBox({
      prompt: `Feature name for ${picked.issue.identifier}`,
      value: suggested,
      validateInput: validateName,
    });
    if (!name) return null;
    const repos = await pickRepos(client);
    if (repos === null) return null;
    return await create(client, name, repos, picked.issue.identifier);
  }

  // Custom path
  const name = await vscode.window.showInputBox({
    prompt: "New feature name (used as the branch name)",
    validateInput: validateName,
  });
  if (!name) return null;
  const repos = await pickRepos(client);
  if (repos === null) return null;
  return await create(client, name, repos);
}

async function pickRepos(client: CanopyClient): Promise<string[] | null> {
  let repoNames: string[] = [];
  try {
    const ws = await client.workspaceStatus();
    repoNames = (ws.repos ?? [])
      .map((r) => (r.name as string) ?? "")
      .filter(Boolean);
  } catch {
    return null;
  }
  if (!repoNames.length) {
    void vscode.window.showWarningMessage("Canopy: no repos in this workspace");
    return null;
  }

  const selected = await vscode.window.showQuickPick(
    repoNames.map((name) => ({ label: name, picked: true })),
    {
      canPickMany: true,
      placeHolder: "Select repos for this feature (all selected by default)",
    },
  );
  if (!selected) return null;
  return selected.map((s) => s.label);
}

async function create(
  client: CanopyClient,
  name: string,
  repos: string[],
  linearIssue?: string,
): Promise<string | null> {
  try {
    if (linearIssue) {
      await client.worktreeCreate({ name, issue: linearIssue, repos });
    } else {
      await client.featureCreate({ name, repos, use_worktrees: true });
    }
    void vscode.window.showInformationMessage(
      `Canopy: created feature ${name}`,
    );
    return name;
  } catch (err) {
    void vscode.window.showErrorMessage(
      `Canopy: failed to create ${name} — ${(err as Error).message}`,
    );
    return null;
  }
}

function slugify(id: string, title: string): string {
  const slug = title
    .replace(/[^a-zA-Z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .toLowerCase()
    .slice(0, 50)
    .replace(/-+$/, "");
  return slug ? `${id.toLowerCase()}-${slug}` : id.toLowerCase();
}

function validateName(value: string): string | null {
  if (!value.trim()) return "Name cannot be empty";
  if (/\s/.test(value)) return "No whitespace allowed in branch names";
  return null;
}
