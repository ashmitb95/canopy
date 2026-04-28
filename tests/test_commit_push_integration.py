"""Integration test: commit then push end-to-end across a feature lane.

Wave 2.3 composition test. The per-action tests (test_commit.py /
test_push.py) cover the matrix; this one walks the canonical workflow
(modify both repos → commit → push --set-upstream) and asserts the
state at the bare remote afterward.
"""
import json
import os
import subprocess

import pytest

from canopy.actions.commit import commit
from canopy.actions.push import push
from canopy.git import repo as git
from canopy.workspace.config import RepoConfig, WorkspaceConfig
from canopy.workspace.workspace import Workspace


def _git(args, cwd):
    subprocess.run(
        ["git"] + args, cwd=cwd, check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )


def _make_workspace(workspace_dir) -> Workspace:
    return Workspace(WorkspaceConfig(
        name="test",
        repos=[
            RepoConfig(name="repo-a", path="./repo-a", role="x", lang="x"),
            RepoConfig(name="repo-b", path="./repo-b", role="x", lang="x"),
        ],
        root=workspace_dir,
    ))


def _features_file(workspace_dir, payload):
    canopy_dir = workspace_dir / ".canopy"
    canopy_dir.mkdir(exist_ok=True)
    (canopy_dir / "features.json").write_text(json.dumps(payload))


def test_commit_then_push_set_upstream_end_to_end(workspace_with_feature, tmp_path):
    """Full happy path: dirty → commit → push --set-upstream → remote sees branch."""
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)

    # Wire bare remotes for each repo.
    bare_paths = {}
    for repo_name in ("repo-a", "repo-b"):
        bare = workspace_with_feature / f"{repo_name}.git"
        bare.mkdir()
        _git(["init", "--bare", "-b", "main"], cwd=bare)
        _git(["remote", "add", "origin", str(bare)],
             cwd=workspace_with_feature / repo_name)
        bare_paths[repo_name] = bare

    # Modify a tracked file in each repo (simulating real WIP).
    (workspace_with_feature / "repo-a" / "src" / "models.py").write_text(
        "class User:\n    name: str\n    new_field: int\n"
    )
    (workspace_with_feature / "repo-b" / "src" / "types.ts").write_text(
        "export interface User { name: string; new: number; }\n"
    )

    commit_result = commit(ws, "wave 2.3 integration", feature="auth-flow")
    assert commit_result["feature"] == "auth-flow"
    api_sha = commit_result["results"]["repo-a"]["sha"]
    ui_sha = commit_result["results"]["repo-b"]["sha"]
    assert len(api_sha) == 40
    assert len(ui_sha) == 40

    # The commits exist locally on auth-flow.
    assert git.head_sha(workspace_with_feature / "repo-a") == api_sha
    assert git.head_sha(workspace_with_feature / "repo-b") == ui_sha

    # First push needs --set-upstream (the no_upstream blocker would catch
    # otherwise — covered in test_push.py; here we go straight to the
    # successful path).
    push_result = push(ws, feature="auth-flow", set_upstream=True)
    assert push_result["feature"] == "auth-flow"
    for repo in ("repo-a", "repo-b"):
        per = push_result["results"][repo]
        assert per["status"] == "ok"
        assert per.get("set_upstream") is True

    # Bare remote actually has the auth-flow ref now, pointing at the
    # local commit.
    for repo in ("repo-a", "repo-b"):
        local_sha = git.head_sha(workspace_with_feature / repo)
        remote_sha = subprocess.run(
            ["git", "rev-parse", "auth-flow"],
            capture_output=True, text=True, cwd=bare_paths[repo],
        ).stdout.strip()
        assert remote_sha == local_sha, f"{repo}: remote != local"

    # Second push (no new commits) is a no-op everywhere.
    again = push(ws, feature="auth-flow")
    for repo in ("repo-a", "repo-b"):
        assert again["results"][repo]["status"] == "up_to_date"
