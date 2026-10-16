---
name: auto
description: Delegate coding through Antigravity worker, native Claude Code CLI or Claude cloud when the user invokes /auto or requests an external coding worker. Antigravity coordinates planning, review and sandboxed integration. Excludes Q&A synthesis and delegated production, SSH or deployment work.
---

# Delegated coding in Antigravity (Gemini)

Read [the shared coding workflow](workflow.md) for every `/auto` task, including L0.
It defines the isolation, review, verification and apply gates. The current Antigravity session owns the
task; [routing](routing.json) supplies model roles.

Route execution and review separately using the shared workflow's review criteria.
Start with `native_roles.reviewer` from [routing](routing.json); for complex architecture use the configured planner (`gemini-3.8-pro`).
Use Antigravity's subagent tools (`invoke_subagent`) with an explicit model and a bounded brief.
The current Antigravity coordinator dispatches, resolves findings, performs runtime checks and integrates the result.

Choose the executor using the shared workflow's task-fit criteria and the user's
funding preference. Model defaults are starting candidates; assess uncertainty,
failure impact and likely rework before each dispatch.
For local agy execution, `agy_worker.py` runs an isolated child worker in a separate Git worktree under macOS sandbox:

```bash
W="$HOME/.gemini/config/skills/auto/agy_worker.py"
python3 "$W" run --repo "$PWD" --brief '<brief.md>' --model '<agy-model>' \
  --platform gemini --coordinator-model '<actual-model-or-current>' \
  --task-id '<task-id>' --name '<slug>'
```

For suitable GitHub tasks routed to confirmed unexpired Claude cloud credits, use the
[cloud workflow](cloud-workflow.md): prepare, observe funding, launch/attach,
import the result, then sandboxed verify and reviewed-SHA apply.

For native Claude Code subscription execution, use the
[native CLI workflow](claude-local-workflow.md) and `claude_local.py`.

Prefer available included subscription allowance, following `auto_funding` in the
shared profile. GLM, DeepSeek and MiniMax are prepaid `api_advisors` for planning
and read-only review through the shared MoA runner; use them only with applicable
explicit spending authorization.

On quota exhaustion, stop and preserve the partial result. Follow the shared
workflow's required decision by an available candidate from
`quota_handoff.decider_candidates` before any successor model
or coordinator implementation takes over.

The resulting metadata identifies Gemini/Antigravity as coordinator and agy as executor. Read
the whole patch, verify in the sandbox, then apply only the reviewed SHA. Handle
execution-boundary and operational L0 work directly.

End with the shared workflow's **模型调用说明**: actual coordinator, invoked
review/planning agents and execution models/channels, including failed attempts.
