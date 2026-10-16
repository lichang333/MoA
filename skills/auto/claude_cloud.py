#!/usr/bin/env python3
"""Claude cloud transport for /auto; local review/verify/apply stays in agy_worker.

No private quota API, credential scraping, API fallback, cloud polling or automatic
merge. Funding is a recent manual observation, not a live meter or spending cap.
New sessions use the interactive official CLI. Attach its displayed session ID;
an ambiguous launch is never retried automatically. Import already-fetched Git
results without checking cloud code out or running it in the user's worktree.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

# Resolve shared runtime even when this file is invoked through an installed link.
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import agy_worker as worker

CONFIG = Path(__file__).resolve().parents[2] / "config/headless.json"
SESSION = re.compile(r"(?:session|cse)_[A-Za-z0-9]+\Z")
RUN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,160}\Z")
CLOUD_RULES = """This is a bounded Claude cloud task, not a local agy worker.
Read CLAUDE.md and the task brief. Do not call paid external model APIs, install
skills, access credentials, deploy, or operate production systems. Do not edit
agent control files, hooks or security settings. No extra subagents unless the
brief requests them. Do not merge or push the base branch. If implementation is
requested, use a separate branch and report its commit and exact checks; push
that task branch only if the brief authorizes it. Cloud checks do not replace
the coordinator's local sandbox verification. Finish and stop when the bounded
brief is complete; do not start follow-on tasks.

TASK BRIEF:
"""


def now():
    return dt.datetime.now(dt.timezone.utc)


def timestamp(value):
    value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return value.astimezone(dt.timezone.utc)


def policy():
    return json.loads(CONFIG.read_text())["cloud_defaults"]


def safe_env():
    # Drop API keys, provider overrides and all Git steering variables. Keep the
    # user's HOME for official Claude OAuth/keychain and GitHub SSH authentication.
    return worker.min_env(DISABLE_AUTOUPDATER="1", **worker.GIT_ENV)


def git(repo, *args, attrs=False):
    return subprocess.run(
        ["git", *worker.SAFE_GIT, *(worker.ATTR_OFF if attrs else []),
         "-C", str(repo), *args], env=safe_env(), check=True,
        capture_output=True).stdout


def commit(repo, ref):
    if not ref or ref.startswith("-") or any(c.isspace() for c in ref):
        raise ValueError("invalid Git ref")
    return git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode().strip()


def session_id(value):
    if value.startswith("https://claude.ai/"):
        match = re.fullmatch(r"https://claude\.ai/(?:code|epitaxy)/((?:session|cse)_[A-Za-z0-9]+)/?(?:\?[^#]*)?", value)
        value = match[1] if match else ""
    if not SESSION.fullmatch(value):
        raise ValueError("expected a Claude cloud session ID or claude.ai session URL")
    return value


def load(rid):
    if not RUN.fullmatch(rid):
        raise ValueError("invalid run ID")
    m = worker.load(rid)
    if m["executor"] != "claude-cloud":
        raise ValueError("not a Claude cloud run")
    return m


run_lock = worker.run_lock


def emit(m):
    print(json.dumps(m, indent=2, ensure_ascii=False))


def cmd_prepare(a):
    cfg = policy()
    model = a.model or cfg["model"]
    if model not in cfg["allowed_models"]:
        raise ValueError("model is not in the subscription-compatible cloud allowlist")
    repo = git(a.repo, "rev-parse", "--show-toplevel").decode().strip()
    base = commit(repo, a.base)
    branch = git(repo, "branch", "--show-current").decode().strip()
    if not branch:
        raise ValueError("prepare from a named branch; detached HEAD is not supported")
    origin = git(repo, "remote", "get-url", "origin").decode().strip()
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?", origin)
    if not match:
        raise ValueError("origin must be a credential-free github.com URL")
    remote = "https://github.com/" + match[1] + ".git"
    brief = Path(a.brief).read_text()
    if not brief.strip():
        raise ValueError("empty task brief")
    rid = now().strftime("%Y%m%d-%H%M%S-cloud-") + uuid.uuid4().hex[:12]
    run_dir = Path(worker.RUNS) / rid
    run_dir.mkdir(parents=True, mode=0o700)
    prompt = (CLOUD_RULES + f"Expected starting commit: {base}. Before working, compare git HEAD; "
              "if it differs, stop and report the mismatch.\n\n" + brief)
    (run_dir / "brief-1.md").write_text(brief)
    (run_dir / "prompt.txt").write_text(prompt)
    m = dict(id=rid, repo=repo, base=base, branch=branch, origin=remote,
             worktree=os.path.join(worker.WT_BASE, rid), venv="", model="unknown", requested_model=model,
             platform=a.platform, coordinator_model=a.coordinator_model,
             task_id=a.task_id, executor="claude-cloud", created=now().isoformat(),
             brief_sha256=hashlib.sha256(brief.encode()).hexdigest(),
             prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
             rounds=[], verified=[], submissions=[], state="prepared",
             remote_status="unknown", usage=None, cost_usd=None)
    worker.save(m)
    emit(dict(run=rid, base=base, repository=match[1], branch=branch, model=model,
              state="prepared", next="observe-funding, then launch; or attach an existing session"))


def cmd_funding(a):
    m = load(a.run_id)
    observed, expires = timestamp(a.observed_at), timestamp(a.expires_at)
    if not 0 < a.remaining or not a.remaining < float("inf"):
        raise ValueError("remaining allowance must be positive and finite")
    if a.source == "subscription" and a.remaining > 100:
        raise ValueError("subscription remaining must be a percentage <= 100")
    if observed > now() or expires <= now() or observed >= expires:
        raise ValueError("funding observation/expiry is invalid or expired")
    previous = m.get("last_funding_observed_at") or (m.get("funding") or {}).get("observed_at")
    if previous and observed <= timestamp(previous):
        raise ValueError("a strictly newer account observation is required; old observations cannot be replayed")
    observed_model = getattr(a, "session_model", None)
    if observed_model is not None and observed_model not in policy()["allowed_models"]:
        raise ValueError("observed session model is outside the permitted cloud models")
    if observed_model and not m.get("session_id"):
        raise ValueError("attach the observed session before recording its model")
    m["funding"] = dict(source=a.source, remaining=a.remaining,
                        unit="USD" if a.source == "cloud-credit" else "percent",
                        observed_at=observed.isoformat(), expires_at=expires.isoformat(),
                        extra_usage_enabled=False, evidence="manual-account-panel",
                        session_model=observed_model)
    if observed_model:
        m["model"] = observed_model
    m["last_funding_observed_at"] = observed.isoformat()
    worker.save(m)
    emit(m["funding"])


def funding_ready(m):
    f = m.get("funding") or {}
    if (f.get("source") not in ("cloud-credit", "subscription") or
            f.get("extra_usage_enabled") is not False or not f.get("remaining", 0) > 0):
        raise ValueError("fresh funding observation required; no paid API fallback")
    observed = timestamp(f["observed_at"])
    age = (now() - observed).total_seconds()
    if age < 0 or age > policy()["funding_max_age_minutes"] * 60 or timestamp(f["expires_at"]) <= now():
        raise ValueError("funding observation is stale or expired; refresh from the account panel")
    if f.get("used_for_submission"):
        raise ValueError("funding observation already used; check allowance before another submission")


def auth_ready():
    result = subprocess.run(["claude", "auth", "status", "--json"], env=safe_env(),
                            capture_output=True, text=True, timeout=30)
    try:
        auth = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("unable to verify Claude CLI subscription login; check claude auth status") from error
    if (result.returncode or auth.get("loggedIn") is not True or auth.get("authMethod") != "claude.ai" or
            auth.get("apiProvider") != "firstParty" or auth.get("subscriptionType") not in ("pro", "max")):
        raise ValueError("Claude Pro/Max subscription login required (claude auth login); API authentication is refused")


def cmd_launch(a):
    m = load(a.run_id)
    if m["state"] != "prepared" or m.get("session_id"):
        raise ValueError("launch already attempted/attached; inspect the cloud UI and attach, never blindly retry")
    funding_ready(m)
    prompt = (Path(worker.RUNS) / m["id"] / "prompt.txt").read_text()
    if hashlib.sha256(prompt.encode()).hexdigest() != m["prompt_sha256"]:
        raise ValueError("saved prompt changed; prepare a new run")
    cmd = ["claude", "--safe-mode", "--model", m["requested_model"], "--cloud", prompt]
    if a.dry_run:
        emit(dict(command=cmd, cwd=m["worktree"], base=m["base"], origin=m["origin"],
                  warning="interactive launch; attach the displayed cloud session ID afterward"))
        return
    auth_ready()
    # Branch-match preflight: GitHub may advance again before cloud cloning, so
    # the brief also requires checking the expected base. If Claude falls back to
    # a bundle, the isolated launch tree contains only that committed snapshot.
    out = git(m["repo"], "ls-remote", "--exit-code", m["origin"], "refs/heads/" + m["branch"]).decode().split()
    if not out or out[0] != m["base"]:
        raise ValueError("remote branch does not match recorded base; push/reprepare before launching")
    os.makedirs(worker.WT_BASE, exist_ok=True)
    worker.make_tree(m["repo"], m["worktree"], m["base"])
    git(m["worktree"], "checkout", "-q", "-B", m["branch"], m["base"])
    git(m["worktree"], "remote", "add", "origin", m["origin"])
    m["state"] = "launch_attempted"
    m["funding"]["used_for_submission"] = now().isoformat()
    worker.save(m)  # persist before the side effect, including interrupted/ambiguous outcomes
    try:
        rc = subprocess.run(cmd, cwd=m["worktree"], env=safe_env()).returncode
    except (OSError, KeyboardInterrupt):
        raise ValueError("launch outcome unknown; check Claude cloud UI and attach the session; do not retry")
    m["launch_exit_code"] = rc
    worker.save(m)
    emit(dict(run=m["id"], state=m["state"], exit_code=rc,
              next="attach the cloud session ID from the CLI or UI; exit code is not task completion"))
    if rc:
        raise SystemExit(rc)


def cmd_attach(a):
    m, sid = load(a.run_id), session_id(a.session)
    if m.get("session_id") and m["session_id"] != sid:
        raise ValueError("run is already bound to a different cloud session")
    if not m.get("session_id"):
        previous = (m.get("funding") or {}).get("observed_at")
        if previous and not m.get("last_funding_observed_at"):
            m["last_funding_observed_at"] = previous
        m.pop("funding", None)
        m["model"] = "unknown"
    m.update(session_id=sid, session_url="https://claude.ai/code/" + sid)
    if m["state"] in ("prepared", "launch_attempted"):
        m["state"] = "attached"
    worker.save(m)
    emit(dict(run=m["id"], session_url=m["session_url"], remote_status="unknown"))


def cmd_send(a):
    m = load(a.run_id)
    if not m.get("session_id"):
        raise ValueError("attach a cloud session first")
    funding_ready(m)
    if (m.get("funding") or {}).get("session_model") not in policy()["allowed_models"]:
        raise ValueError("observe the actual cloud session model before sending; requested model is not evidence")
    brief = Path(a.brief).read_text()
    if not brief.strip():
        raise ValueError("empty follow-up")
    auth_ready()
    n = len(m["submissions"]) + 1
    (Path(worker.RUNS) / m["id"] / f"followup-{n}.md").write_text(brief)
    submission = dict(at=now().isoformat(), brief_sha256=hashlib.sha256(brief.encode()).hexdigest(),
                      state="outcome-unknown")
    m["submissions"].append(submission)
    m["funding"]["used_for_submission"] = submission["at"]
    worker.save(m)
    try:
        r = subprocess.run(["claude", "--safe-mode", "-p", "--cloud", m["session_id"],
                            "--output-format", "json"], input=CLOUD_RULES + brief,
                           env=safe_env(), text=True, capture_output=True, timeout=60,
                           cwd=m["repo"])
        response = json.loads(r.stdout)
        # Do not trust response metadata, arbitrary URLs or raw stderr as our own records.
        if r.returncode or response.get("ok") is not True or response.get("session_id") != m["session_id"]:
            raise ValueError("cloud message outcome unconfirmed; inspect the session before retrying")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyboardInterrupt) as error:
        raise ValueError("cloud message outcome unknown; inspect the session before retrying") from error
    submission["state"] = "submitted"
    worker.save(m)
    emit(dict(run=m["id"], state="submitted", remote_status="unknown", session_url=m["session_url"]))


def cmd_import(a):
    m = load(a.run_id)
    if not m.get("session_id"):
        raise ValueError("attach the source cloud session first")
    result = commit(m["repo"], a.ref)
    git(m["repo"], "merge-base", "--is-ancestor", m["base"], result)
    patch = git(m["repo"], "diff", "--binary", "--full-index", "--no-renames", "--no-color",
                "--no-ext-diff", "--no-textconv", m["base"], result, "--", attrs=True)
    expected = sorted(set(worker.zsplit(git(m["repo"], "diff", "--name-only", "-z", "--no-renames",
                                          m["base"], result, "--", attrs=True))))
    run_dir = Path(worker.RUNS) / m["id"]
    fd, temporary = tempfile.mkstemp(prefix="import-", suffix=".patch", dir=run_dir)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(patch)
        paths, binary = worker.patch_paths(temporary, m["repo"])
        if paths != expected:
            raise ValueError("patch paths mismatch; import refused")
        flags = worker.flags_for(paths, binary)
        # Keep cloud control-file edits out of local execution, even before verify.
        if flags["protected_paths"]:
            raise ValueError("cloud result changes protected paths: " + repr(flags["protected_paths"]))
        raw = git(m["repo"], "diff", "--raw", "-z", "--no-renames", m["base"], result, "--", attrs=True)
        entries = worker.zsplit(raw)
        for header in entries[::2]:
            if any(mode in ("120000", "160000") for mode in header.lstrip(":").split()[:2]):
                raise ValueError("cloud result changes symlinks or submodules; import refused")
        sha = hashlib.sha256(patch).hexdigest()
        rnd = len(m["rounds"]) + 1
        # Validation completed: publish immutable round artifact, then current patch.
        (run_dir / f"diff-{rnd}.patch").write_bytes(patch)
        os.replace(temporary, run_dir / "diff.patch")
        m["rounds"].append(dict(round=rnd, status="imported", seconds=0, sha256=sha,
                                paths=paths, flags=flags, result_commit=result,
                                source_ref=a.ref, usage=None))
        m["verified"] = []
        m.pop("applied", None)
        m.update(state="imported", result_commit=result)
        worker.save(m)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    emit(dict(run=m["id"], executor="claude-cloud", base=m["base"], result_commit=result,
              patch=str(run_dir / "diff.patch"), patch_sha256=sha,
              REVIEW_FLAGS={k: v for k, v in flags.items() if v},
              next="review the entire patch, then agy_worker.py verify --full and apply --sha"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sp = p.add_subparsers(dest="command", required=True)
    r = sp.add_parser("prepare", help="save a brief and immutable base; no model call")
    r.add_argument("--repo", required=True)
    r.add_argument("--brief", required=True)
    r.add_argument("--base", default="HEAD")
    r.add_argument("--model")
    r.add_argument("--platform", choices=("codex", "claude", "gemini", "agy", "headless"), default="codex")
    r.add_argument("--coordinator-model", default="current")
    r.add_argument("--task-id")
    r.set_defaults(fn=cmd_prepare)
    r = sp.add_parser("observe-funding", help="record actual panel data; not a quota fetch or spending cap")
    r.add_argument("run_id")
    r.add_argument("--source", choices=("cloud-credit", "subscription"), required=True)
    r.add_argument("--remaining", type=float, required=True, help="USD credit or percent subscription remaining")
    r.add_argument("--observed-at", required=True)
    r.add_argument("--expires-at", required=True, help="credit expiry or earliest subscription quota reset")
    r.add_argument("--extra-usage", choices=("off",), required=True, help="must have checked the actual account switch")
    r.add_argument("--session-model", help="actual attached session model family from its UI; required before send")
    r.set_defaults(fn=cmd_funding)
    r = sp.add_parser("launch", help="interactive official CLI; never automatically retry")
    r.add_argument("run_id")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=cmd_launch)
    r = sp.add_parser("attach", help="record an existing cloud session without calling a model")
    r.add_argument("run_id")
    r.add_argument("--session", required=True)
    r.set_defaults(fn=cmd_attach)
    r = sp.add_parser("send", help="submit one follow-up; this does not wait for completion")
    r.add_argument("run_id")
    r.add_argument("--brief", required=True)
    r.set_defaults(fn=cmd_send)
    r = sp.add_parser("import-ref", help="import an already-fetched commit without checkout or code execution")
    r.add_argument("run_id")
    r.add_argument("--ref", required=True)
    r.set_defaults(fn=cmd_import)
    r = sp.add_parser("status", help="local record only; remote status and actual cost remain unknown")
    r.add_argument("run_id")
    r.set_defaults(fn=lambda a: emit(load(a.run_id)))
    a = p.parse_args()
    try:
        if a.command == "prepare":
            a.fn(a)
        else:
            with run_lock(a.run_id):
                a.fn(a)
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as error:
        # Never echo raw CLI auth output or Git URLs containing embedded secrets.
        message = str(error) if isinstance(error, ValueError) else type(error).__name__
        p.exit(1, "REFUSED: " + message + "\n")


if __name__ == "__main__":
    main()
