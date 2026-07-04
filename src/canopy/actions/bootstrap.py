"""``canopy worktree bootstrap`` — env files, deps, IDE workspace (M6).

Three optional steps, gated per repo + per invocation:

  1. **Env file copy** — per-repo ``env_files`` lists files (relative to
     repo root) to copy from the main checkout into the worktree.
  2. **Dependency install** — per-repo ``install_cmd`` runs once in the
     worktree directory (e.g. ``uv sync`` / ``pnpm install``).
  3. **IDE workspace file** — workspace-level ``ide = "vscode"`` writes
     ``.canopy/workspaces/<feature>.code-workspace`` listing every
     worktree dir for the feature.

Each step is **off by default**. When the relevant config exists, the
caller must pass ``bootstrap=True`` (or set ``bootstrap_default = true``
in ``[workspace]``).

Failure of any step doesn't roll back the worktree — the worktree is
still valid. The caller can re-run ``canopy worktree bootstrap`` to
retry just the failed step.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from ..workspace.workspace import Workspace
from .aliases import resolve_feature
from .errors import BlockerError
from .ide_workspace import render_code_workspace

ALLOWED_STEPS = ("env", "deps", "ide", "hooks")


def bootstrap_feature(
    workspace: Workspace,
    feature: str,
    *,
    force: bool = False,
    steps: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Run all three steps for every repo in a feature.

    Args:
        workspace: loaded workspace.
        feature: feature alias.
        force: overwrite existing destination env files.
        steps: subset of {"env", "deps", "ide"} to run; default = all.

    Returns ``{feature, results: {<repo>: {env, deps}}, ide}``.
    Per-step result shape::

        env  → {status: "ok"|"skipped"|"missing_source", files_copied: [...]}
        deps → {status: "ok"|"failed"|"skipped", exit_code, duration_ms,
                stderr_tail?}
        ide  → {status: "ok"|"skipped"|"no_ide_configured", path?}
    """
    feature_name = resolve_feature(workspace, feature)
    chosen_steps = _validate_steps(steps)
    worktree_paths = _resolve_worktree_paths(workspace, feature_name)

    if not worktree_paths:
        raise BlockerError(
            code="no_worktrees",
            what=(
                f"feature '{feature_name}' is not warm in any slot "
                f"(nothing to bootstrap) — `canopy switch {feature_name}` first"
            ),
        )

    results: dict[str, dict[str, Any]] = {}
    for repo_name, worktree_path in worktree_paths.items():
        results[repo_name] = bootstrap_repo(
            workspace, feature_name, repo_name, worktree_path,
            force=force, steps=chosen_steps,
        )

    ide_result: dict[str, Any]
    if "ide" in chosen_steps and workspace.config.ide and workspace.config.ide != "none":
        ide_result = _write_ide_workspace(workspace, feature_name, worktree_paths)
    else:
        ide_result = {"status": "no_ide_configured"} if "ide" in chosen_steps else {"status": "skipped"}

    return {
        "feature": feature_name,
        "results": results,
        "ide": ide_result,
    }


def bootstrap_repo(
    workspace: Workspace,
    feature_name: str,
    repo_name: str,
    worktree_path: Path,
    *,
    force: bool = False,
    steps: Iterable[str] = ALLOWED_STEPS,
) -> dict[str, Any]:
    """Run env-copy + deps-install for a single repo's worktree."""
    chosen = set(steps)
    state = workspace.get_repo(repo_name)
    main_path = state.abs_path
    repo_config = state.config

    env_result: dict[str, Any] = {"status": "skipped", "files_copied": []}
    if "env" in chosen:
        if repo_config.env_files:
            env_result = _copy_env_files(
                repo_config.env_files, main_path, worktree_path, force=force,
            )
        else:
            env_result = {"status": "skipped", "files_copied": [],
                           "reason": "no env_files configured"}

    deps_result: dict[str, Any] = {"status": "skipped"}
    if "deps" in chosen:
        if repo_config.install_cmd:
            deps_result = _run_install(repo_config.install_cmd, worktree_path)
        else:
            deps_result = {"status": "skipped", "reason": "no install_cmd configured"}

    result: dict[str, Any] = {"env": env_result, "deps": deps_result}
    if "hooks" in chosen:
        result["hooks"] = _run_hook_install(worktree_path, repo_config)
    return result


# ── step 1: env-file copy ──────────────────────────────────────────────

def _copy_env_files(
    env_files: list[str],
    src_dir: Path,
    dst_dir: Path,
    *,
    force: bool,
) -> dict[str, Any]:
    """Copy each file relative to ``src_dir`` into ``dst_dir``.

    Missing source files surface as ``missing_source`` per file but
    don't block the others. Existing destinations are skipped unless
    ``force=True``.
    """
    copied: list[str] = []
    skipped: list[str] = []
    missing: list[str] = []
    for rel in env_files:
        src = src_dir / rel
        dst = dst_dir / rel
        if not src.exists():
            missing.append(rel)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and not force:
            skipped.append(rel)
            continue
        shutil.copy2(src, dst)
        copied.append(rel)

    if missing and not copied and not skipped:
        status = "missing_source"
    elif copied or skipped:
        status = "ok"
    else:
        status = "skipped"

    out: dict[str, Any] = {
        "status": status,
        "files_copied": copied,
    }
    if skipped:
        out["files_skipped"] = skipped
    if missing:
        out["files_missing"] = missing
    return out


# ── step 2: dep install ────────────────────────────────────────────────

def _run_install(install_cmd: str, worktree_path: Path) -> dict[str, Any]:
    """Run ``install_cmd`` in ``worktree_path`` and capture exit + duration."""
    import time
    start = time.monotonic()
    proc = subprocess.run(
        install_cmd, shell=True, cwd=worktree_path,
        capture_output=True, text=True,
    )
    duration_ms = int((time.monotonic() - start) * 1000)
    out: dict[str, Any] = {
        "status": "ok" if proc.returncode == 0 else "failed",
        "exit_code": proc.returncode,
        "duration_ms": duration_ms,
    }
    if proc.returncode != 0:
        # Tail the last few lines of stderr — full output would balloon
        # the JSON return for the dashboard. Caller can rerun manually
        # for full output if needed.
        tail = "\n".join(proc.stderr.splitlines()[-10:])
        out["stderr_tail"] = tail
    return out


# ── step: per-clone hook install ───────────────────────────────────────

def _run_hook_install(worktree_path: Path, repo_cfg) -> dict[str, Any]:
    """Install per-clone git hooks (husky-style) in a worktree.

    If package.json has a "prepare" script (husky's install hook), run it
    via the repo's package manager (idempotent, fast — no full install).
    Else if a .husky/ dir exists, point core.hooksPath at it. No-op
    otherwise.
    """
    import json as _json
    from ..git import repo as git
    pkg = worktree_path / "package.json"
    if pkg.exists():
        try:
            data = _json.loads(pkg.read_text())
            if "prepare" in (data.get("scripts") or {}):
                pm = "pnpm" if (worktree_path / "pnpm-lock.yaml").exists() else "npm"
                cp = subprocess.run([pm, "run", "prepare"], cwd=str(worktree_path),
                                    capture_output=True, text=True)
                return {"status": "ok" if cp.returncode == 0 else "failed",
                        "mechanism": f"{pm}-prepare", "exit_code": cp.returncode}
        except Exception as e:
            return {"status": "failed", "error": str(e)}
    if (worktree_path / ".husky").is_dir():
        try:
            git.set_hooks_path(worktree_path, ".husky")
            return {"status": "ok", "mechanism": "hooksPath"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}
    return {"status": "skipped", "reason": "no husky/prepare detected"}


# ── step 3: IDE workspace file ─────────────────────────────────────────

def _write_ide_workspace(
    workspace: Workspace,
    feature_name: str,
    worktree_paths: dict[str, Path],
) -> dict[str, Any]:
    """Write ``.canopy/workspaces/<feature>.code-workspace`` atomically."""
    if workspace.config.ide != "vscode":
        return {"status": "skipped",
                "reason": f"ide={workspace.config.ide!r} not supported (vscode only in v1)"}
    ws_dir = workspace.config.root / ".canopy" / "workspaces"
    ws_dir.mkdir(parents=True, exist_ok=True)
    out_path = ws_dir / f"{feature_name}.code-workspace"
    body = render_code_workspace(workspace, feature_name, worktree_paths)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(body)
    tmp.replace(out_path)
    return {"status": "ok", "path": str(out_path)}


# ── helpers ────────────────────────────────────────────────────────────

def _validate_steps(steps: Iterable[str] | None) -> set[str]:
    if steps is None:
        return set(ALLOWED_STEPS)
    chosen = set(steps)
    bad = chosen - set(ALLOWED_STEPS)
    if bad:
        raise BlockerError(
            code="unknown_bootstrap_step",
            what=f"unknown step(s): {sorted(bad)}",
            expected={"allowed_steps": list(ALLOWED_STEPS)},
        )
    return chosen


def _resolve_worktree_paths(
    workspace: Workspace, feature_name: str,
) -> dict[str, Path]:
    """Resolve each repo's warm worktree dir for ``feature_name``.

    Wave 3.0: the authoritative source is slots.json — a warm feature's
    per-repo worktrees live under its slot at
    ``.canopy/worktrees/worktree-N/<repo>``. Falls back to the legacy
    ``features.json`` ``worktree_paths`` cache for pre-3.0 workspaces (no
    slots.json). The old code read only the legacy cache, which is empty in
    3.0 — so bootstrap raised ``no_worktrees`` for every warm feature.
    """
    from . import slots as slots_mod
    from .aliases import repos_for_feature

    slot_id = slots_mod.slot_for_feature(workspace, feature_name)
    if slot_id is not None:
        out: dict[str, Path] = {}
        for repo_name in repos_for_feature(workspace, feature_name):
            p = slots_mod.slot_worktree_path(workspace, slot_id, repo_name)
            if (p / ".git").exists():
                out[repo_name] = p
        return out

    # Legacy pre-3.0 fallback: features.json worktree_paths cache.
    import json
    path = workspace.config.root / ".canopy" / "features.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    entry = data.get(feature_name) or {}
    raw = entry.get("worktree_paths") or {}
    return {repo: Path(p) for repo, p in raw.items() if p}
