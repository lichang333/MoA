---
name: moa
description: Use when the user invokes the /moa command or asks to process a task/prompt using the Mixture of Agents (MoA) workflow. This skill orchestrates spawning worker subagents (logic analyst, creative writer, technical reviewer) to process a prompt and then aggregates their responses into a single high-quality output. It supports both local Gemini subagents and external model mixing (GPT-4o, Claude 3.5 Sonnet, GLM-4, DeepSeek-Chat, MiniMax-M3, Gemini-3.5-Flash) via a python runner.
---

# Mixture of Agents (MoA) Workflow

## Purpose
This skill implements the Mixture of Agents (MoA) design pattern. When running inside
Claude Code, the **preferred** mode is Claude-Orchestrated Mode: the Python runner gathers
the external API workers, Claude (this session) adds its own vote for free, and Claude
performs the final aggregation itself — no paid Anthropic API call and no aggregator API cost.

Modes:
1. **Claude-Orchestrated Mode (preferred, free Claude vote)**: Run `moa_runner.py --raw` to
   collect worker answers from the configured API models (GLM-4, DeepSeek-Chat, MiniMax-M3,
   Gemini-3.5-Flash, and GPT-4o / Claude API if their keys are set). Claude then adds its own
   answer and synthesizes everything directly in the conversation.
2. **Full-Script API Mode**: Run `moa_runner.py` (no `--raw`) to let the script both call
   workers and pick a paid API aggregator (Anthropic > OpenAI > Gemini > DeepSeek > GLM).
   Use only when not running inside Claude Code, or when a fully headless run is required.

## Operating Rules
- When the user runs `/moa` or triggers this skill, first verify they provided the target prompt. If not, ask for it.
- Default to **Mode 1 (Claude-Orchestrated)** when running inside Claude Code — it adds a free Claude vote and avoids aggregator API cost.
- Keys are read from the environment or the config file (`~/Desktop/moa_keys.env` or `.env` inside the skill directory).

### Deciding deep mode (Claude judges automatically)
Claude decides whether to run the deep cross-review (GLM 5.2), unless the user overrides:
- **Explicit override wins**: if the prompt contains `--deep` → always deep; if it contains `--fast` or `--no-deep` → never deep. Strip these flags before sending the prompt to the runner.
- **Otherwise Claude auto-judges.** Because deep mode costs one paid GLM 5.2 call, DEFAULT TO NORMAL and only escalate to deep when the task is genuinely hard. Escalate when ANY of these hold:
  - Multi-step reasoning, non-trivial code/architecture/algorithm/math design, or a decision with real trade-offs.
  - High stakes where a wrong answer is costly (financial/legal/medical/security/data-loss), or the user explicitly wants rigor ("thorough", "carefully", "重要", "深度").
  - The proposer answers (from `--raw`) **materially disagree** or several errored, so a single synthesis is risky.
  - Long, multi-part prompts, or ambiguous prompts with competing valid interpretations.
- **Keep normal** for: simple factual lookups, short/casual generation, quick edits, or anything Claude is already highly confident about.
- **Be transparent about cost**: when auto-escalating to deep, state one short line first (e.g. "任务较复杂,升级 deep 模式:多一次 GLM 5.2 付费评审") so the user isn't surprised by the paid call. Never run deep silently.

---

### Mode 1: Claude-Orchestrated Mode (preferred)
1. Run the runner in raw mode to collect the external workers only (no paid aggregation):
   ```bash
   python3 /Users/elleryli/.agents/skills/moa/moa_runner.py --raw "<prompt>"
   ```
2. Parse the JSON between the `===MOA_RAW_JSON_START===` and `===MOA_RAW_JSON_END===` markers — it is a `{model_name: response}` map of the external worker answers.
3. **Web-ground if the prompt is time-sensitive**: the external workers have NO live web access, so for anything about recent/latest/current events, news, prices, market data, releases, or "what's new" topics, Claude MUST run WebSearch (and WebFetch as needed) to gather real current data before answering. Prefer authoritative/primary sources.
4. **Add Claude's own vote**: independently produce a strong Claude answer to the original prompt, grounded in the web results from step 3 when applicable (do not just echo the workers).
5. **Aggregate as Claude**: synthesize the external worker answers plus Claude's own web-grounded answer into one outstanding final response, applying the **Proposer weighting** below. Prefer fresh, verifiable facts over stale model output; flag any worker answers that are outdated, hallucinated, or errored. Retain the best logic, fix errors, format cleanly, and do not name models unless useful. This aggregation is done by Claude directly — it costs nothing extra.

   **Proposer weighting (priors from observed behavior — adjust per response, not blindly):**
   - **DeepSeek-Chat — HIGH.** Consistently solid, well-structured, reliable. Use as a primary backbone of the synthesis.
   - **MiniMax-M3 — HIGH (breadth).** Most thorough/comprehensive; best for coverage and edge cases. Caveats: verbose, and it emits chain-of-thought (now stripped by the runner) — weight its *conclusions*, not its length.
   - **Gemini-3.5-Flash — MEDIUM-HIGH.** Strong and often contributes unique angles others miss; had past reliability issues (now on the streaming endpoint). Mine it for novel ideas.
   - **GLM-4-flash — LOW.** Fast/cheap breadth filler and error-redundancy; tends to be shallow/generic. Treat as a tie-breaker or a source of a stray unique point — do NOT lean on it for depth.
   - **Claude (self) — anchor.** Claude's own web-grounded answer is the correctness anchor; when a proposer conflicts with verifiable facts, trust the facts.
   - **Always override priors with the actual response:** a LOW model that clearly nails a point beats a HIGH model that's wrong this time. Discard any proposer that errored or is stale.
6. **Deep cross-review (plan B, when deep mode is active per "Deciding deep mode" above)**: after Claude's draft synthesis, send it to the strong GLM 5.2 reviewer for an adversarial critique:
   ```bash
   python3 /Users/elleryli/.agents/skills/moa/moa_runner.py --review "You are an adversarial reviewer. Find errors, gaps, unsupported claims, and risks in the following draft answer to <original prompt>. Be specific and critical. DRAFT:\n<Claude draft>"
   ```
   Parse GLM 5.2's critique between `===MOA_REVIEW_START===` and `===MOA_REVIEW_END===`, then have Claude produce the FINAL answer incorporating or explicitly rejecting each point. This is the "Claude + GLM 5.2 dual-brain" path and costs one paid GLM 5.2 call — do NOT run it for simple tasks.
7. Be transparent about worker failures (timeouts/errors) when they materially affect the result.
8. Output the final synthesized response to the user, with a "Sources:" list when web data was used.

---

### Mode 2: Full-Script API Mode
Use when not inside Claude Code (fully headless):
1. Run the script:
   ```bash
   python3 /Users/elleryli/.agents/skills/moa/moa_runner.py "<prompt>"
   ```
2. Display progress (worker status, aggregation) and output the final synthesized response. Note: this path calls a paid API aggregator.

---

### Mode 3: Local Subagent Mode (Fallback)
If no external keys are configured, use the environment's native subagent
mechanism (in Claude Code that is the **Agent tool** — `define_subagent`/
`invoke_subagent` do not exist there; spawn three parallel Agent calls instead):
1. **Define 3 specialized subagents** with these roles:
   - `moa-logic`: "You are a subagent specialized in logical reasoning, data structures, algorithms, correctness, and edge cases. Analyze the prompt, write a correct and logically sound solution, and discuss edge cases."
   - `moa-creative`: "You are a subagent specialized in high-quality technical writing, clear structures, explanations, and readable presentation. Explain the solution beautifully, formatting it with clean markdown."
   - `moa-critic`: "You are a subagent specialized in code review, potential performance bottlenecks, and security. Review the solution, point out potential flaws, security issues, or performance concerns, and how to address them."
2. **Invoke concurrently** (in Claude Code: three Agent tool calls in one message). Do not block. Wait for them to respond.
3. **Aggregate**: Collect all 3 responses, synthesize them, and output the final response to the user.
