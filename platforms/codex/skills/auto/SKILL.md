---
name: auto
description: Delegate coding through Antigravity or Claude cloud when the user invokes /auto or requests an external coding worker. Codex coordinates planning, review and sandboxed integration. Excludes Q&A synthesis and delegated production, SSH or deployment work.
---

# Delegated coding in Codex

Read [the shared coding workflow](workflow.md) for every `/auto` task, including L0.
It defines the isolation, review, verification and apply gates. The current session owns the
task; [routing](routing.json) supplies model roles.

Route execution and review separately using the shared workflow's review criteria.
Small L0 implementation can still need a different-model, read-only review of
identity rules, compatibility or app acceptance. Start with `native_roles.reviewer`
from [routing](routing.json); for complex architecture use the configured planner.
Select an eligible alternative if the reviewer matches the author. Use the native
subagent API's fresh-context option with an explicit model and a bounded brief;
do not rely on an inherited model as evidence of cross-model review. If the author
model is unknown, perform the available review and disclose that model diversity
is unconfirmed. If the selected reviewer is unavailable, disclose it and follow
the shared fallback policy. The current coordinator dispatches,
resolves findings, performs runtime checks and integrates the result.

`native_roles.implementer` is a preference for a future/native coding workflow,
not permission to bypass this skill's external execution boundary. Native agents
do not inherit agy's guard or macOS sandbox.

Choose the executor using task suitability and the user's funding preference.
For a GitHub task routed to confirmed unexpired Claude cloud credits under that
preference, use the
[cloud workflow](cloud-workflow.md): prepare, observe funding, launch/attach,
import the result, then sandboxed verify and reviewed-SHA apply. Credit/plan
status is observed from the account panel, not inferred from model availability.
Unknown or exhausted funding does not authorize API fallback. For local agy
execution, choose a default from `agy_routes` or a suitable Claude/GPT-OSS option
from `agy_alternatives`, following the shared workflow's availability and funding
checks. Do not substitute a native Codex/OpenAI API model ID into the agy CLI.

Prefer available included subscription allowance, following `auto_funding` in the
shared profile. GLM, DeepSeek and MiniMax are prepaid `api_advisors` for planning
and read-only review through the shared MoA runner; use them only with applicable
explicit spending authorization. Their API access is not a coding-worker adapter.
See the shared workflow's funding priority and exact advisor invocation.

On quota exhaustion, stop and preserve the partial result. Follow the shared
workflow's required decision by an available candidate from
`quota_handoff.decider_candidates` (Astra, Fable, Opus 5.5 or Muse) before any
successor model or coordinator implementation takes over. Model discovery alone
is not an automatic fallback. If none of these decision makers is available,
retain the work and report it.

```bash
W="$HOME/.agents/skills/auto/agy_worker.py"
python3 "$W" run --repo "$PWD" --brief '<brief.md>' --model '<agy-model>' \
  --platform codex --coordinator-model '<actual-model-or-current>' \
  --task-id '<task-id>' --name '<slug>'
```

The resulting metadata identifies Codex as coordinator and agy as executor. Read
the whole patch, verify in the sandbox, then apply only the reviewed SHA. Handle
execution-boundary and operational L0 work directly; a user may still choose cloud
for an ordinary small GitHub change. User-authorized scope determines commits and external actions.

End with the shared workflow's **模型调用说明**: actual coordinator, invoked
review/planning agents and execution models/channels, including failed attempts.
Configured Astra/Gemini/Claude routes alone are not evidence of a call.
