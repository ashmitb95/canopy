# Canopy - A Multi-provider, multi-repo orchestration tool

<p align="center">
  <img src="media/canopy-icon.png" alt="Canopy logo: a tree of worktrees with an agent at the hub" width="180">
</p>

**Claude, Codex, Grok, and any ACP agent working together in VS Code, on your own subscriptions.**

You talk to one lead in one chat. The lead does the research, writes the plan, and hands each part to the agent you picked for that kind of work: Codex implements, Grok reviews, Claude researches, or any mix you like. Canopy writes the handoffs, shows you each agent's work as it happens, and checks the results itself before anyone calls a job done. Each piece of work lives in its own lane, a branch with its own worktree in every repo it touches, so agents never trip over each other or over the code you are running.

![The lead hands an implementation task to Codex, Codex's card streams its work, and Canopy records the files changed and the test result before the lead reports back](media/readme/chat.gif)

## Install

Install [Canopy from the VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=SingularityInc.canopy), or run:

```sh
code --install-extension SingularityInc.canopy
```

Then open Canopy from the activity bar. Setup walks you through connecting your agents.

## How it works

- **One chat, any lead.** Start a chat with Claude, Codex, or Grok in charge, and switch the lead whenever you like. A message goes to the lead unless you `@mention` another agent, and it goes straight away, even while others are working.
- **Roles you set once.** Pick who does Research, Implement, and Review. The lead hands each kind of work to its agent without being asked. With roles enforced, only the implementer can change code; everyone else is read-only.
- **Handoffs written for you.** The lead passes on its findings and plan, so the delegate goes straight to the change instead of rediscovering the codebase. Canopy adds what the delegate missed in the chat and the lane's goal and notes.
- **Big plans, one phase at a time.** A multi-phase plan is handed over phase by phase. The next phase starts only when the last one reports done and its checks pass.
- **Watch it happen.** Each delegate's card streams what it reads, runs, and finds. Redirect it with an `@mention` or stop it from the card.
- **Facts, not claims.** When a delegate says it is done, Canopy checks. It records the files that really changed and the commands that really ran, runs your check command (say, `npm test`) itself, and waits for anything left running in the background. The lead judges the report against that record, and so can you.
- **Questions go to the lead first.** If a delegate asks something the chat already answers, the lead answers it. Product decisions come to you.
- **Undo per agent.** Every delegate's changes are snapshotted. Undo one agent's work and keep everyone else's.

## Setup

![Setup: Claude and Codex connected, Grok signed out, Gemini not installed](media/readme/setup.png)

Three steps: connect the CLIs you already use (each keeps its own sign-in), choose who does what, and tell Canopy how to set up new worktrees: the setup command and the env files to copy for each repo. Open Setup again any time from the gear in the Canopy sidebar.

## Lanes

![Lanes: auth-flow in the primary checkout, three warm worktrees, and two cold branches](media/readme/lanes.png)

A lane is a unit of work: the same branch in every repo of your workspace that has it, with one goal, plan, and set of notes.

- **The primary checkout** is the folder you cloned, where your env files and dev server live. The lane in it is the one you run.
- **Warm lanes** have a ready worktree, set up with your env files and setup command, so agents can work on them while you run something else.
- **Cold lanes** are only a branch until you warm them up.

**Run in primary** brings a lane into the primary checkouts and moves whatever was there into a worktree, uncommitted work included, across every repo in the lane, or not at all.

Start a lane from a GitHub or Linear issue: Canopy names the branch, seeds the lane's goal and notes from the issue, and opens a chat on it.

## Review

Every chat has a review screen: who did what, each agent's report, the files it changed and the checks it passed, and its diff. Undo any agent's changes, move the lane into the primary checkout to try it, or open a pull request through your own `gh` login.

## More

- Chats in the right sidebar or in editor tabs, and Conversations to browse them all. Open tabs come back after a reload.
- The full composer for whichever agent you are talking to: model, reasoning effort, permission mode, files, images, and slash commands.
- Streaming replies, reasoning, tool cards, diffs, plans, LaTeX, and Mermaid. Answer questions and allow or deny actions from the chat.
- Notifications when a chat finishes, fails, or needs you.
- MCP servers: see each server's state and tools, and sign in from the chat.
- Colors come from your VS Code theme.

## Requirements

- VS Code 1.106 or later, and Git.
- At least one agent CLI, installed and signed in:
  - Claude: Claude Code (`claude auth status`).
  - Codex: the Codex CLI or the official Codex extension (`codex login status`).
  - Grok: the Grok CLI from https://x.ai/cli, signed in with `grok login`.
  - Cursor, OpenCode, and Gemini also work, and `canopy.customAgents` adds other ACP agents.
- Optional: the GitHub CLI (`gh`) for issues and pull requests, and a Linear API key for Linear issues.

## Your accounts, your credentials

Canopy runs the agent CLIs installed on your machine, signed in the way you signed them in. It never reads, stores, or forwards your credentials, and it never calls a provider's API itself, so usage counts against your own plan with each provider. To bill Claude to an Anthropic API key instead, set `ANTHROPIC_API_KEY` before starting VS Code; Canopy tells you when that is in effect.

The only key Canopy keeps is a Linear API key, if you add one. It stays in VS Code's secret storage and is sent only to Linear.

## Looking for the Canopy CLI?

The earlier command-line Canopy now lives at [ashmitb95/canopy-cli](https://github.com/ashmitb95/canopy-cli).

## Development

See [AGENTS.md](AGENTS.md) for commands, verification, and architecture links.

## License

[MIT](LICENSE)
