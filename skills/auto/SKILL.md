---
name: auto
description: Use when the user invokes /auto <task> (or asks to "让 Gemini 干活 / 分配给 moa / 用 antigravity 写代码"). Claude triages the coding task's difficulty, delegates the implementation to Gemini workers through the Antigravity CLI (agy) in sandboxed throwaway git worktrees, and stays responsible for the brief, code review, verification, and commits. Not for Q&A synthesis (that is /moa) and never for prod/ssh/deploy work.
---

# /auto — Claude triages, Gemini implements, Claude guarantees quality

The user's standing concern: **Gemini has broken their system before.** Safety and code
quality outrank speed and token savings. When in doubt, do it yourself.

## Hard rules (never relax without telling the user)

1. **Workers never touch the real system.** No prod, no ssh, no VPS, no deploys, no secrets,
   no live DB. Those tasks are L0 (Claude), full stop.
2. **Workers only run through `agy_worker.py`.** Never invoke `agy --dangerously-skip-permissions`
   any other way — `AUTO_WORKER=1` is what turns the guard on.
3. **Worker code never runs outside the sandbox — not even after review.** Verify with
   `agy_worker.py verify --full` (patch → fresh tree at the user's HEAD → sandbox). Do not run the tests "in place" in
   the user's checkout after applying: python-dotenv walks up to the real `.env`, and the
   network and ssh-agent are live there.
4. **Only the reviewed bytes get applied.** `apply` requires the sha256 of the patch you read,
   a passing `verify --full` of that sha onto the current HEAD, and clean target files. A
   send-back round replaces the patch → review again.
5. **Claude commits.** Push / PR / deploy still need the user's confirmation as usual.
6. If the guard blocks something legitimately needed, Claude does that step itself. Do not
   loosen the guard or sandbox mid-task; propose the change to the user. After editing
   `agy_guard.py`, run `python3 ~/.claude/skills/auto/test_guard.py` (must be all ok).
7. Suspicious guard denials (network, ssh, reading outside the worktree, touching
   `.git`/`.claude`/`AGENTS.md`) are reported to the user even if the task succeeded.

## 1. Triage (announce it in one line before starting)

Format: `分级 L2 → Gemini 3.1 Pro：<one-line reason>`. User overrides win: `--self`,
`--l1`/`--l2`/`--l3`, `--model <id>` (list with `agy models`).

| Level | Signals | Who |
|---|---|---|
| **L0** | ≲30 lines / 1–2 files; needs this conversation's context that is costly to brief; anything operational (prod, ssh, deploys, secrets, live DB); the task's centre of gravity is **prod-bound code**: `deploy/`, `node-managers/`, `scripts/`, `migrations/`, `run.sh`, `wsgi.py`, `requirements*.txt`, `app/config.py`; the guard/sandbox itself; urgent hotfix; the user is debugging live | **Claude directly** |
| **L1** | Well-specified and mechanical: tests for existing code, boilerplate, a small endpoint/UI piece in 1–3 files, renames, docs | `gemini-3.8-flash-high` |
| **L2** | Multi-file feature or bug fix with a clear spec and clear acceptance tests | `gemini-3.1-pro-high` |
| **L3** | Ambiguous, architectural, cross-cutting, or high-stakes logic | Claude designs first, then either splits into L1/L2 sub-briefs, or runs **two** workers in parallel (`gemini-3.1-pro-high` + `claude-opus-4-6-thinking`, both on Antigravity quota) and picks/merges the better patch |

Why L0 exists: briefing + reviewing costs Claude tokens too. Delegation pays off only when the
implementation (exploring, writing, iterating on tests) is much larger than brief + review.

## 2. Write the brief (self-contained — the worker has none of this conversation)

Write it to the scratchpad as `brief.md`:

```
GOAL: <one sentence: the behaviour change>
CONTEXT: <files to read first, with paths and the relevant functions; how the pieces connect>
REQUIREMENTS: <numbered, testable>
CONSTRAINTS: <what must not change (APIs, output formats, golden tests), style to match, files off-limits>
ACCEPTANCE: <tests to add/extend and the exact commands that must pass, e.g. `python -m pytest -q tests/test_x.py`>
OUT OF SCOPE: <tempting adjacent changes to leave alone>
```

The repo's `AGENTS.md` (auto-loaded by agy) carries the standing project rules; the brief
carries only the task. `agy_worker.py` prepends the worker rules (sandbox, report format).
The worker starts from a commit (`--base`, default `HEAD`): it never sees uncommitted changes.

## 3. Run

```bash
W=~/.claude/skills/auto/agy_worker.py
python3 $W run --repo "$PWD" --brief <scratchpad>/brief.md --model gemini-3.1-pro-high --name <slug>
# L3 dual: two `run`s with run_in_background, different --model and --name
```

Output (JSON): run id, status, Gemini tokens, `patch` + `patch_sha256`, diffstat,
**`REVIEW_FLAGS`**, guard denials, and the worker's own report (a claim, not evidence).

## 4. Review (Claude — this is the job)

Read **the whole patch file** (`runs/<id>/diff.patch`), not the worker's report. Note its sha256.

`REVIEW_FLAGS`, when present, mean:
- `PATCH_PATHS_MISMATCH` / `CAPTURE_FAILED` — the patch does not describe the worker tree
  (forged headers?) or could not be captured: reject the run, tell the user. `apply` refuses it.
- `leftover_processes_killed` — worker code left processes running after the run: suspicious;
  mention it to the user.
- `protected_paths` — control files (`.git*`, `.claude`, `AGENTS.md`, `.envrc`, `.pth`, …). The
  guard and sandbox should have made this impossible: treat as hostile, reject, tell the user.
- `sensitive_paths` — prod-bound code (`deploy/`, `node-managers/`, `migrations/`, …). Line by
  line, and say so in the final message. If the task wasn't about them, send back.
- `execution_surface` — `conftest.py`, `pytest.ini`, `pyproject.toml`, `setup.*`, `Makefile`,
  `package.json`, `*.sh`: code that runs during tests/builds. Read as executable code.
- `binary_files` — a binary file (or text with a NUL) in a code change: reject unless the brief
  asked for it (`apply` needs `--allow-binary`).
- `ignored_untracked` — gitignored files the worker created; they are NOT in the patch, so a
  green `test` in the worker tree may depend on them. `verify --full` is what counts.

Checklist:
- **Scope**: only what the brief asked; no drive-by refactors or reformatting.
- **Tests**: new behaviour tested; nothing deleted, skipped, loosened; goldens untouched.
  Every new/changed test is code that executes — look for subprocess, sockets, `requests`,
  env reads, writes outside `tmp_path`.
- **Security**: auth decorators on new routes; input validation; no SQL string building; no
  unescaped `innerHTML` (use `esc()`); no secrets, tokens, IPs, high-entropy strings, debug prints.
- **Compatibility**: everything `AGENTS.md` lists as must-not-change.
- **Correctness**: edge cases, error paths, transactions, time zones, units (bytes vs GB).
- **Fit**: naming, comment density, i18n in both languages, CSS tokens.

## 5. Verify, send back, or take over

```bash
python3 $W test   <run_id> -- python -m pytest -q tests/test_x.py   # quick, in the worker tree
python3 $W verify <run_id> --full -- python -m pytest -q            # authoritative: gates apply
python3 $W verify <run_id> -- node --test tests/admin_billing_ui.test.js   # extra checks as needed
```

`verify` snapshots `diff.patch`, applies it to a fresh standalone repo at `--onto` (default: the
user's current `HEAD`) and runs the command sandboxed. `--full` marks the full-suite run that
`apply` requires — only use it for the real full suite. Skipped tests count as unverified.

- **Small nits**: apply, then Claude fixes them in the user's tree → outcome `fixed`.
- **Real defects**: `python3 $W resume <run_id> --brief <feedback.md>` with numbered findings
  (file:line, what is wrong, what correct looks like). **Max 2 send-back rounds.** After each
  round read `changed_since_last_round`, then the **whole** new patch again (new sha).
- Still wrong after 2 rounds, or the approach is wrong: escalate one level (new `run`) or
  Claude implements it → outcome `rejected` for the worker run.

## 6. Apply, commit, record, clean

```bash
python3 $W apply  <run_id> --sha <sha256 you reviewed>   # sha + full verify on HEAD + clean files
# applies to the working tree only (unstaged); Claude stages and commits explicitly
# Claude's own follow-up edits, then commit (Claude-authored message + co-author line).
# Tests after Claude's own edits: run them via run_sandboxed.sh on a fresh worktree of the
# commit, or via `verify` before applying — never unsandboxed in place (hard rule 3).
python3 $W record <run_id> --level L2 --outcome accepted|fixed|rejected \
    --defects scope,tests,security,compat,correctness,style --notes "<one line>"
python3 $W clean  <run_id>
```

Final message to the user: level + model, rounds, what Claude changed on top of the worker's
patch, test results (from `verify`), REVIEW_FLAGS that fired, notable guard denials.

## 7. Calibrate (every ~10 ledger entries)

Read `~/.claude/skills/auto/runs.jsonl`. If a model keeps needing send-backs for a task class,
move that class up a level; if L2 tasks pass first time, try L1 for them. Record changes in
"Observed" below with the date.

### Observed
- 2026-10-11: setup. Flash-medium: toy bug fix 18s / 27k input tokens; a one-test task in
  linkdesk took 409s / 77k input — most of it a `git diff` pager hang (fixed: PAGER=cat).

## Token economics (answer for the user when asked)

- Gemini's tokens (Antigravity quota) replace Claude's for **exploring the codebase, writing
  code, and iterating on tests** — usually the bulk of an implementation.
- Claude still pays for: triage, the brief, reading the full diff, reading verify output, and
  send-back rounds. A worker that needs two rounds can cost Claude more than doing it.
- Net: clear win on L2 and well-specified L1 work with sizeable diffs; break-even or worse on
  small edits (hence L0) and on L3 (Claude still designs and reviews harder).
- Spawning Claude subagents/workflows to "help" eats the savings — keep /auto runs lean.
- Measure, don't guess: `runs.jsonl` has Gemini tokens per run.

## Security model (red-teamed 2026-10-11; keep it this way)

| Layer | What it stops |
|---|---|
| Standalone shallow repo in `$TMPDIR/auto-worker/<id>` (base commit only) | worker edits never touch the user's checkout; no stash, branches, remotes or credentials to read |
| `agy_guard.py` (agy PreToolUse hook, default-deny, fail-closed) | file reads/writes outside the worktree; control files (case-insensitive — APFS!); secrets; network/browser/MCP/unknown tools; shell beyond one simple allowlisted command; daemons |
| `sandbox.sb` via `run_sandboxed.sh` (every worker command and every verify) | network incl. unix sockets; writes outside worktree + private tmp; control files at any depth; links in the worktree; reading `$HOME`, `/private/tmp`, `/private/var/folders` except worktree/venv/private tmp; signals; launchd/AppleEvents/Shortcuts/Automator; caller's env (scrubbed) |
| Process sweep (env marker + cwd) after every run/test/verify | setsid'd daemons outliving the run and editing the tree after capture |
| Host-side git: explicit git dir, hooks/fsmonitor off, in-tree attributes ignored on reads, bytes-only output, `-z` unquoted paths, flags parsed from the patch by `git apply --numstat` | steering host git via `.git`/hooks/`.gitattributes`; lone-CR header forgery; non-ASCII path flag bypass |
| `verify --full` → `apply --sha` | testing a different tree than the one reviewed; applying a stale, unverified, flag-mismatched patch, onto a moved HEAD, or over the user's WIP |
| Minimal env for agy and sandboxed commands | Claude-session tokens leaking into worker code or patches |

Known residual risk: the reviewed patch is applied to the user's repo and later runs for real
(commit, deploy). Review is the last line of defence — that is why rules 3–4 and the
REVIEW_FLAGS exist.

## Files

| Path | What |
|---|---|
| `agy_worker.py` | run / resume / test / verify / apply / record / clean / list |
| `agy_guard.py` | agy PreToolUse hook; inert unless `AUTO_WORKER=1` |
| `test_guard.py` | offline guard tests (run after any guard change) |
| `test_worker.py` | worker-flow + sandbox regression tests with a fake agy and a toy repo (run after any change to `agy_worker.py`, `sandbox.sb`, `run_sandboxed.sh`) |
| `sandbox.sb`, `run_sandboxed.sh` | the macOS sandbox profile and its launcher |
| `~/.gemini/config/hooks.json` | registers the guard with agy (global; answers "ask" = no-op for normal agy use) |
| `runs/<id>/` | briefs, responses, per-round patches, meta (incl. verify results) |
| `runs.jsonl` | one line per finished task: level, model, rounds, Gemini tokens, outcome, defects |
| `logs/guard.jsonl` | every worker tool call the guard decided on (rotates at 5 MB) |

## Troubleshooting

- `agy` asks to log in / quota errors → tell the user; do not fall back to the deprecated
  `gemini` CLI (its personal OAuth tier was shut down — `IneligibleTierError`).
- Headless agy without `AUTO_WORKER=1` auto-denies every shell command and **aborts the run**;
  a hook "allow" cannot override that, hence skip-permissions + guard. Hook output `{}` or no
  output = deny; `{"decision":"ask"}` = defer to normal rules.
- Worker reports a needed read-only command as denied → consider adding it to the guard
  allowlist with a test case, after telling the user.
- Sandboxed command can't find a file under `~/Documents`: by design (only worktree, git dir
  and venv are readable). Run sandboxed commands with the worktree as cwd.
