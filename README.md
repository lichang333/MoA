# MoA — shared workers for Codex and Claude Code

Separate platform instructions, one shared implementation. The current session
coordinates tasks, external models contribute answers or isolated code changes,
and the coordinator reviews and integrates the result.

| Workflow | Purpose | Execution |
|---|---|---|
| `/moa` | Multi-model Q&A and analysis | Native analysis or external API answers; current-session synthesis |
| `/auto` | Delegated coding | agy, native Claude Code CLI or explicit Claude cloud sessions; local sandbox verification and reviewed-patch apply |

Codex uses the current session for dispatch and integration, with Astra for complex
planning or important review. Claude keeps its own tools and routes. Provider
models and role defaults live in `config/`; application profiles inherit shared
provider settings from `config/headless.json`.

The shared runners under `skills/` are platform-agnostic: any agent host can
drive them directly, including Muse (Meta's personal AI assistant). Use
`--platform headless` with the shared scripts when no platform entrypoint
applies; platform folders are symlinks into the shared implementation.

## Layout

```text
AGENTS.md / CLAUDE.md           platform-specific project entrypoints
platforms/codex/skills/         Codex moa and auto skill entrypoints
platforms/claude/skills/        Claude moa and auto skill entrypoints
shared/                        common project and workflow rules
config/                        provider defaults and platform routing profiles
skills/moa/                    shared API runner and offline tests
skills/auto/                   agy/native Claude executors, cloud bridge, guard, sandbox and tests
tests/                         installer tests
```

Platform folders link to shared scripts, workflow documents and profiles. Edit the
source in `skills/`, `shared/` or `config/`; there are no copied implementations.
API keys remain in the existing local `skills/moa/.env`, with no per-platform copy.

## Install or migrate

```bash
./install.sh --dry-run
./install.sh                         # both platforms
./install.sh --platform codex        # only Codex
./install.sh --platform claude       # only Claude
```

Codex installs into `~/.agents/skills/{moa,auto}`. Claude installs into
`~/.claude/skills/{moa,auto}`. The installer replaces the old shared Claude→Codex
link with independent links, backs up conflicts under
`~/.local/share/moa-install-backups/`, and preserves unrelated Gemini hooks.
A Codex-only migration also detaches a recognized old managed Claude→Codex link,
so Claude does not silently start reading Codex instructions. Other unselected
platform installations are left alone.

The shared agy guard is registered for either platform. An existing `.env` is
preserved. When moving from an older installed checkout, its existing local key
file is copied if the new checkout has none; otherwise `.env.example` is used.
Old run records remain in their original checkout. Re-running the installer
is safe. Start a fresh session if the current host has cached skill instructions.

## Inspect routes without calling models

```bash
python3 skills/moa/moa_runner.py --platform codex --show-config
python3 skills/moa/moa_runner.py --platform claude --dry-run
```

These commands do not load credentials or send requests. `native_roles` are
instructions for the host coordinator; `agy_routes` select external coding workers.
These settings do not change the active chat model,
automatically create an Astra session, or send OpenAI model IDs to Antigravity.

For API-backed Q&A, both application profiles default to raw collection:

```bash
python3 skills/moa/moa_runner.py --platform codex --models deepseek,minimax --coordinator-model current --task-id example -- 'Question to compare'
```

The coordinator synthesizes successful answers. Installed platform entrypoints
infer their platform even when `--platform` is omitted. Use `--platform headless`
only when an additional paid API aggregator is wanted. A bare invocation of the
shared core script retains legacy headless behavior. `--raw`, `--review`, `--glm52`
and existing output markers remain
available. External provider model defaults are preserved; offline tests do not
establish their current live API availability.

## Coding execution and records

`--platform codex` identifies the coordinator. Executors are **agy**, **claude-local** and the explicit **claude-cloud** bridge,
recorded separately.
Native Codex/Claude subagents help with read-only planning and review; they do not
inherit agy hooks or sandboxing. Delegated implementation follows the
[shared coding workflow](shared/auto-workflow.md).

The agy executor retains disposable standalone repos, a default-deny guard, macOS
sandboxing, process cleanup and whole-patch review. Applying requires the reviewed
SHA, full verification against the current HEAD, clean target files and protected
path checks. `.codex` is protected at any depth, including mixed-case paths.

Runs identify the platform, coordinator model (or `current` when unknown), task ID
and executor. API records live under `skills/moa/runs/`; coding records and ledger
remain under `skills/auto/runs/` and `runs.jsonl`. IDs are unique across concurrent
starts. Same-run resume/verify/apply must stay sequential; there is no persistent
queue or crash-recovery service. Records may contain model output, briefs or
patches and are ignored by Git.

agy can continue the same session once after an explicitly retryable network
failure. `--network-retries 0` disables recovery (maximum: two). Attempts preserve
partial patches and share the original time budget; quota/authentication errors
or safety/review flags stop instead. See the shared workflow for the exact gates.

## Native Claude Code CLI

The [native CLI workflow](shared/claude-local-workflow.md) uses first-party
Claude Pro/Max included allowance. `claude_local.py` provides prepare,
observe-funding, run and feedback resume. Native tools are disabled; a trusted
MCP broker supplies scoped file operations and sandboxed tests. Partial patches,
actual reported model IDs and usage are retained; full verification and reviewed
SHA apply use the shared worker. No automatic model fallback or paid API switch.

## Claude cloud credits and subscription execution

The [cloud workflow](shared/cloud-workflow.md) uses the official signed-in Claude
CLI, with no Anthropic API key. Prefer unexpired eligible cloud credits for
suitable GitHub tasks when minimizing new cash spending. It supports preparing
bounded briefs, launching or attaching cloud sessions, submitting follow-ups and
importing an already-fetched result commit. Imported code still requires whole
patch review, local macOS sandbox verification and reviewed-SHA apply.

```bash
python3 skills/auto/claude_cloud.py prepare --repo "$PWD" --brief '<brief.md>' --platform codex
python3 skills/auto/claude_cloud.py attach '<run-id>' --session '<Claude-cloud-session-URL>'
python3 skills/auto/claude_cloud.py status '<run-id>'
```

These three commands call no model. Before `launch` or `send`, record a recent
actual account-panel observation with `observe-funding`; when attaching an older
session, prepare with `--base '<confirmed-cloud-start-commit>'` and its original
brief rather than assuming local HEAD. For funding fields,
use `--help` or the
workflow for fields. Unknown/stale/expired funding is refused. Each observation
is single-use, repeated observations cannot reset it, and same-run mutations are
locked. This preflight is not a live spending cap: ongoing cloud tasks can use
regular subscription allowance after promo credit is depleted. Extra usage must
remain off; the bridge never purchases credits or falls back to a paid API.

Progress and resulting branch/model are checked in the Claude UI. Local status
does not pretend to know remote completion, remaining quota or actual cost.
Requested and observed model families are separate. Cloud execution does not
inherit agy's guard, and the remote GitHub branch can advance after launch
preflight; the cloud brief must check the expected base before starting.
Automatic quota polling and background scheduling are not implemented.

## Offline verification

```bash
python3 skills/moa/test_runner.py
python3 skills/auto/test_guard.py
python3 skills/auto/test_worker.py
python3 skills/auto/test_cloud.py
python3 skills/auto/test_local.py
python3 skills/auto/test_recovery.py
python3 tests/test_install.py
python3 tests/test_platforms.py
```

Runner tests mock providers. Worker tests use fake agy and temporary toy repos;
installer tests use temporary homes. Sandbox tests require macOS `sandbox-exec`.
They make no paid model calls. Run both auto suites after changing the guard,
sandbox or worker; run affected runner/installer suites for their changes.
