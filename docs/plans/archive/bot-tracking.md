---
status: shipped
priority: P1
effort: ~3d
depends_on: ["augments.md"]
shipped: 2026-05-02
---

# Bot-comment tracking + `commit --address`

## Why

PRs collect comments from multiple bots (CodeRabbit, Korbit, Cubic, Copilot) alongside human reviewers. Today canopy treats them all as one undifferentiated "review comments" stream — agents can't quickly answer "are all the bot nits resolved?" or "which commit addressed bot comment #123456?" without re-deriving from PR history.

The user's framing in the dogfood transcript: *"bot comments should be fixed and committed one by one addressing the comment title for tracking. A dev can ask: are all the bot comments in this set of PRs resolved?"*

This plan adds a distinct workflow concern: track per-comment "addressed by which commit," provide a rollup ("all bot comments resolved?"), and add a `commit --address <comment-id>` flag with auto-formatted commit messages that include the comment URL for downstream tracing.

## Goal

Treat bot review comments as a distinct workflow concern with structured persistence + a focused command. Specifically:

- Distinguish bot vs human review threads using the existing `author_type == "Bot"` signal + the configurable `review_bots` augment from N3 (per-workspace whitelist of substrings).
- Persist per-comment resolution state in `<workspace>/.canopy/state/bot_resolutions.json`.
- Add `canopy commit --address <comment-id> -m "..."` that auto-formats the commit message with the bot comment title + URL and records the resolution.
- Add `canopy bot-status [--feature <X>]` rollup CLI + MCP tool.
- Insert `awaiting_bot_resolution` state in the state machine (per architectural decision: do not gate `approved`).

## Non-goals

- Auto-posting replies to bot comments (deferred Wave 4 — `draft_replies` plan).
- Inferring resolution from commit content/diff. v1 requires explicit `--address <comment-id>` to claim resolution.
- Unifying with human-comment workflows. Humans request changes; canopy already handles that via `needs_work`. Bots produce nits; this plan handles them as a distinct, less-blocking signal.

## State machine placement

Insert `awaiting_bot_resolution` between `awaiting_review` and `approved`. Do **not** gate `approved` — human approval is the merge gate; bot nits are a side-channel.

```
drifted > needs_work (human) > in_progress > ready_to_commit
       > ready_to_push > awaiting_bot_resolution > awaiting_review
       > approved > no_prs
```

**Trigger** for `awaiting_bot_resolution` per repo:
- (a) no human `CHANGES_REQUESTED` review_decision
- (b) no actionable human threads (`actionable_human_count == 0`)
- (c) ≥1 actionable bot thread (`actionable_bot_count > 0`)
- (d) PR not yet `APPROVED`

If approved + bot threads still open: state stays `approved`; surface "address bot comments" as a *secondary* CTA in `next_actions` (not gating). Bot comments don't block merge.

## Data model changes

- `src/canopy/integrations/github.py:_normalize_comments` (line 537): include `id` field — `"id": c.get("id")`. Backward-compat (consumers ignoring the field continue working).
- **New persistent state:** `<workspace>/.canopy/state/bot_resolutions.json`. Append-only mapping `{<comment_id>: {feature, repo, commit_sha, addressed_at, comment_title}}`. Written by `commit --address`. Read by `bot_comments_status` and by `feature_state` to compute `actionable_bot_count` (subtracting resolved comments).
- `src/canopy/actions/feature_state.py:_per_repo_facts`: split `actionable_count` into `actionable_human_count` + `actionable_bot_count`. Bot determined by `author_type == "Bot"` AND author matching `bot_authors(workspace)` (uses N3's `review_bots` augment via the `bot_authors()` helper from `actions/augments.py`).
- `src/canopy/actions/feature_state.py:_decide_state`: insert `awaiting_bot_resolution` per the trigger rules above.

## New CLI / MCP surface

### `canopy commit --address <comment-id> [-m "..."]`

- Resolves `<comment-id>` against the feature's actionable bot threads (via `_per_repo_facts`).
- Looks up the comment's `body` (truncated first sentence as the title) and `url`.
- Auto-formats commit message: `<user message>\n\nAddresses bot comment: "<title-fragment>" (<url>)`. If no `--message` is given, uses just the auto-line.
- On commit success, appends to `bot_resolutions.json`.
- Returns the existing per-repo result dict with an extra `addressed_comment_id` field.

### `canopy bot-status [--feature <X>] [--unresolved-only]`

- Per-PR rollup of bot comments — total, resolved, unresolved.
- `--unresolved-only` lists just the open ones with comment URLs.
- `--json` returns the structured dict (used by the agent and the dashboard).

### MCP tool: `bot_comments_status(feature: str | None = None)`

Returns:
```python
{
  "feature": "sin-6-cache-stats",
  "repos": {
    "test-api": {
      "pr_number": 142,
      "total_bot_comments": 4,
      "resolved": 2,
      "unresolved": 2,
      "threads": [
        {"id": 123456, "author": "coderabbit", "url": "...", "resolved": True, "resolved_by_commit": "abc123de"},
        ...
      ]
    }
  },
  "all_resolved": False,
}
```

## Files to touch

- `src/canopy/integrations/github.py` (line 537) — add `"id": c.get("id")` to normalized comment dict
- `src/canopy/actions/feature_state.py` (lines 133–217 + 318–327) — split actionable counts; add `awaiting_bot_resolution` state
- `src/canopy/actions/commit.py` (line 165) — add `address: str | None = None` param; pre-process message; write to `bot_resolutions.json` on success
- **New:** `src/canopy/actions/bot_resolutions.py` — `record_resolution(workspace, comment_id, feature, repo, sha, title)`; `load_resolutions(workspace)`; `is_resolved(workspace, comment_id) -> bool`
- **New:** `src/canopy/actions/bot_status.py` — `bot_comments_status(workspace, feature) -> dict` rollup
- `src/canopy/cli/main.py` — `cmd_bot_status` + subparser; extend `cmd_commit` argparse with `--address`
- `src/canopy/mcp/server.py` — register `bot_comments_status` MCP tool
- `tests/test_bot_resolutions.py` (new) — record + load + persist round-trip
- `tests/test_bot_status.py` (new) — rollup correctness with mixed resolved/unresolved fixtures
- `tests/test_commit.py` (extended) — extend with `--address` cases (resolves comment id, message format, side-effect to `bot_resolutions.json`)
- `tests/test_feature_state.py` (extended) — extend with cases that exercise `awaiting_bot_resolution`

## Implementation order

1. Add `id` to normalized comments (`integrations/github.py:537`). Update fixtures in `tests/test_review_filter.py` and `tests/test_reads.py`.
2. New `actions/bot_resolutions.py` module — file IO for `.canopy/state/bot_resolutions.json`. Pure functions; unit-tested.
3. Split actionable counts in `_per_repo_facts`. Use the `bot_authors()` helper from N3 (or fallback to `author_type == "Bot"` if N3 not yet shipped).
4. Add `awaiting_bot_resolution` state in `_decide_state` per the trigger rules.
5. Extend `commit()` action with `--address` parameter. Resolve comment ID to title/url. Format message. Record resolution.
6. Build `bot_comments_status` rollup. CLI + MCP wiring.
7. `next_actions` updates: when state is `awaiting_bot_resolution`, surface `canopy commit --address <id> -m "..."` for each unresolved thread.

## Verification

- Unit: `bot_resolutions.py` round-trip; `bot_status.py` rollup with mixed resolved/unresolved fixtures.
- Unit: `_decide_state` returns `awaiting_bot_resolution` for the four trigger conditions; returns `approved` if also approved (per the architectural refinement).
- Integration: `workspace_with_feature` fixture + a fake bot comment fixture → `commit --address <id> -m "fix"` → assert `bot_resolutions.json` has the entry → `bot_comments_status` returns `all_resolved: true`.
- Manual: real PR with bot comments. `canopy bot-status` shows them; `canopy commit --address <id> -m "..."` produces a commit whose message includes the bot comment URL; subsequent `bot-status` shows resolved.

## Edge cases

- **Comment ID resolution from URL.** Some agents will pass the GitHub URL instead of the numeric ID. Accept both; parse the URL and extract the comment ID.
- **Comment that was deleted from GitHub.** `bot_comments_status` skips it from the unresolved list silently; the resolution log entry persists for history.
- **`commit --address` when the comment isn't a bot comment.** Rejected with `BlockerError(code='not_a_bot_comment', ...)` — `--address` is bot-specific. Future: extend to human comments via a separate flag.
- **Multiple `--address` on one commit.** v1 supports a single `--address`. Multi-address can be added later if needed (loop through and call `record_resolution` per id).
- **Concurrent `commit --address` calls.** `bot_resolutions.json` writes use atomic rename (write to temp, rename). Concurrent writes are rare but safe.

## Effort

~3 days.

## After this lands

- The dashboard's "Address bot comments" CTA (action drawer plan) becomes wirable: click → quick-pick lists unresolved bot threads → click one → command palette opens with `canopy commit --address <id> -m "..."` prefilled.
- Historian (next plan) consumes `bot_resolutions.json` + the temporal classifier output to render a "Resolutions log" section in the per-feature memory file.
- The agent answer to "is this PR ready to merge?" becomes definitive: feature_state returns `approved` only when human-side is green; bot-resolution status is a separate, surface-able signal.
