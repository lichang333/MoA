# Optional evidence-review experiment — not an implemented runner mode

Adapted from the user's “MoA 协作约束与提示词指南”. This is a design proposal,
not evidence of higher accuracy, a new CLI flag or permission for paid calls.

## Proposed stages

1. Independent answers: same task and base evidence, fresh separate contexts.
2. Cross-review: target an identified participant and answer version; attach
   specific issues, evidence or testable failure conditions. No forced dissent.
3. Revision: answer each issue with accept / partly_accept / reject / undetermined,
   a short verifiable reason and a complete revised answer.
4. Synthesis: give a usable answer, supported points, unresolved disagreements,
   evidence gaps, next checks, limitations and the actual stop reason.

A review cycle is exactly stages 2 + 3. Initial answers and final synthesis
each happen once. A possible three-participant assignment is A→B, B→C, C→A,
then A→C, B→A, C→B. Reviews must bind to the latest exact answer version.

## Budget before dispatch

Use the full experiment only when its value justifies its cost. Plan at most two
cycles, with a third only when explicitly requested in advance; simple tasks
should keep the existing smaller workflow. No new default fan-out is enabled.

For three participants, one review per participant per cycle, and one final
synthesis, logical calls total 3 + cycles × 6 + 1: 10, 16 or 22 for one, two or
three cycles. Retries and tools add work. When the current coordinator synthesizes,
do not misreport it as an extra external API call. Native access is not proof of
zero resource use, and token counts are not prices.

The future orchestrator needs per-call and total limits on calls, output tokens,
elapsed time and authorized spending, with a final-summary reserve. Unknown price
or usage cannot be treated as zero. Existing subscription-first, prepaid approval
and quota-handoff rules take precedence. This document grants no spending authority.

## What code must enforce

- Fresh contexts for independent candidates; trusted evidence registry separate
  from model-written claims. Preserve source identity to prevent citation washing.
- JSON schemas for answers, reviews, issue responses and final output; validate
  required fields, enum values, unique IDs, answer versions and evidence references.
  A checked flag is accepted only when bound to a coordinator-verified record.
- At most one explicitly budgeted format repair; retain failed participants and
  incomplete review coverage rather than silently inventing missing answers.
- Stop at the budget limit, when no material feasible check remains, or when
  resolving a disagreement requires unavailable evidence or a user decision.
  Mere agreement or continued argument is not a stop/continue criterion.
- Minimal records: prompt version, requested/observed models and channels,
  answer/issue versions, evidence, actual checks, attempts, duration and observed
  usage. Retain unknown costs as unknown; exclude private reasoning and credentials.

Current implementation has independent API requests, versioned common prompts,
single-review mode, non-empty text checks, run records, partial-failure handling,
per-request HTTP timeouts and limited transport attempts. It does NOT implement
the above multi-cycle state machine, schema/reference validator, usage/price
accounting, global budgets, evidence registry or automatic format repair.

## Evaluation before adoption

Compare single-model answers, independent candidates plus synthesis, and the full
review/revision experiment on 12–20 representative tasks. Fix scoring and budgets
in advance, reserve held-out tasks, retain failures, and compare at similar resource
budgets. Prefer runnable checks and identifiable evidence. For subjective grading,
hide the generation method, randomize candidate order and avoid a participant being
the sole judge. Measure important errors, correct/incorrect revisions, uncertainty,
cost and latency; small samples do not establish universal accuracy gains.
