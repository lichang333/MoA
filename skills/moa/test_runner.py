"""Offline routing and failure-contract tests; no local keys or network are used."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import uuid

# Test the shared runner deterministically even when this test file is invoked
# through a platform symlink. Entrypoint inference is checked in subprocesses.
spec = importlib.util.spec_from_file_location("moa_runner", Path(__file__).resolve().with_name("moa_runner.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.enterContext(patch.object(runner, "RUNS_DIR", self.root / "runs"))
        self.env_loader = self.enterContext(patch.object(runner, "load_env"))
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.network = self.enterContext(patch.object(runner.urllib.request, "urlopen",
                                                      side_effect=AssertionError("Network forbidden in offline tests")))

    def invoke(self, args, result="worker answer", side_effect=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(runner, "call_model", return_value=result, side_effect=side_effect) as call:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = runner.main(args)
        return code, stdout.getvalue(), stderr.getvalue(), call

    def record(self):
        files = list(runner.RUNS_DIR.glob("*.json"))
        self.assertEqual(len(files), 1)
        return json.loads(files[0].read_text())

    def raw_response(self, stdout):
        body = stdout.split("===MOA_RAW_JSON_START===\n")[1].split("\n===MOA_RAW_JSON_END===")[0]
        return json.loads(body)

    def test_profiles_share_api_defaults_and_have_distinct_native_roles(self):
        headless = runner.load_config("headless")
        codex = runner.load_config("codex")
        claude = runner.load_config("claude")
        self.assertEqual(headless["mode"], "aggregate")
        self.assertEqual(codex["mode"], "raw")
        self.assertEqual(claude["mode"], "raw")
        self.assertEqual(headless["providers"], codex["providers"])
        self.assertEqual(codex["native_roles"]["planner"], "gpt-6-astra")
        self.assertEqual(codex["agy_routes"]["l1"], claude["agy_routes"]["l1"])
        self.assertEqual(headless["reviewer"]["model"], "glm-5.2")

    def test_config_preview_does_not_read_keys_call_models_or_create_records(self):
        for alias in ("--show-config", "--dry-run"):
            code, stdout, _, call = self.invoke(["--platform", "codex", alias, "--models", "deepseek"])
            self.assertEqual(code, 0)
            config = json.loads(stdout)
            self.assertEqual(config["mode"], "raw")
            self.assertEqual([w["provider"] for w in config["selected_workers"]], ["deepseek"])
            call.assert_not_called()
        self.env_loader.assert_not_called()
        self.network.assert_not_called()
        self.assertFalse(runner.RUNS_DIR.exists())

    def test_codex_and_claude_default_to_raw(self):
        os.environ["DEEPSEEK_API_KEY"] = "synthetic-key"
        for platform in ("codex", "claude"):
            code, stdout, _, call = self.invoke(["--platform", platform, "question"])
            self.assertEqual(code, 0)
            self.assertEqual(self.raw_response(stdout), {"DeepSeek-Chat": "worker answer"})
            self.assertEqual(call.call_count, 1)

    def test_headless_legacy_default_aggregates_and_raw_override_remains(self):
        os.environ["DEEPSEEK_API_KEY"] = "synthetic-key"
        code, stdout, _, call = self.invoke(["question"])
        self.assertEqual(code, 0)
        self.assertIn("FINAL SYNTHESIZED RESPONSE", stdout)
        self.assertEqual(call.call_count, 2)
        code, stdout, _, call = self.invoke(["--raw", "question"])
        self.assertEqual(code, 0)
        self.assertIn("MOA_RAW_JSON_START", stdout)
        self.assertEqual(call.call_count, 1)

    def test_explicit_selection_does_not_call_other_configured_providers(self):
        os.environ.update(DEEPSEEK_API_KEY="deepseek-test-key", OPENAI_API_KEY="openai-test-key")
        code, _, _, call = self.invoke(["--models", "deepseek,deepseek", "question"])
        self.assertEqual(code, 0)
        self.assertEqual(call.call_count, 2)
        self.assertTrue(all(item.args[0] == "deepseek" for item in call.call_args_list))
        self.assertEqual([w["provider"] for w in self.record()["worker_configuration"]], ["deepseek"])

    def test_explicit_missing_key_fails_before_any_model_call(self):
        os.environ["DEEPSEEK_API_KEY"] = "synthetic-key"
        code, _, stderr, call = self.invoke(["--models", "deepseek,openai", "--raw", "question"])
        self.assertNotEqual(code, 0)
        self.assertIn("Selected providers lack API keys: openai", stderr)
        call.assert_not_called()
        self.assertEqual(self.record()["status"], "failed")

    def test_unknown_and_native_models_are_not_api_providers(self):
        for value in ("gpt-6-astra", "planner", "", "deepseek,unknown"):
            with self.subTest(value=value), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    runner.main(["--models", value, "--dry-run"])
                self.assertEqual(stopped.exception.code, 2)
        self.env_loader.assert_not_called()
        self.network.assert_not_called()

    def test_mixed_failure_is_excluded_from_raw_and_recorded(self):
        os.environ.update(DEEPSEEK_API_KEY="test-ds", OPENAI_API_KEY="test-openai")
        def answer(provider, *args):
            if provider == "openai":
                raise ValueError("rejected")
            return "usable answer"
        code, stdout, stderr, _ = self.invoke(["--platform", "codex", "question"], side_effect=answer)
        self.assertEqual(code, 0)
        self.assertEqual(self.raw_response(stdout), {"DeepSeek-Chat": "usable answer"})
        self.assertIn("Partial failure", stderr)
        record = self.record()
        self.assertEqual(record["status"], "partial_success")
        self.assertEqual(record["worker_results"]["openai"]["status"], "failed")

    def test_mixed_failure_is_excluded_from_aggregation(self):
        os.environ.update(DEEPSEEK_API_KEY="test-ds", OPENAI_API_KEY="test-openai")
        def answer(provider, prompt, api_key, model, system, max_tokens):
            if system:
                payload = json.loads(prompt)
                self.assertEqual(payload["worker_responses"], {"DeepSeek-Chat": "usable answer"})
                return "final answer"
            if provider == "openai":
                raise ValueError("bad worker response")
            return "usable answer"
        code, stdout, _, call = self.invoke(["question"], side_effect=answer)
        self.assertEqual(code, 0)
        self.assertIn("final answer", stdout)
        self.assertEqual(call.call_count, 3)
        self.assertEqual(self.record()["status"], "partial_success")

    def test_all_failed_workers_stop_before_aggregation(self):
        os.environ["DEEPSEEK_API_KEY"] = "synthetic-key"
        code, stdout, stderr, call = self.invoke(["question"], side_effect=ValueError("unusable"))
        self.assertNotEqual(code, 0)
        self.assertNotIn("FINAL SYNTHESIZED RESPONSE", stdout)
        self.assertIn("All workers failed", stderr)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(self.record()["status"], "failed")
        self.assertNotIn("aggregation_result", self.record())

    def test_review_alias_uses_configured_reviewer_and_preserves_markers(self):
        os.environ["ZHIPUAI_API_KEY"] = "synthetic-key"
        code, stdout, _, call = self.invoke(["--glm52", "question"])
        self.assertEqual(code, 0)
        self.assertIn("===MOA_REVIEW_START===", stdout)
        self.assertIn("===MOA_REVIEW_END===", stdout)
        self.assertEqual(call.call_args.args[0], "glm")
        self.assertEqual(call.call_args.args[3], "glm-5.2")
        self.assertEqual(self.record()["reviewer_result"]["status"], "success")

    def test_review_error_returns_nonzero_and_no_success_marker(self):
        os.environ["ZHIPUAI_API_KEY"] = "synthetic-key"
        code, stdout, stderr, _ = self.invoke(["--review", "question"], side_effect=ValueError("review failed"))
        self.assertNotEqual(code, 0)
        self.assertNotIn("MOA_REVIEW_START", stdout)
        self.assertIn("Review failed", stderr)
        self.assertEqual(self.record()["status"], "failed")

    def test_aggregation_error_returns_nonzero(self):
        os.environ["DEEPSEEK_API_KEY"] = "synthetic-key"
        code, stdout, stderr, _ = self.invoke(["question"], side_effect=["draft", ValueError("failed")])
        self.assertNotEqual(code, 0)
        self.assertNotIn("FINAL SYNTHESIZED RESPONSE", stdout)
        self.assertIn("Aggregation failed", stderr)
        self.assertEqual(self.record()["aggregation_result"]["status"], "failed")

    def test_run_metadata_is_shared_and_does_not_store_prompt_or_keys(self):
        os.environ["DEEPSEEK_API_KEY"] = "synthetic-private-key"
        prompt = "private original prompt"
        code, _, _, _ = self.invoke(["--platform", "codex", "--coordinator-model", "gpt-6-astra",
                                      "--task-id", "task-42", prompt])
        self.assertEqual(code, 0)
        record = self.record()
        uuid.UUID(record["run_id"])
        self.assertEqual(record["platform"], "codex")
        self.assertEqual(record["executor"], "api")
        self.assertEqual(record["coordinator_model"], "gpt-6-astra")
        self.assertEqual(record["task_id"], "task-42")
        self.assertEqual(record["prompt_characters"], len(prompt))
        self.assertEqual(len(record["prompt_sha256"]), 64)
        self.assertIn("finished_at", record)
        serialized = json.dumps(record)
        self.assertNotIn(prompt, serialized)
        self.assertNotIn("synthetic-private-key", serialized)

    def test_error_messages_redact_transport_key(self):
        os.environ["GEMINI_API_KEY"] = "synthetic-private-key"
        code, _, stderr, _ = self.invoke(["--raw", "question"], side_effect=ValueError(
            "https://example.invalid?key=synthetic-private-key"))
        self.assertNotEqual(code, 0)
        self.assertNotIn("synthetic-private-key", stderr)
        self.assertNotIn("synthetic-private-key", json.dumps(self.record()))

    def test_transient_errors_retry_but_auth_errors_do_not(self):
        settings = runner.load_config("headless")["providers"]["deepseek"]
        with patch.object(runner, "call_model", side_effect=[TimeoutError("slow"), "recovered"]) as call:
            result = runner.run_worker("deepseek", settings, "question", "synthetic-key")
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["attempts"], 2)
            self.assertNotIn("error", result)
            self.assertEqual(call.call_count, 2)
        failure = urllib.error.HTTPError("https://example.invalid", 401, "Unauthorized", {}, None)
        with patch.object(runner, "call_model", side_effect=failure) as call:
            self.assertEqual(runner.run_worker("deepseek", settings, "question", "synthetic-key")["status"], "failed")
            self.assertEqual(call.call_count, 1)

    def test_symlink_resolves_shared_config_env_and_runtime_paths(self):
        link = self.root / "platform" / "moa_runner.py"
        link.parent.mkdir()
        link.symlink_to(Path(runner.__file__).resolve())
        spec = importlib.util.spec_from_file_location("runner_through_link", link)
        linked = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(linked)
        self.assertEqual(linked.SKILL_DIR, Path(runner.__file__).resolve().parent)
        self.assertEqual(linked.env_paths()[0], linked.SKILL_DIR / ".env")
        self.assertEqual(linked.RUNS_DIR, linked.SKILL_DIR / "runs")
        process = subprocess.run([sys.executable, str(link), "--platform", "codex", "--dry-run"],
                                 capture_output=True, text=True, env={})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["native_roles"]["planner"], "gpt-6-astra")

    def test_platform_entrypoints_infer_raw_without_platform_argument(self):
        repo = runner.SKILL_DIR.parent.parent
        for platform in ("codex", "claude"):
            platform_dir = repo / "platforms" / platform / "skills" / "moa"
            installed = self.root / platform / ".agents" / "skills" / "moa"
            installed.parent.mkdir(parents=True)
            installed.symlink_to(platform_dir, target_is_directory=True)
            for entry in (platform_dir / "moa_runner.py", installed / "moa_runner.py"):
                with self.subTest(platform=platform, entry=str(entry)):
                    process = subprocess.run([sys.executable, str(entry), "--show-config"],
                                             capture_output=True, text=True, env={})
                    self.assertEqual(process.returncode, 0, process.stderr)
                    config = json.loads(process.stdout)
                    self.assertEqual(config["platform"], platform)
                    self.assertEqual(config["mode"], "raw")

    def test_core_keeps_headless_default_and_explicit_platform_always_wins(self):
        repo = runner.SKILL_DIR.parent.parent
        cases = [
            (runner.SKILL_DIR / "moa_runner.py", [], "headless", "aggregate"),
            (repo / "platforms/codex/skills/moa/moa_runner.py", ["--platform", "headless"], "headless", "aggregate"),
            (repo / "platforms/claude/skills/moa/moa_runner.py", ["--platform", "codex"], "codex", "raw"),
            (runner.SKILL_DIR / "moa_runner.py", ["--platform", "claude"], "claude", "raw"),
        ]
        for entry, flags, platform, mode in cases:
            with self.subTest(entry=str(entry), flags=flags):
                process = subprocess.run([sys.executable, str(entry), *flags, "--show-config"],
                                         capture_output=True, text=True, env={})
                self.assertEqual(process.returncode, 0, process.stderr)
                config = json.loads(process.stdout)
                self.assertEqual(config["platform"], platform)
                self.assertEqual(config["mode"], mode)

    def test_config_accepts_explicit_api_model_and_rejects_circular_inheritance(self):
        config_dir = self.root / "config"
        shutil.copytree(runner.CONFIG_DIR, config_dir)
        path = config_dir / "codex.json"
        config = runner.load_config("codex")
        config["providers"]["openai"]["model"] = "gpt-6-astra"
        path.write_text(json.dumps(config))
        with patch.object(runner, "CONFIG_DIR", config_dir):
            self.assertEqual(runner.load_config("codex")["providers"]["openai"]["model"], "gpt-6-astra")
            path.write_text(json.dumps({"extends": "codex.json"}))
            with self.assertRaisesRegex(ValueError, "circular"):
                runner.load_config("codex")

    def test_adapter_payloads_use_configured_models_without_network(self):
        providers = runner.load_config("headless")["providers"]
        for provider, settings in providers.items():
            with self.subTest(provider=provider):
                if provider == "gemini":
                    content = b'data: {"candidates":[{"content":{"parts":[{"text":"answer"}]}}]}\n\n'
                elif provider == "anthropic":
                    content = b'{"content":[{"type":"text","text":"answer"}]}'
                else:
                    content = b'{"choices":[{"message":{"content":"answer"}}]}'
                self.network.side_effect = None
                self.network.return_value = io.BytesIO(content)
                answer = runner.call_model(provider, "question", "synthetic-key", settings["model"])
                self.assertEqual(answer, "answer")
                request = self.network.call_args.args[0]
                payload = json.loads(request.data)
                if provider == "gemini":
                    self.assertIn(settings["model"], request.full_url)
                else:
                    self.assertEqual(payload["model"], settings["model"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
