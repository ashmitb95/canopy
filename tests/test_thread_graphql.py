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


def test_author_type_from_graphql_typename(tmp_path):
    """Bot and User author __typename propagates to author_type on each comment."""
    fake = {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": [
        {"id": "PRRT_bot", "isResolved": False, "resolvedAt": None,
          "comments": {"nodes": [{
              "databaseId": 10, "path": "a.py", "line": 1,
              "body": "bot comment", "createdAt": "2026-05-20T10:00:00Z",
              "url": "https://github.com/o/r/pull/1#a",
              "author": {"login": "cursor[bot]", "__typename": "Bot"},
          }]}},
        {"id": "PRRT_human", "isResolved": False, "resolvedAt": None,
          "comments": {"nodes": [{
              "databaseId": 11, "path": "b.py", "line": 2,
              "body": "human comment", "createdAt": "2026-05-21T10:00:00Z",
              "url": "https://github.com/o/r/pull/1#b",
              "author": {"login": "alice", "__typename": "User"},
          }]}},
    ]}}}}}
    with _mock_graphql_response(fake):
        from canopy.integrations.github import get_review_comments
        comments, _ = get_review_comments(tmp_path, "o", "r", 1)

    by_path = {c["path"]: c for c in comments}
    assert by_path["a.py"]["author_type"] == "Bot"
    assert by_path["b.py"]["author_type"] == "User"


def test_resolved_count_counts_threads_not_comments(tmp_path):
    """resolved_count should be 1 for a resolved thread with 3 comments."""
    fake = {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": [
        {"id": "PRRT_resolved", "isResolved": True, "resolvedAt": "2026-05-25T00:00:00Z",
          "comments": {"nodes": [
              {"databaseId": 1, "path": "a.py", "line": 1, "body": "c1",
                "createdAt": "2026-05-20T00:00:00Z", "url": "u1",
                "author": {"login": "alice", "__typename": "User"}},
              {"databaseId": 2, "path": "a.py", "line": 2, "body": "c2",
                "createdAt": "2026-05-21T00:00:00Z", "url": "u2",
                "author": {"login": "alice", "__typename": "User"}},
              {"databaseId": 3, "path": "a.py", "line": 3, "body": "c3",
                "createdAt": "2026-05-22T00:00:00Z", "url": "u3",
                "author": {"login": "alice", "__typename": "User"}},
          ]},
        },
    ]}}}}}
    with _mock_graphql_response(fake):
        from canopy.integrations.github import get_review_comments
        comments, resolved_count = get_review_comments(tmp_path, "o", "r", 1)

    assert resolved_count == 1  # one thread resolved, not 3 comments
    assert comments == []


def test_get_review_comments_fallback_path_carries_thread_id(tmp_path, monkeypatch):
    """When GraphQL path fails, REST fallback comments must still have thread_id=''."""
    import json as _json
    from canopy.integrations import github as ghmod

    # Make GraphQL path fail
    monkeypatch.setattr(ghmod, "list_review_threads",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated")))
    # Disable MCP path
    monkeypatch.setattr(ghmod, "is_mcp_configured", lambda *a, **k: False)
    # Simulate gh CLI available
    monkeypatch.setattr(ghmod, "have_gh_cli", lambda: True)
    fake_rest = _json.dumps([{
        "id": 1, "path": "a.py", "line": 1, "body": "b",
        "user": {"login": "u", "type": "User"},
        "created_at": "2026-05-20T00:00:00Z",
        "url": "https://github.com/o/r/pull/1#r1",
    }])
    monkeypatch.setattr(ghmod, "_gh", lambda *a, **k: fake_rest)

    # GraphQL path is gated on is_github_configured — stub that too
    monkeypatch.setattr(ghmod, "is_github_configured", lambda *a, **k: False)

    from canopy.integrations.github import get_review_comments
    comments, _ = get_review_comments(tmp_path, "o", "r", 1)
    assert len(comments) == 1
    assert comments[0]["thread_id"] == ""
