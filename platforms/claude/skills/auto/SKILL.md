---
name: auto
description: Delegate coding through Antigravity or Claude cloud when the user invokes /auto or requests an external coding worker. Claude triages, briefs, reviews, verifies and integrates. Excludes Q&A synthesis and delegated production, SSH or deployment work.
---

# Delegated coding in Claude Code

Read [the shared coding workflow](workflow.md) for every `/auto` task, including L0.
Claude in this session owns the brief, review, verification and integration.
[Routing](routing.json) provides the L1/L2 models.

For suitable GitHub tasks, prefer confirmed unexpired cloud credits when that
matches the user's funding preference. Read the [cloud workflow](cloud-workflow.md)
for the official CLI bridge and import/verification gates. Check actual allowance;
unknown funding is not permission to use an API. Otherwise use the existing agy
route when its included allowance is available. A Claude cloud worker should
complete its bounded brief, not recursively dispatch new cloud workers.

Handle operational/security L0 work directly; an explicit cloud preference can
still apply to ordinary small GitHub changes. For L3, design first and split implementation into precise
briefs. If independent implementations are useful, the `agy_routes.l3` route supplies the
existing two-model option; each gets its own run and isolated tree. Review and
verify the chosen/combined patch rather than trusting either report.

```bash
W="$HOME/.claude/skills/auto/agy_worker.py"
python3 "$W" run --repo "$PWD" --brief '<brief.md>' --model '<agy-model>' \
  --platform claude --coordinator-model '<actual-model-or-current>' \
  --task-id '<task-id>' --name '<slug>'
```

Choose independent review separately from execution using the shared workflow's
criteria, including small L0 changes with meaningful acceptance uncertainty. Use a
suitable available native review model explicitly when a different-model pass is
warranted; an inherited same-model Agent is not cross-model review. Give it fresh,
bounded read-only context and disclose unavailable or unconfirmed model choices.
Avoid duplicating the worker's entire implementation effort. Native
agents do not inherit agy's guard or sandbox. Keep worker/imported code verification
sandboxed and apply only the reviewed SHA; direct L0 edits use the shared workflow's
coordinator checks. Follow the user's authorization for commits and
external actions, and report material denials or review flags.

End with the shared workflow's **模型调用说明**: actual coordinator, invoked
review/planning agents and execution models/channels, including failed attempts.
Configured routes alone are not evidence of a call.
