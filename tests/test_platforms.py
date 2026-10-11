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
            "moa": ("moa_runner.py", "test_runner.py"),
            "auto": ("agy_worker.py", "agy_guard.py", "run_sandboxed.sh",
                     "sandbox.sb", "test_guard.py", "test_worker.py", "test_recovery.py", "claude_cloud.py", "test_cloud.py"),
        }
        for platform in ("codex", "claude"):
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
                    for name, source in expected.items():
                        self.assertTrue((entry / name).is_symlink(), name)
                        self.assertTrue((entry / name).is_file(), name)
                        self.assertEqual((entry / name).resolve(), source.resolve())
                    profile = json.loads((entry / "routing.json").read_text())
                    self.assertTrue((entry / profile["extends"]).is_file())

    def test_installed_command_shapes_resolve_without_model_calls(self):
        for platform in ("codex", "claude"):
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
                    [sys.executable, str(entry / "auto/claude_cloud.py"), "prepare", "--help"],
                    text=True, capture_output=True, check=True,
                )


if __name__ == "__main__":
    unittest.main()
