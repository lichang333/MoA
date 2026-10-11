---
name: auto
description: Delegate coding through isolated Antigravity workers when the user invokes /auto or asks Gemini or Antigravity to implement a task. Claude triages, briefs, reviews, verifies and integrates. Excludes Q&A synthesis and delegated production, SSH or deployment work.
---

# Delegated coding in Claude Code

Read [the shared coding workflow](workflow.md) before launching a worker. Claude
in this session owns the brief, review, verification and integration; agy runs
external coding workers. [Routing](routing.json) provides the L1/L2 models.

Handle L0 work directly. For L3, design first and split implementation into precise
briefs. If independent implementations are useful, the `agy_routes.l3` route supplies the
existing two-model option; each gets its own run and isolated tree. Review and
verify the chosen/combined patch rather than trusting either report.

```bash
W="$HOME/.claude/skills/auto/agy_worker.py"
python3 "$W" run --repo "$PWD" --brief '<brief.md>' --model '<agy-model>' \
  --platform claude --coordinator-model '<actual-model-or-current>' \
  --task-id '<task-id>' --name '<slug>'
```

Use native Claude Agent calls only where they add useful read-only planning or
review; avoid duplicating the worker's entire implementation effort. Native
agents do not inherit agy's guard or sandbox. Keep verification sandboxed and
apply only the reviewed SHA. Follow the user's authorization for commits and
external actions, and report material denials or review flags.
