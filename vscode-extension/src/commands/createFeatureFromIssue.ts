import * as vscode from "vscode";

import { CanopyClient } from "../canopyClient";
import { LinearIssue } from "../types";

/**
 * Creates a feature lane directly from a Linear issue (right-click or click
 * from the Linear Issues tree). Skips the free-text search that
 * `runCreateFeature` starts with — the issue is already picked.
 */
export async function runCreateFeatureFromIssue(
  client: CanopyClient,
  issue: LinearIssue,
): Promise<string | null> {
  const suggested = slugify(issue.identifier, issue.title);

  const name = await vscode.window.showInputBox({
    prompt: `Feature name for ${issue.identifier}`,
    value: suggested,
    validateInput: validateName,
  });
  if (!name) return null;

  const repos = await pickRepos(client);
  if (repos === null) return null;

  try {
    await client.worktreeCreate({
      name,
      issue: issue.identifier,
      repos,
    });
    void vscode.window.showInformationMessage(
      `Canopy: created feature ${name} from ${issue.identifier}`,
    );
    return name;
  } catch (err) {
    void vscode.window.showErrorMessage(
      `Canopy: failed to create ${name} — ${(err as Error).message}`,
    );
    return null;
  }
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
