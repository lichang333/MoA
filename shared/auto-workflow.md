# Shared delegated coding workflow

The coordinator owns the brief, review, verification and integration. External
executors are Antigravity (`agy`), [native Claude Code](claude-local-workflow.md)
(`claude-local`) and the explicit [Claude cloud bridge](cloud-workflow.md).
All start from a commit and exclude the user's uncommitted changes. Prefer available
included subscription allowance; choose cloud for suitable GitHub work within the
user's funding preference. agy retains its local guard and sandbox. An executor's model selection does not prove remaining allowance.

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
  uses agy, the native Claude broker or the documented cloud route. The coordinator can implement small
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

### Task-fit model selection

The levels above select a workflow. L0 assigns execution to the coordinator; it
does not imply low difficulty or risk. Judge the bounded task by uncertainty,
reasoning across components, failure impact and how reliably it can be verified,
rather than file count alone. Preserve the user's explicit model/channel choice.

`agy_routes`, `agy_alternatives`, `fallback_routes` and the native/cloud model
defaults are starting candidates, not mandatory choices for every task. Within
the funding rules, choose a suitable model for the whole accepted result,
including briefing, review and likely rework:

- Handle straightforward L0 work directly. Add a planning/review call only when
  it resolves a concrete uncertainty covered by the review criteria below.
- For a precise implementation with clear local checks, start with the routine
  route; Sonnet is a native Claude option for this kind of work.
- For unresolved architecture, difficult diagnosis, interacting invariants or
  consequential logic, consider an eligible stronger reasoning model up front,
  such as Opus on a supported Claude channel. Plan or review with it where useful;
  clear implementation subtasks can then use the routine route. Production and
  execution-boundary operations still stay with the coordinator.

Choose one executor per bounded brief and pass the selected `--model` explicitly,
including for native/cloud preparation. In the existing brief, give a short reason
for the model/channel and any extra review; no separate planning call is needed
just to make this choice. An L3 candidate list does not request parallel implementations.

If feedback reveals a wrong approach or repeated substantive failures, reassess
the brief and model before another attempt, within the existing feedback limit.
Do not keep a routine model solely because it is the default, or restart completed
work when handing over. Quota/authentication/capacity failures follow their own
rules below; they are not evidence of task difficulty or permission to bypass
funding, handoff or verification gates.

Check `agy models` when choosing a model or changing routes. A listed model proves
availability, not remaining quota. Use the user's current allowance statement or
an actual account observation without inventing a balance, independent pools or
reset time; do not save a temporary quota claim as a permanent fact. Claude and
GPT-OSS through agy use the Antigravity channel, not Claude cloud credits, native
Claude/Codex subscriptions or the standalone provider API keys. GPT-OSS is not a
native Codex model. On a quota/auth failure, stop that attempt and inspect captured
work; quota failures require the senior-model handoff decision below before a replacement
executor or coordinator implementation takes over. Never silently rerun partially
completed work or fall back to separately billed APIs without applicable explicit authorization.
When the Models & Usage panel conflicts with a CLI quota error, refresh the panel
before concluding either is wrong. Check both weekly and five-hour windows and
the panel's quota-group labels: a model in the same exhausted group is not an
eligible quota fallback. Keep credit overages off unless the user authorizes them.

When considering native Claude Code, inspect `claude --version` and its actual
`/model` picker (including disabled and extra-credit-only entries) rather than
assuming it offers the same versions as agy. Checking the picker requires no
model prompt and should not change the user's default. Prefer channel-specific
aliases over freezing today's displayed version into the skill. A newer native
model does not make that model available through agy or establish cloud eligibility.
Native Claude Code local delegation uses `claude_local.py` and its
[broker workflow](claude-local-workflow.md). Check its independent subscription
allowance, prepare the isolated run and observe funding before execution. Model
discovery alone is not a completed integration or authorization for extra usage.

An explicit cloud preference can route a small
or L1/L2 GitHub task through the cloud workflow instead; size alone is not a reason
to ignore that preference. Production/credential work and changes to the execution
guard or sandbox still stay with the coordinator.

Choose execution and independent review separately: L0 keeps implementation or
operations with the coordinator, but does not exempt the result from review.
Announce the execution level/model and the review route (or brief skip reason).
User model choices take priority when the executor supports them.
Read `routing.json` and its shared defaults, `headless.json`
(installed next to the skill; source is `config/headless.json`),
for `agy_routes` and `agy_alternatives`; `agy models` can confirm external
executor availability. Do not substitute an OpenAI model ID into the agy CLI.

Write a brief containing `GOAL`, `CONTEXT` (files/functions), `REQUIREMENTS`,
`CONSTRAINTS`, `ACCEPTANCE` (exact checks), and `OUT OF SCOPE`. Distinct tasks need
distinct briefs and run IDs. Keep shared-file edits sequential and reverify each
patch after integration changes HEAD. For prod-bound code such as migrations,
deployment scripts and runtime configuration, prefer coordinator implementation.

### Funding priority and API advisors

Follow `auto_funding`: use suitable, available **included subscription allowance
first**, then eligible authorized cloud credit, then explicitly authorized prepaid
API balance. A channel's real billing mode matters more than its model name;
extra-credit-only subscription entries count as paid usage. Preserve an explicit
user choice for a particular task. This is coordinator routing policy, not an
automatic billing control implemented in the worker.

`api_advisors.providers` includes GLM, DeepSeek and MiniMax. The user identifies
these as prepaid channels. Remember them as candidates, but their keys, balances
or inclusion in the list do not by themselves authorize consuming credit. Before
a paid call, check for applicable explicit spending authorization in this session;
if absent, present the concrete provider/model, purpose and bounded call scope for
approval. Existing authorization need not be requested again. Do not top up,
enable overages or call models just to probe quota.

These providers are implemented by the shared `skills/moa/moa_runner.py` as text
analysis, so `/auto` may use them for planning or read-only review under that
funding policy. They are not guarded coding executors and cannot replace the
specified quota decision makers. Resolve model IDs from `providers` in the active
profile instead of copying versions into a prompt. Use an explicit single provider
and raw mode to avoid default fan-out or a second paid aggregation call:

```bash
python3 '<installed-moa-skill>/moa_runner.py' --platform codex \
  --models '<glm|deepseek|minimax>' --raw -- '<sanitized bounded review brief>'
```

Use the calling platform (`codex` or `claude`). Provide only the necessary sanitized
brief/diff; no credentials, live-service access or tool execution. `--review` selects
the separate configured `reviewer` (currently GLM); `--models` does not override it.
`--show-config` / `--dry-run` reads routing without credentials or model calls.
Record real API calls and failures as channel `api` in the model usage note.
Actual code execution through these APIs needs a separately implemented adapter
with the same isolation, patch provenance, full verification and apply gates.

### Quota handoff decision

When an executor reports exhausted quota, preserve its partial patch, run ID,
base commit, error and verification state. Stop that execution attempt; a quota
error is not a retryable network interruption. Refresh the relevant usage panel
when available, checking both limit windows, quota groups and credit-overage state.
Do not test capacity by sending disposable prompts to other models.

Choose an available decision maker from `quota_handoff.decider_candidates`:
Astra, Fable, Opus 5.5 or Muse. These are eligible decision-maker identities, not
interchangeable CLI model IDs or proof of installed adapters. Resolve each name
through its actual host/model picker, check available authorized quota, and do
not invent an endpoint or model ID for Muse. If the current coordinator's actual
identity is confirmed as an eligible candidate, it may decide in this session;
otherwise use a supported native, read-only invocation with fresh bounded context.
A role default or unknown inherited model does not establish decision-maker identity.

Give the decision maker the task and remaining acceptance criteria, failed model/channel and
error, captured patch summary/SHA and known review findings, available executor
capabilities, freshly observed quota data (or the user's current statement, with
its limits), and the user's funding preferences. The decision maker chooses one of:

- a specific eligible successor model **and channel**, with a bounded handoff brief;
- coordinator takeover for appropriate repair or integration work;
- retain the work and wait for quota or missing information.

Record the decision, evidence and reason in an ignored run artifact such as
`quota-handoff-<attempt>.md`, and tell the user the outcome before dispatching.
Existing authorization covers a suitable successor using available included or
already-authorized quota; ask only if the choice needs new spending or access.
Models in an exhausted shared group, unimplemented adapters, and unobserved
native Claude or Claude cloud funding are not eligible.
Never enable credit overages or consume prepaid API credit merely to keep going;
apply the funding priority and authorization rule above.

If a candidate is unavailable, another available candidate on this list may decide.
If none is available or no candidate returns a decision, keep the artifacts and
report the missing decision; do not substitute an unlisted model or launch a
successor without the user's waiver. Read-only review and preparation may continue.
This quota rule takes precedence over ordinary review fallback.

A successor must inspect existing work and receive only the remaining scope.
Use the supported guarded runner/bridge; do not rewrite model identity in old run
metadata or bypass the guard to switch a CLI. Preserve each attempt's provenance.
The complete resulting patch still needs whole-patch review, sandboxed full
verification and the existing SHA/HEAD apply gates, including coordinator repairs.
This is a coordinator workflow, not a background quota monitor or automatic CLI
failover; scheduling a later retry remains a separate user request.

### When agy cannot run

The worker summary names the cause instead of a bare `ERROR`:

- `QUOTA_EXHAUSTED` (value: the reported reset time): the account's allowance for
  that quota group is used up. Follow the quota handoff decision above. Other agy
  models are eligible successors only when observed working in a different quota
  group (for example a run that is still making progress or succeeded after the
  exhaustion); otherwise the handoff decision can consider `fallback_routes`
  from the profile, adjusted to the remaining task's difficulty and risk, or
  Claude cloud when cloud credits are actually observed for a GitHub task.
- `CAPACITY_UNAVAILABLE`: server-side capacity (HTTP 503), not quota. Wait at
  least a minute and `resume` the same run once; if it repeats, choose another
  model for the remaining scope.

claude-local draws on the same Claude subscription as a Claude Code coordinator.
Read both usage windows before each dispatch. The `sonnet` default is a starting
point for routine tasks; use the task-fit criteria above for the actual selection.
Note when the allowance resets: a near reset can favor waiting when the user's
timing permits. Keep extra usage off. Fable is not included in Pro without
usage credits; a different-model review then falls back to an available model
(for example Sonnet when the author is Opus) and the report says so.

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

For a Node project, add `--node-modules '<repo>/node_modules'` (an npm-installed
tree matching the base commit's lockfile; a base that tracks node_modules is refused).
It is cloned copy-on-write into the worker and verify trees and never enters the
patch (any case variant). The worker may run its tools as
`node node_modules/<pkg>/<script>` inside the sandbox; npm/npx and installs stay
unavailable. agy's file tools cannot edit node_modules, but sandboxed worker code
can, so `test` re-clones it before each call and `verify` always uses a fresh clone.
`test` stays advisory (worker code can plant other resolution paths or caches in its
tree); only `verify --full` on a fresh tree gates apply.

A worker is stopped with status `stalled`, keeping its partial patch, when for
`--stall-timeout` awake seconds (default 600, `0` disables) it makes no tool call
and no sandboxed command started by that agy process is still running; leftover
background processes do not count. Progress is read from the log of the guard
registered in `~/.gemini/config/hooks.json`. agy's own print timeout and a SUCCESS
without a final report are recorded as `timeout` and `incomplete`, never as success.
`seconds` is wall time and `active_seconds` excludes host sleep; a
`host_sleep_seconds` field means the Mac slept during the run.

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
| `INCOMPLETE_RUN` | The worker did not finish: review the partial patch, then resume with the remaining scope or take over |

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
commands rather than copying the illustrative pytest command blindly. A passing
verify tree is removed afterwards (`--keep-tree` keeps it); a failing one stays
until `clean`. `test --venv` and `verify --venv`, `--node-modules` or
`--no-node-modules` apply to that call only; `verify` records them in `verified`.

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
python3 "$W" review '<run-id>' --model gpt-6-astra
python3 "$W" apply '<run-id>' --sha '<reviewed-sha256>'
python3 "$W" record '<run-id>' --level L2 --outcome accepted \
  --notes '<review and verification summary>'
python3 "$W" clean '<run-id>'
```

`review` invokes the local `codex exec` in a read-only sandbox using the user's
logged-in ChatGPT subscription (`gpt-6-astra` by default) to evaluate the generated
patch against the brief. It checks for correctness, edge cases, regression risks and
safety issues, printing the review and saving it to `runs/<id>/codex_review.json`.

Apply changes the working tree without staging. Commit, push, PR and deployment
follow the user's requested scope and standing authorization. Coordinator edits
to worker output must also be tested in a fresh sandboxed tree. Use outcomes
`accepted`, `fixed`, or `rejected`, and record relevant defect categories. Keep
platform/coordinator/task metadata with the run; legacy records remain readable.

Report the executor/model, revisions, coordinator corrections, verification
results and material flags. Review recurring defects in the ledger to adjust
routing based on observed performance; do not assume a model always wins.
Include a material routing change and its reason in the existing record notes.
Assess efficiency using available whole-task usage, retries and acceptance results;
without comparable evidence, do not claim that a default change saved money.

### Model usage note

Include a short **模型调用说明** (or the user's language) in the final response:
coordinator, any planning/review agents actually invoked, and each execution
model with its channel (`agy`, `claude-local` or `claude-cloud`), and API advisors as `api`. Include failed/abandoned attempts
and model switches; mention network continuations when they occurred. For L0
handled entirely by the coordinator, say no external coding model was called.
If independent review was skipped or fell back, give the actual reason; L0 alone
is not a reason. Distinguish a same-model pass from confirmed cross-model review.

Use dispatch records, run metadata and observed cloud session models as evidence.
For agy, label `model` as the CLI-selected model; do not claim independent backend
verification. For native Claude and cloud, distinguish `requested_model` from the observed
session model. If the coordinator/subagent model is unavailable, write “当前会话（具体模型未暴露）”
or “继承主会话（具体模型未暴露）”; do not infer it from role defaults. Mention funding
only when observed, and distinguish Google's agy allowance from Claude's cloud
credits/subscription. Do not infer charges or remaining balance from token counts.

Example shape (replace fields with evidence, omit unused roles):
> 模型调用说明：协调＝<当前会话模型>；审查＝<实际审查模型>；执行＝<CLI 指定模型 / 云端观察模型>（<渠道>，<成功/失败>）；网络续接＝<实际次数，如有>。

Configured routes are options, not a list of models called on every `/auto` run.
Read the current profile rather than copying model versions into this note.
The shared `providers`/`worker_defaults` configure the MoA API runner. `/auto` can
select an authorized `api_advisors` provider for text analysis; configuration alone
does not mean it was called or make it a coding executor.

If agy login or sandbox setup fails, report that condition or let the coordinator
take over. Quota exhaustion follows the required senior-model handoff decision above.
Do not fall back to a different unsandboxed worker CLI.
