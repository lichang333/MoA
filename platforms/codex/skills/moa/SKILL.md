---
name: moa
description: Run multi-model Q&A or analysis when the user invokes /moa or requests Mixture of Agents synthesis. Use Codex native subagents or the shared external API runner, then synthesize in the current session. For delegated code implementation, use auto instead.
---

# MoA in Codex

The current Codex session coordinates the work and produces the final answer.
Read [the shared workflow](workflow.md) for runner options, evidence handling and
run records. [Routing](routing.json) contains the Codex role choices and inherits
external provider settings from the common profile.

- For native collaboration, use the subagent tools actually available in this
  session. Decompose independent research or analysis into self-contained briefs;
  select available models from `native_roles`. When selecting a different model,
  use the tool's supported fresh-context mode and include the required context.
- Use the configured Astra planner/reviewer for difficult plans, substantial
  disagreement or consequential verification. The current session retains
  dispatch, evidence collection and integration. Ordinary tasks need no extra
  management pass. If a requested model is unavailable, state that limitation
  and use the current session unless the user's requirement prevents it.
- For external model perspectives, run the shared script beside this skill:

  ```bash
  python3 "$HOME/.agents/skills/moa/moa_runner.py" --platform codex --raw \
    --coordinator-model '<actual-model-or-current>' --task-id '<task-id>' \
    -- '<question>'
  ```

  `--models deepseek,minimax` illustrates selecting external providers. Inspect
  `--show-config` without making a model call. External calls use their API keys
  and billing; native subagents use the host's own model access.
- Use Codex's available search tools for current information. Synthesize successful
  answers in this session; Codex is not a reason to select headless API aggregation.
- If external providers are unavailable, native analysis can still satisfy the
  request; disclose missing perspectives when they matter. Do not invent tool
  names or treat plain API responses as code-executing agents.
