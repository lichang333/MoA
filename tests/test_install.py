"""Offline installation tests; every invocation gets its own temporary HOME."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
HOOK_KEY = "claude-auto-worker-guard"


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="moa-install-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        # Spaces exercise hook-command quoting and shell argument handling.
        self.repo = self.root / "project with spaces"
        self.repo.mkdir()
        self.user_home = self.root / "user home"
        self.user_home.mkdir()
        shutil.copy2(REPO / "install.sh", self.repo / "install.sh")
        self.write("hooks/agy-hooks.json", json.dumps({HOOK_KEY: {
            "PreToolUse": [{"matcher": "*", "hooks": [
                {"type": "command", "command": "~/.claude/skills/auto/agy_guard.py",
                 "timeout": 15}]}]}}))
        self.write("skills/moa/.env.example", "EXAMPLE_API_KEY=\n")
        self.write("skills/auto/agy_guard.py", "#!/usr/bin/env python3\n")
        for platform in ("codex", "claude"):
            for skill in ("moa", "auto"):
                self.write(f"platforms/{platform}/skills/{skill}/SKILL.md",
                           f"{platform}: {skill}\n")

    def write(self, relative, content, home=False):
        path = (self.user_home if home else self.repo) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def invoke(self, *args, success=True):
        env = dict(os.environ, HOME=str(self.user_home))
        result = subprocess.run(["bash", str(self.repo / "install.sh"), *args],
                                env=env, capture_output=True, text=True, timeout=10)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def link(self, relative, target):
        path = self.user_home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target, target_is_directory=True)
        return path

    def old_install(self, name="old checkout", platform="codex", fifo=False):
        shared = self.root / name / "skills/moa"
        shared.mkdir(parents=True)
        (shared / "moa_runner.py").write_text("# Previous shared runner\n")
        if fifo:
            os.mkfifo(shared / ".env")
        else:
            (shared / ".env").write_text(f"TEST_API_KEY={name}\n")
            (shared / ".env").chmod(0o600)
        (shared / "runs").mkdir()
        (shared / "runs/history.json").write_text('{"old": true}\n')
        directory = ".agents" if platform == "codex" else ".claude"
        self.link(f"{directory}/skills/moa", shared)
        return shared

    def assert_installed(self, platform):
        directory = ".agents" if platform == "codex" else ".claude"
        for skill in ("moa", "auto"):
            path = self.user_home / directory / "skills" / skill
            self.assertTrue(path.is_symlink())
            self.assertEqual(os.readlink(path), str(self.repo / "platforms" / platform /
                                                   "skills" / skill))

    def hooks(self):
        return json.loads((self.user_home / ".gemini/config/hooks.json").read_text())

    def backups(self):
        return list((self.user_home / ".local/share/moa-install-backups").glob("*/*"))

    def snapshot(self):
        result = {}
        for path in self.root.rglob("*"):
            key = str(path.relative_to(self.root))
            if path.is_symlink():
                result[key] = ("symlink", os.readlink(path), path.lstat().st_mtime_ns)
            elif path.is_file():
                result[key] = ("file", path.read_bytes(), path.stat().st_mtime_ns)
            else:
                result[key] = ("other", path.stat().st_mode, path.stat().st_mtime_ns)
        return result

    def test_default_installs_independent_platforms_and_shared_guard(self):
        self.invoke()
        self.assert_installed("codex")
        self.assert_installed("claude")
        hook = self.hooks()[HOOK_KEY]["PreToolUse"][0]["hooks"][0]
        self.assertEqual(shlex.split(hook["command"]),
                         [str(self.repo / "skills/auto/agy_guard.py")])
        self.assertEqual(hook["timeout"], 15)
        self.assertEqual((self.repo / "skills/moa/.env").read_text(), "EXAMPLE_API_KEY=\n")

    def test_platform_selection_is_independent(self):
        self.invoke("--platform", "codex")
        self.assert_installed("codex")
        self.assertFalse((self.user_home / ".claude").exists())
        self.assertIn(HOOK_KEY, self.hooks())

    def test_claude_only_does_not_install_codex(self):
        self.invoke("--platform", "claude")
        self.assert_installed("claude")
        self.assertFalse((self.user_home / ".agents").exists())
        self.assertIn(HOOK_KEY, self.hooks())

    def test_legacy_shared_install_is_migrated_with_backups(self):
        self.link(".agents/skills/moa", self.repo / "skills/moa")
        self.link(".claude/skills/auto", self.repo / "skills/auto")
        self.link(".claude/skills/moa", "../../.agents/skills/moa")
        self.invoke()
        self.assert_installed("codex")
        self.assert_installed("claude")
        self.assertEqual(len(self.backups()), 3)
        self.assertTrue(all(path.is_symlink() for path in self.backups()))

    def test_codex_only_detaches_recognized_legacy_claude_chain(self):
        self.link(".agents/skills/moa", self.repo / "skills/moa")
        path = self.link(".claude/skills/moa", "../../.agents/skills/moa")
        result = self.invoke("--platform", "codex")
        self.assert_installed("codex")
        self.assertEqual(path.resolve(), self.repo / "platforms/claude/skills/moa")
        self.assertFalse((self.user_home / ".claude/skills/auto").exists())
        self.assertIn("migration:", result.stdout)

    def test_repeated_install_is_no_op_and_preserves_api_keys(self):
        self.write("skills/moa/.env", "PRIVATE_TEST_KEY=do-not-overwrite\n")
        self.invoke()
        before = self.snapshot()
        result = self.invoke()
        self.assertEqual(before, self.snapshot())
        self.assertNotIn("PRIVATE_TEST_KEY", result.stdout + result.stderr)

    def test_cross_repo_migration_copies_existing_config_and_preserves_old_runs(self):
        previous = self.old_install()
        result = self.invoke()
        migrated = self.repo / "skills/moa/.env"
        self.assertEqual(migrated.read_bytes(), (previous / ".env").read_bytes())
        self.assertEqual(migrated.stat().st_mode & 0o777, 0o600)
        self.assertEqual((previous / "runs/history.json").read_text(), '{"old": true}\n')
        self.assertFalse((self.repo / "skills/moa/runs").exists())
        self.assertIn(str(previous / ".env"), result.stdout)
        self.assertNotIn("TEST_API_KEY", result.stdout + result.stderr)
        self.assert_installed("codex")
        self.assert_installed("claude")

    def test_current_config_takes_priority_over_old_checkout(self):
        self.old_install()
        current = self.write("skills/moa/.env", "KEEP_CURRENT_TEST_KEY=true\n")
        current.chmod(0o640)
        before = current.read_bytes(), current.stat().st_mtime_ns, current.stat().st_mode
        result = self.invoke()
        self.assertEqual(before, (current.read_bytes(), current.stat().st_mtime_ns,
                                  current.stat().st_mode))
        self.assertNotIn("copied existing API configuration", result.stdout)

    def test_old_config_selection_uses_platform_order(self):
        first = self.old_install("codex checkout")
        self.old_install("claude checkout", "claude")
        self.invoke()
        self.assertEqual((self.repo / "skills/moa/.env").read_bytes(),
                         (first / ".env").read_bytes())

    def test_old_config_selection_is_limited_to_selected_platform(self):
        self.old_install("codex checkout")
        selected = self.old_install("claude checkout", "claude")
        self.invoke("--platform", "claude")
        self.assertEqual((self.repo / "skills/moa/.env").read_bytes(),
                         (selected / ".env").read_bytes())

    def test_old_config_migration_follows_runner_symlink(self):
        previous = self.old_install()
        entry = self.root / "old entry"
        entry.mkdir()
        (entry / "moa_runner.py").symlink_to(previous / "moa_runner.py")
        installed = self.user_home / ".agents/skills/moa"
        installed.unlink()
        installed.symlink_to(entry, target_is_directory=True)
        self.invoke("--platform", "codex")
        self.assertEqual((self.repo / "skills/moa/.env").read_bytes(),
                         (previous / ".env").read_bytes())

    def test_dry_run_previews_existing_config_migration_without_changes(self):
        previous = self.old_install()
        before = self.snapshot()
        result = self.invoke("--dry-run")
        self.assertEqual(before, self.snapshot())
        self.assertIn(f"would copy existing API configuration from {previous / '.env'}",
                      result.stdout)
        self.assertNotIn("TEST_API_KEY", result.stdout + result.stderr)

    def test_dry_run_never_reads_or_copies_old_fifo_config(self):
        self.old_install(fifo=True)
        before = self.snapshot()
        result = self.invoke("--dry-run")
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.repo / "skills/moa/.env").exists())
        self.assertNotIn("would copy existing API configuration", result.stdout)

    def test_conflicts_and_dangling_links_are_preserved(self):
        self.write(".agents/skills/moa/custom.txt", "existing skill", home=True)
        self.link(".agents/skills/auto", self.root / "missing")
        self.write(".claude/skills/moa", "existing file", home=True)
        self.invoke()
        saved = {path.name: path for path in self.backups()}
        self.assertEqual((saved[".agents_skills_moa"] / "custom.txt").read_text(),
                         "existing skill")
        self.assertTrue(saved[".agents_skills_auto"].is_symlink())
        self.assertEqual(os.readlink(saved[".agents_skills_auto"]), str(self.root / "missing"))
        self.assertEqual(saved[".claude_skills_moa"].read_text(), "existing file")
        self.assert_installed("codex")
        self.assert_installed("claude")

    def test_hook_merge_changes_only_owned_key(self):
        original = {"other-guard": {"PreToolUse": [{"matcher": "custom"}]},
                    "settings": ["unrelated", 7], HOOK_KEY: {"old": True}}
        self.write(".gemini/config/hooks.json", json.dumps(original), home=True)
        self.invoke()
        updated = self.hooks()
        self.assertEqual(updated["other-guard"], original["other-guard"])
        self.assertEqual(updated["settings"], original["settings"])
        self.assertNotEqual(updated[HOOK_KEY], original[HOOK_KEY])
        saved = next(path for path in self.backups() if path.name == ".gemini_config_hooks.json")
        self.assertEqual(json.loads(saved.read_text()), original)

    def test_malformed_hooks_fail_before_any_mutation(self):
        self.write(".gemini/config/hooks.json", "{invalid JSON", home=True)
        before = self.snapshot()
        self.invoke(success=False)
        self.assertEqual(before, self.snapshot())

    def test_nonobject_hooks_fail_before_any_mutation(self):
        self.write(".gemini/config/hooks.json", "[]", home=True)
        before = self.snapshot()
        self.invoke(success=False)
        self.assertEqual(before, self.snapshot())

    def test_dry_run_has_no_mutations_on_fresh_install(self):
        before = self.snapshot()
        result = self.invoke("--dry-run")
        self.assertEqual(before, self.snapshot())
        self.assertIn("would link", result.stdout)
        self.assertIn("would create skills/moa/.env", result.stdout)

    def test_dry_run_preserves_conflicts_and_never_opens_existing_env(self):
        self.write(".agents/skills/moa/custom.txt", "keep me", home=True)
        self.write(".gemini/config/hooks.json", "{}", home=True)
        # A FIFO hangs any accidental read; the installer must only check existence.
        env_path = self.repo / "skills/moa/.env"
        os.mkfifo(env_path)
        before = self.snapshot()
        result = self.invoke("--dry-run")
        self.assertEqual(before, self.snapshot())
        self.assertIn("would back up", result.stdout)
        self.assertTrue(env_path.exists())

    def test_invalid_platform_is_rejected_without_mutation(self):
        before = self.snapshot()
        self.invoke("--platform", "unknown", success=False)
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
