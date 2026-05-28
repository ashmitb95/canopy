"""``canopy conflicts`` — cross-feature file-overlap detection.

Pairwise intersects each active feature's changed-file set per repo. Flags
pairs that touch the same file (and, when we can read it cheaply, the
same line ranges) so the user can rebase proactively instead of discovering
the conflict at PR-merge time.

V1 ships file-level severity by default — same file in both features ==
``high`` because the rebase will produce a textual conflict marker even if
the diffs would have auto-merged. The ``--lines`` flag opts into the more
expensive line-range comparison and downgrades to ``medium`` when the
files overlap but the actual line ranges don't intersect.

Read-only — no canopy state files are touched.
"""
from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

from ..git import repo as git
from ..git.multi import cross_repo_diff
from ..workspace.workspace import Workspace
from . import slots as slots_mod
from .aliases import resolve_feature

_GENERATED_HINT = re.compile(
    r"(?:^|/)(?:package-lock\.json|pnpm-lock\.yaml|yarn\.lock|Cargo\.lock|"
    r"poetry\.lock|uv\.lock|Pipfile\.lock|composer\.lock|Gemfile\.lock)$"
)


def find_conflicts(
    workspace: Workspace,
    *,
    feature: str | None = None,
    other: str | None = None,
    include_cold: bool = False,
    line_level: bool = False,
) -> dict[str, Any]:
    """Compute pairwise file-overlap across active features.

    Args:
        workspace: loaded workspace.
        feature: scope to "what overlaps with this feature." When set,
            the result only includes pairs where ``feature`` is one side.
        other: further scope to "specifically <feature> vs <other>."
            Requires ``feature``.
        include_cold: also consider cold features (no worktree). Default
            keeps the focus on active rotation since cold features are
            less likely to merge soon.
        line_level: when True, compute per-file line ranges to differentiate
            ``high`` (lines overlap) from ``medium`` (same file, disjoint
            lines). When False (default), any shared file is ``high``.

    Returns:
        ``{features: [<scanned>], pairs: [<ConflictPair>], generated_at}``.
        Pairs are sorted high → low severity.
    """
    feature_names = _enumerate_features(workspace, include_cold=include_cold)
    if feature is not None:
        scoped = resolve_feature(workspace, feature)
        if scoped not in feature_names:
            feature_names.append(scoped)
        feature_names = [scoped] + [f for f in feature_names if f != scoped]
        if other is not None:
            other_resolved = resolve_feature(workspace, other)
            feature_names = [scoped, other_resolved]

    diffs: dict[str, dict[str, dict[str, Any]]] = {}
    for name in feature_names:
        diffs[name] = cross_repo_diff(workspace, name)

    pairs: list[dict[str, Any]] = []
    iterator: Iterable[tuple[str, str]]
    if feature is not None:
        scoped = feature_names[0]
        iterator = ((scoped, b) for b in feature_names if b != scoped)
    else:
        iterator = combinations(feature_names, 2)

    for a, b in iterator:
        overlap = compute_overlap(diffs[a], diffs[b], workspace=workspace,
                                  feature_a=a, feature_b=b,
                                  line_level=line_level)
        if not _has_overlap(overlap):
            continue
        severity, suggestion = classify(overlap, a, b)
        pairs.append({
            "feature_a": a,
            "feature_b": b,
            "overlap": overlap,
            "severity": severity,
            "suggestion": suggestion,
        })

    pairs.sort(key=lambda p: _SEVERITY_ORDER[p["severity"]])
    return {
        "features": feature_names,
        "pairs": pairs,
    }


_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _enumerate_features(workspace: Workspace, *, include_cold: bool) -> list[str]:
    """Return canonical + warm features, plus cold ones when requested."""
    state = slots_mod.read_state(workspace)
    canonical_feature: str | None = (
        state.canonical.feature if state and state.canonical else None
    )
    warm_features: set[str] = {
        e.feature for e in (state.slots.values() if state else [])
    }
    names: list[str] = []
    if canonical_feature:
        names.append(canonical_feature)

    # Walk features.json directly for the full roster — keeps the
    # implementation independent of whichever helper is in vogue.
    features_path = workspace.config.root / ".canopy" / "features.json"
    if features_path.exists():
        import json
        try:
            data = json.loads(features_path.read_text("utf-8"))
        except (OSError, ValueError):
            data = {}
    else:
        data = {}

    for name, entry in data.items():
        if name in names:
            continue
        if entry.get("status") and entry["status"] != "active":
            continue
        # A feature is "warm" if it occupies a slot OR if features.json
        # records worktree_paths for it (the slot map may be stale, and
        # explicit worktree_paths still mean the feature has a working tree).
        has_worktree = name in warm_features or bool(entry.get("worktree_paths"))
        if not include_cold and not has_worktree and name != canonical_feature:
            continue
        names.append(name)
    return names


def compute_overlap(
    diff_a: dict[str, dict[str, Any]],
    diff_b: dict[str, dict[str, Any]],
    *,
    workspace: Workspace | None = None,
    feature_a: str | None = None,
    feature_b: str | None = None,
    line_level: bool = False,
) -> dict[str, dict[str, Any]]:
    """Pairwise file intersection grouped by repo.

    Returns ``{<repo>: {files: [<path>], lines_a_only?, lines_b_only?,
    lines_both?, generated_files?}}``. Repos with no overlap are omitted.
    """
    out: dict[str, dict[str, Any]] = {}
    repos = set(diff_a.keys()) & set(diff_b.keys())
    for repo in sorted(repos):
        files_a = set((diff_a.get(repo) or {}).get("changed_files") or [])
        files_b = set((diff_b.get(repo) or {}).get("changed_files") or [])
        shared = sorted(files_a & files_b)
        if not shared:
            continue
        entry: dict[str, Any] = {
            "files": shared,
            "generated_files": [f for f in shared if _GENERATED_HINT.search(f)],
        }
        if line_level and workspace is not None and feature_a and feature_b:
            entry.update(_line_overlap(workspace, repo, feature_a, feature_b, shared))
        out[repo] = entry
    return out


def _has_overlap(overlap: dict[str, dict[str, Any]]) -> bool:
    return any(entry.get("files") for entry in overlap.values())


def classify(
    overlap: dict[str, dict[str, Any]],
    feature_a: str,
    feature_b: str,
) -> tuple[str, str]:
    """Return ``(severity, suggestion)``.

    Heuristic:
      - ``high``   when any repo has line-level overlap, OR when line
                   data isn't available and there's ≥1 shared real file
                   (non-generated).
      - ``medium`` when only generated/lockfile-style files overlap, OR
                   when line data shows zero-line overlap on shared files.
      - ``low``    fallback (currently unused — kept for the suggestion
                   layer).
    """
    has_line_data = any("lines_both" in entry for entry in overlap.values())
    line_overlap = any(entry.get("lines_both", 0) > 0 for entry in overlap.values())

    only_generated = all(
        entry["files"] and entry["files"] == entry.get("generated_files", [])
        for entry in overlap.values()
    )

    if line_overlap or (not has_line_data and not only_generated):
        severity = "high"
    elif only_generated:
        severity = "medium"
    else:
        severity = "medium"

    if severity == "high":
        suggestion = (
            f"Rebase {feature_b} onto {feature_a} (or vice versa) before "
            f"opening a PR — they touch the same file(s)."
        )
    elif only_generated:
        suggestion = (
            "Both features touch generated/lockfile-style files. Likely "
            "auto-mergeable; re-run the dep installer after rebasing."
        )
    else:
        suggestion = (
            "Same files modified but disjoint lines. Should auto-merge but "
            "worth a glance before opening a PR."
        )
    return severity, suggestion


# ── line-level helper ────────────────────────────────────────────────────

def _line_overlap(
    workspace: Workspace,
    repo_name: str,
    feature_a: str,
    feature_b: str,
    files: list[str],
) -> dict[str, int]:
    """Aggregate per-file line-range intersections into single counters.

    Reads ``git diff --unified=0`` for each (feature → base) pair and
    parses the ``@@`` hunk headers to extract the changed line ranges in
    the *new* file. Intersects per file, then sums.
    """
    try:
        state = workspace.get_repo(repo_name)
    except KeyError:
        return {"lines_a_only": 0, "lines_b_only": 0, "lines_both": 0}
    base = state.config.default_branch
    repo_path = state.abs_path

    ranges_a = _file_line_ranges(repo_path, base, feature_a, files)
    ranges_b = _file_line_ranges(repo_path, base, feature_b, files)
    a_only = b_only = both = 0
    for f in files:
        ra = ranges_a.get(f, [])
        rb = ranges_b.get(f, [])
        a_lines = _lines_in_ranges(ra)
        b_lines = _lines_in_ranges(rb)
        a_only += len(a_lines - b_lines)
        b_only += len(b_lines - a_lines)
        both += len(a_lines & b_lines)
    return {"lines_a_only": a_only, "lines_b_only": b_only, "lines_both": both}


_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _file_line_ranges(
    repo_path: Path,
    base: str,
    branch: str,
    files: list[str],
) -> dict[str, list[tuple[int, int]]]:
    """Read ``git diff --unified=0`` and return per-file ``[(start, len), …]``."""
    if not files:
        return {}
    out: dict[str, list[tuple[int, int]]] = {f: [] for f in files}
    try:
        diff_out = git._run_ok(
            ["diff", "--unified=0", "--no-color",
             f"{base}...{branch}", "--", *files],
            cwd=repo_path,
        )
    except git.GitError:
        return out

    current_file: str | None = None
    for line in diff_out.split("\n"):
        if line.startswith("diff --git "):
            current_file = None
        elif line.startswith("+++ "):
            # +++ b/<path>
            current_file = line[6:].strip() if line.startswith("+++ b/") else None
        elif line.startswith("@@") and current_file in out:
            m = _HUNK_HEADER.match(line)
            if not m:
                continue
            start = int(m.group(1))
            length = int(m.group(2)) if m.group(2) else 1
            if length > 0:
                out[current_file].append((start, length))
    return out


def _lines_in_ranges(ranges: list[tuple[int, int]]) -> set[int]:
    s: set[int] = set()
    for start, length in ranges:
        s.update(range(start, start + length))
    return s
