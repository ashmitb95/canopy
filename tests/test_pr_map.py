from canopy.actions import pr_map


def test_pr_map_exposes_pr_mapping_functions():
    assert callable(pr_map._fetch_open_prs)
    assert callable(pr_map._group_by_feature)
    assert callable(pr_map._select_repos)


def test_pr_map_imports_no_review_filter():
    import inspect
    src = inspect.getsource(pr_map)
    assert "review_filter" not in src
    assert "classify_threads" not in src
