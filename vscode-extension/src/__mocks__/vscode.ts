/**
 * Stub of the `vscode` module for jest tests.
 *
 * Real extension code imports `vscode` at the top of every file; tests run
 * outside the editor and have no real `vscode` module. This file fills in
 * the small subset of the API our tests touch and lets the rest fall back
 * to Jest mock functions so missing methods produce a clean error rather
 * than a confusing "module not found".
 *
 * Add new entries as tests start exercising more of the API. Don't try to
 * be exhaustive — the goal is "tests run", not "shadow the entire VSCode
 * surface".
 */

const noop = () => {};

export const window = {
  showInformationMessage: jest.fn(),
  showWarningMessage: jest.fn(),
  showErrorMessage: jest.fn(),
  createOutputChannel: jest.fn(() => ({
    appendLine: noop,
    append: noop,
    show: noop,
    clear: noop,
    dispose: noop,
  })),
  createStatusBarItem: jest.fn(() => ({
    text: "",
    tooltip: "",
    command: undefined,
    show: noop,
    hide: noop,
    dispose: noop,
  })),
  registerTreeDataProvider: jest.fn(),
};

export const workspace = {
  getConfiguration: jest.fn(() => ({
    get: jest.fn(),
    update: jest.fn(),
  })),
  workspaceFolders: undefined as unknown[] | undefined,
  onDidChangeConfiguration: jest.fn(() => ({ dispose: noop })),
  createFileSystemWatcher: jest.fn(() => ({
    onDidChange: jest.fn(() => ({ dispose: noop })),
    onDidCreate: jest.fn(() => ({ dispose: noop })),
    onDidDelete: jest.fn(() => ({ dispose: noop })),
    dispose: noop,
  })),
};

export const commands = {
  registerCommand: jest.fn(() => ({ dispose: noop })),
  executeCommand: jest.fn(),
};

export class EventEmitter<T = unknown> {
  event = jest.fn() as unknown as (listener: (e: T) => void) => { dispose: () => void };
  fire(_data: T): void {}
  dispose(): void {}
}

export const StatusBarAlignment = { Left: 1, Right: 2 } as const;

export class TreeItem {
  constructor(public label: string, public collapsibleState?: number) {}
}

export const TreeItemCollapsibleState = { None: 0, Collapsed: 1, Expanded: 2 } as const;

export const Uri = {
  file: (p: string) => ({ fsPath: p, scheme: "file", path: p }),
  parse: (s: string) => ({ fsPath: s, scheme: "file", path: s }),
};

export const ThemeIcon = class {
  constructor(public id: string) {}
};

export const RelativePattern = class {
  constructor(public base: string, public pattern: string) {}
};

// Default export so `import vscode from "vscode"` also works.
export default {
  window,
  workspace,
  commands,
  EventEmitter,
  StatusBarAlignment,
  TreeItem,
  TreeItemCollapsibleState,
  Uri,
  ThemeIcon,
  RelativePattern,
};
