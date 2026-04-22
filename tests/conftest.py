"""
Shared test fixtures for Canopy tests.

Creates a realistic multi-repo workspace with two Git repos (api + ui),
each with a main branch and some commits.
"""
import os
import subprocess
from pathlib import Path

import pytest


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
    _create_repo(ws / "api", {
        "src/app.py": "from models import User\n\ndef main():\n    pass\n",
        "src/models.py": "class User:\n    name: str\n    email: str\n",
        "requirements.txt": "flask\n",
    })

    # Create ui repo
    _create_repo(ws / "ui", {
        "src/App.tsx": "export default function App() { return <div>Hello</div> }\n",
        "src/types.ts": "export interface User { name: string; email: string; }\n",
        "package.json": '{"name": "ui", "version": "1.0.0"}\n',
    })

    return ws


@pytest.fixture
def workspace_with_feature(workspace_dir):
    """Workspace with a feature branch in both repos.

    Creates 'auth-flow' branch in both api and ui with some commits.
    """
    api = workspace_dir / "api"
    ui = workspace_dir / "ui"

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
name = "api"
path = "./api"
role = "backend"
lang = "python"

[[repos]]
name = "ui"
path = "./ui"
role = "frontend"
lang = "typescript"
"""
    (workspace_dir / "canopy.toml").write_text(toml_content)
    return workspace_dir
