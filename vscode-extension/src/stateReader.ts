/**
 * StateReader — synchronous reads of canopy's on-disk state files.
 *
 * Tier 1 of the two-tier data model. The dashboard / sidebar tree need to
 * answer "what's the active feature? what's on each repo's HEAD? did
 * preflight pass for this sha?" *instantly* on every render — going through
 * an async CLI subprocess for those reads adds 50-200 ms of jank per call.
 *
 * The state files are tiny (a few KB each) and live on the local
 * filesystem; sync `fs.readFileSync` is faster than the async equivalent
 * and lets the caller render in the same tick. A per-key TTL cache keeps
 * repeated calls within a render burst nearly free; file watchers
 * (`watchers.ts`) call `invalidate(key)` on disk writes so cached values
 * never lag real state by more than the watcher debounce window.
 *
 * Anything beyond raw state (cross-repo aggregation, alias resolution,
 * temporal classification of comments) goes through `canopyCli.ts` —
 * that's enrichment, and the Python action layer is the single source of
 * truth for it.
 *
 * Design source: matches the pattern in
 * `AgathaCrystal/canopy@extension-rewrite:vscode-extension/src/stateReader.ts`,
 * rewritten in our voice.
 */
import * as fs from "node:fs";
import * as path from "node:path";

export type StateKey =
  | "active_feature"
  | "heads"
  | "preflight"
  | "features"
  | "canopy_toml";

export interface ActiveFeature {
  feature: string | null;
  per_repo_paths?: Record<string, string>;
  activated_at?: string;
  last_touched?: Record<string, string>;
}

export interface HeadEntry {
  branch: string;
  sha: string;
}

export interface PreflightEntry {
  passed: boolean;
  ran_at: string;
  head_sha_per_repo?: Record<string, string>;
}

export interface FeatureEntry {
  repos: string[];
  status?: "active" | "merged" | "archived";
  created_at?: string;
  linear_issue?: string;
  linear_url?: string;
  linear_title?: string;
  branches?: Record<string, string>;
  worktree_paths?: Record<string, string>;
  use_worktrees?: boolean;
}

/** Minimal canopy.toml shape — the sidebar / dashboard only need a few keys. */
export interface CanopyToml {
  workspace_name: string;
  repo_names: string[];
  /** Issue tracker name from `[issue_provider] name = "..."`, or "" if unset. */
  tracker_type: string;
  /** Per-repo `label` mappings from `[[repos]] label = "..."`, if any. */
  repo_labels: Record<string, string>;
}

interface CacheEntry<T> {
  expiresAt: number;
  value: T | null;
}

const DEFAULT_TTL_MS = 5_000;

export class StateReader {
  private cache = new Map<StateKey, CacheEntry<unknown>>();

  constructor(
    private readonly workspaceRoot: string,
    private readonly ttlMs: number = DEFAULT_TTL_MS,
  ) {}

  /** Read `.canopy/state/active_feature.json`. `null` when no canonical feature. */
  activeFeature(): ActiveFeature | null {
    return this.readJson("active_feature", ".canopy/state/active_feature.json");
  }

  /** Read `.canopy/state/heads.json`. Map of repo → {branch, sha}. */
  heads(): Record<string, HeadEntry> {
    return this.readJson("heads", ".canopy/state/heads.json") ?? {};
  }

  /** Read `.canopy/state/preflight.json`. Map of feature → result. */
  preflight(): Record<string, PreflightEntry> {
    return this.readJson("preflight", ".canopy/state/preflight.json") ?? {};
  }

  /** Read `.canopy/features.json`. Map of feature name → entry. */
  features(): Record<string, FeatureEntry> {
    return this.readJson("features", ".canopy/features.json") ?? {};
  }

  /**
   * Parse `canopy.toml` for the few keys the extension UI needs without
   * pulling in a TOML dependency. Regex-based; not a full TOML parser.
   */
  canopyToml(): CanopyToml {
    return this.readCached("canopy_toml", () => parseCanopyTomlMinimal(
      this.tryRead(path.join(this.workspaceRoot, "canopy.toml")) ?? "",
    ));
  }

  /** Convenience: workspace name from canopy.toml, or "" if unparseable. */
  workspaceName(): string {
    return this.canopyToml().workspace_name;
  }

  /** Convenience: list of canopy-managed repo names. */
  repoNames(): string[] {
    return this.canopyToml().repo_names;
  }

  /** Convenience: configured issue-provider name ("linear" / "github_issues" / ""). */
  trackerType(): string {
    return this.canopyToml().tracker_type;
  }

  /** True iff the workspace has an issue provider configured. */
  hasIssueTracker(): boolean {
    return Boolean(this.trackerType());
  }

  /** Drop a single key's cache. File watchers call this on disk writes. */
  invalidate(key: StateKey): void {
    this.cache.delete(key);
  }

  /** Drop all caches. Use sparingly — prefer per-key invalidation. */
  invalidateAll(): void {
    this.cache.clear();
  }

  // ── Internals ──────────────────────────────────────────────────────────

  private readJson<T>(key: StateKey, relPath: string): T | null {
    return this.readCached<T | null>(key, () => {
      const raw = this.tryRead(path.join(this.workspaceRoot, relPath));
      if (raw === null) return null;
      try {
        return JSON.parse(raw) as T;
      } catch {
        // Treat malformed JSON the same as a missing file. The doctor's
        // state-integrity checks will surface the real issue separately.
        return null;
      }
    });
  }

  private readCached<T>(key: StateKey, load: () => T): T {
    const hit = this.cache.get(key);
    if (hit && hit.expiresAt > Date.now()) {
      return hit.value as T;
    }
    const value = load();
    this.cache.set(key, { expiresAt: Date.now() + this.ttlMs, value });
    return value;
  }

  private tryRead(absPath: string): string | null {
    try {
      return fs.readFileSync(absPath, "utf8");
    } catch (e) {
      // ENOENT is the expected case for "this file hasn't been created yet"
      // (workspace just initialized, no features yet, etc.). Return null and
      // let the caller decide whether the absence is meaningful.
      if ((e as NodeJS.ErrnoException).code === "ENOENT") return null;
      return null;
    }
  }
}

// ── Module-level helpers (exported for tests) ───────────────────────────

/**
 * Minimal `canopy.toml` parser — extracts only the few fields the extension
 * UI needs. Avoids adding a TOML dep when we read maybe 5 keys total.
 *
 * Recognized:
 *   [workspace]            name = "<string>"
 *   [[repos]]              name = "<string>"     label = "<string>"
 *   [issue_provider]       name = "<string>"
 *
 * Anything else (per-repo augments, sub-tables under [issue_provider.<n>],
 * etc.) is ignored — that's CLI-side concern.
 */
export function parseCanopyTomlMinimal(text: string): CanopyToml {
  const out: CanopyToml = {
    workspace_name: "",
    repo_names: [],
    tracker_type: "",
    repo_labels: {},
  };
  if (!text) return out;

  // Section iterator — splits the file into [section, body] pairs while
  // ignoring blank/comment lines. We only care about three section types.
  const sectionRegex = /^\s*\[(\[[^\]]+\]|[^\]]+)\]\s*$/gm;
  type Section = { name: string; body: string };
  const sections: Section[] = [];
  let match: RegExpExecArray | null;
  let lastEnd = 0;
  let lastName = "__preamble__";
  while ((match = sectionRegex.exec(text)) !== null) {
    sections.push({ name: lastName, body: text.slice(lastEnd, match.index) });
    lastName = match[1].trim();
    lastEnd = sectionRegex.lastIndex;
  }
  sections.push({ name: lastName, body: text.slice(lastEnd) });

  for (const { name, body } of sections) {
    if (name === "workspace") {
      out.workspace_name = matchKeyString(body, "name") ?? out.workspace_name;
    } else if (name === "[repos]") {
      const repoName = matchKeyString(body, "name");
      if (repoName) {
        out.repo_names.push(repoName);
        const label = matchKeyString(body, "label");
        if (label) out.repo_labels[repoName] = label;
      }
    } else if (name === "issue_provider") {
      out.tracker_type = matchKeyString(body, "name") ?? out.tracker_type;
    }
    // Any other section (`issue_provider.<name>`, `augments`, etc.) is
    // outside this UI parser's concern — CLI handles those.
  }
  return out;
}

function matchKeyString(body: string, key: string): string | null {
  // Match `key = "value"` or `key = 'value'`. Ignores whitespace and TOML
  // comments (anything after `#` on the same line is dropped first).
  const cleaned = body
    .split("\n")
    .map((line) => line.replace(/#.*$/, "").trimEnd())
    .join("\n");
  const re = new RegExp(`^\\s*${key}\\s*=\\s*["']([^"']*)["']\\s*$`, "m");
  const m = re.exec(cleaned);
  return m ? m[1] : null;
}
