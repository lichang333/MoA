#!/usr/bin/env python3
"""Regression tests for agy_worker.py + run_sandboxed.sh, using a FAKE agy and a toy repo
(never the user's repos, never Gemini). Each scenario is an attack or failure found by the
2026-10-11 red-team rounds. Run: python3 ~/.claude/skills/auto/test_worker.py
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

SOURCE_DIR = os.path.dirname(os.path.realpath(__file__))
TMP = os.path.realpath(tempfile.mkdtemp(prefix="auto-worker-test-"))
# Isolate run records and the ledger from real user runs, including when launched via a
# platform symlink. Copy only the runtime under test, never local state or credentials.
DIR = os.path.join(TMP, "auto")
W = [sys.executable, os.path.join(DIR, "agy_worker.py")]
SB = os.path.join(DIR, "run_sandboxed.sh")
REPO = os.path.join(TMP, "repo")
FAKE = os.path.join(TMP, "bin")
RESULTS, CREATED = [], []


def sh(*cmd, cwd=None, env=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"{cmd}: {r.stderr}")
    return r


def setup():
    os.makedirs(DIR)
    for name in ("agy_worker.py", "run_sandboxed.sh", "sandbox.sb"):
        shutil.copy2(os.path.join(SOURCE_DIR, name), os.path.join(DIR, name))
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
    # Read guard events from this isolated runtime, never the user's registered hook log.
    os.environ["AUTO_GUARD_LOG"] = os.path.join(DIR, "logs", "guard.jsonl")


def fake_agy(script, response=None):
    """The fake agy runs `script` (bash) in the worker tree, then prints a SUCCESS json line."""
    with open(os.path.join(FAKE, "agy"), "w") as f:
        payload = {"status": "SUCCESS", "response": "done", "usage": {}, **(response or {})}
        f.write("#!/bin/bash\n" + script + "\nprintf '%s\\n' " + shlex.quote(json.dumps(payload)) + "\n")
    os.chmod(os.path.join(FAKE, "agy"), 0o755)


def run(name, script, *extra):
    fake_agy(script)
    brief = os.path.join(TMP, "brief.md")
    open(brief, "w").write("GOAL: test\n")
    env = dict(os.environ, PATH=FAKE + ":" + os.environ["PATH"])
    r = sh(*W, "run", "--repo", REPO, "--brief", brief, "--model", "fake", "--name", name, "--timeout", "60", *extra, env=env)
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
    legacy_rid = o["run"]
    check("default coordination provenance is backward-compatible",
          (o.get("platform"), o.get("coordinator_model"), o.get("task_id"), o.get("executor")) == ("claude", "current", None, "agy"))
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
    # Exercise actual sandbox writes, including existing mixed-case nested config files.
    codex_paths = (".codex/config.toml", "sub/.CoDeX/config.toml")
    for rel in codex_paths:
        path = os.path.join(wt, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").write("original\n")
    r = sh(SB, wt, "/bin/sh", "-c", "echo changed > .codex/config.toml; echo changed > sub/.CoDeX/config.toml; mkdir -p other/.CODEX; echo new > other/.CODEX/config.toml",
           cwd=wt, env=dict(os.environ, AUTO_WORKER_GITDIR=wt + "/.git"), check=False)
    check("sandbox: root and nested mixed-case .codex writes blocked",
          all(open(os.path.join(wt, rel)).read() == "original\n" for rel in codex_paths)
          and not os.path.exists(os.path.join(wt, "other/.CODEX/config.toml")), r.stderr[-300:])
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

    # 10. A forged worker output cannot bypass the protected-path apply gate for Codex.
    o = run("codex-protected", "mkdir -p .codex sub/.CoDeX; echo x > .codex/config.toml; echo x > sub/.CoDeX/config.toml",
            "--platform", "codex", "--coordinator-model", "gpt-6-astra", "--task-id", "task-test")
    check("patch capture flags root and nested mixed-case .codex",
          set(o.get("REVIEW_FLAGS", {}).get("protected_paths", [])) == set(codex_paths))
    sh(*W, "verify", o["run"], "--full", "--", "/usr/bin/true")
    r = sh(*W, "apply", o["run"], "--sha", o["patch_sha256"], check=False)
    check("apply refuses protected .codex even after full verify",
          r.returncode != 0 and "protected paths" in r.stderr and not os.path.exists(os.path.join(REPO, ".codex")), r.stderr)
    expected = {"platform": "codex", "coordinator_model": "gpt-6-astra", "task_id": "task-test", "executor": "agy"}
    meta = json.load(open(os.path.join(DIR, "runs", o["run"], "meta.json")))
    record = json.loads(sh(*W, "record", o["run"], "--level", "L2", "--outcome", "rejected").stdout)
    ledger = json.loads(open(os.path.join(DIR, "runs.jsonl")).readlines()[-1])
    check("coordination provenance persists in summary, meta and ledger",
          all(all(item.get(k) == v for k, v in expected.items()) for item in (o, meta, record, ledger)))

    # 11. Missing provenance in an old run defaults to Claude, including resume/record.
    legacy_path = os.path.join(DIR, "runs", legacy_rid, "meta.json")
    legacy = json.load(open(legacy_path))
    for key in expected:
        legacy.pop(key, None)
    with open(legacy_path, "w") as f:
        json.dump(legacy, f)
    fake_agy("true", response={"executor": "native"})
    resumed = json.loads(sh(*W, "resume", legacy_rid, "--brief", os.path.join(TMP, "brief.md"), env=env).stdout)
    legacy_record = json.loads(sh(*W, "record", legacy_rid, "--level", "L1", "--outcome", "rejected").stdout)
    check("legacy meta resumes and records with compatible defaults",
          all((item.get("platform"), item.get("coordinator_model"), item.get("task_id"), item.get("executor")) == ("claude", "current", None, "agy")
              for item in (resumed, json.load(open(legacy_path)), legacy_record)))
    check("worker-reported executor cannot override coordinator metadata",
          json.load(open(os.path.join(DIR, "runs", legacy_rid, "response-2.json"))).get("executor") == "native"
          and resumed.get("executor") == legacy_record.get("executor") == "agy")

    # 12. Two runs at the same fixed second/slug get independent trees and shared core
    # state when launched through a platform symlink. The executor remains fake agy.
    entry = os.path.join(TMP, "platform-auto", "agy_worker.py")
    os.makedirs(os.path.dirname(entry))
    os.symlink(W[1], entry)
    fixed_clock = """import datetime, importlib.util, sys
spec = importlib.util.spec_from_file_location('worker', sys.argv[1])
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
class FixedDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 1, 1, 0, 0, 0, tzinfo=tz)
worker.datetime.datetime = FixedDateTime
sys.argv = sys.argv[1:]
worker.main()
"""
    fake_agy("echo parallel > parallel.txt")
    procs = [subprocess.Popen([sys.executable, "-c", fixed_clock, entry, "run", "--repo", REPO,
                              "--brief", os.path.join(TMP, "brief.md"), "--model", "fake", "--name", "same-slug",
                              "--platform", platform], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for platform in ("codex", "headless")]
    parallel = []
    for p in procs:
        out, err = p.communicate(timeout=90)
        check("parallel worker exits successfully", p.returncode == 0, err[-300:])
        if p.returncode == 0:
            item = json.loads(out)
            parallel.append(item)
            CREATED.append(item["run"])
    check("same-second same-slug runs have independent random IDs and trees",
          len(parallel) == 2 and len({x["run"] for x in parallel}) == 2
          and len({x["worktree"] for x in parallel}) == 2
          and all(x["run"].startswith("20260101-000000-same-slug-") for x in parallel))
    check("platform symlink shares core run state and preserves platform provenance",
          len(parallel) == 2 and {x["platform"] for x in parallel} == {"codex", "headless"}
          and all(os.path.isfile(os.path.join(DIR, "runs", x["run"], "meta.json")) for x in parallel)
          and not os.path.exists(os.path.join(os.path.dirname(entry), "runs")))

    # 11. agy may report SUCCESS after its own print timeout: never treat partial output as success.
    o = run("partial", "echo p >> app.py; echo '[agy] print timeout after 40m0s with turn in progress; returning partial output' >&2")
    check("agy print timeout is recorded as an incomplete timeout, patch kept",
          o["status"] == "timeout" and "print timeout" in o["REVIEW_FLAGS"].get("INCOMPLETE_RUN", "")
          and "app.py" in o.get("diffstat", ""), json.dumps(o)[-400:])
    fake_agy("echo q >> app.py", response={"response": "  "})
    o = json.loads(sh(*W, "run", "--repo", REPO, "--brief", os.path.join(TMP, "brief.md"), "--model", "fake",
                      "--name", "no-report", "--timeout", "60", env=dict(os.environ, PATH=FAKE + ":" + os.environ["PATH"])).stdout)
    CREATED.append(o["run"])
    check("SUCCESS without a final report is incomplete",
          o["status"] == "incomplete" and "INCOMPLETE_RUN" in o["REVIEW_FLAGS"], json.dumps(o)[-300:])

    # 12. stall watchdog: no tool call for --stall-timeout awake seconds stops the worker, keeps the patch;
    # other runs' guard events are not progress.
    glog = os.path.join(DIR, "logs", "guard.jsonl")
    other = shlex.quote(json.dumps({"run": "someone-else", "tool": "view_file", "decision": "allow"}))
    t0 = time.time()
    o = run("stall", f"mkdir -p {shlex.quote(os.path.dirname(glog))}; echo s >> app.py; "
            f"for i in $(seq 120); do echo {other} >> {shlex.quote(glog)}; sleep 1; done", "--stall-timeout", "3")
    elapsed = time.time() - t0
    check("stall: stopped early, status stalled, patch captured, flagged",
          o["status"] == "stalled" and elapsed < 40 and "app.py" in o.get("diffstat", "")
          and "awake time" in o["REVIEW_FLAGS"].get("INCOMPLETE_RUN", ""), f"{elapsed:.0f}s " + json.dumps(o)[-300:])
    mine = 'printf \'{"run":"%s","conv":"12345678-1234-4234-8234-123456789abc","tool":"view_file","decision":"allow"}\\n\' "$AUTO_RUN_ID"'
    o = run("progress", f"mkdir -p {shlex.quote(os.path.dirname(glog))}; "
            f"for i in 1 2 3 4 5; do {mine} >> {shlex.quote(glog)}; sleep 1.5; done; echo g >> app.py", "--stall-timeout", "3")
    meta = json.load(open(os.path.join(DIR, "runs", o["run"], "meta.json")))
    check("steady tool calls keep a slow worker alive and are counted",
          o["status"] == "SUCCESS" and o["tool_events"] >= 5
          and meta["rounds"][-1]["guard_conversation"] == "12345678-1234-4234-8234-123456789abc"
          and "host_sleep_seconds" not in o, json.dumps(o)[-300:])

    o = run("long-command", f"{shlex.quote(SB)} \"$AUTO_WORKER_ROOT\" /bin/sleep 7; echo l >> app.py", "--stall-timeout", "3")
    check("a long sandboxed command is activity, not a stall", o["status"] == "SUCCESS", json.dumps(o)[-300:])
    o = run("think-after-command", f"mkdir -p {shlex.quote(os.path.dirname(glog))}; "
            f"{shlex.quote(SB)} \"$AUTO_WORKER_ROOT\" /bin/sleep 7; sleep 1.5; {mine} >> {shlex.quote(glog)}; echo k >> app.py",
            "--stall-timeout", "4")
    check("thinking right after a long command is not a stall", o["status"] == "SUCCESS", json.dumps(o)[-300:])
    t0 = time.time()
    o = run("leftover-holder", f"{shlex.quote(SB)} \"$AUTO_WORKER_ROOT\" /bin/sh -c '(/bin/sleep 40 &)'; sleep 60",
            "--stall-timeout", "4")
    wt = json.load(open(os.path.join(DIR, "runs", o["run"], "meta.json")))["worktree"]
    holders = sh("lsof", "-t", "--", wt + ".busy", check=False).stdout.split()
    check("a leftover sandboxed process does not keep a silent worker alive, and is swept",
          o["status"] == "stalled" and time.time() - t0 < 40 and not holders, f"{o['status']} {holders}")

    # Sandbox bookkeeping beside the tree cannot be redirected: neither by sandboxed code nor by links.
    r = sh(SB, wt, "/bin/sh", "-c", f'ln -sf /dev/null {shlex.quote(wt + ".busy")} && echo escaped; rmdir "$TMPDIR" && echo escaped; true', cwd=wt, check=False)
    check("sandboxed code cannot replace the busy marker or remove its TMP dir",
          "escaped" not in r.stdout and os.path.isfile(wt + ".busy") and not os.path.islink(wt + ".busy")
          and os.path.isdir(wt + ".tmp"), r.stdout + r.stderr)
    victim_file = os.path.join(TMP, "victim")
    open(victim_file, "w").close()
    with open(victim_file) as held:
        victim = subprocess.Popen(["/bin/sleep", "60"], pass_fds=(held.fileno(),))
    os.unlink(wt + ".busy")
    os.symlink(victim_file, wt + ".busy")
    r = sh(SB, wt, "/usr/bin/true", cwd=wt, check=False)
    sh(*W, "clean", o["run"], check=False)
    check("a symlinked busy marker is refused; sweep and clean never follow it, clean removes the link",
          r.returncode == 2 and "refusing BUSY" in r.stderr and victim.poll() is None
          and not os.path.lexists(wt + ".busy") and os.path.isfile(victim_file), r.stderr)
    victim.kill()
    sh("git", "init", "-q", wt)
    os.symlink(TMP, wt + ".tmp")
    r = sh(SB, wt, "/usr/bin/true", cwd=wt, check=False)
    check("a symlinked TMP dir is refused", r.returncode == 2 and "refusing symlinked TMP" in r.stderr, r.stderr)
    os.unlink(wt + ".tmp")
    shutil.rmtree(wt)

    quota = "Individual quota reached. Please upgrade your subscription. Resets in 2h3m4s."
    fake_agy(f"echo q >> app.py; echo 'error: {quota}' >&2", response={"status": "ERROR", "error": quota, "response": ""})
    env = dict(os.environ, PATH=FAKE + ":" + os.environ["PATH"])
    o = json.loads(sh(*W, "run", "--repo", REPO, "--brief", os.path.join(TMP, "brief.md"), "--model", "fake",
                      "--name", "quota", "--timeout", "60", env=env, check=False).stdout)
    CREATED.append(o["run"])
    check("an exhausted agy quota is flagged with its reset time and the partial patch kept",
          o["status"] == "ERROR" and "QUOTA_EXHAUSTED" in o["REVIEW_FLAGS"] and "app.py" in o.get("diffstat", ""),
          json.dumps(o)[-300:])
    busy = json.dumps({"short_error": "UNAVAILABLE (code 503): No capacity available for model fake on the server",
                       "status": "UNAVAILABLE", "error_code": 503, "code_kind": "http", "retryable": True})
    fake_agy(f"echo {shlex.quote('AGY_ERROR: ' + busy)} >&2; exit 3", response={"status": "ERROR"})
    o = json.loads(sh(*W, "run", "--repo", REPO, "--brief", os.path.join(TMP, "brief.md"), "--model", "fake",
                      "--name", "capacity", "--timeout", "60", env=env, check=False).stdout)
    CREATED.append(o["run"])
    check("server capacity (503) is flagged as capacity, not quota, and not auto-retried",
          "CAPACITY_UNAVAILABLE" in o["REVIEW_FLAGS"] and "QUOTA_EXHAUSTED" not in o["REVIEW_FLAGS"]
          and o["network_recovery"]["retries"] == 0, json.dumps(o)[-300:])

    # 13. --node-modules: a copy-on-write clone in the worker and verify trees, never in the patch.
    deps = os.path.join(TMP, "deps", "node_modules")
    os.makedirs(os.path.join(deps, "tool"))
    open(os.path.join(deps, "tool", "index.js"), "w").write("// dep\n")
    o = run("node-deps", 'test -f node_modules/tool/index.js && echo ok > nm.txt; '
            'case "$*" in *"npm, npx and package installs are unavailable"*) echo note > note.txt;; esac',
            "--node-modules", deps)
    rid = o["run"]
    check("node_modules cloned into the worker tree, preamble says how to use it, excluded from the patch",
          set(o.get("diffstat", "").split()) >= {"nm.txt", "note.txt"} and "node_modules" not in o.get("diffstat", ""),
          o.get("diffstat", ""))
    vtree = os.path.join(json.load(open(os.path.join(DIR, "runs", rid, "meta.json")))["worktree"] + "-verify")
    r = sh(*W, "verify", rid, "--full", "--", "/bin/test", "-f", "node_modules/tool/index.js", check=False)
    check("verify clones node_modules and removes a passing tree", r.returncode == 0 and not os.path.exists(vtree), r.stderr)
    r = sh(*W, "verify", rid, "--keep-tree", "--venv", os.path.join(TMP, "deps"), "--", "/bin/test", "-f", "nm.txt", check=False)
    meta = json.load(open(os.path.join(DIR, "runs", rid, "meta.json")))
    check("--keep-tree keeps it; --venv applies to that verification only",
          r.returncode == 0 and os.path.isdir(vtree) and meta["verified"][-1]["venv"] == os.path.join(TMP, "deps")
          and not meta["venv"], r.stderr)
    venv = os.path.join(TMP, "fake-venv")
    os.makedirs(os.path.join(venv, "bin"))
    open(os.path.join(venv, "bin", "python"), "w").write("#!/bin/sh\necho used > venv-marker\n")
    os.chmod(os.path.join(venv, "bin", "python"), 0o755)
    r = sh(*W, "verify", rid, "--keep-tree", "--venv", venv, "--", "python", "-m", "anything", check=False)
    check("verify --venv runs that interpreter", r.returncode == 0 and os.path.isfile(os.path.join(vtree, "venv-marker")), r.stderr)
    worker_tool = os.path.join(json.load(open(os.path.join(DIR, "runs", rid, "meta.json")))["worktree"], "node_modules", "tool", "index.js")
    open(worker_tool, "w").write("// tampered by worker code\n")
    r = sh(*W, "test", rid, "--", "/usr/bin/grep", "-q", "dep", "node_modules/tool/index.js", check=False)
    check("test re-clones the run's node_modules before using its tools", r.returncode == 0, r.stderr)
    r = sh(*W, "verify", rid, "--no-node-modules", "--", "/bin/test", "!", "-e", "node_modules", check=False)
    check("verify --no-node-modules skips the clone", r.returncode == 0, r.stderr)
    # Earlier verified code may lock files in its TMP (chmod/chflags); the next verify starts clean.
    r = sh(*W, "verify", rid, "--keep-tree", "--", "/bin/sh", "-c",
           'mkdir -p "$TMPDIR/locked" && echo stale > "$TMPDIR/locked/cache" && chflags uchg "$TMPDIR/locked/cache" '
           '&& chmod 555 "$TMPDIR/locked"', check=False)
    locked = os.path.isfile(os.path.join(vtree + ".tmp", "locked", "cache"))
    r2 = sh(*W, "verify", rid, "--", "/bin/sh", "-c", 'test ! -e "$TMPDIR/locked"', check=False)
    check("a locked TMP left by earlier verified code is removed before the next verify",
          r.returncode == 0 and locked and r2.returncode == 0 and not os.path.lexists(os.path.join(vtree + ".tmp", "locked")),
          r.stderr + r2.stderr)
    r = sh(*W, "verify", rid, "--", "/bin/test", "-f", "missing", check=False)
    check("a failing verify tree is kept for inspection", r.returncode != 0 and os.path.isdir(vtree), r.stderr)
    r = sh(*W, "run", "--repo", REPO, "--brief", os.path.join(TMP, "brief.md"), "--model", "fake",
           "--node-modules", os.path.join(TMP, "nope"), check=False, env=dict(os.environ, PATH=FAKE + ":" + os.environ["PATH"]))
    check("a missing --node-modules dir is refused before any run state", r.returncode != 0 and "not a directory" in r.stderr, r.stderr)
    o = run("case-variant", "mkdir -p pkg/Node_Modules/dep; echo x > pkg/Node_Modules/dep/index.js; echo c > case.txt")
    check("case-variant node_modules never enters the patch", "case.txt" in o.get("diffstat", "")
          and "node_modules" not in o.get("diffstat", "").lower(), o.get("diffstat", ""))
    vendored = os.path.join(TMP, "vendored")
    sh("git", "init", "-q", vendored)
    os.makedirs(os.path.join(vendored, "Node_Modules"))
    open(os.path.join(vendored, "Node_Modules", "x.js"), "w").write("x\n")
    sh("git", "-C", vendored, "add", "-A")
    sh("git", "-C", vendored, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "vendored")
    before = set(os.listdir(os.path.join(DIR, "runs")))
    r = sh(*W, "run", "--repo", vendored, "--brief", os.path.join(TMP, "brief.md"), "--model", "fake", "--name", "vendored",
           "--node-modules", deps, check=False, env=dict(os.environ, PATH=FAKE + ":" + os.environ["PATH"]))
    leaked = [x for x in os.listdir(os.path.dirname(vtree)) if "-vendored-" in x]
    check("a base commit that tracks node_modules is refused and leaves no run state",
          r.returncode != 0 and "already has node_modules" in r.stderr
          and set(os.listdir(os.path.join(DIR, "runs"))) == before and not leaked, r.stderr + str(leaked))

    for rid in CREATED:
        sh(*W, "clean", rid, check=False)
        shutil.rmtree(os.path.join(DIR, "runs", rid), ignore_errors=True)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} passed")
    sys.exit(0 if all(RESULTS) else 1)


if __name__ == "__main__":
    main()
