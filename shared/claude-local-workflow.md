# Native Claude Code execution

Use `claude_local.py` for a bounded local coding task funded by confirmed Claude
Pro/Max included allowance. Record executor `claude-local`; this is separate from
Antigravity and Claude cloud. The current coordinator owns selection, review and
integration. A quota successor still requires the shared senior-model decision.

## Prepare and check funding

Inspect the installed CLI version and actual `/model` picker without sending a
probe prompt or changing the default. Use an eligible alias from
`claude_local_defaults` in the shared profile. A listed or requested alias is not
proof of quota, actual backend version or subscription eligibility.

```bash
L='<installed-auto-skill>/claude_local.py'
W='<installed-auto-skill>/agy_worker.py'
python3 "$L" prepare --repo "$PWD" --brief '<brief.md>' --model opus \
  --platform codex --coordinator-model '<actual-model-or-current>' --task-id '<task-id>'
python3 "$L" observe-funding '<run-id>' --remaining '<remaining-percent>' \
  --observed-at '<ISO-time-with-zone>' --expires-at '<earliest-reset-or-expiry>' \
  --extra-usage-off --evidence account-panel
python3 "$L" run '<run-id>' --dry-run
python3 "$L" run '<run-id>' --timeout 1200
```

Preparation, funding recording and dry-run make no model call. Preparation imports
only the chosen commit into a standalone repository, excludes uncommitted changes
and rejects secret-looking tracked paths. The preflight checks first-party
Claude Pro/Max login with the same isolated CLI settings and a scrubbed environment;
API keys and alternate-provider variables are not passed through.

Read `/usage` or the account panel: both current-session and weekly limits must be
positive, with usage credits/extra usage off. Record the more constrained remaining
percentage and earliest applicable reset/expiry, never a permanent balance.
An explicit current user statement can use `--evidence user-statement`.
Funding observations expire after the configured interval, are consumed once, and
must be newer before another submission. This observation is not a live spending
cap. The adapter does not enable usage credits, purchase tokens or switch to an API.

## Execution boundary

The model uses only five trusted MCP broker tools: list/read/write/edit workspace
files and run allowlisted tests. All native CLI tools are disabled. Restricted
mode, empty setting sources, disabled hooks/skills/memory and a strict explicit
MCP configuration prevent repository/user customization from supplying tools.
Managed policy may still apply; inspect any configured managed customization.
This adapter does not rely on hooks to fail closed and never offers native Bash
as a fallback. Broker failure stops the action.

File tools reject secret/control paths, outside paths, hardlinks and non-text or
oversized files. Candidate test execution uses the existing network-denied macOS
sandbox and process cleanup. The CLI itself needs subscription network/keychain
access; it is not described as sandboxed candidate code. The trusted broker is
launched with Python `-I`, never importing project modules.

Real runs retain the CLI `system/init` inventory. Unexpected tools, missing broker,
plugins or initialization errors terminate the invocation. `EndConversation` is
the sole permitted auxiliary builtin. This event verifies reported runtime tools;
it does not independently prove which instruction files were read before startup.
Offline fixtures and `--help` checks alone do not prove a live CLI inventory.

Quota/auth errors, invalid structured results, timeout and interruption retain the
partial patch and stop. There is no automatic retry or model fallback. Runtime
configuration hashes must match preparation. Every same-run mutation takes the
shared lock. Investigate a retained `running` state after coordinator interruption
before continuing; do not replay an ambiguous launch blindly.

## Review, verify and continue

Read the complete captured patch, then use the shared worker's `test`,
`verify --full`, reviewed-SHA `apply`, `record` and `clean` commands. Required
checks, protected paths, clean target files and current HEAD gates are unchanged.
The native broker supports bounded Python/Node checks; the coordinator performs
the project's complete build/test commands through sandboxed `verify`.

For an ordinary review defect, return a bounded feedback brief to the worker
instead of having the coordinator redo the implementation. Record a fresh funding
observation and use `claude_local.py resume '<run-id>' --brief '<feedback.md>'`.
This starts a **new CLI session** in the retained worker tree with the original
brief and feedback; it does not resume a failed conversation. Follow the shared
limit of two feedback rounds and the separate quota handoff rule.

The model usage note includes requested alias, actual models reported by the CLI,
channel, task, failures and switches. Metadata/ledger retain native token usage,
including cached input. Token counts are not billed amounts or remaining quota.

Run `test_local.py`, `test_guard.py`, `test_worker.py`, `test_recovery.py`,
`test_cloud.py` and `tests/test_platforms.py` after execution-boundary changes.
These use local fixtures without model calls. Report live integration separately.
