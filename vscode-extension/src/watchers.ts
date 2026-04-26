import * as vscode from "vscode";

interface WatcherCallbacks {
  onFeaturesChanged: () => void;
  onWorktreeChanged: () => void;
  /**
   * Wave 2.9 state files — fired when the active-feature pointer
   * changes (canopy switch), when the post-checkout hook records a
   * head, or when preflight records a fresh result. Drives the
   * cockpit's auto-refresh.
   */
  onStateFilesChanged?: () => void;
}

/**
 * Debounced FileSystemWatchers covering canopy's persistent state:
 *
 *   1. `.canopy/features.json`            (300ms) → tree views + cockpit
 *   2. `.canopy/worktrees/**\/.git/{HEAD,index}` (500ms) → Changes view
 *   3. `.canopy/state/{active_feature,heads,preflight}.json` (200ms) → cockpit
 *
 * State-file changes get the tightest debounce since the cockpit's
 * "what's canonical" + "is preflight stale" displays are user-facing
 * and we want them to react quickly to a `canopy switch` from the CLI.
 */
export function createWatchers(
  workspaceRoot: vscode.WorkspaceFolder,
  cb: WatcherCallbacks,
): vscode.Disposable {
  const disposables: vscode.Disposable[] = [];

  const featuresPattern = new vscode.RelativePattern(
    workspaceRoot,
    ".canopy/features.json",
  );
  const featuresWatcher = vscode.workspace.createFileSystemWatcher(featuresPattern);
  const fireFeatures = debounce(cb.onFeaturesChanged, 300);
  featuresWatcher.onDidCreate(fireFeatures);
  featuresWatcher.onDidChange(fireFeatures);
  featuresWatcher.onDidDelete(fireFeatures);
  disposables.push(featuresWatcher);

  const worktreePattern = new vscode.RelativePattern(
    workspaceRoot,
    ".canopy/worktrees/**/.git/{HEAD,index}",
  );
  const worktreeWatcher = vscode.workspace.createFileSystemWatcher(worktreePattern);
  const fireWorktree = debounce(cb.onWorktreeChanged, 500);
  worktreeWatcher.onDidCreate(fireWorktree);
  worktreeWatcher.onDidChange(fireWorktree);
  worktreeWatcher.onDidDelete(fireWorktree);
  disposables.push(worktreeWatcher);

  if (cb.onStateFilesChanged) {
    const statePattern = new vscode.RelativePattern(
      workspaceRoot,
      ".canopy/state/{active_feature,heads,preflight}.json",
    );
    const stateWatcher = vscode.workspace.createFileSystemWatcher(statePattern);
    const fireState = debounce(cb.onStateFilesChanged, 200);
    stateWatcher.onDidCreate(fireState);
    stateWatcher.onDidChange(fireState);
    stateWatcher.onDidDelete(fireState);
    disposables.push(stateWatcher);
  }

  return vscode.Disposable.from(...disposables);
}

function debounce<T extends (...args: unknown[]) => void>(fn: T, ms: number): T {
  let handle: NodeJS.Timeout | null = null;
  return ((...args: unknown[]) => {
    if (handle) clearTimeout(handle);
    handle = setTimeout(() => {
      handle = null;
      fn(...args);
    }, ms);
  }) as T;
}
