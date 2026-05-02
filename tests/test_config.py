"""Tests for workspace.config module."""
import pytest
from pathlib import Path
from canopy.workspace.config import (
    load_config, validate_config,
    ConfigNotFoundError, ConfigError,
    WorkspaceConfig, RepoConfig,
)


def test_load_config(canopy_toml):
    config = load_config(canopy_toml / "canopy.toml")

    assert config.name == "test-workspace"
    assert len(config.repos) == 2
    assert config.repos[0].name == "repo-a"
    assert config.repos[0].role == "backend"
    assert config.repos[0].lang == "python"
    assert config.repos[1].name == "repo-b"
    assert config.repos[1].role == "frontend"


def test_load_config_from_directory(canopy_toml):
    config = load_config(canopy_toml)
    assert config.name == "test-workspace"


def test_load_config_not_found(tmp_path):
    with pytest.raises(ConfigNotFoundError):
        load_config(tmp_path / "nonexistent.toml")


def test_load_config_missing_name(tmp_path):
    (tmp_path / "canopy.toml").write_text("""
[workspace]

[[repos]]
name = "repo-a"
path = "./repo-a"
""")
    with pytest.raises(ConfigError, match="Missing.*name"):
        load_config(tmp_path)


def test_load_config_no_repos(tmp_path):
    (tmp_path / "canopy.toml").write_text("""
[workspace]
name = "test"
""")
    with pytest.raises(ConfigError, match="No.*repos"):
        load_config(tmp_path)


def test_load_config_duplicate_repo_names(tmp_path):
    (tmp_path / "canopy.toml").write_text("""
[workspace]
name = "test"

[[repos]]
name = "repo-a"
path = "./repo-a"

[[repos]]
name = "repo-a"
path = "./api2"
""")
    with pytest.raises(ConfigError, match="Duplicate"):
        load_config(tmp_path)


def test_validate_config_valid(canopy_toml):
    config = load_config(canopy_toml)
    warnings = validate_config(config)
    assert len(warnings) == 0


def test_validate_config_missing_path(tmp_path):
    config = WorkspaceConfig(
        name="test",
        repos=[RepoConfig(name="missing", path="./nonexistent")],
        root=tmp_path,
    )
    warnings = validate_config(config)
    assert len(warnings) == 1
    assert "does not exist" in warnings[0]


def test_validate_config_not_git(tmp_path):
    (tmp_path / "notgit").mkdir()
    config = WorkspaceConfig(
        name="test",
        repos=[RepoConfig(name="notgit", path="./notgit")],
        root=tmp_path,
    )
    warnings = validate_config(config)
    assert len(warnings) == 1
    assert "not a git repository" in warnings[0]


def test_default_branch_override(tmp_path):
    (tmp_path / "canopy.toml").write_text("""
[workspace]
name = "test"

[[repos]]
name = "legacy"
path = "./legacy"
default_branch = "master"
""")
    config = load_config(tmp_path)
    assert config.repos[0].default_branch == "master"


# ── [augments] block (M2) ────────────────────────────────────────────────


def test_augments_block_parsed(tmp_path):
    (tmp_path / "canopy.toml").write_text("""
[workspace]
name = "test"

[augments]
preflight_cmd = "make check"
test_cmd = "pytest"
review_bots = ["coderabbit", "korbit"]

[[repos]]
name = "api"
path = "./api"
""")
    config = load_config(tmp_path)
    assert config.augments == {
        "preflight_cmd": "make check",
        "test_cmd": "pytest",
        "review_bots": ["coderabbit", "korbit"],
    }


def test_augments_missing_block_defaults_to_empty(tmp_path):
    (tmp_path / "canopy.toml").write_text("""
[workspace]
name = "test"

[[repos]]
name = "api"
path = "./api"
""")
    config = load_config(tmp_path)
    assert config.augments == {}
    assert config.repos[0].augments == {}


def test_augments_per_repo_override(tmp_path):
    (tmp_path / "canopy.toml").write_text("""
[workspace]
name = "test"

[augments]
preflight_cmd = "make check"

[[repos]]
name = "api"
path = "./api"
augments = { preflight_cmd = "uv run pytest tests/fast" }

[[repos]]
name = "ui"
path = "./ui"
""")
    config = load_config(tmp_path)
    api = next(r for r in config.repos if r.name == "api")
    ui = next(r for r in config.repos if r.name == "ui")
    assert api.augments == {"preflight_cmd": "uv run pytest tests/fast"}
    assert ui.augments == {}


def test_augments_block_must_be_table(tmp_path):
    # `augments = "..."` must be at top level, not under [workspace], for it
    # to land at data["augments"]. Quoted-string value triggers the type check.
    (tmp_path / "canopy.toml").write_text("""
augments = "not a table"

[workspace]
name = "test"

[[repos]]
name = "api"
path = "./api"
""")
    with pytest.raises(ConfigError, match="augments.*must be a table"):
        load_config(tmp_path)


def test_per_repo_augments_must_be_table(tmp_path):
    (tmp_path / "canopy.toml").write_text("""
[workspace]
name = "test"

[[repos]]
name = "api"
path = "./api"
augments = "not a table"
""")
    with pytest.raises(ConfigError, match="augments must be a table"):
        load_config(tmp_path)


def test_augments_preserves_unknown_keys(tmp_path):
    """Lenient parser — future augments don't require schema migration."""
    (tmp_path / "canopy.toml").write_text("""
[workspace]
name = "test"

[augments]
future_key = "value"
another = 42

[[repos]]
name = "api"
path = "./api"
""")
    config = load_config(tmp_path)
    assert config.augments["future_key"] == "value"
    assert config.augments["another"] == 42
