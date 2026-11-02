# Roadmap

AgentDeck is a multi-agent, multi-provider orchestrator for large features: different providers do different work, the harness moves the work between them, and the user stays in one conversation.

Planned work, in priority order. [lanes.md](lanes.md) and [architecture.md](architecture.md) describe what exists today.

## 1. Orchestrated chats

One chat for a feature. Each stage runs on the provider set for it, for example Claude plans and Grok builds, and the harness handles every switch.

Providers cannot share a live session: each keeps its own context in its own format. A chat is therefore a timeline over several provider sessions.

- `SessionRecord` holds one provider session per provider, with the active one marked. The journal records which provider produced each item.
- The transcript is one conversation, with a marker at each takeover.
- A provider returning to the chat resumes its own session and receives only the handoffs since it last ran.
- Chats that use one provider work as they do today. Routing is opt-in per lane.

### Routing

Each stage has a default provider, model, and mode from `[task.<id>]` in `.agentdeck/config.toml`. The composer can override the next stage.

| Event | Default next step |
|---|---|
| Research finished | Plan |
| Plan approved | Build |
| Build turn finished, with its plan steps done | Review |
| Review reports changes needed | Build, up to a set number of rounds |
| Review passes | Done: notify the user |

Stages advance only on these explicit events, never by inference from a message's content. A failed turn, a rate limit, or a pending approval or question stops the chain and tells the user. The user can stop or redirect at any point.

To verify: how to tell "changes needed" from "passes" reliably. Candidates are a required verdict line in the review, or a structured output format.

### Handoff documents

The harness writes a document at every switch, without user involvement, to `.agentdeck/lanes/<lane>/handoffs/<n>-<from>-to-<to>.md`. Starting routing on a chat with no lane creates one.

| Layer | Source | Contents |
|---|---|---|
| **Facts** | The harness, no model call | The user's messages verbatim, question answers, approvals and denials, commits, diff summary, uncommitted files, commands run and their results, plan progress |
| **Reasoning** | The outgoing agent, in a hidden turn with a fixed template | Goal, what was done, decisions and why, approaches rejected, what remains, risks, where to look |
| **Record** | The journal, rendered to a readable file | The stage's complete transcript, for anything the first two layers left out |

- The incoming agent receives the document, stamped with each repo's commit. It can read the record when it needs more, so nothing is out of reach.
- The hidden turn does not appear in the transcript, and it costs the outgoing provider's usage.
- If the hidden turn fails or the provider has hit a limit, the document goes out with facts and the record only, and says so.
- Handoffs replace the current chat summary as the source for handoffs. That summary holds only a file list and the end of the last reply.

### Visibility

At a glance, the user always knows which provider is doing what:

- **Chat header:** a stage rail, such as `Plan · Claude ✓ → Build · Grok (working) → Review · Claude`, with the active stage marked. Its stages can be clicked to jump to that point.
- **Transcript:** provider avatar on each reply, and a takeover marker with a link to the handoff document.
- **During a switch:** a visible "Preparing handoff" state.
- **Sessions and Lanes:** each row shows the active provider, stage, and current activity.
- **Notifications:** name the stage and provider, and fire when the chain stops or finishes.

### Constraints

- Controls follow the active provider: model, modes, effort, fork, and rewind differ by provider.
- Rewind and fork stay within the current provider's stretch at first.
- This replaces the rule that handoffs never advance on their own. The rule that remains: only explicit events advance them.

## 2. Parallel work

Large features need more than one writer at a time, and a lane allows one. An approved plan splits into tasks, each with a provider, its own branch and worktree under the lane, and a dependency order. Tasks without dependencies run at once, and each gets a handoff document.

To design: how tasks are declared in the plan, who integrates finished branches into the lane and resolves conflicts, how failures affect dependents, and limits on concurrency and usage.

## 3. Lanes and Sessions redesign

- A collapsible **Lanes** section above **Sessions** in the primary sidebar, and a full view in an editor tab. Main is the most prominent element; warm lanes are one click from moving into main; cold lanes stay folded away.
- Session rows show state, active provider, current activity, lane, and time: needs input (with the request and inline actions), working, waiting, finished, failed, idle.
- Both become webviews, because a native tree cannot show this. Keyboard navigation and context menus must carry over.
- New status data: a current-activity line summarized from each provider's tool events.
- Show what changed in main to chats on other lanes, on their next turn.
- Park a warm lane as cold, after checking for uncommitted work.

Open: the lane layout (spine, stack, rail, or swap board).

## 4. New Worktree

One action from the Lanes section and the full view: choose an agent, optionally an issue. It creates the branch and worktree, warms it up, and opens the chat. Everything downstream follows from the lane.

To verify: renaming a branch from the first message when no issue was chosen.

## 5. GitHub and Linear

Picking an issue seeds the lane: its goal, a link, and the description and comments in lane memory, which the brief then points every chat at. The app fetches once; agents spend no context on it.

- **GitHub:** through the user's `gh` login. AgentDeck stores no token.
- **Linear:** an API key in SecretStorage first, OAuth later.

## 6. Release

- Claude terms: pass the CLI's environment through instead of removing `ANTHROPIC_API_KEY`, label the provider "Claude Agent" in menus not titled "Agents", avoid "Claude Code" in product names and any implied endorsement, and include notices for the bundled Agent SDK.
- Name and icon, a private repository, fresh history before going public, code and security review, Windows and remote support or a stated lack of it, tests inside VS Code, Marketplace and Open VSX listings, and CI for provider version bumps.

## 7. Claude connection settings (low priority)

Set up subscription, API key, and Bedrock inside AgentDeck, and switch between whichever are configured.

| Connection | What the CLI gets | Where credentials live |
|---|---|---|
| **Subscription** | Its own sign-in; `ANTHROPIC_API_KEY` unset | The CLI, through Anthropic's flow |
| **API key** | `ANTHROPIC_API_KEY`, optional `ANTHROPIC_BASE_URL` | VS Code SecretStorage |
| **Amazon Bedrock** | `CLAUDE_CODE_USE_BEDROCK=1`, `AWS_PROFILE`, optional `AWS_REGION` and model pins | The AWS credential chain, or `AWS_BEARER_TOKEN_BEDROCK` in SecretStorage |

These set environment variables on the spawned CLI only. Each chat shows its connection.

To verify: whether `env` in the CLI's `settings.json` overrides these variables, whether a session resumes across connections, and what a backend lacks (quota on API key and Bedrock, WebSearch on Bedrock).

The hard rule on credentials in [AGENTS.md](../AGENTS.md) changes with this work: never read or store Claude account credentials; API keys the user adds go only in SecretStorage and only to the CLI's environment.
