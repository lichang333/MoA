# Shared project conventions

- Keep platform instructions separate and runtime implementations shared. Provider
  models and role defaults belong in `config/`, not in prompts or Python constants.
- A platform identifies the coordinating application; an executor identifies the
  tool that runs the work. Recording `platform=codex` does not make agy a Codex executor.
- Preserve local API keys, existing user configuration and unrelated hooks. Never
  commit `.env`, run outputs, briefs or credentials. Do not call paid models merely
  to validate a refactor; use mocked transports and disposable local fixtures.
- Keep the agy default-deny guard, sandboxed execution, whole-patch review, SHA,
  HEAD and verification gates intact. Native subagents are not covered by agy hooks.
- Security and worker changes require both `python3 skills/auto/test_guard.py` and
  `python3 skills/auto/test_worker.py`, plus `python3 skills/auto/test_recovery.py`
  for transport recovery. Runner changes require
  `python3 skills/moa/test_runner.py`; installer changes require
  `python3 tests/test_install.py`. These tests use local fixtures and no live models.
- Cloud transport changes also require `python3 skills/auto/test_cloud.py`.
  Imported cloud code must use the same local sandbox, full verification and
  reviewed-SHA apply gates. Observed credit/plan data is not a live spending cap.
- After editing a platform skill, validate its frontmatter and check its links.
  Run `python3 tests/test_platforms.py` to check complete installable entrypoints.
  State which checks ran and any untested live integration in the final report.
