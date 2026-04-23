// TypeScript mirrors of the JSON shapes returned by canopy-mcp.
// Source of truth: src/canopy/mcp/server.py and src/canopy/features/coordinator.py

export interface RepoState {
  has_branch: boolean;
  ahead?: number;
  behind?: number;
  dirty?: boolean;
  changed_files?: string[];
  changed_file_count?: number;
  default_branch?: string;
  worktree_path?: string;
  error?: string;
}

export interface FeatureLane {
  name: string;
  repos: string[];
  created_at: string;
  status: "active" | "merged" | "abandoned" | "done" | string;
  repo_states: Record<string, RepoState>;
  linear_issue?: string;
  linear_title?: string;
  linear_url?: string;
}

export interface WorkspaceConfigSettings {
  name: string;
  max_worktrees: number;
}

export interface CanopyContext {
  cwd: string;
  workspace_root: string | null;
  feature: string | null;
  repo_paths: string[];
  repo_names: string[];
  branch: string | null;
  context_type:
    | "feature_dir"
    | "repo_worktree"
    | "repo"
    | "workspace_root"
    | "unknown"
    | string;
}

export interface FeatureChange {
  path: string;
  status: string; // M / A / D / R / C / T / ?
}

export interface FeatureChangesPerRepo {
  has_branch: boolean;
  path: string;
  default_branch: string;
  changes: FeatureChange[];
  error?: string;
}

export interface FeatureChangesResult {
  feature: string;
  repos: Record<string, FeatureChangesPerRepo>;
}

export interface WorktreeRepoInfo {
  path: string;
  branch: string;
  dirty: boolean;
  dirty_count: number;
  dirty_files: string[];
  ahead: number;
  behind: number;
  default_branch: string;
}

export interface WorktreeInfo {
  features: Record<string, { repos: Record<string, WorktreeRepoInfo> }>;
  repos: Record<
    string,
    {
      main_path: string;
      worktrees: Array<{
        path: string;
        head: string;
        branch: string;
        is_bare: boolean;
      }>;
    }
  >;
}

export interface FeatureDiff {
  feature: string;
  repos: Record<
    string,
    {
      has_branch: boolean;
      files_changed: number;
      insertions: number;
      deletions: number;
      changed_files: string[];
    }
  >;
  summary: {
    participating_repos: number;
    total_repos: number;
    total_files_changed: number;
    total_insertions: number;
    total_deletions: number;
  };
  type_overlaps: Array<{
    file_pattern: string;
    repos: string[];
    files: Array<{ repo: string; path: string }>;
  }>;
}

export interface ReviewStatus {
  feature: string;
  has_prs: boolean;
  repos: Record<
    string,
    {
      branch: string;
      owner?: string;
      repo_name?: string;
      pr?: {
        number: number;
        title: string;
        url: string;
        state: string;
        head_branch: string;
      };
    }
  >;
}

export interface ReviewComment {
  path: string;
  line: number;
  body: string;
  author: string;
  state: string;
  created_at: string;
  url: string;
  in_reply_to_id: number | null;
}

export interface ReviewComments {
  feature: string;
  total_comments: number;
  repos: Record<
    string,
    {
      pr_number: number;
      pr_url: string;
      pr_title: string;
      comments: ReviewComment[];
    }
  >;
}

export interface PreflightResult {
  feature: string;
  context_type: string;
  all_passed: boolean;
  results: Record<
    string,
    {
      status: string;
      dirty_count: number;
      hooks: { type: string; passed: boolean; output: string };
    }
  >;
}

export interface LinearIssue {
  identifier: string;
  title: string;
  state: string;
  url: string;
}

export interface LogEntry {
  sha: string;
  short_sha: string;
  repo: string;
  author: string;
  date: string;
  subject: string;
}
