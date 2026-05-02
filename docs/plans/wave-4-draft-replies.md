---
status: queued
priority: P2
effort: ~2d
depends_on: ["bot-tracking.md"]
---

# Wave 4 — `draft_replies` for addressed PR review threads

## Mental model

When a reviewer leaves a comment like *"please rename `foo` to `bar`"* on a PR, the canopy workflow today is:

1. User reads the comment in the dashboard's "Actionable threads" list.
2. User edits the file in the worktree, renames `foo` → `bar`.
3. User commits + pushes.
4. **User manually goes to the PR, types "Done — renamed to `bar` in <commit-sha>", clicks Reply.**

Step 4 is rote. The information needed to write that reply is all in the workspace:
- The original comment text + file:line
- The diff between the comment's commit and HEAD for that file
- The commit sha(s) that touched the relevant lines

`draft_replies` is the MCP tool that walks the open PR comments per repo, identifies which ones have been **addressed** (i.e., the file:line they reference has been modified in commits *after* the comment was posted), and emits a draft reply for each. The user reviews + posts (or edits + posts) — canopy doesn't auto-post.

This is the load-bearing automation for the dashboard's "Address comments in Claude" / "Draft replies for addressed threads" actions.

---

## Behavioral spec

`canopy draft_replies [--feature X] [--repo R] [--include-likely-resolved]`

For each open PR in the feature's repos:

1. Fetch all unresolved review comments (existing `review_comments` MCP tool already does this — reuse).
2. For each comment:
   a. Get the comment's `commit_id` (the sha at which the comment was made) and `path` + `line`.
   b. Run `git log <commit_id>..HEAD -- <path>` to find commits that touched the file after the comment.
   c. If any commits found, the comment is **addressed**.
   d. For addressed comments, generate a draft reply (see template below).
3. Return a structured list `{ feature, repos: { <repo>: { addressed: [<draft>, ...], unaddressed: [<comment>, ...] } } }`.

`--include-likely-resolved` extends the addressed set with the existing temporal classifier's "likely_resolved_threads" (already computed by `review_filter`). These are weaker signal — comments that *seem* resolved by recent activity but didn't directly touch the file:line.

### Draft format

```python
{
    "comment_id": "...",
    "comment_url": "https://github.com/.../pull/123#discussion_r456",
    "original_comment": {
        "author": "alice",
        "path": "src/api/search.py",
        "line": 18,
        "body": "rename foo to bar",
    },
    "addressing_commits": [
        {"sha": "abc123", "subject": "rename foo to bar in search", "date": "2026-04-25T10:00:00Z"},
    ],
    "draft_reply": "Done — renamed `foo` → `bar` in abc123.",
    "confidence": "high",  # high / medium / low
}
```

### Reply template

The reply text is generated from a small set of patterns based on the comment text + addressing commit subject. Order of preference:

1. **Specific commit subject match.** If the addressing commit's subject mentions the same identifier as the comment (e.g. comment says "rename foo to bar", commit subject says "rename foo to bar in search"), use: `Done — <commit subject>. (<sha>)`
2. **Generic addressed.** Fallback: `Addressed in <sha>: <commit subject>.`
3. **Multiple commits.** If 2+ commits address one comment: `Addressed across <N> commits — see <sha-list>.`

The template is deliberately simple. **No LLM call** in v1. The user reviews the draft before posting; fancy NLP isn't worth the cost/latency for a draft they'll edit anyway. (Add LLM-augmented drafts in a future Wave 4.1 if user feedback says drafts are too rote.)

`confidence`:
- `high` — single commit, file:line touched directly, commit subject mentions same keyword as comment.
- `medium` — single commit, file:line touched, no keyword match.
- `low` — multiple commits, only line range touched (not exact line). Surface but warn.

---

## State model changes

None. `draft_replies` is read-only — it generates text, doesn't post anything, doesn't update any canopy state files.

---

## Command surface changes

| Today | After Wave 4 |
|---|---|
| `canopy draft_replies` (does not exist) | New CLI command + MCP tool. |
| `canopy review` | Unchanged — read-only PR status. |
| `canopy review-comments` (CLI) / `review_comments` (MCP) | Unchanged — returns raw unresolved comments. `draft_replies` consumes its output. |

---

## Files to touch

### New

- `src/canopy/actions/draft_replies.py` — orchestrator. Fetch comments → walk file history per comment → classify addressed vs unaddressed → generate drafts.
- `tests/test_draft_replies.py` — fixture-driven cases:
  - addressed by a single commit (high confidence)
  - addressed by multiple commits (low confidence)
  - unaddressed (file untouched since comment)
  - addressed-but-no-keyword-match (medium confidence)
  - comment on deleted file (status: addressed, confidence high, special template)

### Modified

- `src/canopy/cli/main.py` — `cmd_draft_replies(args)` + subparser.
- `src/canopy/mcp/server.py` — register `@mcp.tool() draft_replies(...)`.
- `src/canopy/git/repo.py` — extend with `log_for_path(repo_path, since_sha, path)` if not already there. Returns list of `{sha, subject, date}` for commits that touched `path` after `since_sha`.
- `docs/commands.md` — `draft_replies` section.
- `docs/agents.md` — add to the review-loop recipe.
- Both skill files — list as a preferred tool when the agent is helping with PR comment triage.

---

## Tasks (rough sequence)

### T1 — `git/repo.py` — file-history primitive

`log_for_path(repo_path, since_sha, path) -> [{sha, subject, date}]`. Wraps `git -C <repo> log <since_sha>..HEAD --pretty=format:"%H|%s|%aI" -- <path>`. Empty list if no commits since.

Tests in `tests/test_repo.py`: workspace_with_feature → modify file → assert log_for_path returns the modifying commit.

### T2 — `actions/draft_replies.py` — classifier

Pure function `classify_comment(comment, file_history) -> {status, confidence, addressing_commits}`. Status is `"addressed"` or `"unaddressed"`. Confidence per the rules above. No git calls; takes pre-fetched data.

Tests: table-driven on the rule combinations.

### T3 — `actions/draft_replies.py` — reply template

Pure function `render_reply(original, addressing_commits, confidence) -> str`. The 3 template branches above.

Tests: snapshot-style — given fixture inputs, assert exact output string. Catches accidental wording drift.

### T4 — `actions/draft_replies.py` — orchestrator

Compose: per repo → fetch unresolved comments → for each comment, call `log_for_path` → call `classify_comment` → if addressed, call `render_reply` → assemble result dict.

Use the existing `actions/reads.py` helpers for the comment fetch (don't re-implement). Parallelize per repo via the existing `concurrent.futures` pattern.

Tests: end-to-end with a fixture PR that has 3 comments (1 addressed by single commit, 1 addressed by multiple, 1 unaddressed). Assert returned shape.

### T5 — CLI + MCP wrappers

CLI prints a per-comment summary table on stdout (status / confidence / draft preview). `--json` returns structured dict. MCP tool returns `result.to_dict()`.

### T6 — Docs + skills

- `docs/commands.md` — example invocation + sample output.
- `docs/agents.md` — review-loop recipe: `review_status` (find PRs) → `review_comments` (raw threads) → `draft_replies` (auto-draft addressed) → user posts → repeat.
- Skill files — flag as preferred over manually walking file histories.

---

## Edge cases to remember

- **Comment on deleted file.** `git log` against a deleted path still works (`git log -- <path>` shows the deletion commit). Treat the deleting commit as the addressing commit. Reply template: `Addressed by removing this file in <sha>.`
- **Comment on renamed file.** `git log --follow -- <path>` to track across renames. Surface the rename in the addressing commit list (keep `--follow` on by default).
- **Comment on a binary file.** Same logic — `git log` works on binary files; addressing means a commit modified them.
- **Force-push erases the comment's commit_id.** If `git cat-file -e <comment_id>` fails, mark the comment `confidence: low`, status `unaddressed`, with a warning (`comment_commit_missing: true`). The user resolved it differently; canopy can't tell.
- **Comment has no `commit_id`** (some legacy comments). Skip — return as `unaddressed` with `confidence: low`.
- **Replies already exist on the thread.** Existing `review_comments` MCP tool filters to *unresolved* threads, so a thread with replies that resolved it is already excluded. No special handling needed here.

---

## Out of scope

- Posting the drafts. `draft_replies` returns drafts; user (or a future "post replies" tool) posts them.
- LLM-augmented drafts. Template-based v1; LLM as Wave 4.1 if the templates are too rigid in practice.
- Cross-PR comment correlation (e.g. one comment that says "see also issue #123"). Out of scope.
- Conversational threading (replying to specific reply within a thread). v1 emits one draft per top-level comment.

---

## After this lands

- The dashboard's "Draft replies for addressed threads" button (Plan 5: action drawer) becomes wirable: click → call `draft_replies` → render the draft list in a modal → user reviews + clicks "Post all" or edits individually.
- The CLI gives reviewers a one-shot way to triage their own addressed comments before re-requesting review.
- The agent's review-loop becomes: find unresolved → check what's addressed → draft replies → suggest the user post them. Three MCP calls instead of N file-history walks.
