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

  /**
   * Promote a feature to the canonical (main) slot via the Wave 2.9
   * canonical-slot model. The previously-canonical feature evacuates to
   * a worktree (default) or hibernates with a feature-tagged stash
   * (`releaseCurrent: true`). Replaces the deleted `feature_switch`.
   *
   * UI surfaces label `releaseCurrent` as "Hibernate" — see
   * docs/agents.md vocabulary note.
   */
  switchFeature(opts: {
    feature: string;
    releaseCurrent?: boolean;
    noEvict?: boolean;
    evict?: string;
  }) {
    return this.call<{
      feature: string;
      mode: "active_rotation" | "wind_down";
      per_repo_paths: Record<string, string>;
      previously_canonical?: string;
      eviction?: { feature: string; repos: Array<{ repo: string; stashed: boolean; stash_ref?: string; removed: boolean }> };
      branches_created?: Array<{ repo: string; branch: string; base: string }>;
      activated_at: string;
      migration?: { ran: boolean; canonical_detected: string | null };
      per_repo: Array<{ repo: string; status: string; [k: string]: unknown }>;
    }>("switch", {
      feature: opts.feature,
      release_current: opts.releaseCurrent ?? false,
      no_evict: opts.noEvict ?? false,
      evict: opts.evict ?? null,
    });
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

  // ── Wave 2.9 / Wave 7 method coverage ─────────────────────────────

  /**
   * Compute feature state + suggested next actions (dashboard backend).
   * Returns the 8-state machine result. Same shape the agent reads.
   */
  featureState(feature: string) {
    return this.call<FeatureStateResult>("feature_state", { feature });
  }

  /**
   * Cross-repo PR enumeration grouped by feature lane, prioritized.
   * Each entry carries `is_canonical` + `physical_state` per the
   * canonical-slot model (Wave 2.9).
   */
  triage(opts: { author?: string; repos?: string[] } = {}) {
    return this.call<TriageResult>("triage", {
      author: opts.author ?? "@me",
      repos: opts.repos ?? null,
    });
  }

  /** Cached drift report from `.canopy/state/heads.json`. */
  drift(feature?: string) {
    return this.call<DriftResult>("drift", feature ? { feature } : {});
  }

  /** Temporally-classified PR review threads per repo. */
  githubGetPrComments(alias: string) {
    return this.call<GhCommentsResult>("github_get_pr_comments", { alias });
  }

  /** PR data per repo for an alias. */
  githubGetPr(alias: string) {
    return this.call<GhPrResult>("github_get_pr", { alias });
  }

  /** Branch HEAD / divergence / upstream per repo. */
  githubGetBranch(alias: string, repo?: string) {
    return this.call<GhBranchResult>("github_get_branch", {
      alias,
      repo: repo ?? null,
    });
  }

  /** Fetch a Linear issue by alias (issue ID or feature alias). */
  linearGetIssue(alias: string) {
    return this.call<LinearIssueResult>("linear_get_issue", { alias });
  }

  /** Run a shell command in a canopy-managed repo. */
  run(repo: string, command: string, opts: { feature?: string; timeoutSeconds?: number } = {}) {
    return this.call<RunResult>("run", {
      repo,
      command,
      feature: opts.feature ?? null,
      timeout_seconds: opts.timeoutSeconds ?? 60,
    });
  }

  // ── Stash (feature-aware) ─────────────────────────────────────────

  stashSaveFeature(feature: string, message = "", repos?: string[]) {
    return this.call<StashSaveResult>("stash_save_feature", {
      feature,
      message,
      repos: repos ?? null,
    });
  }

  stashListGrouped(feature?: string) {
    return this.call<StashListGroupedResult>(
      "stash_list_grouped",
      feature ? { feature } : {},
    );
  }

  stashPopFeature(feature: string, repos?: string[]) {
    return this.call<StashPopResult>("stash_pop_feature", {
      feature,
      repos: repos ?? null,
    });
  }
}

// ── Result type aliases (kept inline for now; promote to types.ts when stable)

export type FeatureStateResult = {
  feature: string;
  state:
    | "drifted"
    | "needs_work"
    | "in_progress"
    | "ready_to_commit"
    | "ready_to_push"
    | "awaiting_review"
    | "approved"
    | "no_prs";
  summary: {
    alignment?: { aligned: boolean; expected: Record<string, string>; actual: Record<string, string | null>; drifted_repos: string[]; missing_repos: string[]; has_worktrees?: boolean };
    dirty_repos?: string[];
    ahead_repos?: Record<string, number>;
    actionable_count?: number;
    likely_resolved_count?: number;
    review_decisions?: Record<string, string>;
    preflight?: { passed: boolean; ran_at: string; head_sha_per_repo: Record<string, string> } | null;
    [k: string]: unknown;
  };
  next_actions: Array<{
    action: string;
    args: Record<string, unknown>;
    primary?: boolean;
    label?: string;
    preview?: string;
  }>;
  warnings: Array<{ code: string; what: string; [k: string]: unknown }>;
};

export type TriageFeature = {
  feature: string;
  linear_issue: string;
  linear_url: string;
  linear_title: string;
  priority:
    | "changes_requested"
    | "review_required_with_bot_comments"
    | "review_required"
    | "approved"
    | "unknown";
  is_canonical: boolean;
  physical_state: "canonical" | "warm" | "cold" | "mixed";
  repos: Record<string, {
    pr_number: number;
    pr_url: string;
    pr_title: string;
    branch: string;
    review_decision: string;
    actionable_count: number;
    likely_resolved_count: number;
    has_actionable_bot_thread: boolean;
    physical_state: "canonical" | "warm" | "cold";
    path: string;
  }>;
};

export type TriageResult = {
  author: string;
  canonical_feature: string | null;
  features: TriageFeature[];
};

export type DriftResult = {
  features: Record<string, {
    aligned: boolean;
    expected: Record<string, string>;
    actual: Record<string, string | null>;
    drifted_repos: string[];
    missing_repos: string[];
  }>;
  source: "heads.json" | "live";
  generated_at: string;
};

export type GhCommentsResult = {
  alias: string;
  repos: Record<string, {
    actionable_threads: Array<{ id: string; path: string; line: number; body: string; author: string; author_type: string; created_at: string; url: string; reason: string }>;
    likely_resolved_threads: Array<{ id: string; path: string; line: number; body: string; author: string; created_at: string; reason: string }>;
    resolved_thread_count: number;
    latest_commit_at: string;
    review_decision: string;
  }>;
};

export type GhPrResult = {
  alias: string;
  repos: Record<string, {
    pr_number: number;
    pr_url: string;
    title: string;
    body: string;
    state: string;
    head_branch: string;
    base_branch: string;
    review_decision: string;
    mergeable: string;
    draft: boolean;
  } | null>;
};

export type GhBranchResult = {
  alias: string;
  repos: Record<string, {
    branch: string;
    exists_locally: boolean;
    head_sha?: string;
    ahead?: number;
    behind?: number;
    has_upstream?: boolean;
    pr_number?: number | null;
  }>;
};

export type LinearIssueResult = {
  alias: string;
  issue_id: string;
  title: string;
  state: string;
  url: string;
  description: string;
  raw: unknown;
};

export type RunResult = {
  exit_code: number;
  stdout: string;
  stderr: string;
  cwd: string;
  duration_ms: number;
};

export type StashSaveResult = {
  feature: string;
  repos: Array<{ repo: string; stashed: boolean; stash_ref?: string; message?: string }>;
};

export type StashListGroupedResult = {
  by_feature: Record<string, Array<{
    repo: string; ref: string; branch: string; ts: string; message: string; age_seconds?: number;
  }>>;
  untagged: Array<{ repo: string; ref: string; message: string }>;
};

export type StashPopResult = {
  feature: string;
  repos: Array<{ repo: string; popped: boolean; stash_ref?: string; reason?: string }>;
};
