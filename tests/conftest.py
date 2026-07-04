"""
Shared test fixtures for Canopy tests.

Creates a realistic multi-repo workspace with two Git repos (api + ui),
each with a main branch and some commits.
"""
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _no_background_bootstrap():
    """Tests must not spawn real detached bootstrap processes — they race
    with git/state ops on the shared tmp repos and make CI flaky. The
    background spawn's logic is covered in isolation (test_slot_bootstrap
    monkeypatches _spawn_deps_background; test_slots_concurrency tests the
    real multiprocess slots.json safety). See phase-4 CANOPY_NO_BG_BOOTSTRAP."""
    prev = os.environ.get("CANOPY_NO_BG_BOOTSTRAP")
    os.environ["CANOPY_NO_BG_BOOTSTRAP"] = "1"
    yield
    if prev is None:
        os.environ.pop("CANOPY_NO_BG_BOOTSTRAP", None)
    else:
        os.environ["CANOPY_NO_BG_BOOTSTRAP"] = prev


def _git(args: list[str], cwd: Path) -> str:
    """Run a git command in a directory."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True, cwd=cwd,
        env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
             "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"},
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def _create_repo(path: Path, files: dict[str, str], branch: str = "main") -> None:
    """Create a Git repo with initial files and commits."""
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", branch], cwd=path)
    _git(["config", "user.email", "test@test.com"], cwd=path)
    _git(["config", "user.name", "Test"], cwd=path)

    for filename, content in files.items():
        filepath = path / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content)

    _git(["add", "."], cwd=path)
    _git(["commit", "-m", "Initial commit"], cwd=path)


@pytest.fixture
def workspace_dir(tmp_path):
    """Create a multi-repo workspace with api/ and ui/ repos.

    Structure:
        workspace/
        ├── api/     (Python backend, main branch)
        │   ├── src/app.py
        │   ├── src/models.py
        │   └── requirements.txt
        └── ui/      (TypeScript frontend, main branch)
            ├── src/App.tsx
            ├── src/types.ts
            └── package.json
    """
    ws = tmp_path / "workspace"
    ws.mkdir()

    # Create api repo
    _create_repo(ws / "repo-a", {
        "src/app.py": "from models import User\n\ndef main():\n    pass\n",
        "src/models.py": "class User:\n    name: str\n    email: str\n",
        "requirements.txt": "flask\n",
    })

    # Create ui repo
    _create_repo(ws / "repo-b", {
        "src/App.tsx": "export default function App() { return <div>Hello</div> }\n",
        "src/types.ts": "export interface User { name: string; email: string; }\n",
        "package.json": '{"name": "repo-b", "version": "1.0.0"}\n',
    })

    return ws


@pytest.fixture
def workspace_with_feature(workspace_dir):
    """Workspace with a feature branch in both repos.

    Creates 'auth-flow' branch in both api and ui with some commits.
    """
    api = workspace_dir / "repo-a"
    ui = workspace_dir / "repo-b"

    # Create feature branch in api with changes
    _git(["checkout", "-b", "auth-flow"], cwd=api)
    (api / "src" / "auth.py").write_text(
        "import jwt\n\ndef authenticate(token):\n    return jwt.decode(token)\n"
    )
    (api / "src" / "models.py").write_text(
        "class User:\n    name: str\n    email: str\n    token: str\n"
    )
    _git(["add", "."], cwd=api)
    _git(["commit", "-m", "Add auth module"], cwd=api)

    # Create feature branch in ui with changes
    _git(["checkout", "-b", "auth-flow"], cwd=ui)
    (ui / "src" / "Login.tsx").write_text(
        "export default function Login() { return <form>Login</form> }\n"
    )
    (ui / "src" / "types.ts").write_text(
        "export interface User { name: string; email: string; token: string; }\n"
    )
    _git(["add", "."], cwd=ui)
    _git(["commit", "-m", "Add login page and update types"], cwd=ui)

    return workspace_dir


@pytest.fixture
def canopy_toml(workspace_dir):
    """Write a canopy.toml for the workspace."""
    toml_content = """\
[workspace]
name = "test-workspace"

[[repos]]
name = "repo-a"
path = "./repo-a"
role = "backend"
lang = "python"

[[repos]]
name = "repo-b"
path = "./repo-b"
role = "frontend"
lang = "typescript"
"""
    (workspace_dir / "canopy.toml").write_text(toml_content)
    return workspace_dir


# ── Wave 3.0 slot-model fixtures ────────────────────────────────────────


@pytest.fixture
def canopy_toml_for_workspace(workspace_with_feature):
    """canopy.toml inside the workspace_with_feature root (slots=2)."""
    toml = workspace_with_feature / "canopy.toml"
    toml.write_text("""
[workspace]
name = "test"
slots = 2

[[repos]]
name = "repo-a"
path = "repo-a"
install_cmd = "true"

[[repos]]
name = "repo-b"
path = "repo-b"
""")
    return workspace_with_feature


@pytest.fixture
def workspace_with_canonical_only(canopy_toml_for_workspace):
    """Canonical=X, no warm slots, slots=2. Y exists as a cold branch."""
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    from canopy.actions import slots as sm

    ws = Workspace(load_config(canopy_toml_for_workspace))
    for repo in ("repo-a", "repo-b"):
        subprocess.run(["git", "branch", "X"],
                       cwd=canopy_toml_for_workspace / repo, check=True)
        subprocess.run(["git", "checkout", "X"],
                       cwd=canopy_toml_for_workspace / repo, check=True)
        subprocess.run(["git", "branch", "Y"],
                       cwd=canopy_toml_for_workspace / repo, check=True)

    sm.write_state(ws, sm.SlotState(
        slot_count=2,
        canonical=sm.CanonicalEntry(
            feature="X", activated_at=sm.now_iso(),
            per_repo_paths={
                "repo-a": str(canopy_toml_for_workspace / "repo-a"),
                "repo-b": str(canopy_toml_for_workspace / "repo-b"),
            },
        ),
    ))
    return ws


@pytest.fixture
def workspace_with_slots(workspace_with_canonical_only):
    """X canonical, Y warm in worktree-1."""
    from canopy.actions.switch import switch
    # evict_to pins the vacating feature warm (the Phase-4 default would
    # send a clean, PR-less feature cold); slot ids match the old default.
    switch(workspace_with_canonical_only, "Y", evict_to="worktree-1")  # X warm slot-1
    switch(workspace_with_canonical_only, "X", evict_to="worktree-1")  # Y warm slot-1
    return workspace_with_canonical_only


@pytest.fixture
def workspace_with_full_slots(workspace_with_canonical_only):
    """slots=2; both slots filled (A and B); canonical=X."""
    ws = workspace_with_canonical_only
    for branch in ("A", "B"):
        for repo in ("repo-a", "repo-b"):
            subprocess.run(["git", "branch", branch],
                           cwd=ws.config.root / repo, check=True)
    from canopy.actions.switch import switch
    # evict_to pins each vacating feature warm (Phase-4 default sends
    # clean, PR-less features cold); slot ids match the old default.
    switch(ws, "A", evict_to="worktree-1")  # X→warm slot-1, A canonical
    switch(ws, "B", evict_to="worktree-2")  # A→warm slot-2, B canonical
    switch(ws, "X", evict_to="worktree-1")  # B→warm slot-1 (fastpath), X canonical
    # Deterministic LRU ordering: A newer, B older
    from canopy.actions import slots as sm
    state = sm.read_state(ws)
    if state is not None:
        state.last_touched["A"] = "2026-01-02T00:00:00Z"
        state.last_touched["B"] = "2026-01-01T00:00:00Z"
        sm.write_state(ws, state)
    return ws


@pytest.fixture
def workspace_with_two_warm(workspace_with_full_slots):
    """Alias for tests that don't care which features are warm."""
    return workspace_with_full_slots
