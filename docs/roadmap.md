# Roadmap

Planned work, in rough order. [lanes.md](lanes.md) and [architecture.md](architecture.md) describe what exists today.

## 1. Claude connection profiles

Named profiles for how the Claude provider connects, such as `personal` and `work`, with a switcher inside the extension. A user can have several of each type.

| Type | What the CLI gets | Where credentials live |
|---|---|---|
| **Claude account** | Its own sign-in; `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` unset | The CLI, through Anthropic's flow |
| **API key** | `ANTHROPIC_API_KEY`, optional `ANTHROPIC_BASE_URL` for a proxy | VS Code SecretStorage, or the user's environment |
| **Amazon Bedrock** | `CLAUDE_CODE_USE_BEDROCK=1`, `AWS_PROFILE`, optional `AWS_REGION` and model pins | The AWS credential chain, or `AWS_BEARER_TOKEN_BEDROCK` in SecretStorage |

Any profile can set `CLAUDE_CONFIG_DIR`, which keeps its history, settings, and MCP servers apart.

Behaviour:

- The switcher (status bar and chat header) lists configured profiles and always shows the active one. The active profile applies to new chats.
- **A chat stays on the profile it started with**, shown on its row and header. Separate config directories hold separate sessions, and work conversations must not move to a personal account or the reverse. Changing a chat's profile means forking it, with a warning, from a handoff summary.
- A profile sets environment variables on the spawned CLI only. It never edits the user's shell or CLI settings.
- AgentDeck runs the `claude` binary directly, so shell functions and aliases around it do not apply. Profiles replace them inside the extension.
- With no profile configured, the CLI's environment passes through untouched, so stop removing `ANTHROPIC_API_KEY` by default.
- Hide what a backend lacks: quota on API key and Bedrock, WebSearch on Bedrock.

To verify before building:

- Whether `env` in the profile's `settings.json` (which `/setup-bedrock` writes) overrides the variables a profile sets. A separate `CLAUDE_CONFIG_DIR` per profile avoids the conflict.
- How custom base URLs report models, context, and cost.
- How existing chats, which have no profile, map to one. Default: the default config directory.

The hard rule on credentials in [AGENTS.md](../AGENTS.md) changes with this work: never read or store Claude account credentials; API keys the user adds go only in SecretStorage and only to the CLI's environment.

## 2. Claude terms and naming

- Label the provider "Claude Agent" in menus not titled "Agents". Do not use "Claude Code" in product names or imply Anthropic's endorsement.
- Show the active sign-in method instead of steering users to one.
- Include third-party notices for the bundled Agent SDK, which is under Anthropic's Commercial Terms.

## 3. Lanes and Sessions redesign

- A collapsible **Lanes** section above **Sessions** in the primary sidebar, and a full view in an editor tab. Main is the most prominent element; warm lanes are one click from moving into main; cold lanes stay folded away.
- Session rows show state, current activity, lane, and time: needs input (with the request and inline actions), working, waiting, finished, failed, idle.
- Both become webviews, because a native tree cannot show this. Keyboard navigation and context menus must carry over.
- New status data: a current-activity line summarized from each provider's tool events.
- Show what changed in main to chats on other lanes, on their next turn.
- Park a warm lane as cold, after checking for uncommitted work.

Open: the lane layout (spine, stack, rail, or swap board).

## 4. New Worktree

One action from the Lanes section and the full view: choose an agent, optionally an issue. It creates the branch and worktree, warms it up, and opens the chat. Everything downstream already follows from the lane.

To verify: renaming a branch from the first message when no issue was chosen.

## 5. GitHub and Linear

Picking an issue seeds the lane: its goal, a link, and the description and comments in lane memory, which the brief then points every chat at. The app fetches once; agents spend no context on it.

- **GitHub:** through the user's `gh` login. AgentDeck stores no token.
- **Linear:** an API key in SecretStorage first, OAuth later.

## 6. One chat across providers

One chat for a feature, where each stage runs on its own provider: for example, Claude plans and Grok builds. See [Routed chats](#routed-chats).

## 7. Release

Name and icon, a private repository, fresh history before going public, code and security review, Windows and remote support or a stated lack of it, tests inside VS Code, Marketplace and Open VSX listings, and CI for provider version bumps.

## Routed chats

Providers cannot share a live session: each keeps its own context, in its own format. A single chat is therefore a timeline over several provider sessions.

- `SessionRecord` holds one provider session per provider, with the active one marked. The journal records which provider produced each item.
- **On a switch:** the incoming provider gets the lane brief, a handoff summary, and what changed since it last ran. A provider returning to the chat resumes its own session and gets only the delta.
- **The transcript:** one continuous conversation, with a line where each provider takes over.
- **Routing:** per-stage defaults from `[task.<id>]` in `.agentdeck/config.toml`, with a manual override in the composer.
- **Triggers:** clear events only, such as approving a plan starting Build, or Build finishing starting Review. Never inferred from a message's content. Each stage is visible and can be stopped.

Constraints:

- A handoff carries a summary, not the full context, so plans and notes must hold what matters. Lane memory already does this.
- Controls follow the active provider: model, modes, effort, fork, and rewind differ by provider.
- Rewind and fork across a provider boundary need defined behaviour. Start by limiting them to the current provider's stretch.
- This changes the rule that handoffs never advance on their own; it stays opt-in per lane.
