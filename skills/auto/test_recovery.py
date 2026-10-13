"""Offline transport-recovery regressions: fake agy only, no model calls."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from shlex import quote as shlex_quote
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agy_worker as worker

SID = "12345678-1234-4234-8234-123456789abc"
EOF = dict(short_error="agent executor error: generating and executing: proto: unexpected EOF",
           status="UNKNOWN", error_code=2, code_kind="grpc", retryable=True)


def stderr(event):
    return "error: network issue\nAGY_ERROR: " + json.dumps(event) + "\n"


class Recovery(unittest.TestCase):
    def test_only_explicit_transient_stderr_is_retryable(self):
        self.assertIsNotNone(worker.transient_network_error(stderr(EOF), 3, "ERROR"))
        unavailable = dict(EOF, short_error="transport is closing", status="UNAVAILABLE", error_code=14)
        self.assertIsNotNone(worker.transient_network_error(stderr(unavailable), 3, "ERROR"))
        for field, value in (("retryable", "true"), ("retryable", False), ("code_kind", "http"),
                             ("error_code", True), ("error_code", 8), ("status", "INTERNAL"),
                             ("short_error", "unknown internal error"), ("short_error", None),
                             ("short_error", "quota exhausted: unexpected EOF"),
                             ("short_error", "Unauthenticated: unexpected EOF"),
                             ("short_error", "authentication failed: unexpected EOF"),
                             ("short_error", "authorization denied: unexpected EOF"),
                             ("short_error", "oauth failed: unexpected EOF"),
                             ("short_error", "cancelled: unexpected EOF"),
                             ("short_error", "interrupted: unexpected EOF"),
                             ("short_error", "deadline exceeded: unexpected EOF")):
            with self.subTest(field=field, value=value):
                self.assertIsNone(worker.transient_network_error(stderr(dict(EOF, **{field: value})), 3, "ERROR"))
        for text in ("unexpected EOF retryable:true", "AGY_ERROR: {bad", "AGY_ERROR: []",
                     stderr(EOF) + stderr(EOF)):
            self.assertIsNone(worker.transient_network_error(text, 3, "ERROR"))
        for code, status in ((0, "ERROR"), (1, "ERROR"), (3, "timeout"), (3, "interrupted"), (3, "SUCCESS")):
            self.assertIsNone(worker.transient_network_error(stderr(EOF), code, status))

    def simulate(self, *, retries=1, failures=1, mutate=None, clock=None, sleep=None):
        m = dict(id="fixture", rounds=[], guard={"denied": []})
        summaries, persisted = [], []
        def attempt(meta, brief, timeout, conversation=None, hard_deadline=None, stall_timeout=None):
            n = len(meta["rounds"])
            failed = n < failures
            r = dict(status="ERROR" if failed else "SUCCESS", transport_error=EOF if failed else None,
                     response_conversation=SID, sha256="sha", denied_actions=[], swept_pids=[],
                     usage={"input_tokens": 3}, timeout_seconds=timeout)
            s = dict(round=n + 1, status=r["status"], REVIEW_FLAGS={})
            meta["conversation"] = SID
            meta["rounds"].append(r)
            if mutate:
                mutate(meta, r, s)
            summaries.append(s)
            return s
        with tempfile.TemporaryDirectory() as d:
            brief = Path(d) / "brief.md"
            brief.write_text("bounded fixture task")
            with patch.object(worker, "invoke_attempt", side_effect=attempt) as call, \
                    patch.object(worker, "save", side_effect=lambda x: persisted.append(copy.deepcopy(x))), \
                    patch.object(worker.time, "sleep", side_effect=sleep), \
                    patch.object(worker.time, "monotonic", side_effect=clock or (lambda: 100)), \
                    contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
                worker.invoke(m, str(brief), 120, network_retries=retries)
        return m, json.loads(out.getvalue()), call, persisted

    def test_same_conversation_budget_and_usage_are_preserved(self):
        m, result, call, saved = self.simulate(clock=iter([100, 101, 106, 106]).__next__)
        self.assertEqual(call.call_count, 2)
        args = call.call_args_list[1]
        self.assertEqual(args.args[2:4], (114, SID))
        self.assertIn("Do not replay completed operations", args.args[1])
        self.assertEqual([c.kwargs["hard_deadline"] for c in call.call_args_list], [340, 340])
        self.assertEqual(result["invocation_usage"]["input_tokens"], 6)
        self.assertEqual(result["network_recovery"]["stop_reason"], "completed")
        self.assertEqual([r["status"] for r in m["rounds"]], ["ERROR", "SUCCESS"])
        self.assertTrue(any(s["rounds"][0].get("recovery", {}).get("state") == "scheduled" for s in saved))

    def test_retry_limit_and_disabled_setting(self):
        for limit in (0, 1, 2):
            with self.subTest(limit=limit):
                m, result, call, _ = self.simulate(retries=limit, failures=99)
                self.assertEqual(call.call_count, limit + 1)
                self.assertEqual(result["network_recovery"]["retries"], limit)
                self.assertIn("limit", result["network_recovery"]["stop_reason"])

    def test_unsafe_or_ambiguous_attempts_never_resume(self):
        def no_capture(m, r, s):
            r.pop("sha256")
        def guard_denial(m, r, s):
            m["guard"]["denied"] = ["denied"]
        def risk(m, r, s):
            s["REVIEW_FLAGS"] = {"protected_paths": [".codex/config.toml"]}
        for mutate in (no_capture, guard_denial, risk,
                       lambda m, r, s: r.update(denied_actions=["denied"]),
                       lambda m, r, s: r.update(swept_pids=[123]),
                       lambda m, r, s: r.update(response_conversation=None),
                       lambda m, r, s: r.update(response_conversation="--continue"),
                       lambda m, r, s: r.update(transport_error=None)):
            with self.subTest(mutate=mutate):
                _, _, call, _ = self.simulate(mutate=mutate)
                self.assertEqual(call.call_count, 1)
        meta = {"rounds": [dict(transport_error=EOF, response_conversation=SID)]}
        self.assertIn("mismatched", worker.retry_blocker(meta, {}, "00000000-0000-0000-0000-000000000000"))

    def test_budget_exhaustion_and_interrupt_do_not_submit(self):
        _, result, call, _ = self.simulate(clock=iter([100, 190]).__next__)
        self.assertEqual(call.call_count, 1)
        self.assertIn("budget", result["network_recovery"]["stop_reason"])
        m, result, call, _ = self.simulate(sleep=KeyboardInterrupt())
        self.assertEqual(call.call_count, 1)
        self.assertEqual(m["rounds"][0]["recovery"]["state"], "cancelled")
        self.assertIn("interrupted", result["network_recovery"]["stop_reason"])

    def test_guard_progress_counts_each_event_once_across_rotation(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "guard.jsonl")
            event = lambda run: (json.dumps({"run": run, "conv": SID, "tool": "view_file"}) + "\n").encode()
            with open(log, "wb") as f:
                f.write(event("old-run"))
            with patch.dict(os.environ, {"AUTO_GUARD_LOG": log}):
                progress = worker.GuardProgress("me")
            self.assertEqual(progress.poll(), 0)   # history before the attempt is not progress
            line = event("me")
            with open(log, "ab") as f:
                f.write(event("me") + event("other") + line[:9])
            self.assertEqual(progress.poll(), 1)
            with open(log, "ab") as f:
                f.write(line[9:])   # the split line is completed, then the guard rotates
            os.replace(log, log + ".1")
            with open(log, "wb") as f:
                f.write(event("me") + event("me"))
            self.assertEqual(progress.poll(), 3)
            self.assertEqual(progress.conversation, SID)
            self.assertEqual(progress.poll(), 0)
            os.remove(log)   # a missing log is quiet, not an error
            self.assertEqual(progress.poll(), 0)

    def test_guard_log_follows_the_registered_hook(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d).resolve()
            guard_dir = home / "with space" / "auto"
            guard_dir.mkdir(parents=True)
            (guard_dir / "agy_guard.py").write_text("# guard\n")
            hooks = home / "hooks.json"
            def resolve(command):
                hooks.write_text(json.dumps({"claude-auto-worker-guard": {"PreToolUse": [
                    {"matcher": "*", "hooks": [{"type": "command", "command": command}]}]}}))
                env = {k: v for k, v in os.environ.items() if k != "AUTO_GUARD_LOG"}
                with patch.object(worker, "HOOKS_JSON", str(hooks)), patch.dict(os.environ, env, clear=True), \
                        patch.dict(os.environ, {"HOME": str(home)}):
                    return worker.guard_log()
            expected = str(guard_dir / "logs" / "guard.jsonl")
            for command in (shlex_quote(str(guard_dir / "agy_guard.py")), "~/'with space'/auto/agy_guard.py",
                            "python3 " + shlex_quote(str(guard_dir / "agy_guard.py"))):
                with self.subTest(command=command):
                    self.assertEqual(resolve(command), expected)
            for command in ("/nonexistent/agy_guard.py", shlex_quote(str(guard_dir)), "'unterminated"):
                with self.subTest(command=command):
                    self.assertEqual(resolve(command), worker.GUARD_LOG)
            hooks.write_text("not json")
            with patch.object(worker, "HOOKS_JSON", str(hooks)), patch.dict(os.environ, {"AUTO_GUARD_LOG": ""}):
                self.assertEqual(worker.guard_log(), worker.GUARD_LOG)

    def test_guard_events_read_the_hook_log_and_this_checkouts_log(self):
        with tempfile.TemporaryDirectory() as d:
            hook_log, own_log = os.path.join(d, "hook.jsonl"), os.path.join(d, "own.jsonl")
            for path, tool in ((hook_log, "agy"), (own_log, "broker")):
                with open(path, "w") as f:
                    f.write(json.dumps({"run": "r", "tool": tool, "decision": "deny"}) + "\n")
            with patch.object(worker, "GUARD_LOG", own_log), patch.dict(os.environ, {"AUTO_GUARD_LOG": hook_log}):
                self.assertEqual(sorted(e["tool"] for e in worker.guard_events("r")), ["agy", "broker"])
            with patch.object(worker, "GUARD_LOG", own_log), patch.dict(os.environ, {"AUTO_GUARD_LOG": own_log}):
                self.assertEqual([e["tool"] for e in worker.guard_events("r")], ["broker"])

    def test_real_cli_preserves_partial_patch_and_resumes_same_session(self):
        with tempfile.TemporaryDirectory(prefix="auto-recovery-test-") as d:
            root = Path(d).resolve()
            runtime, repo, bin_dir = (root / p for p in ("auto", "repo", "bin"))
            for p in (runtime, repo, bin_dir):
                p.mkdir()
            shutil.copy2(worker.__file__, runtime / "agy_worker.py")
            def git(*args):
                return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                                      env=worker.min_env(**worker.GIT_ENV))
            git("init", "-q")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            (repo / "app.py").write_text("x = 1\n")
            git("add", ".")
            git("commit", "-qm", "base")
            brief = root / "brief.md"
            brief.write_text("complete the isolated fixture")
            fake = bin_dir / "agy"
            fake.write_text(f'''#!{sys.executable}
import json, os, pathlib, sys
state = pathlib.Path({str(root / 'calls.json')!r})
calls = json.loads(state.read_text()) if state.exists() else []
args = sys.argv[1:]
assert os.environ['AUTO_WORKER'] == '1'
assert args[args.index('--model') + 1] == 'fake'
assert '--dangerously-skip-permissions' in args
calls.append(dict(cwd=os.getcwd(), args=args))
state.write_text(json.dumps(calls))
target = pathlib.Path('app.py')
if len(calls) == 1:
    target.write_text(target.read_text() + '# preserved partial change\\n')
    print({stderr(EOF)!r}, file=sys.stderr)
    print(json.dumps(dict(status='ERROR', conversation_id={SID!r}, usage=dict(input_tokens=3))))
    sys.exit(3)
assert args[args.index('--conversation') + 1] == {SID!r}
assert calls[0]['cwd'] == os.getcwd()
assert 'preserved partial change' in target.read_text()
target.write_text(target.read_text() + '# recovered\\n')
print(json.dumps(dict(status='SUCCESS', conversation_id={SID!r}, response='done', usage=dict(input_tokens=4))))
''')
            fake.chmod(0o755)
            env = worker.min_env(PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
                                 AUTO_GUARD_LOG=str(root / "guard.jsonl"))   # never the user's hook log
            # Load the isolated runtime so both run state and worktrees stay in this fixture.
            entry = """import importlib.util, sys
spec = importlib.util.spec_from_file_location('worker', sys.argv[1])
w = importlib.util.module_from_spec(spec); spec.loader.exec_module(w)
w.WT_BASE = sys.argv[2]
sys.argv = [sys.argv[1]] + sys.argv[3:]
w.main()
"""
            cmd = [sys.executable, "-c", entry, str(runtime / "agy_worker.py"), str(root / "trees"),
                   "run", "--repo", str(repo), "--brief", str(brief), "--model", "fake", "--timeout", "60"]
            p = subprocess.run(cmd, env=env, text=True, capture_output=True, timeout=50)
            self.assertEqual(p.returncode, 0, p.stderr)
            out = json.loads(p.stdout)  # exactly one final JSON document
            record = runtime / "runs" / out["run"]
            m = json.loads((record / "meta.json").read_text())
            self.assertEqual([r["status"] for r in m["rounds"]], ["ERROR", "SUCCESS"])
            self.assertEqual(out["invocation_usage"]["input_tokens"], 7)
            self.assertIn("partial change", (record / "diff-1.patch").read_text())
            self.assertIn("# recovered", (record / "diff.patch").read_text())
            first = json.loads((record / "response-1.json").read_text())
            self.assertEqual(first["exit"], 3)
            self.assertIn("unexpected EOF", first["stderr"])
            self.assertEqual((repo / "app.py").read_text(), "x = 1\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
