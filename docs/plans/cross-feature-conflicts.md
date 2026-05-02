---
status: queued
priority: P3
effort: ~1-2d
depends_on: []
---

# `canopy conflicts` — cross-feature file-overlap detection

## Why

Canopy treats features as independent. They are — at the git level. But two active features can touch the same file: `auth-flow` modifies `src/api/server.py` lines 40-60; `payment-flow` modifies the same file lines 50-80. Canopy doesn't notice. The first one merges; the second one rebases and discovers the conflict — at PR review time, when the user has already shipped a PR description and pinged a reviewer.

`canopy conflicts` precomputes overlap. For each pair of active features, intersect their changed-files. Surface pairs whose intersection is non-empty so the user can resolve overlaps proactively (rebase one onto the other, or split the work) instead of discovering at merge time.

This isn't critical infrastructure — most workspaces have low overlap probability — but it's a small, useful tool that turns an "oh shit" surprise into a 30-second proactive check.

Lower-priority than `doctor` and CI status; written here for completeness.

---

## Behavioral spec

`canopy conflicts [--feature <X>] [--with <Y>] [--include-cold]`

Default: enumerate all *active* features (canonical + warm), pairwise compute file-overlap, return non-empty pairs.

`--feature X` scopes to "what overlaps with feature X" — useful for the agent before opening a PR. `--with Y` further scopes to "specifically X vs Y."

`--include-cold` extends the scan to cold features. By default cold features are ignored (their changes are still git-recorded but they're not actively rotating, so conflict probability with active work is lower-priority).

### Per-pair output

```python
{
  "feature_a": "auth-flow",
  "feature_b": "payment-flow",
  "overlap": {
    "test-api": {
      "files": ["src/api/server.py", "src/api/middleware.py"],
      "lines_a_only": 24,         # lines changed by A but not B
      "lines_b_only": 18,
      "lines_both": 12,           # lines changed by BOTH (real conflict candidates)
    },
    "test-ui": {
      "files": [],                # no overlap in this repo
    }
  },
  "severity": "high" | "medium" | "low",
  "suggestion": "Rebase payment-flow onto auth-flow before opening PR; ~12 overlapping lines.",
}
```

### Severity heuristic

- `high`: lines_both > 0 in any repo (genuine line-level overlap; rebase will conflict)
- `medium`: same files modified, no line overlap (likely auto-mergeable but worth checking)
- `low`: shared files but only in non-code areas (e.g., both touched `package.json` → likely a dep bump, often auto-mergeable)

### CLI rendering

```
$ canopy conflicts

  Conflicts (2 pairs)
  ────────────────────────────────────────────────────
  ⚠ auth-flow ↔ payment-flow                           high
    test-api: 2 files, 12 lines overlapping
    suggestion: rebase payment-flow onto auth-flow first

  · doc-1001 ↔ doc-1003                                low
    both touched package.json (likely a dep bump)
```

`--json` returns the structured per-pair list.

---

## State model changes

None. Read-only — uses existing `feature_diff` per feature.

---

## Command surface changes

| Today | After |
|---|---|
| `canopy conflicts` (does not exist) | New CLI command + MCP tool. |
| `canopy triage` | Optional enrichment: when a feature has a high-severity conflict, surface a `conflicts_with: [feature]` field in the triage output. |
| `canopy state <feature>` | Optional enrichment: per-repo conflict-with-other-features count surfaced in the state output. |

The `triage` and `state` enrichments are optional follow-ons; the standalone `conflicts` command is the v1.

---

## Files to touch

### New

- `src/canopy/actions/conflicts.py` — orchestrator. Public function `find_conflicts(workspace, scope=None, include_cold=False) -> list[ConflictPair]`. Internally: enumerate features, compute per-feature changed-files via existing `feature_diff`, pairwise intersect, classify by severity, format suggestion.
- `tests/test_conflicts.py` — fixture-driven cases:
  - Two features touching disjoint files (no conflict reported)
  - Two features sharing a file but disjoint lines (medium severity)
  - Two features sharing lines (high severity)
  - Three features with mixed overlap (returns 3 pairs)
  - Single-repo features (no cross-repo aggregation)

### Modified

- `src/canopy/cli/main.py` — `cmd_conflicts(args)` + subparser.
- `src/canopy/mcp/server.py` — register `conflicts(scope=None, with_=None, include_cold=False)` MCP tool.
- `docs/commands.md` — add `conflicts` section.
- `docs/agents.md` — add to the "before opening a PR" recipe.
- (Follow-on) `actions/triage.py` + `actions/feature_state.py` — opt-in enrichments behind a config flag, deferred to a follow-up if v1 standalone tool is well-received.

---

## Tasks (rough sequence)

### T1 — `feature_diff` reuse

Verify `feature_diff` returns per-file change data we can intersect. The current return shape is `{summary, files: [...]}` with per-file insertions/deletions but maybe not per-line ranges. If only file-level data is exposed, line-level overlap requires a deeper read — `git diff --unified=0` parsing.

Decision point: ship with file-level severity only (high = same file; we can't distinguish line-level without extra git calls), OR add `feature_diff_lines(feature) -> {repo: {file: [line_ranges]}}` as a new helper. The line-level helper is ~30 lines of git output parsing; worth doing for accurate severity.

### T2 — Pairwise intersect

Pure function `compute_overlap(diff_a, diff_b) -> dict[repo, OverlapEntry]`. Runs in O(features²) which is fine for typical N=10-20.

Tests: synthetic diff fixtures.

### T3 — Severity classifier + suggestion

Pure function `classify(overlap) -> (severity, suggestion)`. Deterministic from the overlap shape.

Tests: snapshot per representative input.

### T4 — Orchestrator

`find_conflicts(workspace, scope=None, include_cold=False)`. Composes: enumerate features → fetch diffs (parallelized) → pairwise intersect → classify → return.

`scope` filters to one feature (returns pairs where that feature is one side). `include_cold` extends the feature set.

### T5 — CLI + MCP

Wrappers. CLI prints the grouped output; `--json` returns the structured list. MCP tool returns the same.

### T6 — Docs + skills

`docs/commands.md`, `docs/agents.md`. Skill files mention `conflicts` as part of the pre-PR checklist.

---

## Edge cases to remember

- **Feature with no changes (just-created lane).** Skip — empty diff means no overlap with anyone.
- **Feature touching only renamed files.** Renames count as "changed" by git. The overlap would surface — and it's actually informative (two features both renamed the same file is a real conflict).
- **Generated files in the diff.** If both features touch `package-lock.json`, severity will be `high`, but the suggestion should note "package-lock.json is auto-generated; conflict is likely benign (re-run `pnpm install` after rebase)." Add a config-driven ignore list (`[workspace] conflict_ignore_files = ["package-lock.json", "*.lock", ...]`) for v1.1 — out of scope for v1.
- **Performance with many features.** O(N²) on diff intersections. With N=50 features that's 1225 pairs — fine. Each diff is ~1KB; total memory ~50KB. Feasible.
- **Stale `feature_diff` cache.** `feature_diff` reads from live git (worktree-aware). Conflicts always reflects current state of each feature's branch.

---

## Out of scope

- **Three-way merge prediction.** "If A merges first, will B's rebase succeed?" Real merge simulation is hard (requires actually rebasing). v1 reports overlap; user judges.
- **Conflict resolution suggestions.** The "suggestion" field is heuristic-based ("rebase A onto B first"); doesn't compute the actual rebase.
- **Live monitoring.** No watcher daemon that surfaces conflicts as features grow. v1 is on-demand `canopy conflicts`.
- **Cross-workspace conflicts.** One workspace per invocation.

---

## After this lands

- Before opening a PR, the agent (or user) runs `canopy conflicts --feature <X>` and sees if any active feature's PR will need to rebase against this one. Proactive, not reactive.
- The README's load-bearing table picks up another row: *"Two of your active features quietly touch the same file; conflict surfaces during PR rebase, not before."* → `canopy conflicts` is the proactive check.
- Pairs with the (future) `ship` MCP tool (Wave 2.4 plan): `ship` could call `conflicts --feature <self>` first and warn before opening a PR that's about to step on another feature's toes.
