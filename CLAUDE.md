# Claude entry

Read [the shared project conventions](shared/project-conventions.md) when working in this repository.

Use `platforms/claude/skills/` for Claude-specific instructions and
`config/claude.json` for routing. The current Claude session handles dispatch,
web research, synthesis and code review. External coding workers use agy, the native Claude broker in
`shared/claude-local-workflow.md`, or the explicit Claude cloud bridge in `shared/cloud-workflow.md`; shared code lives in
`skills/` and must not be duplicated here. Cloud workers complete their assigned
brief without recursively dispatching more workers.

The Codex entrypoints describe different native tools and model roles. Do not
load them as the Claude workflow or replace the Claude installation with them.
