---
name: auto
description: Delegate coding through isolated Antigravity workers when the user invokes /auto or asks to assign implementation to Gemini or Antigravity. Codex coordinates planning, review and integration. Excludes Q&A synthesis and delegated production, SSH or deployment work.
---

# Delegated coding in Codex

Read [the shared coding workflow](workflow.md) before launching a worker. It defines
the isolation, review, verification and apply gates. The current session owns the
task; [routing](routing.json) supplies model roles.

Use native Codex subagents for independent read-only exploration and review when
helpful. For complex architecture or consequential acceptance decisions, assign
the configured Astra planner/reviewer a self-contained brief. Use the available
subagent API's fresh-context option when changing model. The current coordinator
dispatches, tracks dependencies, resolves feedback and integrates the result.
If Astra is unavailable, disclose it and retain the work in the current session.

`native_roles.implementer` is a preference for a future/native coding workflow,
not permission to bypass this skill's external execution boundary. Native agents
do not inherit agy's guard or macOS sandbox. This version delegates implementation
through agy; choose the profile's `agy_routes.l1` or `agy_routes.l2` model, not an OpenAI model ID.

```bash
W="$HOME/.agents/skills/auto/agy_worker.py"
python3 "$W" run --repo "$PWD" --brief '<brief.md>' --model '<agy-model>' \
  --platform codex --coordinator-model '<actual-model-or-current>' \
  --task-id '<task-id>' --name '<slug>'
```

The resulting metadata identifies Codex as coordinator and agy as executor. Read
the whole patch, verify in the sandbox, then apply only the reviewed SHA. Handle
L0 work directly. User-authorized scope determines commits and external actions.
