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
- Apply only a fully reviewed patch SHA with passing `verify --full` against the
  current target HEAD and clean target files. A new worker round requires review
  and verification of the new patch.
- Native Codex/Claude subagents do not inherit agy hooks or this sandbox. Within
  this workflow use them for read-only planning/review; delegated implementation
  uses agy or the documented cloud route. The coordinator can implement small
  changes and execution-boundary changes directly.

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

Announce the chosen level and model. User model choices take priority when the
executor supports them. Read `routing.json` and its shared defaults, `headless.json`
(installed next to the skill; source is `config/headless.json`),
for `agy_routes`; `agy models` can confirm external
executor availability. Do not substitute an OpenAI model ID into the agy CLI.

Write a brief containing `GOAL`, `CONTEXT` (files/functions), `REQUIREMENTS`,
`CONSTRAINTS`, `ACCEPTANCE` (exact checks), and `OUT OF SCOPE`. Distinct tasks need
distinct briefs and run IDs. Keep shared-file edits sequential and reverify each
patch after integration changes HEAD. For prod-bound code such as migrations,
deployment scripts and runtime configuration, prefer coordinator implementation.

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

If agy login/quota or sandbox setup fails, report that condition or let the
coordinator take over. Do not fall back to a different unsandboxed worker CLI.
