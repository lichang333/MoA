---
name: auto
description: Delegate coding through Antigravity or Claude cloud when the user invokes /auto or requests an external coding worker. Claude triages, briefs, reviews, verifies and integrates. Excludes Q&A synthesis and delegated production, SSH or deployment work.
---

# Delegated coding in Claude Code

Read [the shared coding workflow](workflow.md) for every `/auto` task, including L0.
Claude in this session owns the brief, review, verification and integration.
[Routing](routing.json) and its shared defaults provide `agy_routes` and
`agy_alternatives`: Gemini, Claude and GPT-OSS are eligible agy options. Choose
using the shared workflow's task, availability and allowance criteria; a model
listing does not establish quota and an agy Claude run does not use cloud credits.

For suitable GitHub tasks, use confirmed unexpired cloud credits when that
matches the user's subscription-first funding preference or an explicit task choice. Read the [cloud workflow](cloud-workflow.md)
for the official CLI bridge and import/verification gates. Check actual allowance;
unknown funding is not permission to use an API. Otherwise use the existing agy
route when its included allowance is available. A Claude cloud worker should
complete its bounded brief, not recursively dispatch new cloud workers.

Prefer available included subscription allowance, following `auto_funding` in the
shared profile. GLM, DeepSeek and MiniMax are prepaid `api_advisors` for planning
and read-only review through the shared MoA runner; use them only with applicable
explicit spending authorization. Their API access is not a coding-worker adapter.
See the shared workflow's funding priority and exact advisor invocation.

On quota exhaustion, stop and preserve the partial result. The shared workflow
requires an available `quota_handoff.decider_candidates` model (Astra, Fable,
Opus 5.5 or Muse) to decide whether and how a successor takes over. Resolve the
candidate through its actual host, rather than assuming an agy model has the same
identity. If none is callable with authorized quota, retain the work and report
the missing decision; do not substitute an unlisted model or call a paid API.

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
