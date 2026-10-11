#!/usr/bin/env python3
"""Regression tests for agy_worker.py + run_sandboxed.sh, using a FAKE agy and a toy repo
(never the user's repos, never Gemini). Each scenario is an attack or failure found by the
2026-10-11 red-team rounds. Run: python3 ~/.claude/skills/auto/test_worker.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

DIR = os.path.dirname(os.path.realpath(__file__))
W = [sys.executable, os.path.join(DIR, "agy_worker.py")]
SB = os.path.join(DIR, "run_sandboxed.sh")
TMP = os.path.realpath(tempfile.mkdtemp(prefix="auto-worker-test-"))
REPO = os.path.join(TMP, "repo")
FAKE = os.path.join(TMP, "bin")
RESULTS, CREATED = [], []


def sh(*cmd, cwd=None, env=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"{cmd}: {r.stderr}")
    return r


def setup():
    os.makedirs(REPO)
    sh("git", "init", "-q", REPO)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        sh("git", "-C", REPO, "config", k, v)
    open(os.path.join(REPO, "app.py"), "w").write("x = 1\n")
    open(os.path.join(REPO, "crlf.txt"), "wb").write(b"line1\r\nline2\r\n")
    sh("git", "-C", REPO, "add", "-A")
    sh("git", "-C", REPO, "commit", "-qm", "base")
    sh("git", "-C", REPO, "stash", "list")
    os.makedirs(FAKE)


def fake_agy(script):
    """The fake agy runs `script` (bash) in the worker tree, then prints a SUCCESS json line."""
    with open(os.path.join(FAKE, "agy"), "w") as f:
        f.write("#!/bin/bash\n" + script + '\necho \'{"status":"SUCCESS","response":"done","usage":{}}\'\n')
    os.chmod(os.path.join(FAKE, "agy"), 0o755)


def run(name, script):
    fake_agy(script)
    brief = os.path.join(TMP, "brief.md")
    open(brief, "w").write("GOAL: test\n")
    env = dict(os.environ, PATH=FAKE + ":" + os.environ["PATH"])
    r = sh(*W, "run", "--repo", REPO, "--brief", brief, "--model", "fake", "--name", name, "--timeout", "60", env=env)
    out = json.loads(r.stdout)
    CREATED.append(out["run"])
    return out


def check(label, ok, detail=""):
    RESULTS.append(ok)
    print(f"{'ok  ' if ok else 'FAIL'} {label}" + (f"  [{detail}]" if not ok and detail else ""))


def main():
    setup()
    # 1. lone CR in content must not forge an extra file patch
    forged = 'hello\\rdiff --git a/.claude/settings.json b/.claude/settings.json\\rnew file mode 100644\\r--- /dev/null\\r+++ b/.claude/settings.json\\r@@ -0,0 +1 @@\\r+{"hooks":1}'
    o = run("cr-forge", f"printf '{forged}\\n' > notes.txt")
    patch = open(o["patch"], "rb").read()
    check("CR forge: patch keeps the CR bytes", b"hello\rdiff --git" in patch)
    check("CR forge: no .claude path in patch", ".claude" not in json.dumps(o.get("REVIEW_FLAGS", {})) and
          not any(".claude" in p for p in json.load(open(os.path.join(DIR, "runs", o["run"], "meta.json")))["rounds"][-1]["paths"]))
    # 2. non-ASCII nested control files are flagged
    o = run("nonascii", "mkdir -p ü tëst && echo x > ü/.envrc && echo x > 'tëst/conftest.py' && echo x > ü/.gitignore")
    f = o.get("REVIEW_FLAGS", {})
    check("non-ASCII: ü/.envrc flagged protected", "ü/.envrc" in f.get("protected_paths", []), json.dumps(f, ensure_ascii=False))
    check("non-ASCII: ü/.gitignore flagged protected", "ü/.gitignore" in f.get("protected_paths", []))
    check("non-ASCII: tëst/conftest.py flagged exec surface", "tëst/conftest.py" in f.get("execution_surface", []))
    # 3. binary file flagged
    o = run("binary", "printf 'a\\0b' > blob.bin")
    check("binary file flagged", "blob.bin" in o.get("REVIEW_FLAGS", {}).get("binary_files", []), json.dumps(o.get("REVIEW_FLAGS")))
    # 4. CRLF edit produces an appliable patch
    o = run("crlf", "printf 'line1\\r\\nLINE2\\r\\n' > crlf.txt")
    r = sh(*W, "verify", o["run"], "--full", "--", "/bin/cat", "crlf.txt", check=False)
    check("CRLF edit verifies (patch applies)", r.returncode == 0, r.stderr[-300:])
    # 5. setsid daemon from sandboxed code is swept
    # a proper daemon: setsid, double fork, closes stdio (so agy's pipe doesn't keep the run waiting)
    daemon = ("python3 -c \"import os,time\nif os.fork()==0:\n os.setsid()\n if os.fork()==0:\n"
              "  [os.close(i) for i in (0,1,2)]; time.sleep(3); open('late.txt','w').write('x')\"")
    o = run("daemon", f"AUTO_WORKER_GITDIR=$PWD/.git {SB} $PWD {daemon}")
    time.sleep(5)
    check("setsid daemon swept before it could write", not os.path.exists(os.path.join(o["worktree"], "late.txt")),
          f"swept={o.get('REVIEW_FLAGS', {}).get('leftover_processes_killed')}")
    # 6. sandbox: shared temp dirs and other trees unreadable; nested control files unwritable
    probe = os.path.join(TMP, "canary.txt")
    open(probe, "w").write("CANARY")
    wt = o["worktree"]
    r = sh(SB, wt, "/bin/cat", probe, cwd=wt, env=dict(os.environ, AUTO_WORKER_GITDIR=wt + "/.git"), check=False)
    check("sandbox: shared $TMPDIR file unreadable", "CANARY" not in r.stdout, r.stdout)
    r = sh(SB, wt, "/bin/sh", "-c", "mkdir -p sub/.claude && echo x > sub/.claude/s.json; echo x > sub/.envrc; echo x > sub/.gitattributes; ls -a sub",
           cwd=wt, env=dict(os.environ, AUTO_WORKER_GITDIR=wt + "/.git"), check=False)
    check("sandbox: nested .claude/.envrc/.gitattributes unwritable",
          not any(os.path.exists(os.path.join(wt, "sub", n)) for n in (".claude/s.json", ".envrc", ".gitattributes")), r.stdout)
    # 7. worker repo is standalone: no stash/branches/remotes from the user's repo
    r = sh("git", "-C", wt, "log", "--all", "--oneline")
    check("worker repo holds only the base commit", len(r.stdout.strip().splitlines()) == 1, r.stdout)
    # 8. apply gates
    o = run("gates", "echo 'y = 2' >> app.py")
    rid, sha = o["run"], o["patch_sha256"]
    r = sh(*W, "apply", rid, "--sha", sha, check=False)
    check("apply refused without verify --full", r.returncode != 0 and "verify --full" in r.stderr, r.stderr)
    sh(*W, "verify", rid, "--", "/usr/bin/true", check=False)
    r = sh(*W, "apply", rid, "--sha", sha, check=False)
    check("apply refused with only a non-full verify", r.returncode != 0, r.stderr)
    sh(*W, "verify", rid, "--full", "--", "/usr/bin/true")
    r = sh(*W, "apply", rid, "--sha", "0" * 64, check=False)
    check("apply refused with wrong sha", r.returncode != 0 and "not the reviewed" in r.stderr, r.stderr)
    open(os.path.join(REPO, "app.py"), "a").write("# user WIP\n")
    r = sh(*W, "apply", rid, "--sha", sha, check=False)
    check("apply refused on dirty target file", r.returncode != 0 and "local changes" in r.stderr, r.stderr)
    check("dirty WIP untouched", open(os.path.join(REPO, "app.py")).read() == "x = 1\n# user WIP\n")
    sh("git", "-C", REPO, "checkout", "-q", "--", "app.py")
    open(os.path.join(REPO, "other.txt"), "w").write("o\n")
    sh("git", "-C", REPO, "add", "other.txt")
    sh("git", "-C", REPO, "commit", "-qm", "user moved on")
    r = sh(*W, "apply", rid, "--sha", sha, check=False)
    check("apply refused after HEAD moved", r.returncode != 0 and "HEAD is" in r.stderr, r.stderr)
    sh(*W, "verify", rid, "--full", "--", "/usr/bin/true")
    r = sh(*W, "apply", rid, "--sha", sha, check=False)
    st = sh("git", "-C", REPO, "status", "--porcelain").stdout
    check("apply succeeds after fresh full verify, unstaged", r.returncode == 0 and st.strip() == "M app.py", r.stderr + st)
    # 9. timeout keeps the round and the patch
    fake_agy("echo t >> app.py; sleep 300")
    env = dict(os.environ, PATH=FAKE + ":" + os.environ["PATH"])
    open(os.path.join(TMP, "brief.md"), "w").write("GOAL: t\n")
    r = sh(*W, "run", "--repo", REPO, "--brief", os.path.join(TMP, "brief.md"), "--model", "fake", "--name", "timeout",
           "--timeout", "-115", env=env, check=False)
    o = json.loads(r.stdout)
    CREATED.append(o["run"])
    check("timeout: status recorded and patch captured", o["status"] == "timeout" and "app.py" in o.get("diffstat", ""), r.stdout[-300:])

    for rid in CREATED:
        sh(*W, "clean", rid, check=False)
        shutil.rmtree(os.path.join(DIR, "runs", rid), ignore_errors=True)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} passed")
    sys.exit(0 if all(RESULTS) else 1)


if __name__ == "__main__":
    main()
