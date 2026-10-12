# Codex entry

Read [the shared project conventions](shared/project-conventions.md) when working in this repository.

Codex skill entrypoints live in `platforms/codex/skills/`; Claude entrypoints live in
`platforms/claude/skills/`. Shared Python and sandbox code stays in `skills/`.
Edit the shared source rather than copying implementations into platform folders.

For multi-agent work, the current session owns dispatch and integration. Use Astra
for complex plans or consequential review when its configured model is available;
keep ordinary tasks with the current coordinator. Consult `config/codex.json` for
role choices. Read-only investigations can run in parallel. Delegated `/auto` code
execution uses agy, the native Claude broker in `shared/claude-local-workflow.md`,
or the Claude cloud bridge. Cloud results return through local
sandbox verification and reviewed-patch apply; cloud execution and native Codex
subagents do not inherit agy's guard. See `shared/cloud-workflow.md` for cloud
funding and transport limits.
