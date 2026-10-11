# Claude cloud execution

Use this route for bounded GitHub code tasks when the user wants Claude cloud
execution or has eligible cloud credits to use. The coordinator dispatches and
reviews; the cloud session runs on Anthropic infrastructure. Local agy guards do
not protect cloud execution. Keep credentials, production work and macOS-only
validation in the coordinating session. Cloud sessions use Linux.

## Funding and task choice

For the user's goal of minimizing new cash spending, prefer unexpired cloud
promotional credits for suitable tasks, then available included subscriptions,
then explicitly authorized existing API balances. Do not invoke multiple APIs
just because their keys exist. Different channels use different pools:

- Claude cloud credits apply to ordinary Cloud sessions; Projects, Routines,
  Remote Control, Chat and Cowork are excluded by the current promotion.
- Claude local sessions use the Claude subscription. agy's Claude models use
  Google's allowance. Anthropic API keys use separate API billing.
- No bridge command enables extra usage, purchases credit, or falls back to an API.
  Keep extra usage off and use Sonnet/Opus. Pro Fable requires paid usage enabled.

Read the actual account Usage panel before dispatch. `observe-funding` records
the source, amount, observation time, expiry/reset time and the extra-usage-off
observation. For subscription funding, use the smallest remaining percentage and
earliest reset among applicable session/weekly limits. Unknown, stale, exhausted
or expired funding blocks the bridge. Each observation authorizes at most one
launch/send; a later actual panel observation is required for another submission.
This is a dispatch preflight, **not a live quota meter or a dollar cap**. An ongoing
cloud task may outlive the observation or consume all promo credit, then use the
regular subscription. Check usage after each bounded task. Never invent balances,
backdate observations or refresh a timestamp without rereading the account panel.

## Prepare and launch

`C` and `W` are `claude_cloud.py` and `agy_worker.py` in this installed auto skill.
Keep task briefs and records under ignored `skills/auto/runs/` (or outside Git).
Prepare records an immutable expected base and prompt hash; it calls no model:

```bash
python3 "$C" prepare --repo "$PWD" --brief '<brief.md>' --platform codex --task-id '<task-id>'
python3 "$C" observe-funding '<run-id>' --source cloud-credit --remaining '<actual-USD>' \
  --observed-at '<ISO-time-with-offset>' --expires-at '<actual-expiry-with-offset>' --extra-usage off
python3 "$C" launch '<run-id>' --dry-run
python3 "$C" launch '<run-id>'
```

The launcher checks Pro/Max first-party subscription authentication, strips API
and Git override environment variables, and preflights the GitHub branch against
the recorded base. It invokes documented `claude --cloud` from a standalone
shallow base-only repository. If Claude bundles local code instead of cloning
GitHub, only that isolated committed snapshot is available. The remote branch
can advance after preflight: the brief requires checking HEAD and stopping on a
mismatch. Local dirty files, stash, unrelated branches and credentials are absent.

`--safe-mode` disables local launcher customizations; it is not evidence that
the cloud environment has inherited the same restrictions. Review the configured
cloud environment and the full task output. `cloud_defaults` supplies the requested
model family, which is not proof of the effective model: verify it in the session UI.

New-session CLI behavior can be interactive and has no assumed asynchronous JSON
creation protocol. Complete normal CLI/UI interaction and attach the displayed
session ID. A failed/interrupted launch may still have created a job: inspect the
cloud UI, never blindly retry. GitHub auth or trust setup is a visible prerequisite,
not something the bridge bypasses. An existing UI-created session can be attached
without launching a duplicate:

```bash
python3 "$C" attach '<run-id>' --session '<session-id-or-Claude-URL>'
python3 "$C" status '<run-id>'
```

For a UI-created session that started earlier, prepare with
`--base '<confirmed-cloud-start-commit>'` rather than assuming local HEAD is its
base. Keep the original task brief; fetch missing history first with trusted Git
tooling. A named current branch is recorded for preparation, but attachment and
import use the explicit base; do not launch a duplicate from this record.
Confirm that the selected session belongs to this repository/base/task before
attaching. Attachment records identity only; it cannot verify remote ownership,
completion, model, branch, or quota. Attaching a session clears prior funding
observations. Local `status` reports metadata with remote state/cost unknown.

## Follow up and retrieve results

Read the cloud session's actual model and account usage, then record a new funding
observation with `--session-model sonnet` or `opus`. The value is the observed
model family, not a request to change it. A single follow-up uses the documented
stdin command `claude -p --cloud <session-id> --output-format json`:

```bash
python3 "$C" observe-funding '<run-id>' --source cloud-credit --remaining '<actual-USD>' \
  --observed-at '<new-observation>' --expires-at '<expiry>' --extra-usage off --session-model opus
python3 "$C" send '<run-id>' --brief '<follow-up.md>'
```

The success response means **submitted**, not completed. There is no fabricated
cloud list/log/diff API; use Claude's UI for progress, reports and branch identity.
Both CLIs share a per-run lock, including verify/apply/record/clean; work on
different runs can proceed independently. Attaching a session invalidates prior
funding while retaining its observation timestamp to prevent replay.
Keep import/verify/apply sequential. Do not rebind a run to another session.

For code results, authorize the task's separate branch push in its brief, confirm
that branch in the cloud report, then fetch it into the coordinator's repo using
normal trusted Git tooling. Do not check it out or run cloud-generated code there.
Import the already-fetched ref:

```bash
python3 "$C" import-ref '<run-id>' --ref 'refs/remotes/origin/<confirmed-task-branch>'
python3 "$W" verify '<run-id>' --full -- python -m pytest -q
python3 "$W" apply '<run-id>' --sha '<whole-patch-reviewed-SHA256>'
python3 "$W" record '<run-id>' --level L2 --outcome accepted --notes '<review and tests>'
python3 "$W" clean '<run-id>'
```

Replace the illustrative pytest command with the project's actual full suite,
passing the executable and arguments separately. Review the complete imported
patch **before** verification. Import resolves the
ref once to a commit, requires ancestry from the recorded base, parses paths with
Git, rejects protected files/symlinks/submodules, and retains binary/execution
surface flags. It does not check cloud code out. Existing sandbox/full-suite/SHA/
HEAD/dirty-target/apply gates remain authoritative. `W test` and `W resume` refuse
cloud runs; `W verify` is the local test entry. Cloud token/cost totals remain
unknown rather than being recorded as zero Gemini tokens.

## Validation and current limits

Run `test_cloud.py`, `test_guard.py`, `test_worker.py` and `tests/test_platforms.py`
after changing this path. Tests use local Git fixtures and mocked Claude calls.
Live UI/CLI results must be reported separately from mocked transport coverage.
There is no autonomous quota polling, persistent scheduler, background monitoring,
remote job cancellation API, or automatic branch fetch/merge in this bridge.

Sources: [official cloud CLI and GitHub/bundle behavior](https://code.claude.com/docs/en/claude-code-on-the-web),
[cloud credit eligibility and exclusions](https://support.claude.com/en/articles/17152539-cloud-sessions-bonus-credit-promotion).
