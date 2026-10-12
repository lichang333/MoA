# Shared MoA workflow

`moa_runner.py` collects external API answers. It is a Q&A and analysis tool, not a
code-executing worker. External providers have no live web access in this runner.
The current coordinating session supplies current evidence and the final synthesis.

## Configuration and execution

Each platform entry includes `routing.json`, linked to its profile in `config/`.
Profiles inherit [shared defaults](headless.json), also linked beside the installed
skill. Provider names in
`worker_defaults` and `--models` select external API workers; `native_roles` select
native session roles, while `agy_routes` select external coding workers. Do not
pass native role names to an API provider endpoint.

Use the script beside the installed skill. These examples assume `R` is that path:

```bash
python3 "$R" --platform codex --show-config
python3 "$R" --platform codex --coordinator-model '<actual-model-or-current>' \
  --task-id '<task-id>' --raw -- '<question>'
python3 "$R" --platform claude --models deepseek,minimax --raw -- '<question>'
```

Both installed platform entrypoints infer their platform and default to raw
answers; explicit `--platform` takes precedence. `--raw` retains the
`===MOA_RAW_JSON_START===` / `===MOA_RAW_JSON_END===` map for existing callers.
Use `--platform headless` only when API aggregation is wanted; this adds a paid
aggregator call. A bare invocation of the shared core script retains legacy
headless behavior.

`--models` accepts comma-separated provider names. Prefer a relevant subset when
it suffices; the legacy default remains all configured providers. Keys are local
to the shared `skills/moa/.env` or the existing environment/Desktop fallback.
Do not print keys or copy them into platform directories.

## Synthesis

1. Give workers a self-contained question with only the context they need.
2. For current facts, obtain primary-source evidence using the host's search tools.
3. Compare successful answers against evidence, resolve disagreements and state
   material uncertainty. Model agreement alone is not proof.
4. Report material worker failures. Do not treat errors as evidence or claim a
   failed provider reviewed the answer.

For a difficult or consequential question, or material disagreement, a second
review can help. Native review follows the host entrypoint. For an external paid
review, announce the additional call and use:

```bash
python3 "$R" --platform codex --review -- '<original question and draft to critique>'
```

The reviewer model comes from the profile. Simple questions do not need an extra
review. User choices such as `--deep`, `--fast` or `--no-deep` guide the coordinator;
remove these workflow flags before invoking the runner.

## Results and records

Each API run writes a record under the shared `skills/moa/runs/` with a unique run
ID, platform, coordinator, task ID, selected models and outcomes. These are local,
gitignored artifacts and can contain model response text. A nonzero exit means
the requested operation failed; partial failures must remain visible even when
useful answers are available. `--show-config` and `--dry-run` inspect routing
without loading credentials or making requests.

## Evidence-based collaboration

The first round receives only the original task and common evidence, in separate
contexts. Do not include another candidate's answer or a majority hint in that
round. Native coordinators must enforce this isolation themselves; the API
runner cannot detect candidate material embedded by its caller.

- Separate facts, assumptions, inferences and recommendations. A proposed test
  remains unverified until it has actually run and its result is recorded.
- Review specific claims, constraints, citations and failure conditions. Accept
  "no substantive issue found"; do not require a quota of objections or agreement.
- Respond to important review findings with accept, partly accept, reject or
  undetermined, a concise checkable reason, and a complete usable revision.
- Repeated citations to one source remain one source. Neither majority agreement,
  model identity nor self-reported confidence establishes correctness.
- Preserve material disagreements and evidence gaps. Prefer the smallest
  verification that could change the conclusion over another discussion round.
- Exchange conclusions, evidence summaries, tests and brief revision reasons;
  do not solicit private chain-of-thought.

API workers have no tools or live browsing here. Model-written "checked" labels
are claims, not verification: the coordinator must match them to supplied source
checks or real tool logs. Prompts now apply these rules to workers, the single
reviewer and the aggregator; they do not implement a trusted evidence registry.

The current runner performs independent collection and optional aggregation.
`--review` makes one logical reviewer call on the caller-supplied task/draft;
it does not fetch previous answers, allocate cross-reviews or revise candidates.
Raw text markers and default call counts are unchanged. See the
[optional four-stage experiment](evidence-review-proposal.md) for capabilities
that require additional orchestration, validation and explicit budgets.
