"use strict";
(() => {
  // webview/preview/showcase.ts
  var ask = "Search buries documents edited this week (ENG-482). Rank recent edits higher, without breaking the existing filters.";
  var plan = "Rank recent edits higher: a recency boost in ranker.ts, then a test and the docs.";
  var context = "Findings: ranker.ts scores by text match only; updatedAt is indexed but never read. Filters run before scoring, so a boost cannot change which documents match. Plan: phase 1 adds a recency boost that decays over 7 days, capped at 1.5x. Phase 2 adds a test that a 2-day-old document outranks an older equal match, and documents the boost.";
  function showcaseSteps() {
    const started2 = () => new Date(Date.now() - 2e3).toISOString();
    const base = {
      id: "showcase",
      title: "Rank recent edits higher",
      lead: "claude",
      target: "claude",
      active: [],
      queue: [],
      members: [
        { agent: "claude", status: "idle", activity: "" },
        { agent: "codex", status: "idle", activity: "", mode: "accept-edits", modes: ["ask", "accept-edits", "full-access"] },
        { agent: "grok", status: "idle", activity: "" }
      ],
      roster: { plan: "claude", research: "claude", implement: "codex", review: "grok" },
      delegations: [],
      violations: [],
      userQuestions: [],
      quotas: {},
      laneId: "search-recency"
    };
    const phase = (n) => ({
      id: `p${n}`,
      lead: "claude",
      agent: "codex",
      role: "implement",
      series: "plan",
      phase: n,
      phases: 2,
      task: n === 1 ? "Add a recency boost to the ranker" : "Test the boost and document it",
      doneWhen: n === 1 ? "Recent documents score higher and the search tests pass." : "A test covers the boost and the docs describe it.",
      context,
      status: "planned",
      added: ["1 message from the chat, word for word", "The search-recency lane: goal, plan, and notes", ...n === 2 ? ["Phase 1's report and changed files"] : []]
    });
    const review = {
      id: "rv",
      lead: "claude",
      agent: "grok",
      role: "review",
      task: "Review the recency boost against the plan",
      doneWhen: "",
      context: "What changed: ranker.ts gains a recency boost, with a test and docs. Check it against the plan, and that filters still run before scoring.",
      status: "planned",
      added: ["The plan and both phase reports"]
    };
    const facts1 = { files: ["M	search/ranker.ts", "M	search/score.ts"], commands: [{ command: "pnpm test search", failed: false }], verify: { command: "pnpm test", ok: true, output: "214 passed" }, violations: [] };
    const facts2 = { files: ["A	search/ranker.test.ts", "M	docs/search.md"], commands: [{ command: "pnpm test search", failed: false }], verify: { command: "pnpm test", ok: true, output: "216 passed" }, violations: [] };
    const report1 = "Done. ranker.ts multiplies the match score by a recency boost: 1.5x today, falling to 1x after 7 days. Filters are untouched.\nSTATUS: done";
    const report2 = "Done. A 2-day-old document now outranks an older equal match, and docs/search.md explains the boost.\nSTATUS: done";
    const report3 = "Matches the plan. Filters still run before scoring, and the boost is capped. One note: the 7 days could be a setting later.\nSTATUS: done";
    const steps = [];
    const at = (t, message) => steps.push([t, message]);
    const item = (t, agent, value, delegation) => {
      at(t, { type: "groupItem", agent, item: value, ...delegation ? { delegation } : {} });
    };
    const said = (t, agent, id, text, delegation, streaming = false) => item(t, agent, { kind: "message", id, role: "assistant", text, streaming }, delegation);
    const tool = (t, agent, id, title, toolKind, status, delegation, output) => item(t, agent, { kind: "tool", id, title, toolKind, status, ...output ? { output } : {} }, delegation);
    const handoff = (t, agent, id, delegation) => item(t, agent, { kind: "message", id, role: "user", parts: [{ type: "text", text: `You are ${agent}, delegated this by claude in a group chat run by Canopy.` }] }, delegation);
    const members = (working, activity) => base.members.map((member) => member.agent === working ? { ...member, status: "running", activity } : member);
    const state = (t, working, activity, delegations) => at(t, { type: "groupState", state: { ...base, delegations, ...working ? { running: working, active: [working], members: members(working, activity) } : {} } });
    at(0, { type: "groupSnapshot", state: base, items: [] });
    item(300, "claude", { kind: "message", id: "u1", role: "user", parts: [{ type: "text", text: ask }] });
    state(700, "claude", "read ranker.ts", []);
    tool(800, "claude", "l-t1", "Read search/ranker.ts", "read", "done");
    tool(1200, "claude", "l-t2", "Grep updatedAt", "search", "done");
    tool(1500, "claude", "l-t3", "Read search/ranker.test.ts", "read", "done");
    said(1900, "claude", "l-m1", "ranker.ts scores by text match only.", void 0, true);
    said(2500, "claude", "l-m1", `ranker.ts scores by text match only. \`updatedAt\` is indexed but never read, and filters run before scoring, so a boost can't change what matches.

${plan} Implement belongs to Codex, so I'm handing it over in two phases with the plan.`);
    const p1 = phase(1);
    const p2 = phase(2);
    const s1 = started2();
    state(3300, "codex", "read ranker.ts", [{ ...p1, status: "running", startedAt: s1 }, p2]);
    handoff(3300, "codex", "c-h1", "p1");
    said(3700, "codex", "c-m1", "Starting from the plan: the boost goes in ranker.ts, scoring only.", "p1");
    tool(4100, "codex", "c-t1", "Read search/ranker.ts", "read", "done", "p1");
    tool(4400, "codex", "c-t2", "Read search/score.ts", "read", "done", "p1");
    state(4800, "codex", "edit ranker.ts", [{ ...p1, status: "running", startedAt: s1 }, p2]);
    tool(4800, "codex", "c-t3", "Edit search/ranker.ts", "edit", "done", "p1");
    tool(5200, "codex", "c-t4", "Edit search/score.ts", "edit", "done", "p1");
    state(5600, "codex", "$ pnpm test search", [{ ...p1, status: "running", startedAt: s1 }, p2]);
    tool(5600, "codex", "c-t5", "Run pnpm test search", "execute", "running", "p1");
    tool(6500, "codex", "c-t5", "Run pnpm test search", "execute", "done", "p1", "Test Files  12 passed (12)\n     Tests  214 passed (214)");
    said(6800, "codex", "c-m2", report1, "p1");
    const done1 = { ...p1, status: "done", startedAt: s1, report: report1, facts: facts1, handoff: "/handoff-1.md", snapshots: [] };
    const s2 = started2();
    state(7400, "codex", "read ranker.test.ts", [done1, { ...p2, status: "running", startedAt: s2 }]);
    handoff(7400, "codex", "c-h2", "p2");
    said(7800, "codex", "c-m3", "Phase 1's boost is in. Adding the test next.", "p2");
    tool(8200, "codex", "c-t6", "Read search/ranker.test.ts", "read", "done", "p2");
    tool(8600, "codex", "c-t7", "Edit search/ranker.test.ts", "edit", "done", "p2");
    const approval = (resolved) => ({
      kind: "approval",
      id: "c-a1",
      title: "Allow Codex to run this command?",
      detail: "pnpm test search --update-snapshots",
      options: [
        { id: "allow", label: "Allow once" },
        { id: "allowForSession", label: "Allow for this session" },
        { id: "deny", label: "Deny" }
      ],
      ...resolved ? { resolved } : {}
    });
    item(9100, "codex", approval(), "p2");
    item(11e3, "codex", approval("allowForSession"), "p2");
    state(11e3, "codex", "$ pnpm test search", [done1, { ...p2, status: "running", startedAt: s2 }]);
    tool(11100, "codex", "c-t8", "Run pnpm test search --update-snapshots", "execute", "running", "p2");
    tool(12e3, "codex", "c-t8", "Run pnpm test search --update-snapshots", "execute", "done", "p2", "Test Files  13 passed (13)\n     Tests  216 passed (216)");
    tool(12300, "codex", "c-t9", "Edit docs/search.md", "edit", "done", "p2");
    said(12700, "codex", "c-m4", report2, "p2");
    const done2 = { ...p2, status: "done", startedAt: s2, report: report2, facts: facts2, handoff: "/handoff-2.md", snapshots: [] };
    const s3 = started2();
    state(13300, "grok", "read the diff", [done1, done2, { ...review, status: "running", startedAt: s3 }]);
    handoff(13300, "grok", "g-h1", "rv");
    said(13700, "grok", "g-m1", "Checking the change against the plan.", "rv");
    tool(14100, "grok", "g-t1", "Run git diff main -- search/ docs/", "execute", "done", "rv", "4 files changed, 61 insertions(+), 6 deletions(-)");
    tool(14600, "grok", "g-t2", "Read search/ranker.ts", "read", "done", "rv");
    said(15200, "grok", "g-m2", report3, "rv");
    const done3 = { ...review, status: "done", startedAt: s3, report: report3, facts: { files: [], commands: [{ command: "git diff main -- search/ docs/", failed: false }], violations: [] }, handoff: "/handoff-3.md", snapshots: [] };
    state(15800, "claude", "Writing", [done1, done2, done3]);
    said(16e3, "claude", "l-m2", "Both phases are in and checked.", void 0, true);
    said(16600, "claude", "l-m2", "Both phases are in and checked: 4 files changed, and Canopy's own test run passed with 216 tests. Grok found no problems; it suggests making the 7-day window a setting later. Filters behave as before.");
    state(17e3, void 0, "", [done1, done2, done3]);
    return steps;
  }

  // webview/preview/scenario.ts
  var record = {
    id: "s1",
    providerId: "claude",
    title: "Fix flaky retry test",
    createdAt: "2026-10-28T10:00:00.000Z",
    updatedAt: "2026-10-28T10:04:00.000Z",
    mode: "ask",
    hasTurns: true,
    laneId: "retry-fix",
    facts: {
      model: { kind: "model", current: "opus", available: [{ id: "opus", label: "Opus 5.5" }, { id: "sonnet", label: "Sonnet 5.5" }] },
      effort: { kind: "effort", current: "high", available: ["low", "medium", "high", "xhigh"] },
      mode: { kind: "mode", current: "ask", available: ["ask", "accept-edits", "plan", "full-access"] },
      context: { kind: "context", usedTokens: 76e3, maxTokens: 2e5 },
      mcp: {
        kind: "mcp",
        servers: [
          { name: "screenscribe", status: "connected", scope: "user", tools: ["analyze_video", "extract_frames"] },
          { name: "claude.ai Notion", status: "needs-auth", scope: "claudeai", tools: [] },
          { name: "linear", status: "failed", scope: "project", tools: [], error: "Connection refused" }
        ]
      }
    }
  };
  var items = [
    {
      kind: "message",
      id: "u1",
      role: "user",
      parts: [
        { type: "text", text: "The retry test in api.test.ts fails about one run in five. Find out why and fix it." },
        { type: "file", path: "/work/src/api.test.ts", range: [40, 72] }
      ]
    },
    { kind: "turn", id: "t1", state: "started" },
    {
      kind: "thought",
      id: "th1",
      text: "The failure rate suggests a timing race rather than a logic bug. The test uses fake timers, so the order of advanceTimersByTime against the retry scheduling matters.",
      streaming: false
    },
    { kind: "tool", id: "tool1", title: "Read /work/src/retry.ts", toolKind: "read", status: "done", paths: ["/work/src/retry.ts"] },
    { kind: "tool", id: "tool2", title: "Grep advanceTimersByTime", toolKind: "search", status: "done" },
    {
      kind: "tool",
      id: "tool3",
      title: "Bash pnpm vitest run api.test.ts",
      toolKind: "execute",
      status: "failed",
      output: "\u2713 api.test.ts > parses response (3ms)\n\xD7 api.test.ts > retries with backoff"
    },
    {
      kind: "plan",
      id: "plan",
      entries: [
        { text: "Find why the retry test is flaky", status: "done" },
        { text: "Schedule the backoff synchronously", status: "in_progress" },
        { text: "Run the test 20 times", status: "pending" }
      ]
    },
    {
      kind: "message",
      id: "a1",
      role: "assistant",
      streaming: false,
      text: "Found it. The test advances the clock before `retry()` has scheduled its backoff, so the timer sometimes fires after the assertion.\n\nI'll schedule the delay synchronously:\n\n```ts\nawait sleep(delay)\nreturn attempt(n + 1)\n```"
    },
    {
      kind: "diff",
      id: "tool4:diff",
      path: "/work/src/retry.ts",
      oldText: "setTimeout(() => attempt(n + 1), delay)",
      newText: "await sleep(delay)\nreturn attempt(n + 1)"
    },
    { kind: "tool", id: "tool5", title: "Read /work/src/sleep.ts", toolKind: "read", status: "done", paths: ["/work/src/sleep.ts"] },
    { kind: "tool", id: "tool6", title: "Read /work/src/api.ts", toolKind: "read", status: "done", paths: ["/work/src/api.ts"] },
    {
      kind: "message",
      id: "m-math",
      role: "assistant",
      streaming: false,
      text: "The backoff grows as $$d_n = d_0 \\cdot 2^n$$ and the flow is:\n\n```mermaid\ngraph LR\n  A[request] --> B{ok?}\n  B -- no --> C[wait d_n]\n  C --> A\n```"
    },
    {
      kind: "approval",
      id: "approval:1",
      title: "Allow Claude to run this command?",
      detail: "pnpm vitest run api.test.ts --repeat 20",
      options: [
        { id: "allow", label: "Allow once" },
        { id: "always", label: "Always allow" },
        { id: "deny", label: "Deny" }
      ]
    }
  ];
  var earlier = [
    {
      kind: "message",
      id: "u0",
      role: "user",
      parts: [
        { type: "command", name: "review" },
        { type: "text", text: "Add a retry helper with exponential backoff." },
        { type: "pasted", text: Array.from({ length: 48 }, (_, line) => `log line ${line + 1}`).join("\n") }
      ]
    },
    { kind: "turn", id: "t0", state: "ended", stopReason: "success", at: "2026-10-28T09:58:00.000Z" },
    {
      kind: "message",
      id: "a0",
      role: "assistant",
      streaming: false,
      text: "Added `retry()` in `src/retry.ts` with exponential backoff, capped at 3 attempts."
    },
    { kind: "diff", id: "d0", path: "/work/src/retry.ts", oldText: null, newText: "export async function retry() {\n  // \u2026\n}" }
  ];
  var claude = {
    id: "claude",
    label: "Claude",
    installUrl: "https://example.invalid",
    capabilities: ["steer", "effort"],
    modes: ["ask", "accept-edits", "plan", "full-access"],
    state: { status: "signed-in", account: "me@example.com", version: "2.1.311" }
  };
  var codex = { ...claude, id: "codex", label: "Codex", state: { status: "signed-out", version: "0.164.0" } };
  var grokInfo = { ...claude, id: "grok", label: "Grok", state: { status: "not-installed" } };
  var providers = { type: "providers", providers: [claude, codex, grokInfo] };
  var chat = [
    providers,
    { type: "assets", attachments: "about:blank" },
    {
      type: "quota",
      providerId: "claude",
      quota: {
        observedAt: new Date(Date.now() - 3 * 6e4).toISOString(),
        windows: [
          { label: "5-hour", usedPercent: 42, resetsAt: new Date(Date.now() + 2 * 36e5).toISOString(), status: "ok" },
          { label: "Weekly", usedPercent: 18, status: "ok" }
        ]
      }
    },
    {
      type: "sessions",
      sessions: [
        { id: "s1", title: "Fix flaky retry test", providerId: "claude", status: "needs-input", updatedAt: "2026-10-28T10:04:00.000Z", inTab: false, laneId: "retry-fix" },
        { id: "s2", title: "Refactor auth middleware", providerId: "claude", status: "idle", updatedAt: "2026-10-28T09:00:00.000Z", inTab: true },
        { id: "s3", title: "Token rotation", providerId: "codex", status: "idle", updatedAt: "2026-10-28T08:00:00.000Z", inTab: false, laneId: "auth-refresh" }
      ]
    },
    { type: "lanes", lanes: [{ name: "retry-fix", where: "api main \u25CF2 \xB7 ui worktree" }, { name: "auth-refresh", where: "ui worktree" }] },
    { type: "provider", provider: claude },
    { type: "editorContext", context: { path: "/work/src/api.test.ts", label: "src/api.test.ts", range: [40, 72] } },
    {
      type: "session",
      sessionId: "s1",
      event: {
        type: "snapshot",
        record,
        status: "needs-input",
        items: [...earlier, ...items],
        queue: [{ id: "q1", parts: [{ type: "text", text: "Also add a regression test that runs the retry with real timers." }] }]
      }
    }
  ];
  var prompts = [
    { kind: "message", id: "pu1", role: "user", parts: [{ type: "text", text: "Plan the retry fix." }] },
    {
      kind: "approval",
      id: "approval:plan",
      title: "Ready to code?",
      subject: {
        kind: "plan",
        text: "1. Schedule the backoff with `await sleep(delay)`.\n2. Add a regression test with real timers.\n3. Run the suite 20 times.",
        filePath: "/work/.claude/plans/retry.md"
      },
      options: [
        { id: "approve:ask", label: "Approve \xB7 Ask before edits" },
        { id: "approve:accept-edits", label: "Approve \xB7 Accept edits" },
        { id: "approve:auto", label: "Approve \xB7 Auto" },
        { id: "keep-planning", label: "Keep planning" }
      ]
    },
    {
      kind: "question",
      id: "question:1",
      questions: [
        {
          id: "q1",
          header: "Backoff",
          question: "Which backoff should the retry use?",
          multiSelect: false,
          allowOther: true,
          options: [
            { id: "o1", label: "Exponential", description: "100ms, 200ms, 400ms\u2026" },
            { id: "o2", label: "Fixed", description: "250ms every time" }
          ]
        },
        { id: "q2", question: "Which suites should run?", multiSelect: true, allowOther: true, options: [{ id: "o1", label: "api" }, { id: "o2", label: "ui" }] }
      ]
    }
  ];
  var groupState = {
    id: "g1",
    title: "Export timeouts",
    lead: "claude",
    target: "claude",
    running: "grok",
    active: ["grok"],
    queue: [],
    members: [
      { agent: "claude", status: "idle", activity: "" },
      { agent: "codex", status: "idle", activity: "" },
      { agent: "grok", status: "running", activity: "Reading export.ts" }
    ],
    roster: { plan: "claude", implement: "codex", review: "grok" },
    delegations: [
      {
        id: "d1",
        lead: "claude",
        agent: "codex",
        role: "implement",
        task: "Stream invoice rows and fix retries, per the plan.",
        doneWhen: "The 50,000-row test passes.",
        status: "done",
        report: "Done. Old endpoint kept. Exports over 1M rows warn first, as you chose.\nSTATUS: done",
        facts: { files: ["M	api/export.ts", "M	api/queue.ts"], commands: [{ command: "pnpm test", failed: false }], verify: { command: "pnpm test", ok: true, output: "215 passed" }, violations: [] },
        added: ["3 messages from the chat, word for word", "The export-timeouts lane: goal, plan, notes, and what changed"],
        answers: [{ question: "Keep the old /export endpoint?", answer: "Yes, from your first message.", by: "claude" }],
        handoff: "/tmp/handoff.md",
        snapshots: []
      },
      {
        id: "d2",
        lead: "claude",
        agent: "grok",
        role: "review",
        task: "Check the change against the plan.",
        doneWhen: "",
        status: "running",
        added: ["2 messages from the chat, word for word", "Codex's handoff and the lane plan"]
      }
    ],
    violations: [{ id: "v1", agent: "grok", files: ["M	api/export.ts"], before: [] }],
    userQuestions: [],
    quotas: {}
  };
  var brief = (agent, role, task) => `You are ${agent}, delegated this by claude in a group chat run by Canopy, in the ${role} role.
Task: ${task}`;
  var groupItems = [
    { agent: "claude", item: { kind: "message", id: "gu1", role: "user", parts: [{ type: "text", text: "Exports time out on large invoices (ENG-214). Keep the CSV format and the old endpoint." }] } },
    { agent: "claude", item: { kind: "message", id: "ga1", role: "assistant", text: "export.ts loads every row into memory. I'd stream rows and restart retries from an empty file. Plan saved to the lane.", streaming: false } },
    { agent: "codex", item: { kind: "message", id: "gc0", role: "user", parts: [{ type: "text", text: brief("codex", "implement", "Stream invoice rows and fix retries, per the plan.") }] }, delegation: "d1" },
    { agent: "codex", item: { kind: "message", id: "gc1", role: "assistant", text: "Reading export.ts first.", streaming: false }, delegation: "d1" },
    { agent: "codex", item: { kind: "tool", id: "gt1", title: "Run pnpm test", toolKind: "execute", status: "done", output: "215 passed" }, delegation: "d1" },
    { agent: "claude", item: { kind: "message", id: "ga2", role: "assistant", text: "Codex is done and the tests pass. Sending it to Grok for review.", streaming: false } },
    { agent: "grok", item: { kind: "message", id: "gg0", role: "user", parts: [{ type: "text", text: brief("grok", "review", "Check the change against the plan.") }] }, delegation: "d2" },
    { agent: "grok", item: { kind: "message", id: "gg1", role: "assistant", text: "Reading the plan, then the diff.", streaming: false }, delegation: "d2" },
    { agent: "grok", item: { kind: "message", id: "gg1u", role: "user", parts: [{ type: "text", text: "Commit as you go, please." }] }, delegation: "d2" },
    { agent: "grok", item: { kind: "tool", id: "gg2", title: "Read export.ts", toolKind: "read", status: "done" }, delegation: "d2" },
    { agent: "grok", item: { kind: "tool", id: "gg3", title: "Run git diff main -- api/", toolKind: "execute", status: "running" }, delegation: "d2" }
  ];
  var started = new Date(Date.now() - 95e3).toISOString();
  var states = (status, extra = {}) => ({ id: status + (extra.task ?? ""), lead: "claude", agent: "codex", role: "implement", task: extra.task ?? `Shown ${status}`, doneWhen: "", status, ...extra });
  var statesGroup = {
    ...groupState,
    running: "codex",
    active: ["codex"],
    members: [
      { agent: "claude", status: "idle", activity: "" },
      { agent: "codex", status: "running", activity: "Editing export.ts", mode: "ask", modes: ["ask", "accept-edits", "full-access"] },
      { agent: "grok", status: "idle", activity: "" }
    ],
    delegations: [
      states("running", { task: "Working", startedAt: started }),
      states("queued", { task: "Up next", agent: "grok", role: "review" }),
      states("question", { task: "Asked the lead", report: "STATUS: question CSV or JSON?", startedAt: started }),
      states("question", { task: "Needs your answer", report: "STATUS: question Block or warn?", startedAt: started }),
      states("done", { task: "Report ready", startedAt: started, handoff: "/x", facts: { files: ["M	a.ts"], commands: [], verify: { command: "pnpm test", ok: true, output: "" }, violations: [] } }),
      states("failed", { task: "Failed", startedAt: started, report: "pnpm install could not reach the registry", facts: { files: ["M	a.ts"], commands: [], violations: [] } }),
      states("stopped", { task: "Stopped by you", startedAt: started, facts: { files: ["M	a.ts"], commands: [], violations: [] } }),
      states("queued", { task: "Resuming after reload", resuming: true, startedAt: started }),
      states("question", { task: "Paused", rounds: 6, report: "STATUS: question again?", startedAt: started, handoff: "/x" })
    ],
    userQuestions: [
      { id: "u1", from: "codex", delegation: "questionNeeds your answer", question: "Exports over 1 million rows could take minutes. Block them, or warn and continue?" },
      { id: "u2", from: "codex", delegation: "questionPaused", question: "We have gone back and forth five times. Which format?" }
    ],
    violations: [{ id: "v1", agent: "grok", files: ["M	api/export.ts"], before: [] }]
  };
  var scenario = new URLSearchParams(location.search).get("scenario");
  var messages = scenario === "new" ? [
    providers,
    { type: "signInProgress", providerId: "codex", progress: { step: "link", url: "https://auth.openai.com/oauth/authorize?x=1" } },
    { type: "empty" }
  ] : scenario === "new-lane" ? [
    {
      type: "newLane",
      data: {
        repos: ["api", "ui"],
        agents: [
          { id: "claude", label: "Claude", ready: true },
          { id: "codex", label: "Codex", ready: true },
          { id: "grok", label: "Grok", ready: true }
        ],
        roster: { lead: "claude", research: "grok", implement: "grok", review: "codex" },
        issues: [],
        notes: []
      }
    },
    {
      type: "newLaneIssues",
      issues: [
        { source: "linear", id: "ENG-214", title: "Exports time out on large invoices", url: "" },
        { source: "github", id: "#482", title: "Dark mode loses contrast in tables", url: "" },
        { source: "linear", id: "ENG-198", title: "Add audit log for admin actions", url: "" }
      ],
      notes: [],
      pick: "ENG-214"
    }
  ] : scenario === "review" ? [
    {
      type: "review",
      review: {
        groupId: "g1",
        title: "Export timeouts",
        laneId: "export-timeouts",
        inPrimary: false,
        delegations: [
          { id: "d1", agent: "claude", role: "research", task: "Find why large exports time out", status: "done", report: "export.ts loads every row into memory. Streaming fixes it without changing the response.", violations: [], commands: 4, failedCommands: 0, undone: false, handoff: true, files: [] },
          {
            id: "d2",
            agent: "codex",
            role: "implement",
            task: "Stream rows in the export and fix retries",
            status: "done",
            report: "Done. The old endpoint is kept. Exports over 1M rows warn first.",
            verify: { command: "pnpm test", ok: true },
            violations: [],
            commands: 9,
            failedCommands: 1,
            undone: false,
            handoff: true,
            files: [
              { path: "api/export.ts", added: 3, removed: 2, lines: ["@@ -10,6 +10,7 @@ export async function exportCsv(invoice, res) {", "-  const rows = await loadAll(invoice)", "-  return toCsv(rows)", "+  const cursor = openCursor(invoice)", "+  if ((await cursor.count()) > 1_000_000) warnLarge(res)", "+  return streamCsv(cursor, res)", " }"] },
              { path: "api/queue.ts", added: 1, removed: 1, lines: ["@@ -3,3 +3,3 @@", "-const RETRIES = 0", "+const RETRIES = 3"] }
            ]
          },
          { id: "d3", agent: "grok", role: "review", task: "Review the export change", status: "done", report: "Passes. One note: exports have no progress indicator.", violations: ["wrote api/export.ts"], commands: 2, failedCommands: 0, undone: false, handoff: true, files: [] }
        ]
      }
    }
  ] : scenario === "setup" ? [
    {
      type: "setup",
      setup: {
        agents: [
          { id: "claude", label: "Claude", status: "signed-in", version: "2.1", installUrl: "" },
          { id: "codex", label: "Codex", status: "signed-in", account: "ChatGPT account", version: "0.160", installUrl: "" },
          { id: "grok", label: "Grok", status: "signed-out", installUrl: "" },
          { id: "gemini", label: "Gemini", status: "not-installed", installUrl: "" }
        ],
        roster: { lead: "claude", research: "", implement: "codex", review: "grok", enforce: true, verify: "pnpm test", questionsTo: "lead" },
        workspace: { name: "my-workspace", maxSlots: 4, worktrees: true, envFiles: [".env*"], repos: [{ name: "api", base: "main", setup: "pnpm install", envFiles: [".env*"] }, { name: "ui", base: "main", envFiles: [".env*"] }] },
        github: "signed-in",
        linear: false,
        palette: "paper"
      }
    }
  ] : scenario === "lanes" ? [
    // The chat view shows lanes when empty; the lane tab ignores this.
    { type: "empty" },
    {
      type: "laneCards",
      lanes: [
        { name: "auth-flow", goal: "Move sign-in to the new session API", place: "primary", paths: [], dirty: 3, chats: 2, status: { agent: "claude", text: "Idle", tone: "idle" }, shared: [{ path: "api/session.ts", added: 120, removed: 4 }, { path: "ui/SignIn.tsx", added: 77, removed: 58 }] },
        { name: "export-timeouts", goal: "Stream invoice exports and fix retries", place: "warm", paths: ["api/.worktrees/wt-1"], dirty: 0, chats: 1, status: { agent: "claude", text: "Finished \xB7 9m ago", tone: "done" } },
        { name: "billing-export", goal: "CSV export for invoices", place: "warm", paths: ["api/.worktrees/wt-2"], dirty: 1, chats: 1, status: { agent: "codex", text: "Needs you", tone: "needs" } },
        { name: "search-ranking", goal: "Rank recent documents higher", place: "warm", paths: ["api/.worktrees/wt-3"], dirty: 0, chats: 1, status: { agent: "grok", text: "Working \xB7 reading search.ts", tone: "working" } },
        { name: "pdf-preview", place: "cold", paths: [], dirty: 0, chats: 0 },
        { name: "old-theme", place: "cold", paths: [], dirty: 0, chats: 0 }
      ]
    }
  ] : scenario === "side" ? [
    {
      type: "side",
      side: {
        lanes: [
          { name: "auth-flow", where: "api primary \u25CF2", primary: true, warm: false, dirty: 2 },
          { name: "export-timeouts", where: "api worktree \u25CF1", primary: false, warm: true, dirty: 1 },
          { name: "billing-export", where: "api worktree", primary: false, warm: true, dirty: 0 },
          { name: "search-ranking", where: "api worktree", primary: false, warm: true, dirty: 0 },
          { name: "pr960-trusted-origin", where: "api branch", primary: false, warm: false, dirty: 0 }
        ],
        groups: [
          { id: "g1", title: "Export timeouts", lead: "claude", running: "codex", activity: "$ node --test", needsYou: false, agents: ["claude", "codex", "grok"], laneId: "export-timeouts" },
          { id: "g2", title: "Billing CSV", lead: "grok", needsYou: true, agents: ["grok", "claude"], laneId: "billing-export" }
        ],
        sessions: [{ id: "s9", title: "Sign-in screens", providerId: "claude", status: "idle", updatedAt: "2026-10-28T08:00:00.000Z", inTab: false, unread: true, laneId: "auth-flow" }]
      }
    }
  ] : scenario === "flow" ? [providers] : scenario === "showcase" ? [providers, { type: "groupComposer", composer: { agent: "claude", sessionId: "m1", provider: claude, facts: record.facts, mode: "ask" } }] : scenario === "states" ? [providers, { type: "groupSnapshot", state: statesGroup, items: [] }] : scenario === "group" ? [
    providers,
    { type: "groupSnapshot", state: { ...groupState, queue: [{ id: "q9", target: "codex", text: "Once Grok is done, tighten the retry test." }] }, items: groupItems },
    { type: "groupComposer", composer: { agent: "claude", sessionId: "m1", provider: claude, facts: record.facts, mode: "accept-edits" } }
  ] : scenario === "prompts" ? [
    providers,
    { type: "provider", provider: claude },
    { type: "session", sessionId: "s1", event: { type: "snapshot", record, status: "needs-input", items: prompts, queue: [] } }
  ] : chat;
  function flowSteps() {
    const brief2 = "You are codex, delegated this by claude in a group chat run by Canopy, in the implement role.\nTask: Stream invoice rows and fix retries";
    const user = { agent: "claude", item: { kind: "message", id: "f-u1", role: "user", parts: [{ type: "text", text: "Large invoice exports time out (ENG-214). Keep the CSV format and the old endpoint." }] } };
    const lead = (id, text, streaming = false) => ({ agent: "claude", item: { kind: "message", id, role: "assistant", text, streaming } });
    const codex2 = (item2) => ({ agent: "codex", item: item2, delegation: "f-d1" });
    const base = {
      id: "flow",
      title: "Export timeouts",
      lead: "claude",
      target: "claude",
      active: [],
      queue: [],
      members: [
        { agent: "claude", status: "idle", activity: "" },
        { agent: "codex", status: "idle", activity: "" },
        { agent: "grok", status: "idle", activity: "" }
      ],
      roster: { plan: "claude", implement: "codex", review: "grok" },
      delegations: [],
      violations: [],
      userQuestions: [],
      quotas: {},
      laneId: "export-timeouts"
    };
    const started2 = new Date(Date.now() - 4e3).toISOString();
    const task = {
      id: "f-d1",
      lead: "claude",
      agent: "codex",
      role: "implement",
      task: "Stream invoice rows and fix retries",
      doneWhen: "The 50,000-row export test passes.",
      context: "Findings: export.ts loads every row before writing the CSV, and retries append to the partial file. Plan: stream rows through a cursor in export.ts, restart retries from an empty file in queue.ts, keep the CSV format and the old endpoint, add a 50,000-row test.",
      added: ["3 messages from the chat, word for word", "The export-timeouts lane: goal, plan, notes, and what changed"],
      startedAt: started2
    };
    const working = (activity, extra = {}) => ({
      ...base,
      running: "codex",
      active: ["codex"],
      members: base.members.map((member) => member.agent === "codex" ? { ...member, status: "running", activity } : member),
      delegations: [{ ...task, status: "running" }],
      ...extra
    });
    const steps = [[0, { type: "groupSnapshot", state: base, items: [user] }]];
    const item = (at, entry) => steps.push([at, { type: "groupItem", agent: entry.agent, item: entry.item, ...entry.delegation ? { delegation: entry.delegation } : {} }]);
    const state = (at, value) => steps.push([at, { type: "groupState", state: value }]);
    state(500, { ...base, running: "claude", active: ["claude"] });
    item(700, lead("f-l1", "export.ts loads every row into memory", true));
    item(1100, lead("f-l1", "export.ts loads every row into memory, and retries append to the partial file. I'll stream the rows and reset retries. Implement belongs to Codex, so I'm handing it over with the plan."));
    state(1500, working("Reading export.ts"));
    item(1500, codex2({ kind: "message", id: "f-c0", role: "user", parts: [{ type: "text", text: brief2 }] }));
    item(1900, codex2({ kind: "message", id: "f-c1", role: "assistant", text: "Reading export.ts and queue.ts first.", streaming: false }));
    item(2300, codex2({ kind: "tool", id: "f-t1", title: "Read export.ts", toolKind: "read", status: "done" }));
    item(2600, codex2({ kind: "tool", id: "f-t2", title: "Read queue.ts", toolKind: "read", status: "done" }));
    state(2900, working("Editing export.ts"));
    item(2900, codex2({ kind: "message", id: "f-c2", role: "assistant", text: "Streaming rows through a cursor, then resetting the file on retry.", streaming: false }));
    item(3300, codex2({ kind: "tool", id: "f-t3", title: "Edit export.ts", toolKind: "edit", status: "done" }));
    item(3600, codex2({ kind: "tool", id: "f-t4", title: "Edit queue.ts", toolKind: "edit", status: "done" }));
    item(3900, codex2({ kind: "tool", id: "f-t5", title: "Edit export.test.ts", toolKind: "edit", status: "done" }));
    state(4200, working("$ pnpm test"));
    item(4200, codex2({ kind: "tool", id: "f-t6", title: "Run pnpm test", toolKind: "execute", status: "running" }));
    item(5e3, codex2({ kind: "tool", id: "f-t6", title: "Run pnpm test", toolKind: "execute", status: "done", output: "Tests  215 passed (215)" }));
    item(5300, codex2({ kind: "message", id: "f-c3", role: "assistant", text: "Done. The export streams, retries start clean, and the 50,000-row test passes.\nSTATUS: done", streaming: false }));
    const done = {
      ...task,
      status: "done",
      handoff: "/handoff.md",
      snapshots: [],
      report: "Done. The export streams, retries start clean, and the 50,000-row test passes.\nSTATUS: done",
      facts: { files: ["M	api/export.ts", "M	api/queue.ts", "A	api/export.test.ts"], commands: [{ command: "pnpm test", failed: false }], verify: { command: "pnpm test", ok: true, output: "215 passed" }, violations: [] }
    };
    state(5700, { ...base, running: "claude", active: ["claude"], delegations: [done] });
    item(6e3, lead("f-l2", "Codex is done, and the test run checked independently passed: 3 files changed, 215 tests pass. The CSV format and the old endpoint are unchanged."));
    state(6400, { ...base, delegations: [done] });
    return steps;
  }
  setTimeout(() => {
    for (const message of messages) window.postMessage(message, "*");
    if (scenario === "flow") for (const [at, message] of flowSteps()) setTimeout(() => window.postMessage(message, "*"), at);
    const play = () => {
      const steps = showcaseSteps();
      for (const [at, message] of steps) setTimeout(() => window.postMessage(message, "*"), at);
      if (!new URLSearchParams(location.search).has("once")) setTimeout(play, (steps.at(-1)?.[0] ?? 0) + 6e3);
    };
    if (scenario === "showcase") play();
  }, 100);
})();
