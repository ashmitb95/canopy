import * as vscode from "vscode";

interface WatcherCallbacks {
  onFeaturesChanged: () => void;
  onWorktreeChanged: () => void;
}

/**
 * Two debounced FileSystemWatchers: one on .canopy/features.json (rebuilds
 * Features + Worktrees + Review trees) and one on .canopy/worktrees/.../HEAD
 * (rebuilds Changes only — cheaper).
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
