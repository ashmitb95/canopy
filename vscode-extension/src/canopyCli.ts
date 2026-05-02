/**
 * CanopyCli — async subprocess wrapper around the `canopy` CLI.
 *
 * Replaces the per-call MCP-stdio roundtrip used by `canopyClient.ts` with
 * direct CLI invocation. The CLI is the single source of truth (the MCP
 * server is just another consumer of the same Python action layer); calling
 * it directly removes a layer of indirection and a lot of message-pump
 * overhead, particularly for read paths that the dashboard renders dozens
 * of times per session.
 *
 * Key responsibilities:
 *
 * - **Subprocess invocation** with the right cwd (CLI looks for `canopy.toml`
 *   relative to cwd, not via env var) and a fully-resolved PATH (so tools like
 *   `git` and `gh` are findable when VSCode was launched from Dock/Spotlight).
 * - **Mixed stdout handling.** Some CLI commands print human-readable Rich
 *   output before JSON, especially on error paths that exit-1. We extract
 *   the first `{` or `[` and JSON-parse from there.
 * - **BlockerError as a typed throw.** The CLI returns `{status: "blocked",
 *   code, what, fix_actions, …}` on structured failure. We throw a
 *   `CanopyBlockerError` carrying those fields so callers can `try/catch`
 *   against them naturally.
 * - **TTL cache for read paths.** Callers opt in via `cacheTtlMs`. Write
 *   operations never cache.
 *
 * This module exposes only the core `exec()` primitive plus a couple of
 * typed wrappers (`state`, `triage`) as proof-of-pattern. New panels add
 * their own wrappers as needed during the UI redesign.
 *
 * Design source: matches the pattern in
 * `AgathaCrystal/canopy@extension-rewrite:vscode-extension/src/canopyCli.ts`,
 * rewritten minimally — Phil's version ships ~30 typed methods; we'll grow
 * ours alongside the redesigned panels.
 */
import { execFile } from "node:child_process";

/** A blocker JSON returned by canopy CLI on a structured failure. */
export interface CanopyBlocker {
  status: "blocked" | "failed";
  code: string;
  what: string;
  expected?: unknown;
  actual?: unknown;
  fix_actions?: Array<{
    action: string;
    args?: Record<string, unknown>;
    safe?: boolean;
    preview?: string | null;
  }>;
  details?: Record<string, unknown>;
}

export class CanopyBlockerError extends Error {
  readonly status: CanopyBlocker["status"];
  readonly code: string;
  readonly what: string;
  readonly expected?: unknown;
  readonly actual?: unknown;
  readonly fix_actions: NonNullable<CanopyBlocker["fix_actions"]>;
  readonly details?: Record<string, unknown>;

  constructor(payload: CanopyBlocker) {
    super(`${payload.code}: ${payload.what}`);
    this.name = "CanopyBlockerError";
    this.status = payload.status;
    this.code = payload.code;
    this.what = payload.what;
    this.expected = payload.expected;
    this.actual = payload.actual;
    this.fix_actions = payload.fix_actions ?? [];
    this.details = payload.details;
  }
}

export interface ExecOptions {
  /**
   * Cache successful results for this many ms. Read-only commands only —
   * write commands MUST omit this. Cache key is the joined args. Default:
   * no caching.
   */
  cacheTtlMs?: number;
  /** Override the per-process default (60 s). */
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 60_000;
const MAX_BUFFER_BYTES = 8 * 1024 * 1024;   // 8 MB — plenty for any --json payload

interface CacheEntry {
  expiresAt: number;
  value: unknown;
}

export class CanopyCli {
  private cache = new Map<string, CacheEntry>();
  private resolvedShellPath: string | null = null;

  constructor(
    private readonly cliPath: string,
    private readonly workspaceRoot: string,
  ) {}

  /**
   * Run `canopy <args…>` in the workspace and return the parsed JSON output.
   *
   * Throws `CanopyBlockerError` if the CLI returned a structured blocker.
   * Throws `Error` for non-blocker subprocess failures (spawn, timeout,
   * malformed JSON).
   */
  async exec<T = unknown>(args: string[], opts: ExecOptions = {}): Promise<T> {
    const { cacheTtlMs, timeoutMs = DEFAULT_TIMEOUT_MS } = opts;
    const cacheKey = args.join("\0");

    if (cacheTtlMs && cacheTtlMs > 0) {
      const hit = this.cache.get(cacheKey);
      if (hit && hit.expiresAt > Date.now()) {
        return hit.value as T;
      }
    }

    const env = await this.subprocessEnv();
    const { stdout, exitCode } = await this.spawn(args, env, timeoutMs);
    const parsed = parseCanopyJson(stdout);

    if (isBlocker(parsed)) {
      throw new CanopyBlockerError(parsed);
    }
    if (exitCode !== 0) {
      // Exit non-zero with no blocker JSON — shouldn't happen in normal use,
      // but if the CLI ever fails to render a structured error, surface what
      // we got rather than swallowing it.
      throw new Error(
        `canopy ${args.join(" ")} exited ${exitCode} without a blocker payload`,
      );
    }

    if (cacheTtlMs && cacheTtlMs > 0) {
      this.cache.set(cacheKey, { expiresAt: Date.now() + cacheTtlMs, value: parsed });
    }
    return parsed as T;
  }

  /** Drop the cache. Call after any write op or on file-watcher invalidation. */
  invalidateCache(): void {
    this.cache.clear();
  }

  // ── Typed wrappers (grow as panels need them) ──────────────────────────

  /** `canopy state <feature> --json` — feature_state dashboard backend. */
  state(feature: string, opts: ExecOptions = {}): Promise<FeatureState> {
    return this.exec<FeatureState>(["state", feature, "--json"], { cacheTtlMs: 15_000, ...opts });
  }

  /** `canopy triage --json` — cross-repo PR enumeration grouped by feature. */
  triage(opts: ExecOptions = {}): Promise<TriageResult> {
    return this.exec<TriageResult>(["triage", "--json"], { cacheTtlMs: 60_000, ...opts });
  }

  // ── Internals ──────────────────────────────────────────────────────────

  private spawn(
    args: string[],
    env: NodeJS.ProcessEnv,
    timeoutMs: number,
  ): Promise<{ stdout: string; exitCode: number }> {
    return new Promise((resolve, reject) => {
      execFile(
        this.cliPath,
        args,
        {
          cwd: this.workspaceRoot,
          env,
          timeout: timeoutMs,
          maxBuffer: MAX_BUFFER_BYTES,
          encoding: "utf8",
        },
        (err, stdout, stderr) => {
          // execFile sets `err` on non-zero exit. Resolve regardless — the
          // caller decides whether the JSON payload is a blocker vs success.
          // Only reject on spawn failure (no `code`), timeout (`killed`),
          // or buffer overflow.
          if (err && (err as NodeJS.ErrnoException).code === "ENOENT") {
            return reject(new Error(`canopy CLI not found at ${this.cliPath}`));
          }
          if (err && (err as { killed?: boolean }).killed) {
            return reject(new Error(`canopy ${args.join(" ")} timed out after ${timeoutMs}ms`));
          }
          const exitCode = err && typeof (err as { code?: number }).code === "number"
            ? (err as { code: number }).code
            : 0;
          // Surface stderr as part of the error if there's no usable stdout.
          if (!stdout && stderr && exitCode !== 0) {
            return reject(new Error(`canopy ${args.join(" ")}: ${stderr.trim()}`));
          }
          resolve({ stdout, exitCode });
        },
      );
    });
  }

  /**
   * Build the subprocess env. Prepends a login-shell PATH so tools like
   * `git`, `gh`, etc. are findable when VSCode was launched from Dock/
   * Spotlight (which give the editor a minimal `/usr/bin:/bin` PATH).
   *
   * Cached after first resolution; the shell call is ~100 ms.
   */
  private async subprocessEnv(): Promise<NodeJS.ProcessEnv> {
    if (this.resolvedShellPath === null) {
      this.resolvedShellPath = await loginShellPath();
    }
    const path = this.resolvedShellPath || process.env.PATH || "";
    return {
      ...process.env,
      PATH: path,
      // CANOPY_ROOT is informational for the CLI; cwd is what actually picks
      // the workspace. Set both for safety.
      CANOPY_ROOT: this.workspaceRoot,
    };
  }
}

// ── Module-level helpers (exported for tests) ───────────────────────────

/**
 * Extract and parse the first JSON value from CLI stdout. Some commands
 * print Rich console output (banner / spinner residue) before the JSON
 * payload, especially on error paths.
 *
 * Returns the parsed value, or throws if no `{` or `[` is found.
 */
export function parseCanopyJson(stdout: string): unknown {
  const trimmed = stdout.trimStart();
  if (!trimmed) {
    throw new Error("canopy returned empty stdout (expected --json output)");
  }
  // Find the first JSON-looking character. Rich console output is plain
  // text; JSON starts with `{` or `[`.
  const firstObj = trimmed.indexOf("{");
  const firstArr = trimmed.indexOf("[");
  let start = -1;
  if (firstObj === -1) start = firstArr;
  else if (firstArr === -1) start = firstObj;
  else start = Math.min(firstObj, firstArr);
  if (start === -1) {
    throw new Error(`canopy stdout had no JSON payload: ${trimmed.slice(0, 200)}`);
  }
  const slice = trimmed.slice(start);
  return JSON.parse(slice);
}

/** True if the parsed value looks like a CanopyBlocker. */
export function isBlocker(value: unknown): value is CanopyBlocker {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Record<string, unknown>).code === "string" &&
    typeof (value as Record<string, unknown>).what === "string" &&
    ((value as Record<string, unknown>).status === "blocked" ||
      (value as Record<string, unknown>).status === "failed")
  );
}

/**
 * Run an interactive login shell to capture the user's real PATH. Returns
 * `null` on any failure — the caller falls back to the inherited PATH.
 *
 * Done as an instance method because the timeout depends on the platform
 * and we may want per-instance overrides later. ~100 ms typical cost; we
 * cache the result.
 */
export async function loginShellPath(): Promise<string | null> {
  return new Promise((resolve) => {
    const shell = process.env.SHELL || "/bin/zsh";
    execFile(
      shell,
      ["-ilc", "echo $PATH"],
      { encoding: "utf8", timeout: 3000, maxBuffer: 1024 * 1024 },
      (err, stdout) => {
        if (err) return resolve(null);
        // Login shells print MOTD/init noise; PATH is on the last non-empty line.
        const lines = stdout.split("\n").map((s) => s.trim()).filter(Boolean);
        const last = lines.pop();
        if (!last || !last.includes(":") || last.includes("=")) {
          // `=` would suggest we accidentally captured an env-set line; skip.
          return resolve(null);
        }
        resolve(last);
      },
    );
  });
}

// ── Result shapes for the wrappers above ────────────────────────────────

export interface FeatureStateAction {
  action: string;
  args: Record<string, unknown>;
  primary?: boolean;
  label?: string;
  preview?: string;
}

export interface FeatureState {
  feature: string;
  state: string;
  summary?: Record<string, unknown>;
  next_actions?: FeatureStateAction[];
  warnings?: Array<{ code: string; what: string; [k: string]: unknown }>;
}

export interface TriageRepoInfo {
  pr_number?: number;
  pr_url?: string;
  pr_title?: string;
  branch?: string;
  review_decision?: string;
  actionable_count?: number;
  actionable_bot_count?: number;
  actionable_human_count?: number;
  physical_state?: "canonical" | "warm" | "cold";
}

export interface TriageFeature {
  feature: string;
  is_canonical: boolean;
  physical_state: "canonical" | "warm" | "cold" | "mixed" | string;
  repos: Record<string, TriageRepoInfo>;
}

export interface TriageResult {
  author?: string;
  canonical_feature: string | null;
  features: TriageFeature[];
}
