---
name: moa
description: Run multi-model Q&A or analysis when the user invokes /moa or requests Mixture of Agents synthesis. Antigravity coordinates native subagents or external API answers and synthesizes the result in the current session. For delegated coding, use auto instead.
---

# MoA in Antigravity (Gemini)

The current Antigravity session coordinates the work and produces the final answer.
Read [the shared workflow](workflow.md) for evidence handling, runner options and
run records. [Routing](routing.json) contains the Gemini profile and inherits
external provider settings from the common profile.

- For native collaboration, use Antigravity's subagent tools (`invoke_subagent`,
  `send_message`, background tasks) available in this session. Decompose independent
  research or analysis into self-contained briefs; select available models from `native_roles`.
- For external model perspectives, run the shared script beside this skill:

  ```bash
  python3 "$HOME/.gemini/config/skills/moa/moa_runner.py" --platform gemini --raw \
    --coordinator-model '<actual-model-or-current>' --task-id '<task-id>' \
    -- '<question>'
  ```

  `--models deepseek,minimax` illustrates selecting external providers. Inspect
  `--show-config` without making a model call. External calls use their API keys
  and billing; native subagents use the host's own model access.
- Use Antigravity's available web/search tools for current information. Synthesize successful
  answers in this session; Antigravity is not a reason to select headless API aggregation.
- If external providers are unavailable, native analysis can still satisfy the
  request; disclose missing perspectives when they matter.
