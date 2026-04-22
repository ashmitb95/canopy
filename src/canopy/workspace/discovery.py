"""
Auto-detect Git repositories in a directory and generate canopy.toml.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .config import RepoConfig
from ..git import repo as git


# Extension → language mapping (by frequency)
_LANG_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".java": "java",
    ".kt": "kotlin", ".kts": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".swift": "swift",
    ".dart": "dart",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".cs": "csharp",
    ".scala": "scala",
    ".php": "php",
    ".lua": "lua",
    ".ex": "elixir", ".exs": "elixir",
}

_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", "vendor", "dist",
    "build", ".venv", "venv", ".tox", "target",
}


def discover_repos(root: Path) -> list[RepoConfig]:
    """Walk immediate children of root and find Git repositories.

    For each repo found, detect primary language and default branch.
    """
    root = root.resolve()
    repos = []

    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue

        # Check if it's a git repo — .git can be a directory (normal)
        # or a file (linked worktree)
        git_dir = child / ".git"
        if not git_dir.exists():
            continue

        lang = _detect_language(child)
        default_branch = _detect_default_branch(child)
        role = _guess_role(child.name, lang)

        # Detect worktree status
        is_linked_worktree = git_dir.is_file()
        worktree_main = None
        if is_linked_worktree:
            main_path = git.worktree_main_path(child)
            if main_path:
                worktree_main = str(main_path)

        repos.append(RepoConfig(
            name=child.name,
            path=f"./{child.name}",
            role=role,
            lang=lang,
            default_branch=default_branch,
            is_worktree=is_linked_worktree,
            worktree_main=worktree_main,
        ))

    return repos


def generate_toml(root: Path, workspace_name: str | None = None) -> str:
    """Generate a canopy.toml string for the given root directory."""
    repos = discover_repos(root)
    name = workspace_name or root.name

    lines = [
        "[workspace]",
        f'name = "{name}"',
        "",
    ]

    for repo in repos:
        lines.append("[[repos]]")
        lines.append(f'name = "{repo.name}"')
        lines.append(f'path = "{repo.path}"')
        if repo.role:
            lines.append(f'role = "{repo.role}"')
        if repo.lang:
            lines.append(f'lang = "{repo.lang}"')
        if repo.default_branch != "main":
            lines.append(f'default_branch = "{repo.default_branch}"')
        lines.append("")

    return "\n".join(lines)


def _detect_language(repo_path: Path) -> str:
    """Detect primary language by file extension frequency."""
    counts: Counter[str] = Counter()

    for item in repo_path.rglob("*"):
        if any(skip in item.parts for skip in _SKIP_DIRS):
            continue
        if item.is_file() and item.suffix in _LANG_MAP:
            counts[_LANG_MAP[item.suffix]] += 1

    if not counts:
        return ""
    return counts.most_common(1)[0][0]


def _detect_default_branch(repo_path: Path) -> str:
    """Detect the default branch from local refs.

    Works for both normal repos (.git is a directory) and linked
    worktrees (.git is a file pointing to the main repo).
    """
    git_path = repo_path / ".git"

    # For linked worktrees, use the git command directly since
    # the .git directory structure is different
    if git_path.is_file():
        return git.default_branch(repo_path)

    # Normal repo: check remote HEAD
    head_ref = git_path / "refs" / "remotes" / "origin" / "HEAD"
    if head_ref.exists():
        try:
            content = head_ref.read_text().strip()
            # "ref: refs/remotes/origin/main"
            if content.startswith("ref:"):
                return content.split("/")[-1]
        except (OSError, IndexError):
            pass

    # Check local refs for common default branch names
    for candidate in ("main", "master"):
        ref_path = git_path / "refs" / "heads" / candidate
        if ref_path.exists():
            return candidate

    # Fallback: parse HEAD for current branch
    head_file = git_path / "HEAD"
    if head_file.exists():
        try:
            content = head_file.read_text().strip()
            if content.startswith("ref: refs/heads/"):
                return content.replace("ref: refs/heads/", "")
        except OSError:
            pass

    return "main"


def _guess_role(name: str, lang: str) -> str:
    """Guess repo role from name and language."""
    name_lower = name.lower()

    backend_hints = {"api", "backend", "server", "service", "core"}
    frontend_hints = {"ui", "frontend", "web", "client", "app"}
    shared_hints = {"shared", "common", "types", "proto", "lib"}
    infra_hints = {"infra", "infrastructure", "deploy", "ops", "terraform"}

    for hint in backend_hints:
        if hint in name_lower:
            return "backend"
    for hint in frontend_hints:
        if hint in name_lower:
            return "frontend"
    for hint in shared_hints:
        if hint in name_lower:
            return "shared"
    for hint in infra_hints:
        if hint in name_lower:
            return "infra"

    # Language-based guess
    if lang in ("python", "java", "go", "rust"):
        return "backend"
    if lang in ("javascript", "typescript"):
        return "frontend"

    return ""
