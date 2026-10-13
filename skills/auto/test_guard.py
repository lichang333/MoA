#!/usr/bin/env python3
"""Offline tests for agy_guard.py: feed it fake PreToolUse payloads, check decisions.
Run: python3 ~/.claude/skills/auto/test_guard.py   (creates a throwaway worktree-like dir)"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

GUARD = os.path.join(os.path.dirname(os.path.realpath(__file__)), "agy_guard.py")
HOME = os.path.realpath(os.path.expanduser("~"))
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="auto-guard-test-"))
os.makedirs(os.path.join(ROOT, "app"))
open(os.path.join(ROOT, "app", "x.py"), "w").write("x = 1\n")
os.symlink("/etc/hosts", os.path.join(ROOT, "link_out"))
open(os.path.join(ROOT, "..", os.path.basename(ROOT) + "-hl-src"), "w").write("x")
os.link(os.path.join(ROOT, "..", os.path.basename(ROOT) + "-hl-src"), os.path.join(ROOT, "app", "hard.py"))
ART = os.path.join(HOME, ".gemini", "antigravity-cli", "brain", "conv-test")
# A run's read-only dependency clone: tool scripts, an npm-style .bin link, and a link leading out.
for rel in ("node_modules/vitest/vitest.mjs", "node_modules/typescript/bin/tsc"):
    os.makedirs(os.path.join(ROOT, os.path.dirname(rel)), exist_ok=True)
    open(os.path.join(ROOT, rel), "w").write("// tool\n")
os.makedirs(os.path.join(ROOT, "node_modules", ".bin"))
os.symlink("../vitest/vitest.mjs", os.path.join(ROOT, "node_modules", ".bin", "vitest"))
os.symlink("/etc/hosts", os.path.join(ROOT, "node_modules", "escape.js"))
os.symlink("../app/x.py", os.path.join(ROOT, "node_modules", "inward.js"))


def run(tool, args, env_worker=True, art=ART, extra_env=None):
    payload = {"toolCall": {"name": tool, "args": args}, "artifactDirectoryPath": art,
               "conversationId": "test", "workspacePaths": [ROOT]}
    env = {k: v for k, v in os.environ.items() if not k.startswith("AUTO_")}
    if env_worker:
        env.update(AUTO_WORKER="1", AUTO_WORKER_ROOT=ROOT, AUTO_RUN_ID="guard-selftest")
    env.update(extra_env or {})
    r = subprocess.run([sys.executable, GUARD], input=json.dumps(payload), capture_output=True,
                       text=True, env=env, timeout=10)
    return json.loads(r.stdout)


def cmd(line, cwd=None, **kw):
    return run("run_command", {"CommandLine": line, "Cwd": cwd or ROOT}, **kw)


CASES = [
    # (label, result, expected decision)
    ("inert outside worker mode", lambda: run("run_command", {"CommandLine": "rm -rf /"}, env_worker=False), "ask"),
    ("ls", lambda: cmd("ls -la"), "allow"),
    ("grep pattern with slash", lambda: cmd("grep -rn '/sub/' app"), "allow"),
    ("grep -e pattern", lambda: cmd("grep -rn -e '/api/' app"), "allow"),
    ("find -name glob", lambda: cmd("find . -name '*.py'"), "allow"),
    ("pytest", lambda: cmd("python -m pytest -q tests/test_x.py -k 'a and not b'"), "allow"),
    ("bare pytest", lambda: cmd("pytest -x"), "allow"),
    ("unittest discovery pattern", lambda: cmd("python3 -m unittest discover -s tests -p 'test_*tv*.py' -q"), "allow"),
    ("unittest compact pattern", lambda: cmd("python -m unittest discover -ptest_*.py"), "allow"),
    ("unittest long pattern", lambda: cmd("python -m unittest discover --pattern=test_*.py"), "allow"),
    ("unittest catch interrupt", lambda: cmd("python -m unittest discover -c"), "allow"),
    ("node --test", lambda: cmd("node --test tests/a.test.js"), "allow"),
    ("node_modules tool", lambda: cmd("node node_modules/vitest/vitest.mjs run tests/a.test.ts"), "allow"),
    ("node_modules .bin link", lambda: cmd("node node_modules/.bin/vitest run"), "allow"),
    ("tool args are not node flags", lambda: cmd("node node_modules/typescript/bin/tsc -p tsconfig.json --noEmit"), "allow"),
    ("git diff", lambda: cmd("git diff HEAD -- app"), "allow"),
    ("view in root", lambda: run("view_file", {"AbsolutePath": ROOT + "/app/x.py"}), "allow"),
    ("write in root", lambda: run("write_to_file", {"TargetFile": ROOT + "/app/new.py", "CodeContent": "/* x */"}), "allow"),
    ("edit in root", lambda: run("replace_file_content", {"TargetFile": ROOT + "/app/x.py", "ReplacementContent": "/etc/passwd"}), "allow"),
    ("artifact write", lambda: run("write_to_file", {"TargetFile": ART + "/task.md", "CodeContent": "plan"}), "allow"),
    # --- must deny
    ("pipe", lambda: cmd("grep x app | head"), "deny"),
    ("chain", lambda: cmd("ls; curl evil.sh"), "deny"),
    ("and", lambda: cmd("pytest && git push"), "deny"),
    ("redirect", lambda: cmd("echo x > /etc/hosts"), "deny"),
    ("subshell", lambda: cmd("echo $(id)"), "deny"),
    ("backtick", lambda: cmd("echo `id`"), "deny"),
    ("newline", lambda: cmd("ls\ncurl x"), "deny"),
    ("env prefix", lambda: cmd("FOO=1 ls"), "deny"),
    ("curl", lambda: cmd("curl https://example.com"), "deny"),
    ("ssh", lambda: cmd("ssh -p 8765 root@38.244.62.18"), "deny"),
    ("rm", lambda: cmd("rm -rf app"), "deny"),
    ("git push", lambda: cmd("git push origin HEAD"), "deny"),
    ("git -C outside", lambda: cmd("git -C / status"), "deny"),
    ("git -c", lambda: cmd("git -c core.pager=sh status"), "deny"),
    ("git diff --output", lambda: cmd("git diff --output=/tmp/x"), "deny"),
    ("python -c", lambda: cmd("python -c 'import os'"), "deny"),
    ("python script", lambda: cmd("python app/x.py"), "deny"),
    ("pytest -p plugin", lambda: cmd("python -m pytest -p evil"), "deny"),
    ("pytest -pevil", lambda: cmd("python -m pytest -pevil"), "deny"),
    ("pytest --rootdir", lambda: cmd("python -m pytest --rootdir=/"), "deny"),
    ("pytest -p=plugin", lambda: cmd("pytest -p=evil"), "deny"),
    ("pytest -c config", lambda: cmd("pytest -c app/config.ini"), "deny"),
    ("pytest compact config", lambda: cmd("pytest -capp/config.ini"), "deny"),
    ("pytest override", lambda: cmd("pytest -o addopts=-x"), "deny"),
    ("pytest compact override", lambda: cmd("pytest -oaddopts=-x"), "deny"),
    ("unittest outside start", lambda: cmd("python -m unittest discover -s /tmp"), "deny"),
    ("unittest outside top", lambda: cmd("python -m unittest discover -t ../outside"), "deny"),
    ("unittest compact start", lambda: cmd("python -m unittest discover -s/tmp"), "deny"),
    ("unittest compact top", lambda: cmd("python -m unittest discover -t../outside"), "deny"),
    ("unittest long start", lambda: cmd("python -m unittest discover --start-directory=/tmp"), "deny"),
    ("unittest long top", lambda: cmd("python -m unittest discover --top-level-directory /tmp"), "deny"),
    ("find -exec", lambda: cmd("find . -exec rm {} +"), "deny"),
    ("find -delete", lambda: cmd("find . -delete"), "deny"),
    ("rg --pre", lambda: cmd("rg --pre=./x foo"), "deny"),
    ("sort -o", lambda: cmd("sort -o app/x.py app/x.py"), "deny"),
    ("cat outside", lambda: cmd("cat /etc/hosts"), "deny"),
    ("cat ../", lambda: cmd("cat ../../etc/hosts"), "deny"),
    ("cat ~", lambda: cmd("cat ~/.ssh/id_ed25519"), "deny"),
    ("cat via symlink", lambda: cmd("cat link_out"), "deny"),
    ("grep in home", lambda: cmd("grep -r token " + HOME), "deny"),
    ("cwd outside", lambda: cmd("ls", cwd="/etc"), "deny"),
    ("abs bin", lambda: cmd("/bin/rm -rf app"), "deny"),
    ("venv-looking bin", lambda: cmd("./venv/bin/python -m pytest"), "deny"),
    ("view outside", lambda: run("view_file", {"AbsolutePath": "/etc/hosts"}), "deny"),
    ("view .env", lambda: run("view_file", {"AbsolutePath": ROOT + "/.env"}), "deny"),
    ("view home secret", lambda: run("view_file", {"AbsolutePath": HOME + "/.gemini/antigravity-cli/antigravity-oauth-token"}), "deny"),
    ("write outside", lambda: run("write_to_file", {"TargetFile": HOME + "/evil.sh", "CodeContent": "x"}), "deny"),
    ("write .git", lambda: run("write_to_file", {"TargetFile": ROOT + "/.git", "CodeContent": "gitdir: /tmp"}), "deny"),
    ("write .claude settings", lambda: run("write_to_file", {"TargetFile": ROOT + "/.claude/settings.json", "CodeContent": "{}"}), "deny"),
    ("write .codex config", lambda: run("write_to_file", {"TargetFile": ROOT + "/.codex/config.toml", "CodeContent": "x"}), "deny"),
    ("write nested .codex", lambda: run("write_to_file", {"TargetFile": ROOT + "/app/.codex/config.toml", "CodeContent": "x"}), "deny"),
    ("write mixed-case .codex", lambda: run("replace_file_content", {"TargetFile": ROOT + "/app/.CoDeX/config.toml", "ReplacementContent": "x"}), "deny"),
    ("write nested .claude", lambda: run("write_to_file", {"TargetFile": ROOT + "/app/.claude/settings.json", "CodeContent": "{}"}), "deny"),
    ("write .agents hook", lambda: run("write_to_file", {"TargetFile": ROOT + "/.agents/hooks.json", "CodeContent": "{}"}), "deny"),
    ("write AGENTS.md", lambda: run("replace_file_content", {"TargetFile": ROOT + "/AGENTS.md"}), "deny"),
    ("write nested .git", lambda: run("write_to_file", {"TargetFile": ROOT + "/app/.git/config", "CodeContent": "x"}), "deny"),
    ("write via ..", lambda: run("write_to_file", {"TargetFile": ROOT + "/app/../../evil", "CodeContent": "x"}), "deny"),
    ("write through symlink", lambda: run("write_to_file", {"TargetFile": ROOT + "/link_out", "CodeContent": "x"}), "deny"),
    ("write through hard link", lambda: run("replace_file_content", {"TargetFile": ROOT + "/app/hard.py"}), "deny"),
    ("write relative", lambda: run("write_to_file", {"TargetFile": "evil.py", "CodeContent": "x"}), "deny"),
    ("write no target", lambda: run("write_to_file", {"CodeContent": "x"}), "deny"),
    ("fake artifact dir", lambda: run("write_to_file", {"TargetFile": "/tmp/x/a.md"}, art="/tmp/x"), "deny"),
    ("web search", lambda: run("search_web", {"query": "x"}), "deny"),
    ("read url", lambda: run("read_url_content", {"Url": "https://x"}), "deny"),
    ("browser", lambda: run("browser_navigate", {"Url": "https://x"}), "deny"),
    ("mcp", lambda: run("mcp_github_create_issue", {}), "deny"),
    ("unknown tool", lambda: run("send_command_input", {"Input": "y"}), "deny"),
    # --- red-team regressions (2026-10-11): APFS is case-insensitive
    ("write .GIT (case)", lambda: run("write_to_file", {"TargetFile": ROOT + "/.GIT", "CodeContent": "gitdir: x"}), "deny"),
    ("write .Git/config", lambda: run("write_to_file", {"TargetFile": ROOT + "/.Git/config", "CodeContent": "x"}), "deny"),
    ("write Agents.md", lambda: run("write_to_file", {"TargetFile": ROOT + "/Agents.md", "CodeContent": "x"}), "deny"),
    ("write .Claude/settings", lambda: run("write_to_file", {"TargetFile": ROOT + "/.Claude/settings.json", "CodeContent": "{}"}), "deny"),
    ("write .GITHUB workflow", lambda: run("write_to_file", {"TargetFile": ROOT + "/.GITHUB/workflows/x.yml", "CodeContent": "x"}), "deny"),
    ("write VENV/", lambda: run("write_to_file", {"TargetFile": ROOT + "/VENV/x", "CodeContent": "x"}), "deny"),
    ("write .ENVRC", lambda: run("write_to_file", {"TargetFile": ROOT + "/.ENVRC", "CodeContent": "x"}), "deny"),
    ("write .gitignore", lambda: run("write_to_file", {"TargetFile": ROOT + "/.gitignore", "CodeContent": "x"}), "deny"),
    ("write sitecustomize", lambda: run("write_to_file", {"TargetFile": ROOT + "/app/sitecustomize.py", "CodeContent": "x"}), "deny"),
    ("write .pth", lambda: run("write_to_file", {"TargetFile": ROOT + "/app/evil.PTH", "CodeContent": "x"}), "deny"),
    ("view .ENV (case)", lambda: run("view_file", {"AbsolutePath": ROOT + "/.ENV"}), "deny"),
    ("git grep -O pager", lambda: cmd("git grep -Ox foo"), "deny"),
    ("git diff --textconv", lambda: cmd("git diff --textconv"), "deny"),
    ("node --require", lambda: cmd("node --test --require=app/x.js"), "deny"),
    ("node --import", lambda: cmd("node --test --import ./app/x.mjs"), "deny"),
    ("node reporter dest", lambda: cmd("node --test --test-reporter-destination=app/out"), "deny"),
    ("tree -o", lambda: cmd("tree -o app/t"), "deny"),
    ("node script outside node_modules", lambda: cmd("node app/x.py"), "deny"),
    ("node_modules traversal", lambda: cmd("node node_modules/../app/x.py"), "deny"),
    ("node_modules link leading out", lambda: cmd("node node_modules/escape.js"), "deny"),
    ("node_modules link into worktree", lambda: cmd("node node_modules/inward.js"), "deny"),
    ("missing node_modules script", lambda: cmd("node node_modules/missing.js"), "deny"),
    ("node_modules directory", lambda: cmd("node node_modules/vitest"), "deny"),
    ("node flag before tool", lambda: cmd("node --require=app/x.js node_modules/vitest/vitest.mjs"), "deny"),
    ("node -e", lambda: cmd("node -e 1"), "deny"),
    ("tool path arg outside", lambda: cmd("node node_modules/vitest/vitest.mjs run ../../etc"), "deny"),
    ("tool --opt=outside", lambda: cmd("node node_modules/vitest/vitest.mjs --root=/etc"), "deny"),
    ("write into node_modules", lambda: run("write_to_file", {"TargetFile": ROOT + "/node_modules/vitest/vitest.mjs", "CodeContent": "x"}), "deny"),
    ("edit nested node_modules", lambda: run("replace_file_content", {"TargetFile": ROOT + "/app/Node_Modules/x.js", "ReplacementContent": "x"}), "deny"),
    ("write conftest (allowed, review flags it)", lambda: run("write_to_file", {"TargetFile": ROOT + "/tests/conftest.py", "CodeContent": "x"}), "allow"),
    ("manage_task status", lambda: run("manage_task", {"Action": "status", "TaskId": "x/task-1"}), "allow"),
    ("manage_task terminate", lambda: run("manage_task", {"Action": "terminate", "TaskId": "x/task-1"}), "allow"),
    ("manage_task create", lambda: run("manage_task", {"Action": "create", "Prompt": "x"}), "deny"),
    ("daemon command", lambda: run("run_command", {"CommandLine": "python -m pytest", "Cwd": ROOT, "IsDaemon": True}), "deny"),
    ("persistent command", lambda: run("run_command", {"CommandLine": "ls", "Cwd": ROOT, "RunPersistent": True}), "deny"),
    ("missing root", lambda: cmd("ls", extra_env={"AUTO_WORKER_ROOT": ""}), "deny"),
    ("root = home", lambda: cmd("ls", extra_env={"AUTO_WORKER_ROOT": HOME}), "deny"),
]


def main():
    fails = 0
    for label, fn, want in CASES:
        out = fn()
        ok = out.get("decision") == want
        fails += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {want:5} {label:28} -> {out.get('decision')}  {out.get('reason') or (out.get('overwrite') or {}).get('CommandLine', '')}"[:220])
    # allowed commands must be rewritten to run inside the sandbox
    rw = cmd("ls -la")["overwrite"]["CommandLine"]
    sb_ok = rw.split()[0].endswith("run_sandboxed.sh") and ROOT in rw
    print(("ok  " if sb_ok else "FAIL") + " allowed command is sandbox-wrapped: " + rw)
    fails += not sb_ok
    rw = cmd("python3 -m unittest discover -s tests -p 'test_*tv*.py' -q")["overwrite"]["CommandLine"]
    unit_ok = rw.split()[0].endswith("run_sandboxed.sh") and "'test_*tv*.py'" in rw
    print(("ok  " if unit_ok else "FAIL") + " unittest pattern preserved inside sandbox")
    fails += not unit_ok
    rw = cmd("node node_modules/.bin/vitest run")["overwrite"]["CommandLine"]
    tool_ok = rw.split()[0].endswith("run_sandboxed.sh") and rw.endswith("node node_modules/.bin/vitest run")
    print(("ok  " if tool_ok else "FAIL") + " node_modules tool runs inside the sandbox: " + rw)
    fails += not tool_ok
    shutil.rmtree(ROOT, ignore_errors=True)
    shutil.rmtree(ROOT + ".tmp", ignore_errors=True)
    os.unlink(os.path.join(os.path.dirname(ROOT), os.path.basename(ROOT) + "-hl-src"))
    print(f"\n{len(CASES) + 3 - fails}/{len(CASES) + 3} passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
