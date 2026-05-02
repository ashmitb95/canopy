---
status: queued
priority: P0
effort: ~1d
depends_on: []
---

# Architecture: provider-injection contract (issue providers)

## Why

Canopy's read tools today are tightly coupled to specific external services — `linear_get_issue`, `linear_my_issues`, `github_get_pr`, etc. That works while we're using exactly those services, but the moment we (or anyone) wants GitHub Issues instead of Linear, every action that touches issue context has to branch on which integration to call. That branching is exactly the kind of code that ages badly and bleeds Linear-shaped assumptions into the contract.

This document defines the provider-injection pattern, scoped to **issue providers** specifically. The pattern is general enough that other concerns (CI providers, code-review platforms, IDE workspace formats, pre-commit frameworks, bot-author detection) could adopt it later, but those use cases are explicitly *named, not specified* in v1 — they only adopt the pattern if it drops in seamlessly during implementation.

## Goal

A provider-agnostic interface for issue providers, defined as a Python protocol, with:
- A small contract that any backend can implement
- A discovery mechanism for finding installed providers
- A configuration mechanism in `canopy.toml` for picking which provider a workspace uses
- A dependency-injection point in the action layer so providers are swappable without touching call sites
- Two reference implementations: Linear (refactored from `integrations/linear.py`) and GitHub Issues (new)

## Doc structure

This is the v1 architecture doc. Code lands in subsequent plans (`docs/plans/issue-providers.md` for the first scaffold).

### 1. Motivation

Why provider injection:
- **External signal** ([issue #5](https://github.com/ashmitb95/canopy/issues/5)): GitHub Issues as a first-class alternative to Linear.
- **Future-proofing**: every team has different issue trackers. Hardcoding Linear (or any single one) limits canopy's reach.
- **Multi-provider workspaces**: rare but real — a monorepo with one repo on Linear and another on JIRA. v1 is workspace-level only; per-repo override is reserved for a future plan.

### 2. The contract

Python protocol / abstract base for an issue provider:

```python
from typing import Protocol
from dataclasses import dataclass

@dataclass
class Issue:
    """Canonical issue shape canopy operates on, regardless of source provider."""
    id: str                  # provider-internal id (Linear UUID, GH issue number, etc.)
    identifier: str          # human-readable key (SIN-7, #142, JIRA-PROJ-123)
    title: str
    description: str | None
    state: str               # canonical states: "todo" | "in_progress" | "done" | "cancelled"
    url: str
    assignee: str | None
    labels: list[str]
    priority: int | None     # 1=urgent, 2=high, 3=medium, 4=low; provider-mapped

class IssueProvider(Protocol):
    """Contract every issue provider must implement."""

    def get_issue(self, alias: str) -> Issue:
        """Resolve an alias to an issue. Alias formats vary by provider:
        - Linear: 'SIN-7'
        - GitHub Issues: '#142' or 'owner/repo#142'
        Raises BlockerError(code='issue_not_found', ...) when not resolvable.
        """

    def list_my_issues(self, limit: int = 50) -> list[Issue]:
        """Return the current user's open issues, ordered by recency or priority."""

    def format_branch_name(
        self,
        issue_id: str,
        title: str | None = None,
        custom_name: str | None = None,
    ) -> str:
        """Provider-specific slug rules. Linear uses 'sin-7-add-search'; GitHub Issues
        might use 'gh-142-add-search'. Custom name overrides the default slug."""

    # Optional: lifecycle automation. v1 contract reserves the slot; first
    # implementations may raise NotImplementedError. Future plans wire this.
    def update_issue_state(self, alias: str, new_state: str) -> None: ...
```

The `Issue` dataclass is the canonical type the action layer consumes. Per-provider mapping (Linear's state names → canopy's, GitHub Issues' labels → canopy's priority field) lives inside each backend.

### 3. Discovery

How canopy finds providers:

**v1: bundled.** Canopy ships built-in modules:
- `canopy.providers.linear` (refactored from `integrations/linear.py`)
- `canopy.providers.github_issues` (new)

A small registry in `canopy.providers.__init__.py`:

```python
_REGISTRY: dict[str, type[IssueProvider]] = {
    "linear": LinearProvider,
    "github_issues": GitHubIssuesProvider,
}

def get_issue_provider(workspace: WorkspaceConfig) -> IssueProvider:
    """Return the configured provider for the workspace, instantiated and cached."""
    name = workspace.issue_provider.name  # from canopy.toml
    cls = _REGISTRY.get(name)
    if cls is None:
        raise BlockerError(code='unknown_issue_provider', what=f"'{name}' is not a known provider", fix_actions=[...])
    return cls(workspace.issue_provider.config)
```

**Future: entry points.** Third-party providers register via `pyproject.toml` entry points (`canopy.providers` group). Out of scope for v1.

### 4. Configuration

How the user/workspace picks a provider — top-level `[issue_provider]` block in `canopy.toml`:

```toml
[issue_provider]
name = "linear"
api_key_env = "LINEAR_API_KEY"   # or in a [issue_provider.linear] sub-table
```

GitHub Issues:

```toml
[issue_provider]
name = "github_issues"
repo = "owner/repo"              # which GH repo hosts the issues for this workspace
```

Provider-specific config goes in a `[issue_provider.<name>]` sub-table when there are multiple keys:

```toml
[issue_provider]
name = "github_issues"

[issue_provider.github_issues]
repo = "owner/repo"
labels_filter = ["good first issue", "help wanted"]   # optional
```

**Per-repo override** is reserved for a future plan. v1 is workspace-level only.

### 5. DI wiring

How the action layer obtains the provider instance:

- New module `src/canopy/providers/__init__.py` exposes `get_issue_provider(workspace) -> IssueProvider`.
- Cached per-workspace; constructed lazily on first access.
- Action code calls `get_issue_provider(ws).get_issue(alias)` instead of `linear.get_issue(workspace.config.root, alias)`.

Call sites to update (search for current direct `linear.*` calls):

- `src/canopy/actions/reads.py:linear_get_issue`
- `src/canopy/actions/reads.py:linear_my_issues`
- `src/canopy/features/coordinator.py:worktree_create` (Linear lookup for issue title)
- `src/canopy/cli/main.py:cmd_issue` (CLI command)
- `src/canopy/mcp/server.py` (the `linear_*` MCP tools)

The `linear_*` MCP tools become deprecation aliases:

```python
@mcp.tool()
def linear_get_issue(alias: str) -> dict:
    """Deprecated: use issue_get."""
    # implementation: just calls issue_get
```

New canonical tools: `issue_get`, `issue_list_my_issues`. The old names continue to work for one release cycle.

### 6. Backward compatibility

Existing code paths:

- Current `integrations/linear.py` becomes the Linear backend implementing the contract. Its public API is preserved during the transition; nothing in the action layer changes shape, just *who* it calls.
- Current `integrations/github.py` PR/branch logic stays separate. PR-platform integration is a different concern from issue-tracker integration; the gh fallback for PRs is fine as-is.
- Existing `mcp__canopy__linear_get_issue` MCP tool keeps working (deprecated alias for `mcp__canopy__issue_get` once the new tool ships).
- Existing `canopy.toml` files without `[issue_provider]` block default to `linear` for backward compatibility (warn with a deprecation notice; v0.X removes the default).

### 7. Examples

#### Linear backend (refactored)

Most logic moves verbatim from `integrations/linear.py`; the wrapping changes:

```python
class LinearProvider:
    def __init__(self, config: dict):
        self.api_key_env = config.get("api_key_env", "LINEAR_API_KEY")

    def get_issue(self, alias: str) -> Issue:
        # existing Linear MCP fallback logic
        raw = _fetch_linear_issue(alias, env_key=self.api_key_env)
        return Issue(
            id=raw["id"],
            identifier=raw["identifier"],
            title=raw["title"],
            description=raw.get("description"),
            state=_map_linear_state(raw["state"]["name"]),
            url=raw["url"],
            assignee=raw.get("assignee", {}).get("name"),
            labels=[l["name"] for l in raw.get("labels", {}).get("nodes", [])],
            priority=raw.get("priority"),
        )
    # list_my_issues + format_branch_name follow the same pattern
```

#### GitHub Issues backend (new, skeleton)

```python
class GitHubIssuesProvider:
    def __init__(self, config: dict):
        self.repo = config["repo"]   # required: "owner/repo"

    def get_issue(self, alias: str) -> Issue:
        # alias like "#142" or "142" or "owner/repo#142"
        issue_num = _parse_alias(alias, default_repo=self.repo)
        raw = _gh_api_issue_get(self.repo, issue_num)
        return Issue(
            id=str(raw["id"]),
            identifier=f"#{raw['number']}",
            title=raw["title"],
            description=raw.get("body"),
            state=_map_gh_state(raw["state"]),  # "open" → "in_progress", "closed" → "done"
            url=raw["html_url"],
            assignee=raw["assignee"]["login"] if raw.get("assignee") else None,
            labels=[l["name"] for l in raw.get("labels", [])],
            priority=_priority_from_labels(raw.get("labels", [])),
        )
    # list_my_issues uses gh api search/issues?q=is:open+assignee:@me
    # format_branch_name: "gh-142-fix-search" or similar
```

### 8. Future candidates (not v1)

One paragraph each — named so future plans can adopt the pattern if it drops in cleanly, but **explicitly not specified or scheduled** here:

- **Bot-author detection** — currently a hardcoded `author_type == "Bot"` substring check. Could be generalized into a "bot detector provider" with per-team rules. *No plan to make this a provider unless seamless during implementation of bot-comment-tracking.*
- **CI providers** (GitHub Actions, CircleCI, Buildkite) — deferred to the CI-status plan. *No plan to make this a provider unless seamless during that plan's implementation.*
- **Code-review platforms** (GitHub, GitLab, Bitbucket) — `gh` fallback works fine today. *No plan to make this a provider unless seamless.*
- **IDE workspace formats** (VS Code `.code-workspace`, JetBrains `.idea/`, Cursor) — bootstrap plan deferred this. *No plan to make this a provider unless seamless.*
- **Pre-commit frameworks** (pre-commit, husky, lefthook) — auto-detection works fine today. *No plan to make this a provider unless seamless.*

**Effort cap on these candidates: < 5% of total architecture-doc effort.** If implementing any of the v1 issue-provider work surfaces a clean way to retrofit one of these, do it. Otherwise leave the existing handling alone.

## Deliverable

The doc itself, committed to `docs/architecture/providers.md`. Code lands in a subsequent plan (`docs/plans/issue-providers.md` will spec the first scaffold: refactor Linear + add GitHub Issues backend).

## Verification

The doc is reviewable as a design artifact. Once a future plan implements an issue-provider backend, that plan's PR description references the section it implements (e.g., "implements §2 contract + §7 Linear backend").

## Out of scope

- Per-repo issue-provider override (workspace-level only in v1)
- Third-party provider entry points (bundled-only in v1)
- Lifecycle automation methods (`update_issue_state`) — contract reserves the slot, first implementations raise `NotImplementedError`
- Multi-provider in a single workspace (one provider per workspace; multi-tenant is a future plan)
- Migrating PR/code-review integrations to the same pattern (different concern; out of scope)
