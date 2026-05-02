# Canopy Roadmap — Epic & Milestone Index

Live status of canopy's planned work. Update this file as milestones progress; each plan's frontmatter is the per-plan source of truth, this doc is the rolled-up dashboard.

**Last updated:** 2026-05-02 (M0, M1, M2, M5 shipped; M3 in-progress)
**Roadmap:** [roadmap.md](roadmap.md) — full architecture context, cross-cutting decisions, sequencing rationale

## Status legend

| Glyph | Meaning |
|---|---|
| 🟦 | queued — not started |
| 🟨 | in-progress — actively being worked |
| ✅ | shipped — merged to main |
| ⛔ | blocked — waiting on a dependency or external decision |

---

## Epic — Agent surface + dogfood-failure recoveries (2026-05)

**Goal:** ship the typed multi-repo agent surface canopy was always meant to be — recovery from setup failures, per-workspace customization, bot-comment tracking, cross-session memory, and a provider-injection pattern that makes Linear-vs-GitHub-Issues a configuration choice instead of a fork.

**Why now:** the dogfood transcript at `~/projects/canopy/canopy-improvement-research.md` exposed three load-bearing gaps (setup didn't propagate across machines, bot comments aren't first-class, no per-workspace customization). [Issue #5](https://github.com/ashmitb95/canopy/issues/5) added a fourth (Linear-vs-GitHub-Issues forking pressure). This epic closes all four.

### Core milestones (in dependency order)

- [x] ✅ **M2 — Augment skill** — [archive/augments.md](archive/augments.md) · shipped 2026-05-02
  Per-workspace `[augments]` block in canopy.toml + opt-in `augment-canopy` skill. Wires `preflight_cmd`; reserves `review_bots` (M3) and `test_cmd` (future).
- [ ] 🟨 **M3 — Bot-comment tracking** — [bot-tracking.md](bot-tracking.md) · P1 · ~3d · depends on M2
  Distinguish bot vs human review comments, `commit --address <id>`, new `awaiting_bot_resolution` state.
- [ ] 🟦 **M4 — Historian** — [historian.md](historian.md) · P1 · ~5-6d · depends on M3
  Cross-session feature memory at `.canopy/memory/<feature>.md`. Auto-read on `canopy switch`.
- [x] ✅ **M5 — Issue-provider scaffold** — [archive/issue-providers.md](archive/issue-providers.md) · shipped 2026-04-27
  Linear refactored into the contract; GitHub Issues backend. New `issue_get` / `issue_list_my_issues` MCP tools; old `linear_*` retained as deprecated aliases. Closes [#5](https://github.com/ashmitb95/canopy/issues/5).

### Quality-of-life additions (slot in alongside or after the core)

- [ ] 🟦 **M6 — Worktree bootstrap** — [worktree-bootstrap.md](worktree-bootstrap.md) · P2 · ~2d · depends on M1
- [ ] 🟦 **M7 — Sidebar single-tree (extension)** — [sidebar-single-tree.md](sidebar-single-tree.md) · P2 · ~1d
- [ ] 🟦 **M8 — Wave 2.4 `ship`** — [wave-2-4-ship.md](wave-2-4-ship.md) · P2 · ~2-3d · depends on M3
- [ ] 🟦 **M9 — Wave 4 `draft_replies`** — [wave-4-draft-replies.md](wave-4-draft-replies.md) · P2 · ~2d · depends on M3
- [ ] 🟦 **M10 — CI status integration** — [ci-status.md](ci-status.md) · P2 · ~2d · depends on M3
- [ ] 🟦 **M11 — Action drawer (extension)** — [action-drawer.md](action-drawer.md) · P3 · ~3-4d · depends on M8 + M9
- [ ] 🟦 **M12 — `canopy conflicts`** — [cross-feature-conflicts.md](cross-feature-conflicts.md) · P3 · ~1-2d

### Shipped

- [x] ✅ **M2 — Augment skill** — [archive/augments.md](archive/augments.md) · shipped 2026-05-02 (PR #10)
- [x] ✅ **M5 — Issue-provider scaffold** — [archive/issue-providers.md](archive/issue-providers.md) · shipped 2026-04-27
- [x] ✅ **M1 — `canopy doctor`** — [archive/doctor.md](archive/doctor.md) · shipped 2026-05-02
- [x] ✅ **M0 — Architecture: provider injection** — [archive/providers-arch.md](archive/providers-arch.md) · delivered as [`docs/architecture/providers.md`](../architecture/providers.md) · shipped 2026-05-02
- [x] ✅ **Wave 2.3 — `commit` + `push`** — [archive/wave-2-3-commit-push.md](archive/wave-2-3-commit-push.md) · shipped 2026-04-26

---

## Effort summary

| Bucket | Milestones | Estimate |
|---|---|---|
| Core (M3–M4) | 2 | ~8–9 days |
| Quality-of-life (M6–M12) | 7 | ~13–18 days |
| **Total queued** | **9** | **~21–27 days** |

---

## How to update this index

When a milestone changes state:

1. Update its checkbox (`[ ]` → `[x]` once shipped).
2. Update its glyph (🟦 → 🟨 → ✅).
3. Update the plan file's frontmatter (`status: queued` → `in-progress` → `shipped`). The two should always agree; frontmatter is the per-plan source of truth, this dashboard is the rolled-up view.
4. When shipped: move the plan to `archive/` and append the ship date to the entry below the "Shipped" heading.

If manual sync becomes painful, a small `scripts/sync-index.py` can read frontmatter from each plan and regenerate this file. Defer until that's actually annoying.

## Decision log (epic-level)

Things decided during planning that don't fit any single milestone:

- **2026-05-02:** "canopy upgrade" absorbed into [doctor.md](doctor.md) — same Issue/repair pattern; one unified command beats two.
- **2026-05-02:** Provider-injection scoped to issue providers only in v1 (M0+M5). Bot-author / CI / code-review / IDE-format / pre-commit-framework adoption deferred behind a < 5% effort cap.
- **2026-05-02:** Historian's "decisions" capture uses hybrid mechanism — explicit MCP tool call (primary) + Stop-hook tail-parse (backup). Format-only too unreliable; tool-only misses free-text decisions.
- **2026-05-02:** Tracking via in-tree docs instead of GitHub issues. Plan files live at `docs/plans/`; this file is the epic dashboard.
