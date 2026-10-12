"""Native transport/broker tests: fixtures only, never call a live model."""
import argparse
import datetime as dt
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import contextlib
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agy_guard as guard
import agy_worker as worker
import claude_broker as broker
import claude_local as local


def init_event(sid="ours", cwd="/tmp"):
    return dict(type="system", subtype="init", session_id=sid, cwd=cwd,
                model="claude-opus-example", tools=broker.TOOL_NAMES,
                mcp_servers=[{"name": "auto_worker", "status": "connected"}], plugins=[])


class LocalFixture(unittest.TestCase):
    def setUp(self):
        Path(worker.WT_BASE).mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="test-claude-local-", dir=worker.WT_BASE))
        (self.root / ".git").mkdir()
        self.outside = tempfile.TemporaryDirectory()
        self.config = dict(root=str(self.root), gitdir=str(self.root / ".git"), venv="", run_id="test-local")
        self.broker = broker.Broker(self.config)
        self.logging = patch.object(guard, "log")
        self.logging.start()

    def tearDown(self):
        self.logging.stop()
        worker.rmtree_tree(str(self.root))
        self.outside.cleanup()

    def call(self, name, **args):
        return self.broker.handle(dict(jsonrpc="2.0", id=1, method="tools/call", params=dict(name=name, arguments=args)))["result"]

    def test_create_read_edit_and_directory(self):
        self.assertNotIn("isError", self.call("write_file", path="src/test.txt", content="hello\nworld\n"))
        self.assertEqual(self.call("read_file", path="src/test.txt", offset=1)["content"][0]["text"], "world\n")
        self.assertNotIn("isError", self.call("edit_file", path="src/test.txt", old_text="world", new_text="reader"))
        self.assertEqual((self.root / "src/test.txt").read_text(), "hello\nreader\n")
        self.assertIn("src/", self.call("list_directory", path=".")["content"][0]["text"])
        self.assertTrue(self.call("edit_file", path="src/test.txt", old_text="absent", new_text="x")["isError"])

    def test_rejects_outside_secrets_control_files_and_git_objects(self):
        for path in ("../escape", str(Path(self.outside.name) / "escape"), ".env", ".env.custom", "a.key", "a.db", ".git/objects/x", ".claude/settings.json"):
            with self.subTest(path=path):
                self.assertTrue(self.call("write_file", path=path, content="x")["isError"])
                self.assertTrue(self.call("read_file", path=path)["isError"])
        self.assertTrue(self.call("write_file", path="AGENTS.md", content="x")["isError"])
        self.assertNotIn("isError", self.call("write_file", path=".env.example", content="EXAMPLE="))

    def test_links_cannot_escape_or_relabel_protected_paths(self):
        external = Path(self.outside.name) / "outside.txt"; external.write_text("private")
        (self.root / "sym").symlink_to(external)
        os.link(external, self.root / "hard")
        (self.root / "git-link").symlink_to(self.root / ".git")
        for path in ("sym", "hard", "git-link/objects/x"):
            self.assertTrue(self.call("read_file", path=path)["isError"])
            self.assertTrue(self.call("write_file", path=path, content="changed")["isError"])
        self.assertEqual(external.read_text(), "private")

    def test_unknown_fields_tools_and_requests_fail_closed(self):
        self.assertTrue(self.call("Bash", command="id")["isError"])
        self.assertTrue(self.call("write_file", path="ok", content="x", root="/")["isError"])
        self.assertTrue(self.call("read_file", path="ok", offset=True)["isError"])
        self.assertTrue(self.call("read_file", path="ok", offset=-1)["isError"])
        response = self.broker.handle(dict(jsonrpc="2.0", id=3, method="resources/read", params={}))
        self.assertEqual(response["error"]["code"], -32601)
        response = self.broker.handle(dict(jsonrpc="2.0", method="tools/call", params=dict(name="write_file", arguments=dict(path="no", content="no"))))
        self.assertIsNone(response); self.assertFalse((self.root / "no").exists())

    def test_bounded_regular_text_files_only(self):
        (self.root / "huge").write_bytes(b"x" * (broker.MAX_BYTES + 1))
        (self.root / "binary").write_bytes(b"x\0x")
        os.mkfifo(self.root / "pipe")
        for name in ("huge", "binary", "pipe"):
            self.assertTrue(self.call("read_file", path=name)["isError"])
        self.assertTrue(self.call("write_file", path="other", content="x" * (broker.MAX_BYTES + 1))["isError"])

    def test_command_no_shell_network_or_git_read_route(self):
        for command in ("curl https://example.com", "git show HEAD:.env", "git log -p", "cat .git/config", "python -c 'pass'", "node -e '1'", "python -m unittest; id", "python -m unittest /etc/passwd"):
            self.assertTrue(self.call("run_tests", command=command)["isError"], command)
        with patch.object(guard, "AGY_BUILTIN", self.outside.name):
            with self.assertRaises(guard.Deny):
                guard.check_command({"CommandLine": "python -m unittest " + self.outside.name}, self.broker.ctx)

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS sandbox")
    def test_candidate_tests_execute_inside_real_sandbox(self):
        (self.root / "test_sandbox.py").write_text('''import os, socket, unittest
class Sandbox(unittest.TestCase):
 def test_isolation(self):
  self.assertTrue(os.environ.get("AUTO_SANDBOX_ROOT"))
  self.assertNotIn("ANTHROPIC_API_KEY", os.environ)
  with self.assertRaises(OSError): socket.create_connection(("127.0.0.1", 9), timeout=1)
  with self.assertRaises(OSError): open(os.path.expanduser("~/.claude.json")).read()
''')
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "should-not-reach-candidate"}):
            result = self.call("run_tests", command="python -m unittest test_sandbox.py")
        self.assertNotIn("isError", result, result)
        self.assertEqual(json.loads(result["content"][0]["text"])["exit"], 0)

    def test_stdio_protocol_works_without_model_or_hooks(self):
        cfg = Path(self.outside.name) / "broker.json"; cfg.write_text(json.dumps(self.config))
        messages = [dict(jsonrpc="2.0", id=1, method="initialize", params={"protocolVersion": "2025-06-18"}),
                    dict(jsonrpc="2.0", method="notifications/initialized"),
                    dict(jsonrpc="2.0", id=2, method="tools/list"),
                    dict(jsonrpc="2.0", id=3, method="tools/call", params=dict(name="write_file", arguments=dict(path="stdio.txt", content="saved")))]
        result = subprocess.run([sys.executable, "-I", str(Path(broker.__file__)), str(cfg)],
                                input="\n".join(map(json.dumps, messages)) + "\n", text=True, capture_output=True, timeout=15,
                                env=local.safe_env(), cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = list(map(json.loads, result.stdout.splitlines()))
        self.assertEqual(len(replies), 3)
        self.assertEqual(len(replies[1]["result"]["tools"]), 5)
        self.assertEqual((self.root / "stdio.txt").read_text(), "saved")


class Transport(unittest.TestCase):
    def test_native_ledger_preserves_actual_models_and_cache_usage(self):
        m = dict(id="fixture", executor="claude-local", created="2026-10-12", repo="/tmp/repo", model="opus",
                 requested_model="opus", observed_models=["claude-opus-example"],
                 rounds=[dict(status="ERROR", seconds=1, usage=dict(input_tokens=3, output_tokens=4, cache_read_input_tokens=9))])
        with tempfile.TemporaryDirectory() as directory, patch.object(worker, "LEDGER", str(Path(directory, "ledger"))), \
                patch.object(worker, "load", return_value=m), patch.object(worker, "save"), contextlib.redirect_stdout(io.StringIO()):
            worker.cmd_record(argparse.Namespace(run_id="fixture",level="L1",outcome="rejected",defects="",notes="fixture"))
            entry = json.loads(Path(worker.LEDGER).read_text())
        self.assertEqual(entry["usage"], dict(input=3, output=4, cache_read=9))
        self.assertEqual(entry["observed_models"], ["claude-opus-example"])
        self.assertEqual(entry["funding_source"], "subscription")
        self.assertNotIn("gemini_tokens", entry)

    def test_funding_observation_cannot_overwrite_locked_metadata(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(worker, "RUNS", directory):
            rid = "fixture"
            Path(directory, rid).mkdir()
            original = dict(id=rid, executor="claude-local", rounds=[{"status": "STARTING"}],
                            funding={"used_for_submission": True}, verified=[{"full": True}], applied={"sha256": "saved"})
            worker.save(original)
            clock = local.now()
            args = argparse.Namespace(run_id=rid, remaining=50, observed_at=clock.isoformat(),
                                      expires_at=(clock + dt.timedelta(hours=1)).isoformat(), evidence="account-panel")
            original.update(worker.coordination(original))
            with worker.run_lock(rid), self.assertRaises(ValueError):
                local.cmd_funding(args)
            self.assertEqual(worker.load(rid), original)
            with contextlib.redirect_stdout(io.StringIO()): local.cmd_funding(args)
            saved = worker.load(rid)
            for key in ("rounds", "verified", "applied"):
                self.assertEqual(saved[key], original[key])
            with self.assertRaises(ValueError): local.cmd_funding(args)

    def test_command_has_only_exact_broker_tools_and_no_fallback(self):
        cmd = local.base_command({"id": "fixture", "cli": "/trusted/claude"})
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "")
        self.assertEqual(cmd[cmd.index("--allowedTools") + 1].split(","), broker.TOOL_NAMES)
        for forbidden in ("--bare", "--safe-mode", "--dangerously-skip-permissions", "--fallback-model", "--chrome"):
            self.assertNotIn(forbidden, cmd)
        for required in ("--restricted", "--strict-mcp-config", "--disable-slash-commands", "--no-chrome"):
            self.assertIn(required, cmd)

    def test_environment_drops_paid_api_and_python_provider_overrides(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "secret", "ANTHROPIC_BASE_URL": "https://other", "CLAUDE_CODE_USE_BEDROCK": "1", "PYTHONPATH": "/bad", "GIT_CONFIG_COUNT": "1"}):
            env = local.safe_env()
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "PYTHONPATH", "GIT_CONFIG_COUNT"):
            self.assertNotIn(key, env)
        self.assertEqual(env["HOME"], os.environ["HOME"])

    def test_result_requires_structured_success_and_expected_session(self):
        result = dict(type="result", subtype="success", is_error=False, session_id="ours", result="done", usage={"input_tokens": 4})
        stream = json.dumps(init_event()) + "\n" + json.dumps(result)
        status, _, models, _ = local.parse_output(stream, "ours", 0)
        self.assertEqual(status, "SUCCESS"); self.assertEqual(models, ["claude-opus-example"])
        self.assertEqual(local.parse_output(stream, "different", 0)[0], "ERROR")
        self.assertEqual(local.parse_output(stream, "ours", 1)[0], "ERROR")
        self.assertEqual(local.parse_output("not JSON", "ours", 0)[0], "ERROR")
        self.assertEqual(local.parse_output(stream + "\n" + json.dumps(result), "ours", 0)[0], "ERROR")
        result.update(is_error=True, subtype="error_during_execution", result="quota exceeded")
        self.assertEqual(local.parse_output(json.dumps(result), "ours", 0)[0], "ERROR")

    def test_initialization_inventory_is_required_and_rejects_extra_capabilities(self):
        local.check_init(init_event(), "ours", "/tmp")
        for changed in ({"tools": broker.TOOL_NAMES + ["Bash"]}, {"tools": []}, {"tools": [{}]},
                        {"mcp_servers": []}, {"plugins": [{"name": "unexpected"}]},
                        {"mcp_server_errors": ["failed"]}, {"session_id": "other"}, {"cwd": "/elsewhere"}):
            with self.assertRaises(ValueError): local.check_init({**init_event(), **changed}, "ours", "/tmp")

    def test_fake_cli_retains_quota_partial_patch_and_requires_reviewed_verification(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(worker, "RUNS", directory):
            rid = "fake-native-quota"
            run_dir = Path(directory, rid); run_dir.mkdir()
            tree = Path(tempfile.mkdtemp(prefix="test-native-lifecycle-", dir=worker.WT_BASE))
            try:
                def git(*args):
                    return subprocess.run(["git", *worker.SAFE_GIT, "-C", str(tree), *args],
                                          env=local.safe_env(), check=True, capture_output=True, text=True).stdout.strip()
                git("init", "-q")
                (tree / "code.py").write_text("value = 1\n")
                git("add", "code.py")
                git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "base")
                base = git("rev-parse", "HEAD")
                script = Path(directory, "fake-claude")
                script.write_text("#!" + sys.executable + "\n" + '''import json,sys,os
from pathlib import Path
sid=sys.argv[sys.argv.index('--session-id')+1]
sys.stdin.read()
event=''' + repr(init_event()) + '''
event.update(session_id=sid,cwd=os.getcwd())
print(json.dumps(event),flush=True)
Path('code.py').write_text('value = 2\\n')
print(json.dumps(dict(type='result',subtype='error_during_execution',is_error=True,session_id=sid,result='quota exhausted',usage={'input_tokens':3})))
sys.exit(1)
''')
                script.chmod(0o700)
                m = dict(id=rid, repo=str(tree), worktree=str(tree), base=base, executor="claude-local", venv="",
                         model="opus", requested_model="opus", observed_models=[], cli=str(script), rounds=[],
                         verified=[], state="prepared", runtime_hashes={})
                (run_dir / "brief-1.md").write_text("GOAL: fixture")
                clock = local.now()
                m["funding"] = dict(extra_usage_enabled=False,remaining=50,observed_at=clock.isoformat(),
                                    expires_at=(clock+dt.timedelta(hours=1)).isoformat())
                worker.save(m)
                args = argparse.Namespace(run_id=rid, command="run", timeout=10, dry_run=False)
                with patch.object(local, "preflight"), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                    local.cmd_invoke(args)
                saved = worker.load(rid)
                self.assertEqual(saved["rounds"][0]["status"], "ERROR")
                self.assertTrue(saved["funding"]["used_for_submission"])
                self.assertEqual(saved["observed_models"], ["claude-opus-example"])
                self.assertIn("+value = 2", (run_dir / "diff.patch").read_text())
                with self.assertRaises(SystemExit) as refused:
                    worker.cmd_apply(argparse.Namespace(run_id=rid, sha=saved["rounds"][0]["sha256"], allow_protected=False,allow_binary=False))
                self.assertIn("verify --full", str(refused.exception))
                # A CLI that never consumes a pipe-sized brief must still time out.
                script.write_text("#!" + sys.executable + "\nimport time\ntime.sleep(60)\n")
                (run_dir / "brief-1.md").write_text("x" * 200_000)
                worker.save(m)
                args.timeout = 1
                started = time.monotonic()
                with patch.object(local, "preflight"), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                    local.cmd_invoke(args)
                self.assertLess(time.monotonic() - started, 10)
                self.assertEqual(worker.load(rid)["rounds"][0]["status"], "timeout")
            finally:
                worker.rmtree_tree(str(tree))

    def test_funding_cannot_reuse_expired_unknown_or_paid_allowance(self):
        clock = local.now()
        f = dict(extra_usage_enabled=False, remaining=20, observed_at=clock.isoformat(), expires_at=(clock + dt.timedelta(hours=1)).isoformat())
        local.funding_ready({"funding": f})
        for changed in ({"extra_usage_enabled": True}, {"remaining": 0}, {"used_for_submission": True}, {"expires_at": (clock-dt.timedelta(seconds=1)).isoformat()}, {"observed_at": (clock-dt.timedelta(hours=2)).isoformat()}):
            with self.assertRaises(ValueError): local.funding_ready({"funding": {**f, **changed}})
        with self.assertRaises(ValueError): local.funding_ready({})

    def test_native_provenance_and_agy_resume_rejection(self):
        self.assertEqual(worker.coordination({"executor": "claude-local", "platform": "codex"})["executor"], "claude-local")
        with patch.object(worker, "load", return_value={"executor": "claude-local"}):
            with self.assertRaises(SystemExit): worker.cmd_resume(argparse.Namespace(run_id="fixture"))

    def test_preflight_uses_same_configuration_and_rejects_api_auth(self):
        m = dict(cli="/trusted/claude", id="fixture", worktree="/tmp")
        good = dict(loggedIn=True, authMethod="claude.ai", apiProvider="firstParty", subscriptionType="pro")
        def run(cmd, **kwargs):
            if cmd[-1] == "--version": return subprocess.CompletedProcess(cmd, 0, "2.1.270", "")
            if cmd[-1] == "--help": return subprocess.CompletedProcess(cmd, 0, "--restricted --tools --setting-sources --strict-mcp-config --permission-mode --disable-slash-commands --no-chrome", "")
            self.assertEqual(cmd[:-3], local.base_command(m))
            return subprocess.CompletedProcess(cmd, 0, json.dumps(good), "")
        with patch.object(local.subprocess, "run", side_effect=run), patch.object(local.sys, "platform", "darwin"), patch.object(Path, "is_file", return_value=True):
            self.assertEqual(local.preflight(m)["subscription"], "pro")
            good["authMethod"] = "api_key"
            with self.assertRaises(ValueError): local.preflight(m)


if __name__ == "__main__":
    unittest.main()
