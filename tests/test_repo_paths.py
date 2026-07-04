import inspect

from canopy.actions import repo_paths


def test_resolve_repo_paths_lives_in_repo_paths():
    assert callable(repo_paths.resolve_repo_paths)


def test_repo_paths_imports_no_fat():
    src = inspect.getsource(repo_paths)
    for fat in ("github", "review_filter", "bot_resolutions", "classify_threads"):
        assert fat not in src, f"repo_paths must not reference {fat}"
