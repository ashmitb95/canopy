"""
Tests for the GraphQL thread API added in T1.

Four tests covering:
1. list_review_threads — returns structured thread + comment data with thread IDs
2. resolve_thread mutation — gh CLI invoked with correct shape
3. reply_to_thread mutation — returns comment url
4. get_review_comments — includes thread_id on each comment dict
"""
from unittest.mock import patch, MagicMock
import json
import pytest


def _mock_graphql_response(response_body):
    """Patch the subprocess call gh api graphql makes."""
    proc = MagicMock(returncode=0, stdout=json.dumps(response_body), stderr="")
    return patch("subprocess.run", return_value=proc)


def test_list_review_threads_returns_thread_ids(tmp_path):
    fake = {
        "data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": [
            {"id": "PRRT_abc", "isResolved": False, "resolvedAt": None,
              "comments": {"nodes": [{
                "databaseId": 1, "path": "a.py", "line": 1,
                "body": "fix this", "author": {"login": "cursor"},
                "createdAt": "2026-05-20T10:00:00Z",
                "url": "https://github.com/o/r/pull/1#x"}]}},
            {"id": "PRRT_def", "isResolved": True, "resolvedAt": "2026-05-25T11:30:00Z",
              "comments": {"nodes": [{
                "databaseId": 2, "path": "b.py", "line": 2,
                "body": "done", "author": {"login": "human"},
                "createdAt": "2026-05-21T10:00:00Z",
                "url": "https://github.com/o/r/pull/1#y"}]}},
        ]}}}}
    }
    with _mock_graphql_response(fake):
        from canopy.integrations.github import list_review_threads
        threads = list_review_threads(tmp_path, "o", "r", 1)
    assert len(threads) == 2
    assert threads[0]["thread_id"] == "PRRT_abc"
    assert threads[0]["is_resolved"] is False
    assert threads[1]["resolved_at"] == "2026-05-25T11:30:00Z"


def test_resolve_thread_mutation_called(tmp_path):
    fake = {"data": {"resolveReviewThread": {"thread": {"id": "PRRT_abc", "isResolved": True}}}}
    with _mock_graphql_response(fake) as m:
        from canopy.integrations.github import resolve_thread
        result = resolve_thread(tmp_path, "PRRT_abc")
    assert result["is_resolved"] is True
    # Verify the gh CLI was invoked with the right shape
    args = m.call_args.args[0]
    assert "graphql" in args
    assert "resolveReviewThread" in " ".join(args)


def test_reply_to_thread_mutation_called(tmp_path):
    fake = {"data": {"addPullRequestReviewThreadReply": {"comment": {
        "id": "C_1", "url": "https://github.com/o/r/pull/1#r"}}}}
    with _mock_graphql_response(fake):
        from canopy.integrations.github import reply_to_thread
        result = reply_to_thread(tmp_path, "PRRT_abc", "Tracking in DOC-1.")
    assert result["url"].endswith("#r")


def test_get_review_comments_includes_thread_id(tmp_path):
    """After T1, every comment dict has a thread_id field."""
    fake_threads = {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": [
        {"id": "PRRT_abc", "isResolved": False, "resolvedAt": None, "comments": {"nodes": [
            {"databaseId": 1, "path": "a.py", "line": 1, "body": "b",
              "author": {"login": "u"}, "createdAt": "2026-05-20T10:00:00Z",
              "url": "https://github.com/o/r/pull/1#x"}]}},
    ]}}}}}
    with _mock_graphql_response(fake_threads):
        from canopy.integrations.github import get_review_comments
        comments, resolved_count = get_review_comments(tmp_path, "o", "r", 1)
    assert comments[0]["thread_id"] == "PRRT_abc"
