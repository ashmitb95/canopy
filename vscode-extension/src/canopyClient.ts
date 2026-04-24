import * as vscode from "vscode";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

import {
  CanopyContext,
  FeatureChangesResult,
  FeatureDiff,
  FeatureLane,
  LinearIssue,
  LogEntry,
  PreflightResult,
  ReviewComments,
  ReviewStatus,
  WorkspaceConfigSettings,
  WorktreeInfo,
} from "./types";

/**
 * Thin wrapper around an MCP stdio connection to canopy-mcp.
 *
 * Holds a single persistent connection per workspace. All extension
 * features call typed methods on this client; the JSON shapes mirror
 * the docs in src/canopy/mcp/server.py.
 */
export class CanopyClient {
  private client: Client | null = null;
  private transport: StdioClientTransport | null = null;
  private connecting: Promise<void> | null = null;
  private mcpPath: string;

  constructor(
    mcpPath: string,
    private readonly canopyRoot: string,
    private readonly outputChannel: vscode.OutputChannel,
  ) {
    this.mcpPath = mcpPath;
  }

  updateMcpPath(newPath: string): void {
    this.mcpPath = newPath;
  }

  async ensureConnected(): Promise<void> {
    if (this.client) return;
    if (this.connecting) return this.connecting;
    this.connecting = this.connect().finally(() => {
      this.connecting = null;
    });
    return this.connecting;
  }

  private async connect(): Promise<void> {
    this.outputChannel.appendLine(
      `[canopy] spawning ${this.mcpPath} (CANOPY_ROOT=${this.canopyRoot})`,
    );

    const env: Record<string, string> = {};
    for (const [k, v] of Object.entries(process.env)) {
      if (typeof v === "string") env[k] = v;
    }
    env.CANOPY_ROOT = this.canopyRoot;

    this.transport = new StdioClientTransport({
      command: this.mcpPath,
      args: [],
      env,
    });

    this.client = new Client(
      { name: "canopy-vscode", version: "0.1.0" },
      { capabilities: {} },
    );

    try {
      await this.client.connect(this.transport);
      this.outputChannel.appendLine("[canopy] connected to canopy-mcp");
    } catch (err) {
      this.client = null;
      this.transport = null;
      throw err;
    }
  }

  async dispose(): Promise<void> {
    try {
      await this.client?.close();
    } catch {
      // ignore
    }
    this.client = null;
    this.transport = null;
  }

  private async call<T>(
    name: string,
    args: Record<string, unknown> = {},
  ): Promise<T> {
    await this.ensureConnected();
    if (!this.client) throw new Error("canopy-mcp client not connected");
    const result = await this.client.callTool({ name, arguments: args });

    if ((result as { isError?: boolean }).isError) {
      const text = this.extractText(result);
      throw new Error(`canopy-mcp tool '${name}' failed: ${text}`);
    }

    // MCP 2025-06 spec adds structuredContent for tools that return structured
    // data; FastMCP populates it alongside the text-block fallback. Prefer it
    // when present — otherwise fall back to JSON-parsing the text content.
    //
    // FastMCP wraps non-dict returns in `{ "result": <value> }` so the payload
    // is always an object (required by the spec). Unwrap that convention so
    // list-returning tools (feature_list, log, linear_my_issues, …) come
    // through as arrays to the caller.
    const structured = (result as { structuredContent?: unknown }).structuredContent;
    if (structured !== undefined && structured !== null) {
      if (
        typeof structured === "object" &&
        !Array.isArray(structured) &&
        Object.keys(structured as Record<string, unknown>).length === 1 &&
        "result" in (structured as Record<string, unknown>)
      ) {
        return (structured as { result: unknown }).result as T;
      }
      return structured as T;
    }

    const text = this.extractText(result);
    if (!text) {
      return {} as T;
    }
    try {
      return JSON.parse(text) as T;
    } catch {
      // FastMCP sometimes returns raw strings — wrap in an object the caller can ignore.
      return text as unknown as T;
    }
  }

  private extractText(result: unknown): string {
    if (!result || typeof result !== "object") return "";
    const blocks = (result as { content?: unknown[] }).content;
    if (!Array.isArray(blocks)) return "";
    const parts: string[] = [];
    for (const block of blocks) {
      if (!block || typeof block !== "object") continue;
      const text = (block as { text?: unknown }).text;
      if (typeof text === "string") parts.push(text);
    }
    return parts.join("");
  }

  // ── Read tools ────────────────────────────────────────────────────────

  workspaceStatus() {
    return this.call<{
      name: string;
      root: string;
      repos: Array<Record<string, unknown>>;
      active_features: string[];
    }>("workspace_status");
  }

  workspaceContext(cwd?: string) {
    return this.call<CanopyContext>("workspace_context", cwd ? { cwd } : {});
  }

  workspaceConfig() {
    return this.call<WorkspaceConfigSettings>("workspace_config");
  }

  featureList() {
    return this.call<FeatureLane[]>("feature_list");
  }

  featureStatus(name: string) {
    return this.call<FeatureLane>("feature_status", { name });
  }

  featureDiff(name: string) {
    return this.call<FeatureDiff>("feature_diff", { name });
  }

  featureChanges(name: string) {
    return this.call<FeatureChangesResult>("feature_changes", { name });
  }

  featureMergeReadiness(name: string) {
    return this.call<{ feature: string; ready: boolean; issues: string[] }>(
      "feature_merge_readiness",
      { name },
    );
  }

  featurePaths(name: string) {
    return this.call<Record<string, string>>("feature_paths", { name });
  }

  worktreeInfo() {
    return this.call<WorktreeInfo>("worktree_info");
  }

  reviewStatus(feature: string) {
    return this.call<ReviewStatus>("review_status", { feature });
  }

  reviewComments(feature: string) {
    return this.call<ReviewComments>("review_comments", { feature });
  }

  log(maxCount = 10, feature?: string) {
    return this.call<LogEntry[]>(
      "log",
      feature ? { max_count: maxCount, feature } : { max_count: maxCount },
    );
  }

  preflight(cwd?: string) {
    return this.call<PreflightResult>("preflight", cwd ? { cwd } : {});
  }

  linearMyIssues(limit = 25) {
    return this.call<LinearIssue[]>("linear_my_issues", { limit });
  }

  // ── Write tools ───────────────────────────────────────────────────────

  featureCreate(opts: {
    name: string;
    repos?: string[];
    use_worktrees?: boolean;
  }) {
    return this.call<FeatureLane & { worktree_paths?: Record<string, string> }>(
      "feature_create",
      {
        name: opts.name,
        repos: opts.repos ?? null,
        use_worktrees: opts.use_worktrees ?? false,
      },
    );
  }

  worktreeCreate(opts: {
    name: string;
    issue?: string;
    repos?: string[];
  }) {
    return this.call<
      | (FeatureLane & { worktree_paths?: Record<string, string> })
      | { error: string; message: string }
    >("worktree_create", {
      name: opts.name,
      issue: opts.issue ?? null,
      repos: opts.repos ?? null,
    });
  }

  featureSwitch(name: string) {
    return this.call<{ feature: string; repos: Record<string, unknown> }>(
      "feature_switch",
      { name },
    );
  }

  featureLinkLinear(feature: string, issue: string) {
    return this.call<FeatureLane>("feature_link_linear", { feature, issue });
  }

  featureDone(feature: string, force = false) {
    return this.call<{
      feature: string;
      worktrees_removed: Record<string, string>;
      branches_deleted: Record<string, string>;
      archived: boolean;
    }>("feature_done", { feature, force });
  }

  sync(strategy: "rebase" | "merge" = "rebase") {
    return this.call<{ results: Record<string, string> }>("sync", { strategy });
  }

  workspaceReinit(opts: { name?: string; dry_run?: boolean } = {}) {
    return this.call<{
      root: string;
      repos: Array<{
        name: string;
        path: string;
        role: string;
        lang: string;
        is_worktree: boolean;
        worktree_main: string | null;
      }>;
      skipped: string[];
      active_worktrees: Record<string, string[]>;
      toml: string;
      written: boolean;
    }>("workspace_reinit", {
      name: opts.name ?? null,
      dry_run: opts.dry_run ?? false,
    });
  }
}
