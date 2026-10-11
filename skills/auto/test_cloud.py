"""Offline cloud bridge regression tests. No Claude or GitHub requests."""
import argparse
import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claude_cloud as cloud
import agy_worker as worker


class CloudBridge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="moa-cloud-test-")
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("remote", "add", "origin", "https://github.com/example/toy.git")
        (self.repo / "value.txt").write_text("original\r\n")
        (self.repo / "check.py").write_text("from pathlib import Path\nassert Path('value.txt').read_text() == 'cloud\\n'\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.brief = self.root / "brief.md"
        self.brief.write_text("GOAL: implement the exact fixture change and report checks")
        self.patchers = [patch.object(worker, "RUNS", str(self.root / "runs")),
                         patch.object(worker, "LEDGER", str(self.root / "runs.jsonl")),
                         patch.object(worker, "WT_BASE", str(self.root / "trees"))]
        for p in self.patchers:
            p.start()
        self.addCleanup(self.tmp.cleanup)
        for p in self.patchers:
            self.addCleanup(p.stop)
        self.rid = self.call(cloud.cmd_prepare, repo=str(self.repo), brief=str(self.brief), base="HEAD",
                             model=None, platform="codex", coordinator_model="current", task_id="fixture")["run"]

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True,
                              check=True, text=True, env=cloud.safe_env()).stdout

    def call(self, fn, **args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            fn(argparse.Namespace(**args))
        return json.loads(out.getvalue()) if out.getvalue().strip() else None

    def attach(self):
        return self.call(cloud.cmd_attach, run_id=self.rid, session="session_ABC123")

    def fund(self, source="cloud-credit", age=0, expires=24):
        return self.call(cloud.cmd_funding, run_id=self.rid, source=source, remaining=99,
                         observed_at=(cloud.now() - dt.timedelta(minutes=age)).isoformat(),
                         expires_at=(cloud.now() + dt.timedelta(hours=expires)).isoformat(),
                         session_model="opus" if cloud.load(self.rid).get("session_id") else None)

    def result(self, path="value.txt", data=b"cloud\r\n"):
        file = self.repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        self.git("add", "--", path)
        self.git("commit", "-qm", "cloud result")
        result = self.git("rev-parse", "HEAD").strip()
        self.git("reset", "--hard", self.base)
        return result

    def import_result(self, ref):
        self.attach()
        return self.call(cloud.cmd_import, run_id=self.rid, ref=ref)

    def test_prepare_attach_are_offline_and_validate_binding(self):
        with patch.object(cloud, "auth_ready", side_effect=AssertionError("unexpected auth")):
            self.attach()
            self.attach()
        with self.assertRaises(ValueError):
            self.call(cloud.cmd_attach, run_id=self.rid, session="session_DIFFERENT")
        for value in ("../escape", "https://evil.test/code/session_A", "--cloud", "file:///tmp/a"):
            with self.assertRaises(ValueError):
                cloud.session_id(value)
        self.assertEqual(cloud.session_id("https://claude.ai/code/session_A?from=cli"), "session_A")
        self.assertEqual(cloud.load(self.rid)["executor"], "claude-cloud")
        with self.assertRaises(ValueError):
            cloud.load("../escape")

    def test_funding_unknown_stale_expired_and_single_use(self):
        with self.assertRaisesRegex(ValueError, "funding"):
            cloud.funding_ready(cloud.load(self.rid))
        self.fund(age=61)
        with self.assertRaisesRegex(ValueError, "stale"):
            cloud.funding_ready(cloud.load(self.rid))
        with self.assertRaisesRegex(ValueError, "expired"):
            self.fund(expires=-1)
        self.fund()
        cloud.funding_ready(cloud.load(self.rid))
        m = cloud.load(self.rid)
        m["funding"]["used_for_submission"] = cloud.now().isoformat()
        worker.save(m)
        with self.assertRaisesRegex(ValueError, "already used"):
            cloud.funding_ready(cloud.load(self.rid))

    def test_auth_rejects_api_and_env_drops_secrets_and_git_injection(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "never-send", "GIT_DIR": "/tmp/evil",
                                     "GIT_CONFIG_COUNT": "1", "CLAUDE_CODE_USE_BEDROCK": "1"}):
            for name in ("ANTHROPIC_API_KEY", "GIT_DIR", "GIT_CONFIG_COUNT", "CLAUDE_CODE_USE_BEDROCK"):
                self.assertNotIn(name, cloud.safe_env())
            self.assertEqual(cloud.commit(self.repo, "HEAD"), self.base)
            self.assertEqual(worker.user_git(str(self.repo), "rev-parse", "HEAD").decode().strip(), self.base)
        bad = subprocess.CompletedProcess([], 0, json.dumps(dict(loggedIn=True, authMethod="api_key")), "")
        with patch.object(cloud.subprocess, "run", return_value=bad):
            with self.assertRaisesRegex(ValueError, "subscription login"):
                cloud.auth_ready()

    def test_same_run_lock_blocks_concurrent_mutations(self):
        with cloud.run_lock(self.rid):
            with self.assertRaisesRegex(ValueError, "busy"):
                with cloud.run_lock(self.rid):
                    self.fail("second writer entered")
        with cloud.run_lock(self.rid):
            self.assertEqual(cloud.load(self.rid)["state"], "prepared")

    def test_worker_cli_cannot_overwrite_cloud_state_while_locked(self):
        self.attach()
        self.fund()
        before = Path(worker.meta_path(self.rid)).read_bytes()
        commands = [("verify", ["--full", "--", "python", "check.py"]),
                    ("apply", ["--sha", "reviewed"]),
                    ("record", ["--level", "L2", "--outcome", "accepted"]),
                    ("clean", [])]
        with cloud.run_lock(self.rid):
            for command, args in commands:
                with self.subTest(command=command), \
                        patch.object(worker, "cmd_" + command) as handler, \
                        patch.object(sys, "argv", ["agy_worker.py", command, self.rid, *args]), \
                        contextlib.redirect_stderr(io.StringIO()) as errors:
                    with self.assertRaises(SystemExit) as raised:
                        worker.main()
                    self.assertEqual(raised.exception.code, 1)
                    self.assertIn("busy", errors.getvalue())
                    handler.assert_not_called()
        self.assertEqual(Path(worker.meta_path(self.rid)).read_bytes(), before)
        with patch.object(worker, "cmd_record") as handler, \
                patch.object(sys, "argv", ["agy_worker.py", "record", self.rid,
                                          "--level", "L2", "--outcome", "accepted"]):
            worker.main()
            handler.assert_called_once()

    def test_launch_observation_cannot_be_replayed_after_attach(self):
        self.fund()
        m = cloud.load(self.rid)
        f = m["funding"]
        m["state"] = "launch_attempted"
        f["used_for_submission"] = cloud.now().isoformat()
        # Exercise upgrade of a pre-watermark record as well as the new format.
        m.pop("last_funding_observed_at")
        worker.save(m)
        self.attach()
        self.assertEqual(cloud.load(self.rid)["last_funding_observed_at"], f["observed_at"])
        with self.assertRaisesRegex(ValueError, "cannot be replayed"):
            self.call(cloud.cmd_funding, run_id=self.rid, source=f["source"], remaining=f["remaining"],
                      observed_at=f["observed_at"], expires_at=f["expires_at"], session_model="opus")
        self.fund()
        cloud.funding_ready(cloud.load(self.rid))

    def test_consumed_observation_cannot_be_replayed_and_attach_model_is_unknown(self):
        self.fund()
        f = cloud.load(self.rid)["funding"]
        with self.assertRaisesRegex(ValueError, "cannot be replayed"):
            self.call(cloud.cmd_funding, run_id=self.rid, source=f["source"], remaining=f["remaining"],
                      observed_at=f["observed_at"], expires_at=f["expires_at"], session_model=None)
        self.attach()
        m = cloud.load(self.rid)
        self.assertEqual(m["model"], "unknown")
        self.assertEqual(m["requested_model"], "sonnet")
        self.assertNotIn("funding", m)
        self.call(cloud.cmd_funding, run_id=self.rid, source="cloud-credit", remaining=99,
                  observed_at=cloud.now().isoformat(), expires_at=(cloud.now() + dt.timedelta(hours=1)).isoformat(),
                  session_model=None)
        with self.assertRaisesRegex(ValueError, "actual cloud session model"):
            self.call(cloud.cmd_send, run_id=self.rid, brief=str(self.brief))

    def test_no_fable_model_and_no_credential_remote(self):
        args = dict(repo=str(self.repo), brief=str(self.brief), base="HEAD", model="fable",
                    platform="codex", coordinator_model="current", task_id=None)
        with self.assertRaisesRegex(ValueError, "allowlist"):
            self.call(cloud.cmd_prepare, **args)
        self.git("remote", "set-url", "origin", "https://secret@github.com/example/toy.git")
        args["model"] = None
        with self.assertRaisesRegex(ValueError, "credential-free"):
            self.call(cloud.cmd_prepare, **args)

    def test_launch_preview_never_calls_cli_and_prompt_is_immutable(self):
        self.fund()
        with patch.object(cloud, "auth_ready", side_effect=AssertionError("unexpected auth")):
            preview = self.call(cloud.cmd_launch, run_id=self.rid, dry_run=True)
        self.assertIn("--cloud", preview["command"])
        self.assertNotIn("--dangerously-skip-permissions", preview["command"])
        self.assertEqual(cloud.load(self.rid)["state"], "prepared")
        (Path(worker.RUNS) / self.rid / "prompt.txt").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "prompt changed"):
            self.call(cloud.cmd_launch, run_id=self.rid, dry_run=True)

    def test_launch_pins_remote_and_blocks_ambiguous_retry(self):
        self.fund()
        real_git = cloud.git
        def fake_git(repo, *args, **kw):
            if args[0] == "ls-remote":
                return (self.base + "\trefs/heads/main\n").encode()
            return real_git(repo, *args, **kw)
        real_run = subprocess.run
        def fake_run(argv, **kw):
            if argv[0] == "claude":
                self.assertIn("--cloud", argv)
                self.assertEqual(self.base, real_git(kw["cwd"], "rev-parse", "HEAD").decode().strip())
                self.assertFalse((Path(kw["cwd"]) / "private.env").exists())
                raise OSError("ambiguous connection drop")
            return real_run(argv, **kw)
        (self.repo / "private.env").write_text("not uploaded")
        with patch.object(cloud, "auth_ready"), patch.object(cloud, "git", side_effect=fake_git), \
                patch.object(cloud.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(ValueError, "outcome unknown"):
                self.call(cloud.cmd_launch, run_id=self.rid, dry_run=False)
        with self.assertRaisesRegex(ValueError, "already attempted"):
            self.call(cloud.cmd_launch, run_id=self.rid, dry_run=False)

    def test_send_records_submission_not_completion_and_no_retry_on_failure(self):
        self.attach()
        self.fund()
        reply = subprocess.CompletedProcess([], 0, json.dumps(dict(ok=True, session_id="session_ABC123",
                                                                  executor="agy", status="completed")), "")
        with patch.object(cloud, "auth_ready"), patch.object(cloud.subprocess, "run", return_value=reply) as run:
            result = self.call(cloud.cmd_send, run_id=self.rid, brief=str(self.brief))
        self.assertEqual(result["state"], "submitted")
        self.assertEqual(result["remote_status"], "unknown")
        self.assertEqual(cloud.load(self.rid)["executor"], "claude-cloud")
        self.assertIn("--cloud", run.call_args.args[0])
        self.fund()
        with patch.object(cloud, "auth_ready"), patch.object(cloud.subprocess, "run", side_effect=subprocess.TimeoutExpired("claude", 60)):
            with self.assertRaisesRegex(ValueError, "outcome unknown"):
                self.call(cloud.cmd_send, run_id=self.rid, brief=str(self.brief))
        self.assertEqual(cloud.load(self.rid)["submissions"][-1]["state"], "outcome-unknown")
        with self.assertRaisesRegex(ValueError, "already used"):
            cloud.funding_ready(cloud.load(self.rid))

    def test_import_preserves_bytes_flags_and_user_checkout(self):
        ref = self.result()
        out = self.import_result(ref)
        self.assertEqual(out["result_commit"], ref)
        self.assertIn(b"cloud\r\n", Path(out["patch"]).read_bytes())
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.base)
        self.assertEqual((self.repo / "value.txt").read_bytes(), b"original\r\n")
        self.assertFalse(Path(cloud.load(self.rid)["worktree"]).exists())
        with self.assertRaises(SystemExit):
            worker.cmd_resume(argparse.Namespace(run_id=self.rid))
        with self.assertRaises(SystemExit):
            worker.cmd_test(argparse.Namespace(run_id=self.rid))
        record = self.call(worker.cmd_record, run_id=self.rid, level="L2", outcome="rejected", defects=None, notes="fixture")
        self.assertIsNone(record["usage"])
        self.assertIsNone(record["cost_usd"])
        self.assertNotIn("gemini_tokens", record)

    def test_import_failure_preserves_previous_patch_and_verification(self):
        out = self.import_result(self.result())
        old_meta = Path(worker.meta_path(self.rid)).read_bytes()
        old_patch = Path(out["patch"]).read_bytes()
        bad = self.result("sub/.CoDeX/settings.json", b"{}")
        with self.assertRaisesRegex(ValueError, "protected paths"):
            self.call(cloud.cmd_import, run_id=self.rid, ref=bad)
        self.assertEqual(Path(worker.meta_path(self.rid)).read_bytes(), old_meta)
        self.assertEqual(Path(out["patch"]).read_bytes(), old_patch)
        with self.assertRaises(ValueError):
            self.call(cloud.cmd_import, run_id=self.rid, ref="--evil")

    def test_import_rejects_symlink_and_unrelated_history(self):
        self.attach()
        (self.repo / "link").symlink_to("/tmp/outside")
        self.git("add", ".")
        self.git("commit", "-qm", "symlink")
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.call(cloud.cmd_import, run_id=self.rid, ref="HEAD")
        self.git("checkout", "--orphan", "unrelated")
        self.git("commit", "-qm", "unrelated")
        with self.assertRaises(subprocess.CalledProcessError):
            self.call(cloud.cmd_import, run_id=self.rid, ref="HEAD")

    @unittest.skipUnless(sys.platform == "darwin", "real local verification requires the macOS sandbox")
    def test_imported_patch_uses_full_verification_and_apply_gates(self):
        out = self.import_result(self.result())
        def apply(sha):
            with contextlib.redirect_stdout(io.StringIO()):
                worker.cmd_apply(argparse.Namespace(run_id=self.rid, sha=sha, allow_protected=False, allow_binary=False))
        with self.assertRaisesRegex(SystemExit, "verify --full"):
            apply(out["patch_sha256"])
        with self.assertRaises(SystemExit) as verified:
            worker.cmd_verify(argparse.Namespace(run_id=self.rid, onto="HEAD", full=True, cmd=["python3", "check.py"]))
        self.assertEqual(verified.exception.code, 0)
        with self.assertRaisesRegex(SystemExit, "not the reviewed"):
            apply("0" * 64)
        (self.repo / "value.txt").write_text("user edits")
        with self.assertRaisesRegex(SystemExit, "local changes"):
            apply(out["patch_sha256"])
        self.git("checkout", "--", "value.txt")
        apply(out["patch_sha256"])
        self.assertEqual((self.repo / "value.txt").read_bytes(), b"cloud\r\n")
        self.assertTrue(self.git("status", "--porcelain").strip().startswith("M value.txt"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
