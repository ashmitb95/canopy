# Provider Injection — Issue Providers

> **Status:** v1 design reference. Code lands in M5 (see [`docs/plans/INDEX.md`](../plans/INDEX.md)).
> **Plan:** [`docs/plans/archive/providers-arch.md`](../plans/archive/providers-arch.md) (the historical spec; this doc is the live artifact).
> **Scope:** issue providers only in v1. Other use cases named in §8 but not specified.

Canopy's read tools today are tightly coupled to specific external services — `linear_get_issue`, `linear_my_issues`, etc. all call directly into [`src/canopy/integrations/linear.py`](../../src/canopy/integrations/linear.py). That works while we use exactly those services, but the moment we want GitHub Issues (or JIRA, or anything else) instead of Linear, every action that touches issue context has to branch on which integration to call. That branching ages badly and bleeds Linear-shaped assumptions into the contract.

This doc defines the provider-injection pattern, scoped to **issue providers**. The pattern is general enough that other concerns (CI providers, code-review platforms, IDE workspace formats, pre-commit frameworks, bot-author detection) could adopt it later, but those use cases are explicitly *named, not specified* here.

---

## 1. Motivation

Three forces:

- **Multi-tracker reality.** Different teams use different issue trackers. Hardcoding Linear (or any single one) limits canopy's reach.
- **Future-proofing.** New trackers (or new versions of existing ones) shouldn't require touching every action in the codebase.
- **Multi-provider workspaces.** Rare but real — a monorepo with one repo on Linear and another on JIRA. v1 is workspace-level only; per-repo override is reserved for a future plan.

The non-motivation: this is **not** a plugin system for end users in v1. Providers are bundled in the canopy package; third-party providers via entry points come later.

---

## 2. The contract

A Python protocol that every issue provider implements. The canonical `Issue` dataclass is what the action layer consumes — providers map their internal shapes into it.

```python
# src/canopy/providers/types.py
from typing import Protocol
from dataclasses import dataclass

@dataclass(frozen=True)
class Issue:
    """Canonical issue shape canopy operates on, regardless of source provider."""
    id: str                  # provider-internal id (Linear UUID, GH issue number-as-string, JIRA key)
    identifier: str          # human-readable key — "SIN-7", "#142", "PROJ-123"
    title: str
    description: str | None
    state: str               # canonical: "todo" | "in_progress" | "done" | "cancelled"
    url: str
    assignee: str | None
    labels: list[str]
    priority: int | None     # 1=urgent, 2=high, 3=medium, 4=low; provider-mapped


class IssueProvider(Protocol):
    """Contract every issue provider must implement."""

    def get_issue(self, alias: str) -> Issue:
        """Resolve an alias to an Issue. Alias formats are provider-specific:
          - Linear: "SIN-7"
          - GitHub Issues: "#142" or "owner/repo#142"
          - JIRA: "PROJ-123"

        Raises BlockerError(code="issue_not_found", ...) when not resolvable.
        """

    def list_my_issues(self, limit: int = 50) -> list[Issue]:
        """Return the current user's open issues, ordered by recency or priority.
        Empty list is valid (user has no open issues)."""

    def format_branch_name(
        self,
        issue_id: str,
        title: str | None = None,
        custom_name: str | None = None,
    ) -> str:
        """Provider-specific slug rules. `custom_name` overrides the default slug
        when the user wants a non-derived branch name.

        Examples:
          Linear:        format_branch_name("SIN-7", "Add /search")        → "sin-7-add-search"
          GitHub Issues: format_branch_name("#142", "Fix flaky test")      → "gh-142-fix-flaky-test"
          With custom:   format_branch_name("SIN-7", custom_name="oauth")  → "sin-7-oauth"
        """

    # Optional. v1 contract reserves the slot; first implementations may raise
    # NotImplementedError. Future plans wire this for lifecycle automation
    # (e.g. flip issue to "in_progress" on `canopy switch <issue>`).
    def update_issue_state(self, alias: str, new_state: str) -> None: ...
```

**Per-provider state mapping** lives inside each backend, not in the protocol. Linear's state names (`Backlog`, `Todo`, `In Progress`, `Done`, `Canceled`, …) and GitHub Issues' `open` / `closed` both collapse to canopy's `todo` / `in_progress` / `done` / `cancelled`. The mapping rules are documented per-backend (§7).

**Errors.** Providers raise `BlockerError` (existing canopy pattern from `src/canopy/actions/errors.py`) with codes the action layer already understands:
- `issue_not_found` — alias didn't resolve
- `provider_not_configured` — credentials missing or wrong (replaces today's `LinearNotConfiguredError`)
- `provider_call_failed` — network / API error from the backend (replaces today's `LinearCallError`)

The existing per-backend exception classes (`LinearNotConfiguredError`, etc. in [`integrations/linear.py:21-29`](../../src/canopy/integrations/linear.py)) get folded into `BlockerError` raises during the M5 refactor.

---

## 3. Discovery

How canopy finds providers.

**v1: bundled.** Canopy ships built-in modules under `src/canopy/providers/`:

```
src/canopy/providers/
├── __init__.py          # registry + get_issue_provider()
├── types.py             # Issue dataclass + IssueProvider protocol
├── linear.py            # LinearProvider (refactored from integrations/linear.py)
└── github_issues.py     # GitHubIssuesProvider (new)
```

Registry in `src/canopy/providers/__init__.py`:

```python
from .linear import LinearProvider
from .github_issues import GitHubIssuesProvider
from .types import Issue, IssueProvider

_REGISTRY: dict[str, type[IssueProvider]] = {
    "linear": LinearProvider,
    "github_issues": GitHubIssuesProvider,
}

# Cached per-workspace
_INSTANCES: dict[Path, IssueProvider] = {}


def get_issue_provider(workspace: WorkspaceConfig) -> IssueProvider:
    """Return the configured provider for the workspace, instantiated and cached.
    Raises BlockerError(code='unknown_issue_provider') for misconfigured names."""
    if workspace.root in _INSTANCES:
        return _INSTANCES[workspace.root]

    config = workspace.issue_provider  # parsed from canopy.toml
    cls = _REGISTRY.get(config.name)
    if cls is None:
        raise BlockerError(
            code="unknown_issue_provider",
            what=f"'{config.name}' is not a known provider",
            expected={"available": sorted(_REGISTRY.keys())},
            fix_actions=[FixAction(action="set issue_provider.name", args={"valid_choices": list(_REGISTRY.keys())})],
        )
    instance = cls(config.options)
    _INSTANCES[workspace.root] = instance
    return instance
```

**Future: entry points.** Third-party providers register via `pyproject.toml` entry points (`canopy.providers` group). Out of scope for v1; document the extension point so the registry pattern doesn't preclude it.

---

## 4. Configuration

The user/workspace picks a provider via a top-level `[issue_provider]` block in `canopy.toml`.

**Linear** (current behavior, made explicit):

```toml
[issue_provider]
name = "linear"

[issue_provider.linear]
api_key_env = "LINEAR_API_KEY"   # default
```

**GitHub Issues:**

```toml
[issue_provider]
name = "github_issues"

[issue_provider.github_issues]
repo = "owner/repo"                                    # required
labels_filter = ["good first issue", "help wanted"]    # optional; restricts list_my_issues
```

**Per-provider `[issue_provider.<name>]` sub-table** holds backend-specific settings. The protocol's `__init__(config: dict)` receives this sub-table; protocol-level keys (`name`) are stripped before passing through.

**Backward compatibility for existing workspaces:**
- Existing `canopy.toml` files without `[issue_provider]` default to Linear. Warn once with a deprecation notice; require explicit config in v0.X+1.
- Per-repo override (`[[repos]] issue_provider = {...}`) is reserved for a future plan. v1 is workspace-level only.

---

## 5. DI wiring

How the action layer obtains the provider instance.

**Single entry point** (new module `src/canopy/providers/__init__.py`):

```python
from canopy.providers import get_issue_provider

# In any action that previously called linear.get_issue(...):
issue = get_issue_provider(workspace).get_issue(alias)
```

**Cached per-workspace.** First call constructs the provider; subsequent calls in the same process return the cached instance. Cache keyed on `workspace.root` so multi-workspace MCP sessions (when that lands) don't share instances across workspaces.

**Call sites that change in M5** (search results from current code):

| File | Current call | Becomes |
|---|---|---|
| `src/canopy/actions/reads.py` | `linear.get_issue(workspace.config.root, alias)` | `get_issue_provider(workspace).get_issue(alias)` |
| `src/canopy/actions/reads.py` | `linear.list_my_issues(workspace.config.root, limit)` | `get_issue_provider(workspace).list_my_issues(limit)` |
| `src/canopy/features/coordinator.py` (worktree_create's Linear lookup) | `linear.get_issue(...)` | `get_issue_provider(workspace).get_issue(alias)` |
| `src/canopy/cli/main.py` (`cmd_issue`) | direct linear call | `get_issue_provider(workspace).get_issue(alias)` |
| `src/canopy/mcp/server.py` (`linear_get_issue`, `linear_my_issues` MCP tools) | direct linear call | new `issue_get` / `issue_list_my_issues` tools wrapping the provider; old names kept as deprecated aliases for one release cycle |

The action layer never imports a provider module directly. Always goes through `get_issue_provider`.

---

## 6. Backward compatibility

**Existing code paths:**

- **`integrations/linear.py`** becomes the Linear backend's implementation source. Its public functions (`get_issue`, `list_my_issues`, `format_branch_name`) move into `src/canopy/providers/linear.py:LinearProvider` methods. The module itself stays importable for one release cycle (re-exports from the new location) so external code doesn't break.
- **`integrations/github.py`** PR/branch logic stays separate. PR-platform integration is a different concern from issue-tracker integration; the `gh` fallback for PRs is fine as-is. Don't conflate review platforms with issue providers.
- **`mcp__canopy__linear_get_issue`** MCP tool keeps working — registered as a deprecated alias for `mcp__canopy__issue_get`. Logs a one-time deprecation warning per session.
- **Workspaces without `[issue_provider]`** in canopy.toml default to Linear with a one-time deprecation warning. Future canopy version (TBD) requires explicit config.

**Migration story:**
1. M5 ships the new providers + registry + new MCP tools, with old MCP tools kept as aliases.
2. Workspaces that update to the M5-shipped canopy version see no behavior change unless they explicitly add `[issue_provider]`.
3. Workspaces that want GitHub Issues add the block, swap their workflow.
4. A future minor release deprecates the old `linear_*` MCP tool names.
5. A future major release removes them.

---

## 7. Examples

### Linear backend (refactored from `integrations/linear.py`)

The bulk of the existing Linear logic moves into `LinearProvider`. Public method bodies are mostly verbatim from today's `linear.py`; the wrapping changes from module-level functions to instance methods.

```python
# src/canopy/providers/linear.py
from canopy.providers.types import Issue, IssueProvider
# ...existing imports

_LINEAR_STATE_MAP = {
    "Backlog":      "todo",
    "Todo":         "todo",
    "In Progress":  "in_progress",
    "In Review":    "in_progress",
    "Done":         "done",
    "Canceled":     "cancelled",
}


class LinearProvider:
    def __init__(self, config: dict):
        self.api_key_env = config.get("api_key_env", "LINEAR_API_KEY")

    def get_issue(self, alias: str) -> Issue:
        # Existing Linear MCP fallback logic, returning Issue instead of dict.
        raw = _fetch_linear_issue(alias, env_key=self.api_key_env)
        if raw is None:
            raise BlockerError(code="issue_not_found", what=f"Linear issue '{alias}' not found")
        return Issue(
            id=raw["id"],
            identifier=raw["identifier"],
            title=raw["title"],
            description=raw.get("description"),
            state=_LINEAR_STATE_MAP.get(raw["state"]["name"], "todo"),
            url=raw["url"],
            assignee=(raw.get("assignee") or {}).get("name"),
            labels=[l["name"] for l in (raw.get("labels") or {}).get("nodes", [])],
            priority=raw.get("priority"),
        )

    def list_my_issues(self, limit: int = 50) -> list[Issue]:
        raw_list = _fetch_my_linear_issues(limit, env_key=self.api_key_env)
        return [self._normalize(raw) for raw in raw_list]

    def format_branch_name(self, issue_id: str, title: str | None = None, custom_name: str | None = None) -> str:
        # Existing logic from integrations/linear.py:format_branch_name
        ...
```

### GitHub Issues backend (new)

```python
# src/canopy/providers/github_issues.py
import re
from canopy.providers.types import Issue, IssueProvider
from canopy.integrations.github import _gh_run  # reuse the existing gh CLI wrapper

_GH_STATE_MAP = {"open": "in_progress", "closed": "done"}
_PRIORITY_LABEL_MAP = {
    "priority/urgent": 1, "priority/high": 2, "priority/medium": 3, "priority/low": 4,
    "p0": 1, "p1": 2, "p2": 3, "p3": 4,
}


class GitHubIssuesProvider:
    def __init__(self, config: dict):
        self.repo = config["repo"]   # required: "owner/repo"
        self.labels_filter = config.get("labels_filter") or []

    def get_issue(self, alias: str) -> Issue:
        issue_num = self._parse_alias(alias)
        raw = _gh_run(["api", f"repos/{self.repo}/issues/{issue_num}"], json=True)
        if raw is None or raw.get("number") is None:
            raise BlockerError(code="issue_not_found", what=f"GitHub issue '{alias}' not found in {self.repo}")
        return self._normalize(raw)

    def list_my_issues(self, limit: int = 50) -> list[Issue]:
        query = f"is:open assignee:@me"
        if self.labels_filter:
            query += " " + " ".join(f'label:"{l}"' for l in self.labels_filter)
        args = ["search", "issues", query, "--limit", str(limit), "--json", "number,title,state,body,url,assignees,labels"]
        raw_list = _gh_run(args, json=True) or []
        return [self._normalize(r) for r in raw_list]

    def format_branch_name(self, issue_id: str, title: str | None = None, custom_name: str | None = None) -> str:
        n = self._parse_alias(issue_id)
        slug = custom_name or self._slugify(title or "")
        return f"gh-{n}-{slug}" if slug else f"gh-{n}"

    def _parse_alias(self, alias: str) -> int:
        # "#142" or "142" or "owner/repo#142"
        m = re.match(r"^(?:[^/]+/[^#]+)?#?(\d+)$", alias)
        if not m:
            raise BlockerError(code="issue_not_found", what=f"can't parse GitHub alias '{alias}'")
        return int(m.group(1))

    def _normalize(self, raw: dict) -> Issue:
        labels = [l["name"] for l in raw.get("labels", [])]
        return Issue(
            id=str(raw["number"]),
            identifier=f"#{raw['number']}",
            title=raw["title"],
            description=raw.get("body"),
            state=_GH_STATE_MAP.get(raw["state"], "todo"),
            url=raw.get("html_url") or raw.get("url"),
            assignee=(raw["assignees"][0]["login"] if raw.get("assignees") else None),
            labels=labels,
            priority=self._priority_from_labels(labels),
        )

    def _priority_from_labels(self, labels: list[str]) -> int | None:
        for l in labels:
            p = _PRIORITY_LABEL_MAP.get(l.lower())
            if p is not None:
                return p
        return None

    def _slugify(self, s: str) -> str:
        s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
        return s[:50]
```

---

## 8. Future candidates (not v1)

The following could adopt the same provider-injection shape if implementation drops in seamlessly. **None are scheduled here.** Effort cap on retrofitting any of them: < 5% of the M5 implementation effort. If retrofitting requires non-trivial refactor, leave the existing handling alone.

- **Bot-author detection** — currently a hardcoded `author_type == "Bot"` substring check. Could become a `BotAuthorDetector` provider with per-team rules (CodeRabbit-style only, JIRA-bot, custom regex, etc.). M3 (bot-tracking) introduces `review_bots` augment as the v1 mechanism; provider-ifying is a future option.
- **CI providers** (GitHub Actions, CircleCI, Buildkite) — deferred to the [ci-status plan](../plans/ci-status.md). Same shape would apply: a `CIProvider` protocol with `get_check_runs(pr)` etc. Don't build until that plan exists.
- **Code-review platforms** (GitHub, GitLab, Bitbucket) — `gh` fallback works today via [`integrations/github.py`](../../src/canopy/integrations/github.py). A `ReviewPlatformProvider` could unify, but the existing gh-or-MCP pattern handles current needs.
- **IDE workspace formats** (VS Code `.code-workspace`, JetBrains `.idea/`, Cursor) — [worktree-bootstrap plan](../plans/worktree-bootstrap.md) defers this. Could become an `IDEWorkspaceWriter` provider.
- **Pre-commit frameworks** (pre-commit, husky, lefthook) — auto-detection in [`integrations/precommit.py`](../../src/canopy/integrations/precommit.py) works today. A `PreflightProvider` would unify but isn't load-bearing.

The pattern is the same in every case: **canonical type + protocol + bundled implementations + canopy.toml selection + single DI entry point**. Build the abstraction when the second backend appears; don't pre-abstract for hypothetical second backends.

---

## Verification

This doc is reviewable as a design artifact. M5 (the issue-provider scaffold per [`docs/plans/INDEX.md`](../plans/INDEX.md)) implements the contract — its PRs reference the section here they implement (e.g., *"implements §5 DI wiring + §7 Linear backend"*). The historical spec for both M0 (this doc) and M5 lives at [`docs/plans/archive/providers-arch.md`](../plans/archive/providers-arch.md) §7.
