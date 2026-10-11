# Shared delegated coding workflow

The coordinator owns the brief, review, verification and integration. External
executors are Antigravity (`agy`) and the explicit [Claude cloud bridge](cloud-workflow.md).
Both start from a commit and exclude the user's uncommitted changes. Choose cloud
for suitable GitHub work with observed eligible funding; agy retains its local
guard and sandbox. Neither executor's model selection proves remaining allowance.

## Execution boundaries

- Local agy workers use `agy_worker.py`; never run skip-permissions agy separately. Its
  `AUTO_WORKER=1` guard is default-deny. Do not loosen the guard to complete a task.
- No production, SSH, deployment, credentials or live databases in worker tasks.
  The coordinator handles such work under the user's existing authorization.
- Local worker code, including imported cloud tests, runs through the macOS
  sandbox. Do not execute it unsandboxed in the user's checkout, even after review.
  Cloud execution uses Anthropic's environment and does not inherit the agy guard.
- For worker/imported patches, apply only a fully reviewed patch SHA with passing `verify --full` against the
  current target HEAD and clean target files. A new worker round requires review
  and verification of the new patch.
- Native Codex/Claude subagents do not inherit agy hooks or this sandbox. Within
  this workflow use them for read-only planning/review; delegated implementation
  uses agy or the documented cloud route. The coordinator can implement small
  changes and execution-boundary changes directly.
- Direct coordinator L0 edits require the repository's applicable checks and real
  acceptance evidence, without inventing a worker run or patch SHA. Worker-derived
  code still requires the sandbox and reviewed-patch gates, including after
  coordinator corrections.

## Triage and briefing

| Level | Task | Route |
|---|---|---|
| L0 | Small/context-heavy edit, live operation, guard/sandbox change or urgent fix | Coordinator |
| L1 | Mechanical implementation with a precise brief | Profile's `agy_routes.l1` |
| L2 | Multi-file feature or bug with clear acceptance criteria | Profile's `agy_routes.l2` |
| L3 | Architecture, ambiguity or consequential logic | Plan first, then split into L1/L2; independent review as needed |

These are the local agy defaults. An explicit cloud preference can route a small
or L1/L2 GitHub task through the cloud workflow instead; size alone is not a reason
to ignore that preference. Production/credential work and changes to the execution
guard or sandbox still stay with the coordinator.

Choose execution and independent review separately: L0 keeps implementation or
operations with the coordinator, but does not exempt the result from review.
Announce the execution level/model and the review route (or brief skip reason).
User model choices take priority when the executor supports them.
Read `routing.json` and its shared defaults, `headless.json`
(installed next to the skill; source is `config/headless.json`),
for `agy_routes`; `agy models` can confirm external
executor availability. Do not substitute an OpenAI model ID into the agy CLI.

Write a brief containing `GOAL`, `CONTEXT` (files/functions), `REQUIREMENTS`,
`CONSTRAINTS`, `ACCEPTANCE` (exact checks), and `OUT OF SCOPE`. Distinct tasks need
distinct briefs and run IDs. Keep shared-file edits sequential and reverify each
patch after integration changes HEAD. For prod-bound code such as migrations,
deployment scripts and runtime configuration, prefer coordinator implementation.

### Independent review routing

For explicit `/auto` tasks, default to one bounded, read-only review when there is
a meaningful judgment to check: ambiguous identity/grouping rules, data loss or
metadata compatibility, behavior that depends on a consuming app, consequential
logic, or a fix that previously failed acceptance. This includes small L0 changes.
Use an eligible different model from the author/coordinator where its identity is
known. Start with the platform's configured native reviewer; if it matches the
author, select a suitable available alternative within the user's model/funding
preferences. Same-model subagents are independent passes, not cross-model review.
If the author model is unknown, still perform useful available review and report
that the difference cannot be confirmed; unknown identity alone is not a fallback.

Skip extra model calls for tasks with no useful separate judgment, such as an
already-verified `git push`, a literal text correction or a known rename without
semantic effects. Do not dispatch models merely to fill roles or report more calls.
For L1/L2, the coordinator's review of a different-model worker can satisfy this
check; add another reviewer only for unresolved uncertainty or material risk.

Give the reviewer fresh context, the question/acceptance criteria, relevant diff,
representative sanitized samples and observed checks. Do not forward the entire
conversation, credentials or live-service access. Request evidence-backed findings
and missing checks; the reviewer may read artifacts but must not edit files, run
candidate code, deploy, SSH or perform live operations. The coordinator collects
needed runtime evidence and validates the actual consuming application when relevant.
Model agreement never replaces real tests or acceptance evidence.

Default to one review pass, with one focused follow-up for a material finding.
Keep context and scope proportional; stop unproductive model rounds. If the chosen
reviewer is unavailable, use an eligible native fallback if available or continue
coordinator review and disclose the limitation. Do not claim the skipped review
occurred, or switch to a paid API/external executor outside existing authorization.
An explicitly required review remains incomplete until performed or waived by the
user; this policy does not waive required checks or execution/verification gates.

## Run, inspect and revise

`W` is the installed skill's `agy_worker.py`; replace the example platform/model
with the entrypoint's actual profile and route:

```bash
python3 "$W" run --repo "$PWD" --brief '<brief.md>' --model '<agy-model>' \
  --platform codex --coordinator-model '<actual-model-or-current>' \
  --task-id '<task-id>' --name '<slug>'
```

Read the entire returned patch and note `patch_sha256`. The worker's report is a
claim; inspect the changed code and verification output. Check scope, executable
test/build changes, compatibility, correctness and accidental secrets. Review
flags have these meanings:

| Flag | Action |
|---|---|
| `PATCH_PATHS_MISMATCH`, `CAPTURE_FAILED` | Reject: capture is unreliable |
| `protected_paths` | Reject control-file changes, including `.codex`, and report |
| `sensitive_paths` | Inspect each change; send back out-of-scope production code |
| `execution_surface` | Review as executable code, including tests/build config |
| `binary_files` | Reject unless the brief requires them; apply needs `--allow-binary` |
| `ignored_untracked` | Worker-tree tests may depend on omitted files; verify the patch |
| `leftover_processes_killed` | Report the unexpected background processes |

Report suspicious guard denials (network, outside reads, control-file writes),
even if the worker produced a useful patch. Do not override protected-path gates
to make an ordinary task pass.

```bash
python3 "$W" test '<run-id>' -- python -m pytest -q tests/test_feature.py
python3 "$W" verify '<run-id>' --full -- python -m pytest -q
python3 "$W" resume '<run-id>' --brief '<feedback.md>'
```

`test` uses the worker tree. `verify` applies a snapshot of the patch to a fresh
standalone repo at the target HEAD, then runs sandboxed. Mark only the actual full
suite `--full`; skipped required checks are unverified. Use the project's real
commands rather than copying the illustrative pytest command blindly.

Feedback names the defect, location and expected behavior. Allow at most two
send-back rounds before escalating or taking over. Every round replaces the patch:
read the full new patch and verify it again. Resume one run sequentially; the
executor is not a persistent queue or a concurrent same-run scheduler.

For agy transport failures, `run` and `resume` allow one automatic continuation
by default; `--network-retries 0` disables it, and the maximum is two. Only exit 3
with a structured, explicitly retryable gRPC EOF/connection error qualifies.
Authentication, quota, local timeout/interruption, missing/mismatched session ID,
guard denials, capture failures and review flags stop recovery for coordinator
review. A denial earlier in the run also blocks automatic continuation.

Recovery uses the same conversation and disposable repo. Each failed round keeps
its response, usage and partial patch; the next attempt must inspect existing
work before continuing. This is not a guarantee that actions execute exactly
once. Backoff and all attempts share the original `--timeout` budget, with one
shared 120-second CLI shutdown grace. Cleanup can extend wall-clock time. The
final stdout remains one JSON summary with `network_recovery` and total
`invocation_usage`; progress goes to stderr. Recovery never changes the provider
or enables a paid API fallback. A failed historical run is not retried on startup.

## Integrate and record

```bash
python3 "$W" apply '<run-id>' --sha '<reviewed-sha256>'
python3 "$W" record '<run-id>' --level L2 --outcome accepted \
  --notes '<review and verification summary>'
python3 "$W" clean '<run-id>'
```

Apply changes the working tree without staging. Commit, push, PR and deployment
follow the user's requested scope and standing authorization. Coordinator edits
to worker output must also be tested in a fresh sandboxed tree. Use outcomes
`accepted`, `fixed`, or `rejected`, and record relevant defect categories. Keep
platform/coordinator/task metadata with the run; legacy records remain readable.

Report the executor/model, revisions, coordinator corrections, verification
results and material flags. Review recurring defects in the ledger to adjust
routing based on observed performance; do not assume a model always wins.

### Model usage note

Include a short **模型调用说明** (or the user's language) in the final response:
coordinator, any planning/review agents actually invoked, and each execution
model with its channel (`agy` or `claude-cloud`). Include failed/abandoned attempts
and model switches; mention network continuations when they occurred. For L0
handled entirely by the coordinator, say no external coding model was called.
If independent review was skipped or fell back, give the actual reason; L0 alone
is not a reason. Distinguish a same-model pass from confirmed cross-model review.

Use dispatch records, run metadata and observed cloud session models as evidence.
For agy, label `model` as the CLI-selected model; do not claim independent backend
verification. For cloud, distinguish `requested_model` from the observed session
model. If the coordinator/subagent model is unavailable, write “当前会话（具体模型未暴露）”
or “继承主会话（具体模型未暴露）”; do not infer it from role defaults. Mention funding
only when observed, and distinguish Google's agy allowance from Claude's cloud
credits/subscription. Do not infer charges or remaining balance from token counts.

Example shape (replace fields with evidence, omit unused roles):
> 模型调用说明：协调＝<当前会话模型>；审查＝<实际审查模型>；执行＝<CLI 指定模型 / 云端观察模型>（<渠道>，<成功/失败>）；网络续接＝<实际次数，如有>。

Configured routes are options, not a list of models called on every `/auto` run.
Read the current profile rather than copying model versions into this note.
The shared `providers`/`worker_defaults` API list belongs to `/moa`; it does not
mean `/auto` invoked those providers.

If agy login/quota or sandbox setup fails, report that condition or let the
coordinator take over. Do not fall back to a different unsandboxed worker CLI.
