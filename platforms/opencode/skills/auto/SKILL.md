---
name: auto
description: Delegate bounded coding tasks from OpenCode to isolated Google AI Ultra (agy) workers under macOS sandbox and guard enforcement (automatically in Build/Swarm or when invoking /auto). OpenCode plans, auto-selects models across all 8 agy families (19 variants), reviews cross-family, verifies in sandbox, and applies reviewed patches. Excludes Q&A synthesis and production/SSH/deployment tasks.
---

# Delegated coding in OpenCode (`/auto`)

Read [the shared coding workflow](workflow.md) for every coding task, including L0. OpenCode owns triage, briefing, automatic model selection, cross-family cold-eyes review, sandbox verification, and integration; [routing](routing.json) and [headless.json](headless.json) supply the active 8-family / 19-variant Google AI Ultra (`agy`) catalog.

## Automatic Coordinator Model Selection & Cost-Saving Routing
Follow `auto_funding` (`included_subscription` first) and **select models automatically without asking the user** (honor explicit user overrides when given). Inspect the active catalog anytime with `python3 "$HOME/.config/opencode/skills/auto/agy_worker.py" models`:
- **L0** (1–2 small edits, live operations, SSH/deploy, guard/sandbox changes): handle directly in OpenCode.
- **Fast L1 / mechanical edits**: `gemini-4-argon-high` or `gemini-4-carbon-medium` (`gemini-4-argon-low` for quick lookups).
- **Standard L1 / L2 implementation/bugfix**: `gemini-4-carbon-high` (or `claude-sonnet-5-5-high`).
- **Deep algorithmic / cross-file synthesis**: `gemini-4-hydrogen-xhigh` or `gemini-4-hydrogen-high`.
- **L3 architecture / tricky diagnosis**: `gemini-pro-orchestrator` (`Orchestrator (Carbon)`), `gemini-pro-orchestrator-argon`, or `claude-opus-5-5-high` (or split into bounded L1/L2 slices).
- **Cold-eyes review (`review --executor agy`)**: always choose a **different family** from the slice author (`claude-opus-5-5-high` / `claude-sonnet-5-5-high` to review Gemini 4; `gemini-pro-orchestrator` to review Claude).
- **Cross-pool failover (`429` / quota)**: automatically switch between the **Gemini 4 / Orchestrator** pool and the **Claude 5.5 / GPT-OSS 120B** (`gpt-oss-120b-medium`) pool while preserving partial patches. Never silently fall back to prepaid APIs without explicit authorization.

| Family | Tier | Canonical Model IDs (19 total; `gemini-3.8` retired) |
|---|---|---|
| Orchestrator (Carbon) | `l3_and_review` | `gemini-pro-orchestrator` |
| Orchestrator (Argon) | `l3_and_review` | `gemini-pro-orchestrator-argon` |
| Gemini 4 Carbon | `coding` | `gemini-4-carbon-high`, `gemini-4-carbon-medium`, `gemini-4-carbon-low` |
| Gemini 4 Argon | `coding_and_fast` | `gemini-4-argon-high`, `gemini-4-argon-medium`, `gemini-4-argon-low` |
| Gemini 4 Hydrogen | `deep_coding` | `gemini-4-hydrogen-xhigh`, `gemini-4-hydrogen-high`, `gemini-4-hydrogen-medium`, `gemini-4-hydrogen-low` |
| Claude Opus 5.5 | `l3_and_review` | `claude-opus-5-5-high`, `claude-opus-5-5-medium`, `claude-opus-5-5-low` |
| Claude Sonnet 5.5 | `coding_and_review` | `claude-sonnet-5-5-high`, `claude-sonnet-5-5-medium`, `claude-sonnet-5-5-low` |
| GPT-OSS 120B | `open_weights_fallback` | `gpt-oss-120b-medium` |

UI display names and shorthands (e.g. `"Claude Opus 5.5"`, `"Gemini 4 Hydrogen (XHigh)"`, `"Orchestrator (Argon)"`) are automatically resolved by `agy_worker.py`.

## Run, review, verify, and apply
Write a self-contained brief (`GOAL`, `CONTEXT`, `REQUIREMENTS`, `CONSTRAINTS`, `ACCEPTANCE`, `OUT OF SCOPE`) to an ignored file or temp path and launch `agy_worker.py`:

```bash
W="$HOME/.config/opencode/skills/auto/agy_worker.py"
python3 "$W" run --repo "$PWD" --brief '<brief.md>' --model '<chosen-agy-model>' \
  --platform opencode --coordinator-model '<actual-model-or-current>' \
  --task-id '<task-id>' --name '<slug>'
```

1. **Inspect patch & flags**: read `diff.patch` completely and check `REVIEW_FLAGS` (`protected_paths` including `.opencode`, `sensitive_paths`, `execution_surface`, `INCOMPLETE_RUN`).
2. **Cold-eyes review (\$0 API cost)**: run cross-family review using `--executor agy` (`--model claude-opus-5-5-high` for Gemini authors, or `gemini-pro-orchestrator` for Claude authors):
   ```bash
   python3 "$W" review '<run-id>' --executor agy --model '<cross-family-reviewer>' --json
   ```
3. **Revise if needed** (max 2 rounds):
   ```bash
   python3 "$W" resume '<run-id>' --brief '<feedback.md>'
   ```
4. **Verify in fresh macOS sandbox & apply reviewed SHA**:
   ```bash
   python3 "$W" verify '<run-id>' --full -- <project-test-command>
   python3 "$W" apply '<run-id>' --sha '<reviewed-sha256>'
   python3 "$W" record '<run-id>' --level L2 --outcome accepted --notes '<summary>'
   python3 "$W" clean '<run-id>'
   ```

For explicit Claude local/cloud routing, see [claude-local-workflow.md](claude-local-workflow.md) and [cloud-workflow.md](cloud-workflow.md). End every `/auto` reply with the shared workflow's **模型调用说明**.
