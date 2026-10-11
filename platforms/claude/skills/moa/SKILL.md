---
name: moa
description: Run multi-model Q&A or analysis when the user invokes /moa or requests Mixture of Agents synthesis. Claude coordinates native agents or external API answers and synthesizes the result in the current session. For delegated coding, use auto instead.
---

# MoA in Claude Code

Claude in the current session owns dispatch, research and final synthesis.
Read [the shared workflow](workflow.md) for evidence handling, runner options and
records. [Routing](routing.json) contains the Claude profile.

For external perspectives:

```bash
python3 "$HOME/.claude/skills/moa/moa_runner.py" --platform claude --raw \
  --coordinator-model '<actual-model-or-current>' --task-id '<task-id>' \
  -- '<question>'
```

Select a relevant subset with `--models` when useful. API workers and optional
API review consume their providers' quotas; synthesis here avoids an additional
aggregator API call but still uses the current session's allowance.

Use Claude Code's available `WebSearch`/`WebFetch` tools for current facts. Compare
worker answers against sources and produce an independent synthesis. For difficult
questions, apply the shared deep-review criteria; the external reviewer is configured
in the profile. User `--fast`/`--no-deep` choices suppress extra review.

If using native collaboration or no external keys are available, use the actual
Claude Code `Agent` tool to assign independent analysis and review. Choose roles
that help this task; do not invent `define_subagent` or `invoke_subagent` tools.
Do not import the Codex entrypoint's model routing into Claude's Agent calls.
