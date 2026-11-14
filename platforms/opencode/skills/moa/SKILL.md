---
name: moa
description: Run multi-model Q&A or analysis when the user invokes /moa or requests Mixture of Agents synthesis in OpenCode. Collects Orchestrator (Carbon) via Google AI Ultra (agy CLI, $0 API cost) plus DeepSeek-Chat and MiniMax-M3, adds the host's web-grounded vote, and synthesizes one verified answer. For delegated coding, use auto or swarm instead.
---

# Mixture of Agents (MoA) in OpenCode

The current OpenCode session (`zhipu/glm-5.2` or active host) is the coordinator and final synthesizer. Read [the shared workflow](workflow.md) for evidence rules and run records. [Routing](routing.json) contains the OpenCode profile and inherits shared defaults from [headless.json](headless.json).

## Why this lineup saves tokens and cost
- **Host (OpenCode `glm-5.2`)**: Anchor vote with live codebase tools and web search, plus final synthesis (avoids a paid API aggregator call).
- **Default Workers (`agy`, `deepseek`, `minimax`)**:
  - `agy` (`Orchestrator (Carbon)` / `gemini-pro-orchestrator`): runs read-only via local `agy --mode plan` on your **Google AI Ultra subscription (\$0 marginal API cost)**.
  - `deepseek` (`DeepSeek-Chat`) & `minimax` (`MiniMax-M3`): independent non-GLM model families via prepaid APIs.
  - `glm` worker is intentionally omitted from `worker_defaults` in `routing.json` to avoid a redundant same-family GLM API call.
- **Zero-API-cost single consult**: pass `--models agy` when you only want a second opinion from `Orchestrator (Carbon)` without spending prepaid API tokens.

## Operating steps
1. Verify the user supplied a prompt (if not, ask via `question` or plain reply). Strip workflow-only flags (`--deep`, `--fast`, `--no-deep`) before passing the prompt to the script.
2. Run the shared runner in raw mode:
   ```bash
   python3 "$HOME/.config/opencode/skills/moa/moa_runner.py" --platform opencode --raw \
     --coordinator-model '<actual-model-or-current>' --task-id '<task-id>' -- '<question>'
   ```
   Inspect `routing.json` or run `--show-config` without calling models. Parse worker answers between `===MOA_RAW_JSON_START===` and `===MOA_RAW_JSON_END===`.
3. **Web-ground current facts**: external workers have no live web access here. Use OpenCode's `websearch` and `webfetch` when the prompt depends on recent releases, docs, prices, or current events.
4. **Add the host's grounded vote and synthesize**: compare worker answers against verified sources and local files, resolve disagreements using evidence rather than majority vote, and preserve material uncertainty or worker failures.
5. **Optional deep cross-review (`--deep`)**: for genuinely complex or high-stakes tasks (or when workers materially disagree), run `--review` to critique the host draft with `Orchestrator (Carbon)` via Google AI Ultra (**\$0 API cost**):
   ```bash
   python3 "$HOME/.config/opencode/skills/moa/moa_runner.py" --platform opencode --review \
     -- 'Original prompt and draft to critique...'
   ```
   Incorporate or explicitly refute each point from `===MOA_REVIEW_START===` ... `===MOA_REVIEW_END===` in the final response. Never pass `--glm52` when the host is GLM.
