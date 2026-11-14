"""Check the actual installable skill packages, without credentials or model calls."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PlatformPackages(unittest.TestCase):
    def test_entrypoints_link_to_complete_shared_runtime(self):
        files = {
            "moa": ("moa_runner.py", "test_runner.py", "evidence_review.py", "test_evidence_review.py"),
            "auto": ("agy_worker.py", "agy_guard.py", "run_sandboxed.sh",
                     "sandbox.sb", "test_guard.py", "test_worker.py", "test_recovery.py", "claude_cloud.py", "test_cloud.py",
                     "claude_local.py", "claude_broker.py", "test_local.py"),
        }
        for platform in ("codex", "claude", "gemini", "opencode"):
            for skill, scripts in files.items():
                entry = ROOT / "platforms" / platform / "skills" / skill
                with self.subTest(platform=platform, skill=skill):
                    self.assertTrue((entry / "SKILL.md").is_file())
                    expected = {name: ROOT / "skills" / skill / name for name in scripts}
                    expected.update({
                        "workflow.md": ROOT / "shared" / f"{skill}-workflow.md",
                        "routing.json": ROOT / "config" / f"{platform}.json",
                        "headless.json": ROOT / "config" / "headless.json",
                    })
                    if skill == "auto":
                        expected["cloud-workflow.md"] = ROOT / "shared/cloud-workflow.md"
                        expected["claude-local-workflow.md"] = ROOT / "shared/claude-local-workflow.md"
                    for name, source in expected.items():
                        self.assertTrue((entry / name).is_symlink(), name)
                        self.assertTrue((entry / name).is_file(), name)
                        self.assertEqual((entry / name).resolve(), source.resolve())
                    profile = json.loads((entry / "routing.json").read_text())
                    self.assertTrue((entry / profile["extends"]).is_file())

        swarm_entry = ROOT / "platforms/opencode/skills/swarm"
        with self.subTest(platform="opencode", skill="swarm"):
            self.assertTrue((swarm_entry / "SKILL.md").is_file())
            swarm_expected = {
                "agy_worker.py": ROOT / "skills/auto/agy_worker.py",
                "moa_runner.py": ROOT / "skills/moa/moa_runner.py",
                "routing.json": ROOT / "config/opencode.json",
                "headless.json": ROOT / "config/headless.json",
                "auto-workflow.md": ROOT / "shared/auto-workflow.md",
            }
            for name, source in swarm_expected.items():
                self.assertTrue((swarm_entry / name).is_symlink(), name)
                self.assertTrue((swarm_entry / name).is_file(), name)
                self.assertEqual((swarm_entry / name).resolve(), source.resolve())

    def test_installed_command_shapes_resolve_without_model_calls(self):
        for platform in ("codex", "claude", "gemini", "opencode"):
            entry = ROOT / "platforms" / platform / "skills"
            with self.subTest(platform=platform):
                preview = subprocess.run(
                    [sys.executable, str(entry / "moa/moa_runner.py"), "--show-config"],
                    text=True, capture_output=True, check=True,
                )
                config = json.loads(preview.stdout)
                self.assertEqual(config["mode"], "raw")
                self.assertEqual(config["platform"], platform)
                self.assertTrue(config["agy_routes"]["l2"])
                subprocess.run(
                    [sys.executable, str(entry / "auto/agy_worker.py"), "run", "--help"],
                    text=True, capture_output=True, check=True,
                )
                subprocess.run(
                    [sys.executable, str(entry / "auto/claude_local.py"), "prepare", "--help"],
                    text=True, capture_output=True, check=True,
                )
                subprocess.run(
                    [sys.executable, str(entry / "auto/claude_cloud.py"), "prepare", "--help"],
                    text=True, capture_output=True, check=True,
                )

    def test_opencode_swarm_agent_and_active_agy_catalog(self):
        agent_path = ROOT / "platforms/opencode/agents/swarm.md"
        self.assertTrue(agent_path.is_file())
        text = agent_path.read_text()
        self.assertTrue(text.startswith("---\n"))
        frontmatter = text.split("---\n", 2)[1]
        self.assertIn("mode: primary", frontmatter)
        self.assertIn("description:", frontmatter)
        self.assertIsNone(
            next((line for line in frontmatter.splitlines() if line.startswith("name:")), None),
            "OpenCode v2 AgentConfig frontmatter must not include `name:`",
        )

        out = subprocess.run(
            [sys.executable, str(ROOT / "platforms/opencode/skills/auto/agy_worker.py"), "models", "--json"],
            text=True, capture_output=True, check=True,
        )
        catalog = json.loads(out.stdout)
        self.assertEqual(len(catalog["families"]), 8)
        self.assertEqual(len(catalog["models"]), 19)
        self.assertNotIn("gemini-3.8", out.stdout)


if __name__ == "__main__":
    unittest.main()
