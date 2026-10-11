#!/usr/bin/env python3
"""Launch and manage Antigravity (agy) workers for Claude's /auto skill.

Every worker gets its own STANDALONE repo under $TMPDIR/auto-worker/<id> holding only the
base commit (shallow fetch: no stash, no other branches, no remotes, no credentials from the
user's repo), runs headless with AUTO_WORKER=1 so agy_guard.py is its only (default-deny)
gate, and leaves a record under runs/<id>/. Nothing reaches the user's checkout until Claude
has reviewed the patch, `verify --full` has tested exactly those bytes on a fresh tree at the
user's current HEAD, and `apply` has re-checked sha, HEAD, cleanliness and flags.

  agy_worker.py run    --repo DIR --brief FILE --model M [--base REF] [--name SLUG] [--timeout S]
  agy_worker.py resume RUN_ID --brief FILE [--timeout S]       # send-back round, same conversation
  agy_worker.py test   RUN_ID -- CMD [ARGS...]                 # quick sandboxed run in the worker tree
  agy_worker.py verify RUN_ID [--full] [--onto REF] -- CMD ... # patch -> fresh tree -> sandboxed CMD
  agy_worker.py apply  RUN_ID --sha SHA256 [--allow-protected] [--allow-binary]
  agy_worker.py record RUN_ID --level L1 --outcome accepted|fixed|rejected [--notes TEXT] [--defects a,b]
  agy_worker.py clean  RUN_ID
  agy_worker.py list

Host-side git never trusts worker-controlled state: explicit --git-dir, hooks/fsmonitor off,
attributes read from the empty tree (in-tree .gitattributes ignored), global/system config
ignored, and all git output handled as bytes with NUL-separated, unquoted paths.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

SKILL_DIR = os.path.dirname(os.path.realpath(__file__))
RUNS = os.path.join(SKILL_DIR, "runs")
LEDGER = os.path.join(SKILL_DIR, "runs.jsonl")
GUARD_LOG = os.path.join(SKILL_DIR, "logs", "guard.jsonl")
SANDBOX = os.path.join(SKILL_DIR, "run_sandboxed.sh")
WT_BASE = os.path.join(os.path.realpath(os.environ.get("TMPDIR", "/tmp")), "auto-worker")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
DIFF_EXCLUDES = [":(glob,exclude).pytest_cache/**", ":(glob,exclude)**/__pycache__/**",
                 ":(glob,exclude)**/*.pyc", ":(glob,exclude)**/node_modules/**"]
SAFE_GIT = ["-c", "core.fsmonitor=", "-c", "core.hooksPath=/dev/null", "-c", "core.attributesFile=/dev/null",
            "-c", "core.quotePath=false", "-c", "core.autocrlf=false",
            "-c", "core.pager=cat", "-c", "advice.detachedHead=false"]
# Worker-tree reads (add/diff/status) ignore in-tree .gitattributes. Not used for `git apply`,
# which segfaults with --attr-source on git 2.54; apply only ever runs on trees whose
# attributes come from the user's own commits (and a patch adding .gitattributes is refused).
ATTR_OFF = [f"--attr-source={EMPTY_TREE}"]
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
# Paths that need Claude's explicit, line-by-line attention (reported in every summary).
PROTECTED_RE = re.compile(r"(^|/)(\.git|\.claude|\.agents?|_agents?|\.gemini|\.github|\.vscode|\.idea|\.?venv)(/|$)"
                          r"|(^|/)(agents\.md|gemini\.md|claude\.md|\.gitmodules|\.gitignore|\.gitattributes|\.envrc"
                          r"|\.flaskenv|\.pre-commit-config\.ya?ml|sitecustomize\.py|usercustomize\.py)$|\.pth$", re.I)
SENSITIVE_RE = re.compile(r"(^|/)(deploy|node-managers|scripts|migrations)/|^(run\.sh|wsgi\.py|requirements[^/]*\.txt"
                          r"|app/config\.py)$", re.I)
EXEC_SURFACE_RE = re.compile(r"(^|/)(conftest\.py|pytest\.ini|pyproject\.toml|setup\.cfg|setup\.py|tox\.ini|Makefile"
                             r"|package\.json|[^/]+\.sh)$", re.I)
CACHE_RE = re.compile(r"(^|/)(\.pytest_cache|__pycache__|node_modules|instance)(/|$)|\.pyc$")
MIN_ENV_KEYS = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TERM", "TMPDIR")
PREAMBLE = """You are a coding worker. Rules for this run (enforced by a guard; violations are denied):
- Work ONLY inside the current directory, a throwaway git repo. Edit files with your file tools.
- Shell: one simple command per call (no pipes, ;, &&, redirects, $()), read-only tools, git
  status/diff/log/show, `python -m pytest`, `node --test`. No network, no installs, no ssh, no git
  commit/push. If something you need is denied, say so in your final reply instead of working around it.
- Do not edit AGENTS.md, .gitignore, .gitattributes, .git, .claude, .agents, .github or venv files.
- Do not leave background processes running when you finish.
- Finish with a short report: what you changed (files), what you verified (exact test commands and
  results), and anything you were unsure about or could not do.

TASK BRIEF:
"""


# ---------------------------------------------------------------- helpers

def git(tree, *args, check=True, cwd=None):
    """git on a tree we created, with an explicit git dir and everything steerable switched off.
    Returns stdout as BYTES (never decoded: a lone CR in file content must stay a CR)."""
    cmd = ["git", *SAFE_GIT, *ATTR_OFF, f"--git-dir={os.path.join(tree, '.git')}", f"--work-tree={tree}", *args]
    r = subprocess.run(cmd, capture_output=True, cwd=cwd or tree, env=dict(os.environ, **GIT_ENV))
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {r.stderr.decode(errors='replace')[-800:]}")
    return r.stdout


def user_git(repo, *args, check=True):
    """git in the USER's checkout (trusted repo), with the same hardening; bytes out."""
    r = subprocess.run(["git", *SAFE_GIT, "-C", repo, *args], capture_output=True, env=dict(os.environ, **GIT_ENV))
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {r.stderr.decode(errors='replace')[-800:]}")
    return r.stdout


def zsplit(b):
    return [x.decode("utf-8", "surrogateescape") for x in b.split(b"\0") if x]


def min_env(**extra):
    env = {k: os.environ[k] for k in MIN_ENV_KEYS if k in os.environ}
    env.update(extra)
    return env


def under_base(path):
    return os.path.realpath(path).startswith(WT_BASE + os.sep)


def rmtree_tree(path):
    """Remove a throwaway tree and its private temp dir — only ever under WT_BASE."""
    for p in (path, path + ".tmp"):
        if os.path.lexists(p) and under_base(p):
            shutil.rmtree(p, ignore_errors=True)


def make_tree(repo, path, sha):
    """Standalone repo at `sha` with nothing else from the user's repo in it."""
    rmtree_tree(path)
    os.makedirs(path)
    subprocess.run(["git", "init", "-q", path], check=True, env=dict(os.environ, **GIT_ENV))
    git(path, "fetch", "-q", "--depth=1", "--no-tags", os.path.realpath(repo), sha)
    git(path, "checkout", "-q", "--detach", "FETCH_HEAD")
    return os.path.realpath(path)


def sweep(root):
    """Kill processes left behind by sandboxed code for this tree (setsid'd daemons escape the
    process-group kill): matched by the AUTO_SANDBOX_ROOT env marker or a cwd inside the tree."""
    me, killed = os.getpid(), []
    marker = f"AUTO_SANDBOX_ROOT={root}".encode()
    ps = subprocess.run(["ps", "-E", "-ww", "-U", str(os.getuid()), "-o", "pid=,command="], capture_output=True).stdout
    pids = {int(l.split()[0]) for l in ps.splitlines() if marker in l and l.split()[0].isdigit()}
    ls = subprocess.run(["lsof", "-a", "-d", "cwd", "-u", str(os.getuid()), "-Fpn"], capture_output=True).stdout
    pid = None
    for l in ls.decode(errors="replace").splitlines():
        if l.startswith("p"):
            pid = int(l[1:])
        elif l.startswith("n") and pid and (l[1:] == root or l[1:].startswith((root + os.sep, root + ".tmp"))):
            pids.add(pid)
    for p in pids - {me, os.getppid()}:
        try:
            os.kill(p, signal.SIGKILL)
            killed.append(p)
        except (ProcessLookupError, PermissionError):
            pass
    return killed


def sweep_until_quiet(root, quiet_rounds=3, gap=0.7, max_rounds=20):
    """Leftovers may fork late (or keep forking); sweep until several consecutive rounds find nothing."""
    killed, quiet = [], 0
    for _ in range(max_rounds):
        k = sweep(root)
        killed += k
        quiet = 0 if k else quiet + 1
        if quiet >= quiet_rounds:
            break
        time.sleep(gap)
    return killed


def meta_path(rid):
    return os.path.join(RUNS, rid, "meta.json")


def load(rid):
    with open(meta_path(rid)) as f:
        return json.load(f)


def save(m):
    tmp = meta_path(m["id"]) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(m, f, indent=2, ensure_ascii=False)
    os.replace(tmp, meta_path(m["id"]))


def guard_events(rid):
    out = []
    for path in (GUARD_LOG + ".1", GUARD_LOG):
        try:
            with open(path, errors="replace") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue   # one bad line must not hide later denials
                    if e.get("run") == rid:
                        out.append(e)
        except OSError:
            pass
    return out


def snapshot_patch(m):
    """Read diff.patch ONCE into a private copy; everything after uses the copy and its hash."""
    with open(os.path.join(RUNS, m["id"], "diff.patch"), "rb") as f:
        data = f.read()
    fd, copy = tempfile.mkstemp(prefix="auto-patch-", suffix=".patch")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return data, hashlib.sha256(data).hexdigest(), copy


def patch_paths(patch_file, cwd):
    """Paths the patch would touch, as git apply itself parses them (not a regex)."""
    if not os.path.getsize(patch_file):
        return [], []
    out = zsplit(subprocess.run(["git", *SAFE_GIT, "apply", "--numstat", "-z", patch_file], cwd=cwd,
                                capture_output=True, env=dict(os.environ, **GIT_ENV), check=True).stdout)
    paths, binary, i = [], [], 0
    while i < len(out):
        add, dele, path = (out[i].split("\t", 2) + ["", ""])[:3]
        if path == "" and i + 2 < len(out):          # rename/copy record: \0old\0new
            paths += [out[i + 1], out[i + 2]]
            i += 3
        else:
            paths.append(path)
            i += 1
        if add == "-" and dele == "-":
            binary.append(paths[-1])
    return sorted(set(paths)), binary


def flags_for(paths, binary):
    return {"protected_paths": [p for p in paths if PROTECTED_RE.search(p)],
            "sensitive_paths": [p for p in paths if SENSITIVE_RE.search(p)],
            "execution_surface": [p for p in paths if EXEC_SURFACE_RE.search(p)],
            "binary_files": binary}


# ---------------------------------------------------------------- capture & invoke

def capture(m, rnd):
    wt, run_dir = m["worktree"], os.path.join(RUNS, m["id"])
    try:
        git(wt, "add", "-A", "--", ".", *DIFF_EXCLUDES)
        patch = git(wt, "diff", "--cached", "--binary", "--full-index", "--no-renames", "--no-color", "--no-ext-diff",
                    "--no-textconv", m["base"])
        index_paths = sorted(set(zsplit(git(wt, "diff", "--cached", "--name-only", "-z", "--no-renames", m["base"]))))
        stat = git(wt, "diff", "--cached", "--stat", "--no-renames", m["base"]).decode(errors="replace").strip()
        tree = git(wt, "write-tree").decode().strip()
    finally:
        git(wt, "reset", "-q", check=False)
    for name in (f"diff-{rnd}.patch", "diff.patch"):
        with open(os.path.join(run_dir, name), "wb") as f:
            f.write(patch)
    pfile = os.path.join(run_dir, "diff.patch")
    paths, binary = patch_paths(pfile, wt)
    flags = flags_for(paths, binary)
    if paths != index_paths:   # the patch claims files the tree doesn't have (forged headers?)
        flags["PATCH_PATHS_MISMATCH"] = {"only_in_patch": sorted(set(paths) - set(index_paths)),
                                         "only_in_tree": sorted(set(index_paths) - set(paths))}
    ignored = [x[3:] for x in zsplit(git(wt, "status", "--porcelain=v1", "-z", "--ignored"))
               if x.startswith("!! ") and not CACHE_RE.search(x[3:])]
    if ignored:
        flags["ignored_untracked"] = ignored[:50]
    prev = next((r.get("tree") for r in reversed(m["rounds"][:-1]) if r.get("tree")), None)
    since = git(wt, "diff", "--stat", prev, tree).decode(errors="replace").strip() if prev else None
    return {"patch": pfile, "sha256": hashlib.sha256(patch).hexdigest(), "diffstat": stat or "(no changes)",
            "paths": paths, "tree": tree, "flags": flags, "changed_since_last_round": since}


def next_round(m):
    nums = [int(x) for x in re.findall(r"brief-(\d+)\.md", " ".join(os.listdir(os.path.join(RUNS, m["id"]))))]
    return max(nums + [len(m["rounds"])]) + 1


def invoke(m, brief_file, timeout, conversation=None):
    with open(brief_file) as f:
        brief = f.read()
    rnd = next_round(m)
    run_dir = os.path.join(RUNS, m["id"])
    with open(os.path.join(run_dir, f"brief-{rnd}.md"), "w") as f:
        f.write(brief)
    if rnd == 1:
        prompt = PREAMBLE + brief
    elif conversation:
        prompt = brief
    else:   # no conversation to continue: restate rules + original task, then the feedback
        with open(os.path.join(run_dir, "brief-1.md")) as f:
            prompt = PREAMBLE + f.read() + "\n\nFEEDBACK ON YOUR PREVIOUS ATTEMPT (already in the tree):\n" + brief
    env = min_env(AUTO_WORKER="1", AUTO_WORKER_ROOT=m["worktree"], AUTO_RUN_ID=m["id"],
                  AUTO_WORKER_GITDIR=os.path.join(m["worktree"], ".git"), AUTO_WORKER_VENV=m.get("venv") or "")
    cmd = ["agy", "-p", prompt, "--model", m["model"], "--dangerously-skip-permissions",
           "--output-format", "json", "--print-timeout", f"{timeout}s"]
    if conversation:
        cmd += ["--conversation", conversation]
    t0, status, out, err, code = time.time(), None, b"", b"", None
    p = subprocess.Popen(cmd, cwd=m["worktree"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout + 120)
        code = p.returncode
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as e:
        status = "timeout" if isinstance(e, subprocess.TimeoutExpired) else "interrupted"
    finally:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        if code is None:
            try:
                out, err = p.communicate(timeout=10)
            except Exception:
                pass
        swept = sweep_until_quiet(m["worktree"])
    out_s, err_s = out.decode(errors="replace"), err.decode(errors="replace")
    resp = {}
    for line in reversed(out_s.strip().splitlines()):
        try:
            resp = json.loads(line)
            break
        except ValueError:
            continue
    status = status or resp.get("status") or f"exit {code}"
    with open(os.path.join(run_dir, f"response-{rnd}.json"), "w") as f:
        json.dump({"exit": code, "status": status, "stderr": err_s[-4000:], "raw_tail": out_s[-2000:], **resp},
                  f, indent=2, ensure_ascii=False)
    if resp.get("conversation_id"):
        m["conversation"] = resp["conversation_id"]
    m["rounds"].append({"round": rnd, "status": status, "seconds": round(time.time() - t0, 1),
                        "usage": resp.get("usage") or {}, "denied_actions": resp.get("denied_actions") or [],
                        "swept_pids": swept})
    save(m)   # the round is on record even if capture fails below
    ev = guard_events(m["id"])
    m["guard"] = {"allowed": sum(e.get("decision") == "allow" for e in ev),
                  "denied": [f'{e.get("tool")}: {e.get("reason")}' for e in ev if e.get("decision") == "deny"]}
    summary = {"run": m["id"], "round": rnd, "status": status, "seconds": m["rounds"][-1]["seconds"],
               "gemini_tokens": m["rounds"][-1]["usage"], "worktree": m["worktree"]}
    try:
        cap = capture(m, rnd)
        m["rounds"][-1].update(tree=cap["tree"], sha256=cap["sha256"], paths=cap["paths"], flags=cap["flags"])
        summary.update(patch=cap["patch"], patch_sha256=cap["sha256"], diffstat=cap["diffstat"],
                       changed_since_last_round=cap["changed_since_last_round"],
                       REVIEW_FLAGS={k: v for k, v in cap["flags"].items() if v})
    except Exception as e:   # never lose the denials report because the patch was weird
        summary["REVIEW_FLAGS"] = {"CAPTURE_FAILED": f"{type(e).__name__}: {e}"}
    save(m)
    if swept:
        summary["REVIEW_FLAGS"]["leftover_processes_killed"] = swept
    summary["guard_denied"] = m["guard"]["denied"][-15:]
    summary["worker_report"] = (resp.get("response") or "")[-6000:]
    if status != "SUCCESS":
        summary["stderr_tail"] = err_s[-1500:]
    print(json.dumps(summary, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- commands

def cmd_run(a):
    repo = user_git(a.repo, "rev-parse", "--show-toplevel").decode().strip()
    base = user_git(repo, "rev-parse", "--verify", a.base + "^{commit}").decode().strip()
    slug = re.sub(r"[^a-z0-9-]+", "-", (a.name or "task").lower()).strip("-")[:40] or "task"
    rid = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + slug
    os.makedirs(WT_BASE, exist_ok=True)
    os.makedirs(os.path.join(RUNS, rid))
    wt = make_tree(repo, os.path.join(WT_BASE, rid), base)
    common = os.path.realpath(user_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip())
    venv = a.venv or next((v for v in (os.path.join(repo, "venv"), os.path.join(os.path.dirname(common), "venv"))
                           if os.path.isfile(os.path.join(v, "bin", "python"))), "")
    m = {"id": rid, "repo": repo, "base": base, "worktree": wt, "model": a.model, "venv": venv,
         "created": datetime.datetime.now().isoformat(timespec="seconds"), "rounds": [], "verified": []}
    save(m)
    invoke(m, a.brief, a.timeout)


def cmd_resume(a):
    m = load(a.run_id)
    if not os.path.isdir(m["worktree"]):
        sys.exit("worktree is gone; start a new run")
    invoke(m, a.brief, a.timeout, conversation=m.get("conversation"))


def sandboxed(m, root, argv):
    if not argv:
        sys.exit("no command given")
    if argv[0] in ("python", "python3", "pytest"):
        py = os.path.join(m["venv"], "bin", "python") if m.get("venv") else "python3"
        argv = [py] + (["-m", "pytest"] if argv[0] == "pytest" else []) + argv[1:]
    env = min_env(AUTO_WORKER_GITDIR=os.path.join(root, ".git"), AUTO_WORKER_VENV=m.get("venv") or "")
    try:
        return subprocess.run([SANDBOX, root] + argv, cwd=root, env=env).returncode
    finally:
        sweep_until_quiet(root)


def cmd_test(a):
    m = load(a.run_id)
    wt = m["worktree"]
    git(wt, "add", "-A", "--", ".", *DIFF_EXCLUDES)
    tree = git(wt, "write-tree").decode().strip()
    git(wt, "reset", "-q", check=False)
    if m["rounds"] and m["rounds"][-1].get("tree") and tree != m["rounds"][-1]["tree"]:
        sys.exit("REFUSED: the worker tree changed since capture (a leftover process?). Use `verify`.")
    print("NOTE: the worker tree may hold ignored files; the authoritative check is `verify --full`.", file=sys.stderr)
    sys.exit(sandboxed(m, wt, a.cmd))


def cmd_verify(a):
    """Apply the current diff.patch (one snapshot) to a fresh tree at --onto and run CMD there, sandboxed."""
    m = load(a.run_id)
    data, sha, copy = snapshot_patch(m)
    try:
        onto = user_git(m["repo"], "rev-parse", "--verify", a.onto + "^{commit}").decode().strip()
        vwt = make_tree(m["repo"], os.path.join(WT_BASE, m["id"] + "-verify"), onto)
        if data:
            r = subprocess.run(["git", *SAFE_GIT, f"--git-dir={vwt}/.git", f"--work-tree={vwt}", "apply", copy],
                               cwd=vwt, capture_output=True, env=dict(os.environ, **GIT_ENV))
            if r.returncode:
                sys.exit(f"patch does not apply onto {a.onto} ({onto[:10]}):\n{r.stderr.decode(errors='replace')}")
        rc = sandboxed(m, vwt, a.cmd)
    finally:
        os.unlink(copy)
    m.setdefault("verified", []).append({"sha256": sha, "onto": onto, "cmd": " ".join(a.cmd), "rc": rc,
                                         "full": a.full, "at": datetime.datetime.now().isoformat(timespec="seconds")})
    save(m)
    print(json.dumps({"verified_patch_sha256": sha, "onto": onto, "full": a.full, "rc": rc}), file=sys.stderr)
    sys.exit(rc)


def cmd_apply(a):
    m = load(a.run_id)
    data, sha, copy = snapshot_patch(m)
    try:
        if a.sha != sha:
            sys.exit(f"REFUSED: diff.patch is {sha}, not the reviewed {a.sha}. Review the current patch.")
        head = user_git(m["repo"], "rev-parse", "HEAD").decode().strip()
        ok = [v for v in m.get("verified", []) if v["sha256"] == sha and v["rc"] == 0 and v.get("full")]
        if not ok:
            sys.exit("REFUSED: no passing `verify --full` for this exact patch.")
        if not any(v["onto"] == head for v in ok):
            sys.exit(f"REFUSED: HEAD is {head[:10]} but the patch was verified onto "
                     f"{ok[-1]['onto'][:10]}. Re-run `verify --full` (it defaults to HEAD).")
        rnd = next((r for r in m["rounds"] if r.get("sha256") == sha), {})
        if (rnd.get("flags") or {}).get("PATCH_PATHS_MISMATCH"):
            sys.exit("REFUSED: patch paths differ from the worker tree (forged headers?). Reject this run.")
        paths, binary = patch_paths(copy, m["repo"])
        prot = [p for p in paths if PROTECTED_RE.search(p)]
        if prot and not a.allow_protected:
            sys.exit(f"REFUSED: protected paths {prot}. Only with --allow-protected after line-by-line review, "
                     "and tell the user.")
        if binary and not a.allow_binary:
            sys.exit(f"REFUSED: binary files {binary}. Only with --allow-binary if the brief asked for them.")
        dirty = zsplit(user_git(m["repo"], "status", "--porcelain=v1", "-z", "--", *paths)) if paths else []
        if dirty:
            sys.exit(f"REFUSED: the user's checkout has local changes in files the patch touches: {dirty}")
        user_git(m["repo"], "apply", "--check", copy)
        user_git(m["repo"], "apply", copy)   # working tree only: Claude stages and commits explicitly
    finally:
        os.unlink(copy)
    m["applied"] = {"sha256": sha, "onto": head, "at": datetime.datetime.now().isoformat(timespec="seconds")}
    save(m)
    print(f"applied {sha[:12]} onto {head[:10]} in {m['repo']} (unstaged; verified by: {ok[-1]['cmd']})")


def cmd_record(a):
    m = load(a.run_id)
    tok = {"input": 0, "output": 0, "cache_read": 0}
    for r in m["rounds"]:
        u = r.get("usage") or {}
        tok["input"] += u.get("input_tokens", 0)
        tok["output"] += u.get("output_tokens", 0)
        tok["cache_read"] += u.get("cache_read_tokens", 0)
    final = (m.get("applied") or {}).get("sha256") or (m["rounds"][-1].get("sha256") if m["rounds"] else None)
    entry = {"date": m["created"][:10], "run": m["id"], "repo": os.path.basename(m["repo"]),
             "level": a.level, "model": m["model"], "rounds": len(m["rounds"]),
             "statuses": [r["status"] for r in m["rounds"]],
             "seconds": round(sum(r["seconds"] for r in m["rounds"]), 1), "gemini_tokens": tok,
             "outcome": a.outcome, "defects": [d for d in (a.defects or "").split(",") if d],
             "guard_denials": len((m.get("guard") or {}).get("denied", [])),
             "verified": any(v["rc"] == 0 and v.get("full") and v["sha256"] == final for v in m.get("verified", [])),
             "applied": bool(m.get("applied")), "notes": a.notes or ""}
    with open(LEDGER, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    m["outcome"] = entry
    save(m)
    print(json.dumps(entry, ensure_ascii=False))


def cmd_clean(a):
    m = load(a.run_id)
    for wt in (m["worktree"], os.path.join(WT_BASE, m["id"] + "-verify")):
        sweep_until_quiet(os.path.realpath(wt) if os.path.exists(wt) else wt)
        rmtree_tree(wt)
    print(f"removed trees for {m['id']} (record kept in {os.path.join(RUNS, a.run_id)})")


def cmd_list(_a):
    for rid in sorted(os.listdir(RUNS)) if os.path.isdir(RUNS) else []:
        try:
            m = load(rid)
        except (OSError, ValueError):
            continue
        live = "live" if os.path.isdir(m["worktree"]) else "cleaned"
        print(f'{rid}  {m["model"]:24} rounds={len(m["rounds"])}  {live:7} {(m.get("outcome") or {}).get("outcome", "-")}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run")
    r.add_argument("--repo", required=True)
    r.add_argument("--brief", required=True)
    r.add_argument("--model", default="gemini-3.1-pro-high")
    r.add_argument("--base", default="HEAD")
    r.add_argument("--name")
    r.add_argument("--venv")
    r.add_argument("--timeout", type=int, default=1200)
    r.set_defaults(fn=cmd_run)
    r = sp.add_parser("resume")
    r.add_argument("run_id")
    r.add_argument("--brief", required=True)
    r.add_argument("--timeout", type=int, default=1200)
    r.set_defaults(fn=cmd_resume)
    r = sp.add_parser("test")
    r.add_argument("run_id")
    r.set_defaults(fn=cmd_test)
    r = sp.add_parser("verify")
    r.add_argument("run_id")
    r.add_argument("--onto", default="HEAD")
    r.add_argument("--full", action="store_true", help="this is the full-suite run that gates apply")
    r.set_defaults(fn=cmd_verify)
    r = sp.add_parser("apply")
    r.add_argument("run_id")
    r.add_argument("--sha", required=True)
    r.add_argument("--allow-protected", action="store_true")
    r.add_argument("--allow-binary", action="store_true")
    r.set_defaults(fn=cmd_apply)
    r = sp.add_parser("record")
    r.add_argument("run_id")
    r.add_argument("--level", required=True, choices=["L1", "L2", "L3"])
    r.add_argument("--outcome", required=True, choices=["accepted", "fixed", "rejected"])
    r.add_argument("--defects")
    r.add_argument("--notes")
    r.set_defaults(fn=cmd_record)
    r = sp.add_parser("clean")
    r.add_argument("run_id")
    r.set_defaults(fn=cmd_clean)
    sp.add_parser("list").set_defaults(fn=cmd_list)
    argv = sys.argv[1:]
    cmd = argv[argv.index("--") + 1:] if "--" in argv else []   # everything after -- is the command
    argv = argv[:argv.index("--")] if "--" in argv else argv
    a = ap.parse_args(argv)
    a.cmd = cmd
    a.fn(a)


if __name__ == "__main__":
    main()
