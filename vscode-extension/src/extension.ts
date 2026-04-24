import * as fs from "node:fs";
import * as path from "node:path";
import * as vscode from "vscode";

import { CanopyClient } from "./canopyClient";
import { runCreateFeature } from "./commands/createFeature";
import { runCreateFeatureFromIssue } from "./commands/createFeatureFromIssue";
import { runInstallBackend } from "./commands/installBackend";
import { runSetupWizard } from "./commands/setupWizard";
import { LinearIssue } from "./types";
import { resolveCanopyMcp } from "./mcpResolver";
import { StatusBarManager } from "./statusBar";
import { ChangesProvider } from "./views/changesProvider";
import { FeaturesProvider } from "./views/featuresProvider";
import { LinearIssuesProvider } from "./views/linearIssuesProvider";
import { ReviewProvider } from "./views/reviewProvider";
import { WorktreesProvider } from "./views/worktreesProvider";
import { createWatchers } from "./watchers";
import {
  DashboardPanel,
  fetchDashboardPayload,
  launchClaudeWorkflow,
} from "./webview/dashboardPanel";

interface Active {
  client: CanopyClient;
  features: FeaturesProvider;
  worktrees: WorktreesProvider;
  changes: ChangesProvider;
  review: ReviewProvider;
  linearIssues: LinearIssuesProvider;
  status: StatusBarManager;
  worktreesView: vscode.TreeView<unknown>;
  refresh: () => Promise<void>;
  dispose: () => void;
}

let active: Active | null = null;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const output = vscode.window.createOutputChannel("Canopy");
  context.subscriptions.push(output);

  const root = findCanopyRoot();
  if (!root) {
    output.appendLine(
      "[canopy] no canopy.toml found in any workspace folder; extension idle",
    );
    await vscode.commands.executeCommand(
      "setContext",
      "canopy.state",
      "no-workspace",
    );
    registerInitCommand(context, output);
    return;
  }

  await vscode.commands.executeCommand("setContext", "canopy.state", "loading");
  await bootstrap(context, output, root);
}

export async function deactivate(): Promise<void> {
  active?.dispose();
  active = null;
}

async function bootstrap(
  context: vscode.ExtensionContext,
  output: vscode.OutputChannel,
  root: vscode.WorkspaceFolder,
): Promise<void> {
  const config = vscode.workspace.getConfiguration("canopy");
  const configuredPath = config.get<string>("canopyMcpPath", "canopy-mcp");
  const refreshSeconds = config.get<number>("refreshIntervalSeconds", 30);

  const resolved = resolveCanopyMcp(configuredPath, root.uri.fsPath);
  output.appendLine(
    `[canopy] resolved canopy-mcp → ${resolved.path} (${resolved.resolvedVia})`,
  );

  const client = new CanopyClient(resolved.path, root.uri.fsPath, output);
  context.subscriptions.push({ dispose: () => void client.dispose() });

  // Probe the connection up front so we can fail loudly instead of letting
  // each tree view spew its own ENOENT toast.
  try {
    await client.ensureConnected();
    await vscode.commands.executeCommand("setContext", "canopy.state", "ok");
  } catch (err) {
    await vscode.commands.executeCommand(
      "setContext",
      "canopy.state",
      "no-mcp",
    );
    output.appendLine(
      `[canopy] ERROR: could not start canopy-mcp: ${(err as Error).message}`,
    );
    output.show(true);
    const pick = await vscode.window.showErrorMessage(
      `Canopy: could not start canopy-mcp (tried ${resolved.path}).`,
      "Install Canopy for me",
      "Open Settings",
      "Show Log",
    );
    if (pick === "Install Canopy for me") {
      await vscode.commands.executeCommand("canopy.installBackend");
    } else if (pick === "Open Settings") {
      void vscode.commands.executeCommand(
        "workbench.action.openSettings",
        "canopy.canopyMcpPath",
      );
    } else if (pick === "Show Log") {
      output.show();
    }
  }

  const status = new StatusBarManager(client);
  context.subscriptions.push(status);

  const features = new FeaturesProvider(client, () => status.activeFeature);
  const worktrees = new WorktreesProvider(client);
  const changes = new ChangesProvider(client, () => status.activeFeature);
  const review = new ReviewProvider(client);
  const linearIssues = new LinearIssuesProvider(client);

  const linearIssuesView = vscode.window.createTreeView("canopy.linearIssues", {
    treeDataProvider: linearIssues,
    showCollapseAll: true,
  });
  const featuresView = vscode.window.createTreeView("canopy.features", {
    treeDataProvider: features,
    showCollapseAll: true,
  });
  const worktreesView = vscode.window.createTreeView("canopy.worktrees", {
    treeDataProvider: worktrees,
    showCollapseAll: true,
  });
  const changesView = vscode.window.createTreeView("canopy.changes", {
    treeDataProvider: changes,
    showCollapseAll: true,
  });
  const reviewView = vscode.window.createTreeView("canopy.review", {
    treeDataProvider: review,
  });
  context.subscriptions.push(
    linearIssuesView,
    featuresView,
    worktreesView,
    changesView,
    reviewView,
  );

  const refresh = async () => {
    try {
      await status.refresh();
    } catch (err) {
      const stack = err instanceof Error ? err.stack ?? err.message : String(err);
      output.appendLine(`[canopy] status.refresh threw:\n${stack}`);
    }
    features.refresh();
    worktrees.refresh();
    changes.refresh();
    review.refresh();
    linearIssues.refresh();
    void updateLinearState(client, root);
    worktreesView.description = worktrees.budgetLabel ?? "";
    featuresView.description = status.activeFeature
      ? `active: ${status.activeFeature}`
      : "";
  };

  const watchers = createWatchers(root, {
    onFeaturesChanged: () => void refresh(),
    onWorktreeChanged: () => {
      changes.refresh();
      void status.refresh();
    },
  });
  context.subscriptions.push(watchers);

  if (refreshSeconds > 0) {
    const tick = setInterval(() => void refresh(), refreshSeconds * 1000);
    context.subscriptions.push({ dispose: () => clearInterval(tick) });
  }

  active = {
    client,
    features,
    worktrees,
    changes,
    review,
    linearIssues,
    status,
    worktreesView,
    refresh,
    dispose: () => {
      void client.dispose();
    },
  };

  registerCommands(context, client, refresh);
  context.subscriptions.push(
    vscode.commands.registerCommand("canopy.retryConnect", async () => {
      output.appendLine("[canopy] retrying MCP connection");
      // Re-read the setting in case the installer just wrote a new path.
      await client.dispose();
      const latestPath = vscode.workspace
        .getConfiguration("canopy")
        .get<string>("canopyMcpPath", "canopy-mcp");
      const latest = resolveCanopyMcp(latestPath, root.uri.fsPath);
      client.updateMcpPath(latest.path);
      output.appendLine(
        `[canopy] retrying with ${latest.path} (${latest.resolvedVia})`,
      );
      try {
        await client.ensureConnected();
        await vscode.commands.executeCommand(
          "setContext",
          "canopy.state",
          "ok",
        );
        await refresh();
      } catch (err) {
        void vscode.window.showErrorMessage(
          `Canopy: still can't connect — ${(err as Error).message}`,
        );
      }
    }),
    vscode.commands.registerCommand("canopy.showLog", () => output.show()),
    vscode.commands.registerCommand("canopy.installBackend", async () => {
      const installed = await runInstallBackend(output);
      if (installed) {
        await vscode.commands.executeCommand("canopy.retryConnect");
      }
    }),

    vscode.commands.registerCommand(
      "canopy.createFeatureFromIssue",
      async (issue?: LinearIssue) => {
        if (!issue || typeof issue !== "object" || !issue.identifier) {
          void vscode.window.showInformationMessage(
            "Canopy: open the Linear Issues panel and click an issue to start a feature from it.",
          );
          return;
        }
        const created = await runCreateFeatureFromIssue(client, issue);
        if (created) {
          await refresh();
          DashboardPanel.show(context, client, created);
        }
      },
    ),

    vscode.commands.registerCommand(
      "canopy.startWorkflowWithClaude",
      async (arg?: unknown) => {
        const name = coerceFeatureName(arg) ?? (await pickFeature(client));
        if (!name) return;
        try {
          const payload = await fetchDashboardPayload(client, name);
          await launchClaudeWorkflow(payload);
        } catch (err) {
          void vscode.window.showErrorMessage(
            `Canopy: couldn't launch Claude workflow — ${(err as Error).message}`,
          );
        }
      },
    ),

    vscode.commands.registerCommand("canopy.configureLinear", async () => {
      const apiKey = await vscode.window.showInputBox({
        title: "Connect Linear",
        prompt: "Paste your Linear API key (lin_api_…). Get one at linear.app/settings/api",
        password: true,
        ignoreFocusOut: true,
        validateInput: (v) =>
          v && v.trim().length > 10 ? null : "Looks too short to be an API key",
      });
      if (!apiKey) return;

      const mcpsPath = vscode.Uri.joinPath(root.uri, ".canopy", "mcps.json");
      let existing: Record<string, unknown> = {};
      try {
        const buf = await vscode.workspace.fs.readFile(mcpsPath);
        existing = JSON.parse(new TextDecoder().decode(buf));
      } catch {
        // no file yet — fine
      }
      existing.linear = {
        command: "npx",
        args: ["-y", "linear-mcp-server"],
        env: { LINEAR_API_KEY: apiKey.trim() },
      };
      await vscode.workspace.fs.writeFile(
        mcpsPath,
        new TextEncoder().encode(JSON.stringify(existing, null, 2) + "\n"),
      );
      void vscode.window.showInformationMessage(
        "Canopy: Linear connected. Refreshing issues…",
      );
      await refresh();
    }),

    vscode.commands.registerCommand("canopy.openMcpsConfig", async () => {
      const mcpsPath = vscode.Uri.joinPath(
        root.uri,
        ".canopy",
        "mcps.json",
      );
      const doc = await vscode.workspace.openTextDocument(mcpsPath).then(
        (d) => d,
        async () => {
          // File doesn't exist — create a stub the user can fill in.
          const stub = JSON.stringify(
            {
              linear: {
                command: "npx",
                args: ["-y", "linear-mcp-server"],
                env: { LINEAR_API_KEY: "lin_api_..." },
              },
            },
            null,
            2,
          );
          await vscode.workspace.fs.writeFile(
            mcpsPath,
            new TextEncoder().encode(stub + "\n"),
          );
          return vscode.workspace.openTextDocument(mcpsPath);
        },
      );
      await vscode.window.showTextDocument(doc);
    }),

    vscode.commands.registerCommand("canopy.reinitDryRun", async () => {
      try {
        const result = await client.workspaceReinit({ dry_run: true });
        const doc = await vscode.workspace.openTextDocument({
          content: result.toml,
          language: "toml",
        });
        await vscode.window.showTextDocument(doc, { preview: true });
        void vscode.window.showInformationMessage(
          `Canopy: detected ${result.repos.length} repo${result.repos.length === 1 ? "" : "s"}, skipped ${result.skipped.length}. Not written.`,
        );
      } catch (err) {
        void vscode.window.showErrorMessage(
          `Canopy reinit preview failed: ${(err as Error).message}`,
        );
      }
    }),

    vscode.commands.registerCommand("canopy.reinit", async () => {
      const choice = await vscode.window.showWarningMessage(
        "Force reinit Canopy workspace?\n\nThis rescans repos + worktrees and OVERWRITES canopy.toml. Feature metadata in .canopy/features.json is untouched.",
        { modal: true },
        "Reinit",
        "Preview first",
      );
      if (!choice) return;
      if (choice === "Preview first") {
        await vscode.commands.executeCommand("canopy.reinitDryRun");
        return;
      }
      try {
        const result = await client.workspaceReinit();
        const repoCount = Array.isArray(result?.repos) ? result.repos.length : 0;
        const skippedCount = Array.isArray(result?.skipped)
          ? result.skipped.length
          : 0;
        const rootPath = result?.root ?? root.uri.fsPath;
        output.appendLine(
          `[canopy] reinit wrote ${repoCount} repos to ${rootPath}/canopy.toml (skipped ${skippedCount})`,
        );
        void vscode.window.showInformationMessage(
          `Canopy: reinit complete — ${repoCount} repo${repoCount === 1 ? "" : "s"} recorded.`,
        );
        try {
          await refresh();
        } catch (refreshErr) {
          const msg = refreshErr instanceof Error ? refreshErr.stack ?? refreshErr.message : String(refreshErr);
          output.appendLine(`[canopy] refresh failed after reinit:\n${msg}`);
          output.show(true);
          void vscode.window.showErrorMessage(
            `Canopy: reinit succeeded but refresh threw (${(refreshErr as Error).message}). See Output panel for stack.`,
          );
        }
      } catch (err) {
        void vscode.window.showErrorMessage(
          `Canopy reinit failed: ${(err as Error).message}`,
        );
      }
    }),
  );
  await refresh();
}

function registerInitCommand(
  context: vscode.ExtensionContext,
  output: vscode.OutputChannel,
): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("canopy.init", () => runSetupWizard(output)),
  );
}

function registerCommands(
  context: vscode.ExtensionContext,
  client: CanopyClient,
  refresh: () => Promise<void>,
): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("canopy.refresh", () => void refresh()),

    vscode.commands.registerCommand("canopy.createFeature", async () => {
      const created = await runCreateFeature(client);
      if (created) {
        await refresh();
        DashboardPanel.show(context, client, created);
      }
    }),

    vscode.commands.registerCommand(
      "canopy.openDashboard",
      async (arg?: unknown) => {
        const name = coerceFeatureName(arg) ?? (await pickFeature(client));
        if (!name) return;
        DashboardPanel.show(context, client, name);
      },
    ),

    vscode.commands.registerCommand("canopy.openDashboardForActive", async () => {
      const ctx = await client.workspaceContext().catch(() => null);
      const name = ctx?.feature ?? (await pickFeature(client));
      if (!name) return;
      DashboardPanel.show(context, client, name);
    }),

    vscode.commands.registerCommand("canopy.switchFeature", async (arg?: unknown) => {
      const name = coerceFeatureName(arg) ?? (await pickFeature(client));
      if (!name) return;
      try {
        await client.featureSwitch(name);
        void vscode.window.showInformationMessage(`Canopy: switched to ${name}`);
        await refresh();
      } catch (err) {
        void vscode.window.showErrorMessage(
          `Canopy: switch failed — ${(err as Error).message}`,
        );
      }
    }),

    vscode.commands.registerCommand("canopy.openInIde", async (arg?: unknown) => {
      const name = coerceFeatureName(arg) ?? (await pickFeature(client));
      if (!name) return;
      try {
        const paths = await client.featurePaths(name);
        const entries = Object.entries(paths);
        if (!entries.length) return;
        for (const [, p] of entries) {
          await vscode.commands.executeCommand(
            "vscode.openFolder",
            vscode.Uri.file(p),
            { forceNewWindow: true },
          );
        }
      } catch (err) {
        void vscode.window.showErrorMessage(
          `Canopy: open failed — ${(err as Error).message}`,
        );
      }
    }),

    vscode.commands.registerCommand("canopy.preflight", async () => {
      try {
        const result = await client.preflight();
        const msg = result.all_passed
          ? "Canopy preflight: all repos passed"
          : "Canopy preflight: see Output for failures";
        void vscode.window.showInformationMessage(msg);
        await refresh();
      } catch (err) {
        void vscode.window.showErrorMessage(
          `Canopy preflight: ${(err as Error).message}`,
        );
      }
    }),

    vscode.commands.registerCommand("canopy.sync", async () => {
      try {
        const result = await client.sync("rebase");
        const failed = Object.entries(result.results).filter(
          ([, v]) => v !== "ok",
        );
        if (failed.length) {
          void vscode.window.showWarningMessage(
            `Canopy sync: ${failed.length} repo${failed.length === 1 ? "" : "s"} failed`,
          );
        } else {
          void vscode.window.showInformationMessage("Canopy: all repos synced");
        }
        await refresh();
      } catch (err) {
        void vscode.window.showErrorMessage(
          `Canopy sync: ${(err as Error).message}`,
        );
      }
    }),

    vscode.commands.registerCommand("canopy.featureDone", async (arg?: unknown) => {
      const name = coerceFeatureName(arg) ?? (await pickFeature(client));
      if (!name) return;
      const choice = await vscode.window.showWarningMessage(
        `Mark ${name} as done? This removes its worktrees and deletes its branches.`,
        { modal: true },
        "Done",
        "Force (discard dirty changes)",
      );
      if (!choice) return;
      try {
        await client.featureDone(name, choice === "Force (discard dirty changes)");
        void vscode.window.showInformationMessage(`Canopy: archived ${name}`);
        await refresh();
      } catch (err) {
        void vscode.window.showErrorMessage(
          `Canopy: done failed — ${(err as Error).message}`,
        );
      }
    }),
  );
}

async function pickFeature(client: CanopyClient): Promise<string | null> {
  try {
    const lanes = await client.featureList();
    if (!lanes.length) {
      void vscode.window.showInformationMessage("Canopy: no features yet");
      return null;
    }
    const choice = await vscode.window.showQuickPick(
      lanes.map((l) => ({
        label: l.name,
        description: l.linear_issue ?? "",
        detail: `${l.repos.join(", ")} · ${l.status}`,
      })),
      { placeHolder: "Pick a feature" },
    );
    return choice?.label ?? null;
  } catch (err) {
    void vscode.window.showErrorMessage(
      `Canopy: ${(err as Error).message}`,
    );
    return null;
  }
}

/**
 * Tree-view commands receive different argument shapes depending on how they
 * were triggered: a string when our own `item.command.arguments` fires on
 * click, but the TreeDataProvider node itself when invoked from the
 * right-click context menu. Extract a feature name from either shape.
 */
function coerceFeatureName(arg: unknown): string | undefined {
  if (typeof arg === "string" && arg) return arg;
  if (arg && typeof arg === "object") {
    const obj = arg as {
      kind?: unknown;
      lane?: { name?: unknown };
      featureName?: unknown;
    };
    if (obj.kind === "feature" && obj.lane && typeof obj.lane.name === "string") {
      return obj.lane.name;
    }
    if (typeof obj.featureName === "string") return obj.featureName;
  }
  return undefined;
}

async function updateLinearState(
  client: CanopyClient,
  root: vscode.WorkspaceFolder,
): Promise<void> {
  const configured = await hasLinearConfig(root);
  if (!configured) {
    await vscode.commands.executeCommand(
      "setContext",
      "canopy.linearState",
      "not-configured",
    );
    return;
  }
  try {
    const issues = await client.linearMyIssues(1);
    await vscode.commands.executeCommand(
      "setContext",
      "canopy.linearState",
      issues.length > 0 ? "ok" : "empty",
    );
  } catch {
    await vscode.commands.executeCommand(
      "setContext",
      "canopy.linearState",
      "empty",
    );
  }
}

async function hasLinearConfig(root: vscode.WorkspaceFolder): Promise<boolean> {
  // Precedence mirrors backend _load_mcp_configs: canopy-specific wins,
  // then the shared .mcp.json (Claude Code convention).
  const canopyPath = vscode.Uri.joinPath(root.uri, ".canopy", "mcps.json");
  try {
    const buf = await vscode.workspace.fs.readFile(canopyPath);
    const parsed = JSON.parse(new TextDecoder().decode(buf));
    if (parsed && typeof parsed === "object" && parsed.linear) return true;
  } catch {
    // fall through to .mcp.json
  }

  const sharedPath = vscode.Uri.joinPath(root.uri, ".mcp.json");
  try {
    const buf = await vscode.workspace.fs.readFile(sharedPath);
    const parsed = JSON.parse(new TextDecoder().decode(buf));
    const servers = parsed?.mcpServers;
    return Boolean(
      servers && typeof servers === "object" && servers.linear,
    );
  } catch {
    return false;
  }
}

function findCanopyRoot(): vscode.WorkspaceFolder | null {
  const folders = vscode.workspace.workspaceFolders ?? [];
  for (const f of folders) {
    if (containsCanopyToml(f.uri.fsPath)) return f;
  }
  return null;
}

function containsCanopyToml(dir: string): boolean {
  let current = dir;
  for (let i = 0; i < 6; i++) {
    if (fs.existsSync(path.join(current, "canopy.toml"))) return true;
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return false;
}
