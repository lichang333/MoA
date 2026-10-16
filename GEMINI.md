# Antigravity / Gemini entry

Read [the shared project conventions](shared/project-conventions.md) when working in this repository.

Antigravity / Gemini skill entrypoints live in `platforms/gemini/skills/` (aliased as
`platforms/agy/skills/`); Claude entrypoints live in `platforms/claude/skills/`; Codex
entrypoints live in `platforms/codex/skills/`. Shared Python and sandbox code stays in `skills/`.
Edit the shared source rather than copying implementations into platform folders.

For multi-agent work, the current Antigravity session owns dispatch, subagents and integration.
Consult `config/gemini.json` for role choices. Read-only investigations can run in parallel
using native Antigravity subagents. Delegated `/auto` code execution uses an isolated agy worker
via `agy_worker.py`, the native Claude broker in `shared/claude-local-workflow.md`, or the Claude
cloud bridge. Cloud results return through local sandbox verification and reviewed-patch apply;
cloud execution does not inherit agy's guard. See `shared/cloud-workflow.md` for cloud
funding and transport limits.
