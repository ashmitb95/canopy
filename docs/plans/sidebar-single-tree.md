# Canopy Sidebar — Collapse to Single Tree (Option A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 5 separate Canopy tree views (Linear Issues, Features, Worktrees, Changes, Review Readiness) with a single unified "Canopy" tree containing three sections: ACTIVE (expandable to per-repo rows), FEATURES (with status pills), and LINEAR INBOX (collapsed mini-section).

**Architecture:** One `CanopyTreeProvider` returning polymorphic `CanopyNode` types tagged by `kind` (`section` | `active` | `active-repo` | `feature` | `feature-repo` | `linear-issue`). Each top-level section is a TreeItem; expansion produces typed children. The provider replaces all 5 existing providers; their files are deleted. Action commands (`canopy.openDashboard`, `canopy.switchFeature`, etc.) re-bind to context values on the new view ID.

**Tech Stack:** TypeScript, VS Code Extension API (`TreeDataProvider`, `TreeItem`, `EventEmitter`), `esbuild` bundle, packaged as `.vsix` via `@vscode/vsce`.

**Working directory:** `/Users/ashmit/projects/canopy/vscode-extension/`

**Why this is needed:** The user reported the existing 5-tree sidebar feels "redundant" and "gives me very little as actionable" because the dashboard + cockpit panels already cover the detail. The sidebar's unique job is (1) always-visible state, (2) launcher / index, (3) glanceable status — none of which need 5 trees.

---

## Pre-flight: Establish baseline

- [ ] **Step 0.1: Read the survey report** below before touching any code.

```
Five existing providers (vscode-extension/src/views/):
- featuresProvider.ts (229L) — FeaturesProvider(client, getActiveFeature)
  Returns FeatureNode → RepoUnderFeatureNode children
  contextValue: "feature" / "feature.repo"
  Exposes: client.featureList, workspace_status, .canopy/worktrees scan

- linearIssuesProvider.ts (118L) — LinearIssuesProvider(client)
  Returns StateGroupNode → IssueNode children
  contextValue: "linear.group" / "linear.issue"
  Exposes: client.linearMyIssues(50), groups by state ("Todo", "In Progress")

- worktreesProvider.ts (105L) — WorktreesProvider(client)
  Returns WorktreeFeatureNode → WorktreeRepoNode children
  contextValue: "worktree.feature" / "worktree.repo" (no menus wired)
  Exposes: client.worktreeInfo, client.workspaceConfig
  Caches: budgetLabel (used by featuresView.description)

- changesProvider.ts (174L) — ChangesProvider(client, getActiveFeature)
  Returns ChangesRepoNode → ChangeFileNode children
  contextValue: "changes.repo" / "changes.file" (no menus wired)
  Only renders when an active feature exists

- reviewProvider.ts (136L) — ReviewProvider(client)
  Returns ReviewNode (leaf, no expansion)
  contextValue: "review.row" (no menus wired)
  Async per-row fetch via reviewStatus + reviewComments + featureMergeReadiness

extension.ts:160-260 wires all 5 in order, single refresh() fan-out.

package.json contributes.views.canopy:
- canopy.linearIssues  (when canopy.state == 'ok')
- canopy.features      (always visible)
- canopy.worktrees     (when canopy.state == 'ok')
- canopy.changes       (when canopy.state == 'ok')
- canopy.review        (when canopy.state == 'ok')

viewsWelcome owners:
- canopy.features:    no-workspace / no-mcp / loading
- canopy.linearIssues: not-configured / empty

Title-bar menus on canopy.features:
- canopy.openCockpit (nav@0)
- canopy.openNewFeature (nav@1)
- canopy.refresh (nav@2 — applied to ALL 5 views currently)
- canopy.reinit (9_danger@1)
- canopy.reinitDryRun (9_danger@2)

view/item/context menus:
- viewItem == "feature":      openDashboard, switchFeature, openInIde, featureDone
- viewItem == "linear.issue": createFeatureFromIssue
```

- [ ] **Step 0.2: Confirm baseline builds**

```bash
cd /Users/ashmit/projects/canopy/vscode-extension
npx tsc --noEmit
npm run build
```
Expected: both clean, dist/extension.js ≈ 442 KB.

---

## Task 1: Add the new unified view to package.json

**Files:**
- Modify: `vscode-extension/package.json` — `contributes.views.canopy` section

- [ ] **Step 1.1: Replace the 5 view entries with one**

Find the `"views": { "canopy": [...]` block (~lines 41-80). Replace the 5 entries with this single entry:

```json
"views": {
  "canopy": [
    {
      "id": "canopy.tree",
      "name": "Canopy",
      "icon": "media/canopy-icon.svg",
      "contextualTitle": "Canopy"
    }
  ]
},
```

Note: no `when` clause — the unified view is always visible. State (no-workspace / no-mcp / loading / ok) is communicated via `viewsWelcome`.

- [ ] **Step 1.2: Update viewsWelcome `view` references**

Find `"viewsWelcome": [...]`. Every entry currently targets `canopy.features` or `canopy.linearIssues`. Change all 5 entries to target `canopy.tree`. Also drop the linearIssues-specific entries (`linearState == 'not-configured'` and `linearState == 'empty'`) — Linear status will be rendered inside the tree itself, not as a viewsWelcome takeover.

The final `viewsWelcome` array should contain exactly 3 entries, all targeting `view: "canopy.tree"`:

```json
"viewsWelcome": [
  {
    "view": "canopy.tree",
    "when": "canopy.state == 'no-workspace'",
    "contents": "No Canopy workspace detected.\n\nA workspace is a directory containing a `canopy.toml` file.\n\n[Initialize Canopy here](command:canopy.init)\n\nLearn more about [Canopy](https://github.com/ashmitb95/canopy)."
  },
  {
    "view": "canopy.tree",
    "when": "canopy.state == 'no-mcp'",
    "contents": "Canopy detected a workspace, but can't start `canopy-mcp`.\n\n[Install Canopy for me](command:canopy.installBackend)\n\nOr wire up an existing install:\n\n[Set canopy-mcp Path](command:workbench.action.openSettings?%22canopy.canopyMcpPath%22)\n\n[Retry](command:canopy.retryConnect)\n\n[Show Log](command:canopy.showLog)"
  },
  {
    "view": "canopy.tree",
    "when": "canopy.state == 'loading'",
    "contents": "Starting canopy-mcp…"
  }
]
```

- [ ] **Step 1.3: Update title-bar menus to single view ID**

Find `"menus": { "view/title": [...]`. Replace every `"view == canopy.features"` with `"view == canopy.tree"`. Drop the multi-view OR clause on `canopy.refresh`. Keep only these 4 commands on the title bar (drop `canopy.reinitDryRun` from title bar — keep it command-palette-only since it's rarely needed):

```json
"view/title": [
  {
    "command": "canopy.openCockpit",
    "when": "view == canopy.tree",
    "group": "navigation@0"
  },
  {
    "command": "canopy.openNewFeature",
    "when": "view == canopy.tree",
    "group": "navigation@1"
  },
  {
    "command": "canopy.refresh",
    "when": "view == canopy.tree",
    "group": "navigation@2"
  },
  {
    "command": "canopy.reinit",
    "when": "view == canopy.tree",
    "group": "9_danger@1"
  }
]
```

- [ ] **Step 1.4: Update view/item/context menus**

Find `"view/item/context": [...]`. Replace `"view == canopy.features"` with `"view == canopy.tree"` everywhere. Replace `"view == canopy.linearIssues"` with `"view == canopy.tree"` for the createFeatureFromIssue entry. The contextValue checks (`viewItem == feature`, `viewItem == linear.issue`, etc.) stay the same.

Final block:

```json
"view/item/context": [
  {
    "command": "canopy.openDashboard",
    "when": "view == canopy.tree && viewItem == feature",
    "group": "1_open@1"
  },
  {
    "command": "canopy.switchFeature",
    "when": "view == canopy.tree && viewItem == feature",
    "group": "1_open@2"
  },
  {
    "command": "canopy.openInIde",
    "when": "view == canopy.tree && viewItem == feature",
    "group": "1_open@3"
  },
  {
    "command": "canopy.featureDone",
    "when": "view == canopy.tree && viewItem == feature",
    "group": "9_destructive@1"
  },
  {
    "command": "canopy.createFeatureFromIssue",
    "when": "view == canopy.tree && viewItem == linear.issue",
    "group": "1_open@1"
  }
]
```

- [ ] **Step 1.5: Verify package.json parses**

```bash
node -e "JSON.parse(require('fs').readFileSync('package.json','utf8')); console.log('ok')"
```
Expected output: `ok`

- [ ] **Step 1.6: Commit**

```bash
git add package.json
git commit -m "feat(extension): collapse 5 sidebar views to single 'canopy.tree' view"
```

---

## Task 2: Create the unified tree provider

**Files:**
- Create: `vscode-extension/src/views/canopyTreeProvider.ts`

- [ ] **Step 2.1: Write the new provider**

Create `vscode-extension/src/views/canopyTreeProvider.ts` with the full content below. The provider returns a single polymorphic `CanopyNode` discriminated by `kind`. Three top-level sections; each section is a TreeItem you can expand.

```typescript
import * as vscode from "vscode";

import { CanopyClient } from "../canopyClient";
import { LinearIssue } from "../types";

type Kind =
  | "section-active"
  | "section-features"
  | "section-linear"
  | "active-feature"     // the row under ACTIVE (clickable → openDashboard)
  | "active-repo"        // per-repo row under the active feature
  | "feature"            // a row under FEATURES
  | "linear-issue"       // a row under LINEAR INBOX
  | "empty";             // placeholder when a section has no children

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

  // Payload pointers — used by getChildren when expanding a parent.
  featureName?: string;
  repoName?: string;
  worktreePath?: string;
  linearIssue?: LinearIssue;
}

export class CanopyTreeProvider implements vscode.TreeDataProvider<CanopyNode> {
  private readonly _onDidChange = new vscode.EventEmitter<CanopyNode | undefined>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  // Caches populated lazily by getChildren so getTreeItem can reference
  // counts in section labels without re-fetching.
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
      // Root: three sections.
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
    const repoCount = lane.repos.length;
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
```

- [ ] **Step 2.2: Type-check the new file in isolation**

```bash
cd /Users/ashmit/projects/canopy/vscode-extension
npx tsc --noEmit
```
Expected: zero errors.

- [ ] **Step 2.3: Commit**

```bash
git add src/views/canopyTreeProvider.ts
git commit -m "feat(extension): add unified CanopyTreeProvider (sections: active / features / linear-inbox)"
```

---

## Task 3: Wire the new provider in extension.ts

**Files:**
- Modify: `vscode-extension/src/extension.ts`

- [ ] **Step 3.1: Update imports**

In extension.ts top imports (~lines 13-17), replace the five provider imports with the new one:

```typescript
// REPLACE these 5 imports:
//   import { ChangesProvider } from "./views/changesProvider";
//   import { FeaturesProvider } from "./views/featuresProvider";
//   import { LinearIssuesProvider } from "./views/linearIssuesProvider";
//   import { ReviewProvider } from "./views/reviewProvider";
//   import { WorktreesProvider } from "./views/worktreesProvider";
// WITH this:
import { CanopyTreeProvider } from "./views/canopyTreeProvider";
```

- [ ] **Step 3.2: Slim the `Active` interface**

Find the `interface Active { ... }` block near the top (~lines 28-39). Replace its `features`/`worktrees`/`changes`/`review`/`linearIssues`/`worktreesView` fields with a single `tree` field:

```typescript
interface Active {
  client: CanopyClient;
  tree: CanopyTreeProvider;
  status: StatusBarManager;
  refresh: () => Promise<void>;
  dispose: () => void;
}
```

- [ ] **Step 3.3: Replace stub view registrations**

Find the block creating `EmptyTreeProvider` stubs (~lines 99-117). Replace those 5 stubs with a single stub for `canopy.tree`:

```typescript
const stubProvider = new EmptyTreeProvider();
const stubTree = vscode.window.createTreeView("canopy.tree", {
  treeDataProvider: stubProvider,
});
const stubSubs: vscode.Disposable[] = [stubTree];
```

- [ ] **Step 3.4: Replace the real provider wiring**

Find the block creating the 5 real providers (~lines 161-195). Replace it with:

```typescript
const status = new StatusBarManager(client);
context.subscriptions.push(status);

const tree = new CanopyTreeProvider(client, () => status.activeFeature);
const treeView = vscode.window.createTreeView("canopy.tree", {
  treeDataProvider: tree,
  showCollapseAll: true,
});
context.subscriptions.push(treeView);
```

- [ ] **Step 3.5: Simplify the refresh fan-out**

Find the `const refresh = async () => { ... }` block (~lines 197-214). Replace with:

```typescript
const refresh = async () => {
  try {
    await status.refresh();
  } catch (err) {
    const stack = err instanceof Error ? err.stack ?? err.message : String(err);
    output.appendLine(`[canopy] status.refresh threw:\n${stack}`);
  }
  tree.refresh();
  void updateLinearState(client, root);
  treeView.description = status.activeFeature
    ? `active: ${status.activeFeature}`
    : "";
};
```

- [ ] **Step 3.6: Update the `Active` instance shape**

Find the block assigning `active = { ... }` (~lines 241-254). Replace with:

```typescript
active = {
  client,
  tree,
  status,
  refresh,
  dispose: () => {
    void client.dispose();
  },
};
```

- [ ] **Step 3.7: Update watcher callbacks**

Find `createWatchers(root, { ... })` (~line 216). The callbacks currently call `changes.refresh()`, `features.refresh()`, etc. Simplify each callback to just `tree.refresh()`:

```typescript
const watchers = createWatchers(root, {
  onFeaturesChanged: () => {
    tree.refresh();
    CockpitPanel.refreshIfOpen();
    DashboardPanel.invalidateAll();
  },
  onWorktreeChanged: () => {
    tree.refresh();
    void status.refresh();
    CockpitPanel.refreshIfOpen();
    DashboardPanel.invalidateAll();
  },
  onStateFilesChanged: () => {
    CockpitPanel.refreshIfOpen();
    DashboardPanel.invalidateAll();
  },
});
```

- [ ] **Step 3.8: Type-check**

```bash
npx tsc --noEmit
```
Expected: zero errors. If you see errors about unused imports for the deleted providers, the imports were missed in Step 3.1 — go back and remove them.

- [ ] **Step 3.9: Commit**

```bash
git add src/extension.ts
git commit -m "feat(extension): wire CanopyTreeProvider; remove 5 separate tree views"
```

---

## Task 4: Delete the old provider files

**Files:**
- Delete: `vscode-extension/src/views/changesProvider.ts`
- Delete: `vscode-extension/src/views/featuresProvider.ts`
- Delete: `vscode-extension/src/views/linearIssuesProvider.ts`
- Delete: `vscode-extension/src/views/reviewProvider.ts`
- Delete: `vscode-extension/src/views/worktreesProvider.ts`

- [ ] **Step 4.1: Delete and confirm no references remain**

```bash
cd /Users/ashmit/projects/canopy/vscode-extension
rm src/views/changesProvider.ts src/views/featuresProvider.ts src/views/linearIssuesProvider.ts src/views/reviewProvider.ts src/views/worktreesProvider.ts
grep -rn "ChangesProvider\|FeaturesProvider\|LinearIssuesProvider\|ReviewProvider\|WorktreesProvider" src/
```
Expected: only matches in `canopyTreeProvider.ts` (none — that file uses `CanopyTreeProvider`). If any matches in `src/` outside of new provider, fix them.

- [ ] **Step 4.2: Type-check**

```bash
npx tsc --noEmit
```
Expected: zero errors.

- [ ] **Step 4.3: Commit**

```bash
git add -A src/views/
git commit -m "chore(extension): delete superseded per-domain tree providers"
```

---

## Task 5: Bump version, build, package, install

- [ ] **Step 5.1: Bump version**

Edit `package.json`: change `"version": "0.3.3"` to `"version": "0.4.0"` (minor bump — sidebar restructure is user-visible breaking UX change).

- [ ] **Step 5.2: Build + package**

```bash
cd /Users/ashmit/projects/canopy/vscode-extension
npm run build
npm run package
```
Expected: dist/extension.js around 440 KB (slightly smaller from removing 5 providers); `canopy-0.4.0.vsix` created.

- [ ] **Step 5.3: Install**

```bash
code --install-extension canopy-0.4.0.vsix --force
```
Expected: "Extension 'canopy-0.4.0.vsix' was successfully installed."

- [ ] **Step 5.4: Reload VS Code window and smoke test**

In VS Code: `Cmd+Shift+P` → `Developer: Reload Window`. Then open `~/projects/canopy-test/` (the integration workspace).

Verify each of these manually:
- [ ] Single "Canopy" tree appears in the activity bar (no 5 separate sections).
- [ ] Three top-level rows: ACTIVE, FEATURES, LINEAR INBOX.
- [ ] LINEAR INBOX is collapsed by default; expanding shows todo issues.
- [ ] ACTIVE shows the canonical feature with description like `SIN-6 · ↑1 · 1 dirty`; expanding shows per-repo rows.
- [ ] Clicking the active feature opens the dashboard.
- [ ] Clicking a per-repo row under ACTIVE opens that worktree folder (only if `worktree_path` exists).
- [ ] FEATURES lists all non-active features with `N repos` description.
- [ ] Right-click on a feature row shows: Open Dashboard, Switch to Feature, Open Worktrees in New Window, Mark Feature Done.
- [ ] Right-click on a Linear issue shows: Start Feature from Linear Issue.
- [ ] Title-bar buttons: Cockpit, New Feature, Refresh, (overflow) Reinit.
- [ ] No stale "Worktrees" / "Changes" / "Review Readiness" / "Linear Issues" trees visible.

- [ ] **Step 5.5: Commit**

```bash
git add package.json canopy-0.4.0.vsix
git commit -m "chore(extension): release 0.4.0 — single-tree sidebar"
```

---

## Self-review checklist (run before declaring complete)

- [ ] Search the diff: any reference to `FeaturesProvider`, `WorktreesProvider`, `LinearIssuesProvider`, `ChangesProvider`, `ReviewProvider`, `canopy.features`, `canopy.worktrees`, `canopy.changes`, `canopy.review`, `canopy.linearIssues` outside the changelog/readme? If yes, remove.
- [ ] viewsWelcome no longer references removed view IDs.
- [ ] All 4 right-click feature commands still appear in the menu (Open Dashboard, Switch to Feature, Open Worktrees in New Window, Mark Feature Done) after the wiring change.
- [ ] Title-bar action buttons (Cockpit, New Feature, Refresh) all visible on the new view.
- [ ] Smoke test was actually performed in VS Code (not skipped).

---

## Rollback plan

If the smoke test reveals issues that block adoption:

```bash
cd /Users/ashmit/projects/canopy/vscode-extension
git revert HEAD~5..HEAD  # all 5 commits from this plan
npm run build && npm run package
code --install-extension canopy-0.3.3.vsix --force  # reinstall last known good
```
