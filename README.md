# MoA — Mixture of Agents skills for Claude Code

Two Claude Code skills that put other models to work while Claude stays in charge of quality.

| Skill | What it does | Models |
|---|---|---|
| [`/moa`](skills/moa/SKILL.md) | Q&A / analysis: several models answer, Claude adds its own web-grounded answer and synthesizes the result | GLM, DeepSeek, MiniMax, Gemini, GPT/Claude APIs (keys in `skills/moa/.env`) |
| [`/auto`](skills/auto/SKILL.md) | Coding: Claude triages a task (L0–L3), delegates implementation to Gemini through the Antigravity CLI (`agy`) in a sandbox, then reviews, verifies and commits | Gemini 3.x (and Claude via Antigravity) on the Antigravity quota |

## Install

```bash
./install.sh
```

It symlinks `skills/moa` → `~/.agents/skills/moa` (and `~/.claude/skills/moa` → that) and
`skills/auto` → `~/.claude/skills/auto`, creates `skills/moa/.env` from `.env.example` if missing,
and merges the `/auto` guard into `~/.gemini/config/hooks.json`. Anything in the way is moved to
`~/.local/share/moa-install-backups/<timestamp>/`, never deleted.

## /auto security model (summary)

Gemini has broken this machine before, so `/auto` assumes the worker is careless or hostile:

1. **Standalone throwaway repo** per task (base commit only: no stash, branches, remotes, credentials).
2. **`agy_guard.py`** — agy PreToolUse hook; inert unless `AUTO_WORKER=1`; default-deny, fail-closed;
   only worktree-local file access, no control files (case-insensitive), one allowlisted shell
   command at a time, no network/browser/MCP tools.
3. **`sandbox.sb`** (macOS `sandbox-exec`) for every worker command and every verification: no
   network, writes only to the worktree, `$HOME` and shared temp dirs unreadable, scrubbed env,
   no launchd/AppleEvents/Shortcuts, leftover processes swept.
4. **Claude reviews the whole patch** (with automatic `REVIEW_FLAGS`).
5. **`verify --full` → `apply --sha`**: only the exact reviewed bytes, tested on a fresh tree at the
   user's current HEAD, land in the user's working tree.

Red-teamed twice (2026-10-11); every finding has a regression test:

```bash
python3 skills/auto/test_guard.py    # guard decisions (offline payloads)
python3 skills/auto/test_worker.py   # worker flow + sandbox (fake agy, toy repo)
```

Run both after any change to the guard, sandbox or worker.

## Not in git

`skills/moa/.env` (API keys), `skills/auto/runs/`, `runs.jsonl`, `logs/` (local run records).
