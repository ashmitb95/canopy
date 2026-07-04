import inspect

from canopy.management import review_ops


def test_review_ops_exposes_three_functions():
    assert callable(review_ops.review_status)
    assert callable(review_ops.review_comments)
    assert callable(review_ops.review_prep)


def test_review_ops_functions_take_workspace_first():
    for fn in (review_ops.review_status, review_ops.review_comments,
               review_ops.review_prep):
        params = list(inspect.signature(fn).parameters)
        assert params[0] == "workspace"
