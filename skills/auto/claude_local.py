#!/usr/bin/env python3
"""Native Claude Code subscription transport for /auto.

Only the trusted stdio broker supplies tools. Reuses agy_worker's isolated Git,
capture, sandbox verification and reviewed-SHA apply; no native-tool fallback.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import agy_worker as worker
import agy_guard as guard
from claude_broker import TOOL_NAMES

CONFIG = Path(__file__).resolve().parents[2] / "config/headless.json"
RUN_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,160}\Z")
PREAMBLE = """You are a bounded native Claude Code coding worker for /auto.
Use ONLY the auto_worker MCP tools. Builtin tools, network, other agents, skills,
installs and production operations are unavailable. Inspect existing work before
editing. Do not work around denied actions or change control/credential files.
run_tests executes only allowlisted test runners in a network-denied macOS sandbox.
Report changed files, exact checks and remaining problems, then stop.
TASK BRIEF:
"""


def policy():
    return json.loads(CONFIG.read_text())["claude_local_defaults"]


def now():
    return dt.datetime.now(dt.timezone.utc)


def timestamp(value):
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return result.astimezone(dt.timezone.utc)


def safe_env():
    # Keep official OAuth/keychain access, never caller API keys, provider or
    # Python/Git steering variables. Tools receive their own scrubbed environment.
    return worker.min_env(DISABLE_AUTOUPDATER="1", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
                          **worker.GIT_ENV)


def load(rid):
    if not RUN_ID.fullmatch(rid):
        raise ValueError("invalid run ID")
    m = worker.load(rid)
    if m["executor"] != "claude-local":
        raise ValueError("not a native Claude Code run")
    return m


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")
    path.chmod(0o600)


def setup_runtime(m):
    run_dir = Path(worker.RUNS) / m["id"]
    broker = run_dir / "broker.json"
    settings = run_dir / "claude-settings.json"
    mcp = run_dir / "mcp.json"
    write_json(broker, dict(root=m["worktree"], gitdir=os.path.join(m["worktree"], ".git"),
                           venv=m["venv"], run_id=m["id"]))
    write_json(settings, dict(autoMemoryEnabled=False, claudeMdExcludes=["**"],
                             forceLoginMethod="claudeai", disableAllHooks=True, enabledPlugins={}))
    write_json(mcp, {"mcpServers": {"auto_worker": {
        "type": "stdio", "command": sys.executable,
        "args": ["-I", str(Path(__file__).with_name("claude_broker.py").resolve()), str(broker)],
    }}})
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (broker, settings, mcp)}


def base_command(m):
    run_dir = Path(worker.RUNS) / m["id"]
    return [m["cli"], "--allowedTools", ",".join(TOOL_NAMES), "--restricted", "--tools", "", "--setting-sources", "",
            "--settings", str(run_dir / "claude-settings.json"), "--strict-mcp-config",
            "--mcp-config", str(run_dir / "mcp.json"), "--disable-slash-commands", "--no-chrome",
            "--permission-mode", "dontAsk"]


def preflight(m):
    if sys.platform != "darwin" or not Path(worker.SANDBOX).is_file() or not Path("/usr/bin/sandbox-exec").is_file():
        raise ValueError("native worker requires the existing macOS sandbox")
    version = subprocess.run([m["cli"], "--version"], env=safe_env(), cwd=m["worktree"],
                             capture_output=True, text=True, timeout=15, check=True).stdout.strip()
    help_text = subprocess.run([m["cli"], "--help"], env=safe_env(), cwd=m["worktree"],
                               capture_output=True, text=True, timeout=15, check=True).stdout
    for flag in ("--restricted", "--tools", "--setting-sources", "--strict-mcp-config",
                 "--permission-mode", "--disable-slash-commands", "--no-chrome"):
        if flag not in help_text:
            raise ValueError("installed Claude CLI lacks required flag: " + flag)
    result = subprocess.run(base_command(m) + ["auth", "status", "--json"], env=safe_env(),
                            cwd=m["worktree"], capture_output=True, text=True, timeout=30)
    try:
        auth = json.loads(result.stdout)
    except ValueError as e:
        raise ValueError("unable to verify subscription authentication") from e
    if (result.returncode or auth.get("loggedIn") is not True or auth.get("authMethod") != "claude.ai" or
            auth.get("apiProvider") != "firstParty" or auth.get("subscriptionType") not in ("pro", "max")):
        raise ValueError("Claude Pro/Max first-party subscription login required; API authentication refused")
    return {"cli_version": version, "auth_method": auth["authMethod"], "subscription": auth["subscriptionType"]}


def cmd_prepare(a):
    cfg = policy()
    model = a.model or cfg["model"]
    if model not in cfg["allowed_models"]:
        raise ValueError("model alias outside native subscription policy")
    brief = Path(a.brief).read_text()
    if not brief.strip():
        raise ValueError("empty brief")
    cli = shutil.which("claude")
    if not cli:
        raise ValueError("Claude Code CLI is not installed")
    repo = worker.user_git(a.repo, "rev-parse", "--show-toplevel").decode().strip()
    base = worker.user_git(repo, "rev-parse", "--verify", a.base + "^{commit}").decode().strip()
    paths = worker.zsplit(worker.user_git(repo, "ls-tree", "-r", "--name-only", "-z", base))
    # A shallow base still contains its Git blobs: don't import secret-named
    # tracked files that code could retrieve through Git objects inside a test.
    if any(guard.SECRET_RE.search(p) for p in paths):
        raise ValueError("base contains secret-looking tracked files; prepare a sanitized base")
    rid = now().strftime("%Y%m%d-%H%M%S-claude-local-") + uuid.uuid4().hex[:12]
    run_dir = Path(worker.RUNS) / rid
    run_dir.mkdir(parents=True, mode=0o700)
    Path(worker.WT_BASE).mkdir(parents=True, exist_ok=True)
    wt = worker.make_tree(repo, os.path.join(worker.WT_BASE, rid), base)
    m = dict(id=rid, repo=repo, base=base, worktree=wt, venv=os.path.realpath(a.venv) if a.venv else "",
             model=model, requested_model=model, observed_models=[], cli=os.path.realpath(cli),
             platform=a.platform, coordinator_model=a.coordinator_model, task_id=a.task_id,
             executor="claude-local", created=now().isoformat(), rounds=[], verified=[], state="prepared")
    (run_dir / "brief-1.md").write_text(brief)
    m["runtime_hashes"] = setup_runtime(m)
    worker.save(m)
    m["preflight"] = preflight(m)
    worker.save(m)
    print(json.dumps(dict(run=rid, model=model, **m["preflight"],
                         next="observe-funding, then run; preparation makes no model call")))


def cmd_funding(a):
    if not RUN_ID.fullmatch(a.run_id):
        raise ValueError("invalid run ID")
    with worker.run_lock(a.run_id):
        m = load(a.run_id)
        observed, expires = timestamp(a.observed_at), timestamp(a.expires_at)
        if not 0 < a.remaining <= 100 or observed > now() or expires <= now() or observed >= expires:
            raise ValueError("invalid allowance observation")
        previous = (m.get("funding") or {}).get("observed_at")
        if previous and observed <= timestamp(previous):
            raise ValueError("a newer observation is required")
        m["funding"] = dict(source="subscription", remaining=a.remaining, unit="percent", extra_usage_enabled=False,
                            observed_at=observed.isoformat(), expires_at=expires.isoformat(), evidence=a.evidence)
        worker.save(m)
        print(json.dumps(m["funding"]))


def funding_ready(m):
    f = m.get("funding") or {}
    if f.get("extra_usage_enabled") is not False or not 0 < f.get("remaining", 0) <= 100:
        raise ValueError("observe included allowance and disabled extra usage before invoking a model")
    age = (now() - timestamp(f["observed_at"])).total_seconds()
    if (not 0 <= age <= policy()["funding_max_age_minutes"] * 60 or
            timestamp(f["expires_at"]) <= now() or f.get("used_for_submission")):
        raise ValueError("fresh unused subscription observation required")


def check_init(event, expected_session, expected_cwd=None):
    if event.get("session_id") != expected_session:
        raise ValueError("unexpected initialization session")
    names = event.get("tools")
    if (not isinstance(names, list) or any(not isinstance(n, str) for n in names) or
            not set(TOOL_NAMES).issubset(names) or
            set(names) - set(TOOL_NAMES) - {"EndConversation"}):
        raise ValueError("unexpected or missing tools in CLI initialization")
    servers = event.get("mcp_servers")
    if servers != [{"name": "auto_worker", "status": "connected"}]:
        raise ValueError("expected only the connected auto_worker MCP server")
    if event.get("plugins") != [] or event.get("plugin_errors") or event.get("mcp_server_errors"):
        raise ValueError("unexpected plugins or initialization errors")
    if expected_cwd and (not isinstance(event.get("cwd"), str) or
                         os.path.realpath(event["cwd"]) != os.path.realpath(expected_cwd)):
        raise ValueError("unexpected initialization workspace")


def watch_process(proc, stream_path, sid, cwd, timeout):
    """Tail a regular file: no blocked stdin/stdout pipes or reader threads."""
    deadline = time.monotonic() + timeout
    pending = b""
    total = 0
    with stream_path.open("rb") as stream:
        while True:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(proc.args, timeout)
            chunk = stream.read(65536)
            total += len(chunk)
            pending += chunk
            if total > 100_000_000 or len(pending) > 4_000_000:
                raise ValueError("CLI output exceeded capture limit")
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                try:
                    event = json.loads(line)
                    if isinstance(event, dict) and event.get("type") == "system" and event.get("subtype") == "init":
                        check_init(event, sid, cwd)
                except (ValueError, TypeError) as e:
                    raise ValueError("initialization/output validation failed: " + str(e)) from e
            if chunk:
                continue
            if proc.poll() is not None:
                return proc.returncode
            try:
                proc.wait(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                pass


def parse_output(output, expected_session, code, expected_cwd=None):
    events = []
    for line in output.splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                events.append(item)
        except ValueError:
            pass
    finals = [e for e in events if e.get("type") == "result"]
    inits = [e for e in events if e.get("type") == "system" and e.get("subtype") == "init"]
    try:
        if len(inits) != 1:
            raise ValueError("missing or ambiguous CLI initialization")
        check_init(inits[0], expected_session, expected_cwd)
    except ValueError as e:
        return "ERROR", {}, [], str(e)
    if len(finals) != 1:
        return "ERROR", {}, [], "Missing or ambiguous structured result"
    result = finals[0]
    if result.get("session_id") != expected_session:
        return "ERROR", result, [], "Unexpected session ID; result retained without resuming"
    models = sorted({e["model"] for e in events if e.get("type") == "system" and isinstance(e.get("model"), str)})
    for e in events:
        if e.get("type") == "assistant" and isinstance(e.get("message"), dict):
            model = e["message"].get("model")
            if isinstance(model, str) and model not in models:
                models.append(model)
    report = result.get("result") if isinstance(result.get("result"), str) else json.dumps(result.get("errors", []))
    success = code == 0 and result.get("subtype") == "success" and result.get("is_error") is False
    return "SUCCESS" if success else "ERROR", result, sorted(models), report


def cmd_invoke(a):
    if not 1 <= a.timeout <= 3600:
        raise ValueError("timeout must be between 1 and 3600 seconds")
    m = load(a.run_id)
    with worker.run_lock(m["id"]):
        m = load(a.run_id)
        resume = a.command == "resume"
        if bool(m["rounds"]) != resume:
            raise ValueError("use run for a prepared task or resume for an existing attempt")
        if m.get("applied") or not os.path.isdir(m["worktree"]):
            raise ValueError("cannot continue an applied or cleaned run")
        if m.get("state") == "running":
            raise ValueError("previous invocation was interrupted without finalization; inspect retained work")
        for path, digest in m["runtime_hashes"].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
                raise ValueError("trusted runtime configuration changed")
        preflight(m)
        run_dir = Path(worker.RUNS) / m["id"]
        original = (run_dir / "brief-1.md").read_text()
        brief = Path(a.brief).read_text() if resume else original
        if not brief.strip():
            raise ValueError("empty feedback")
        # Fresh CLI session per round: explicitly re-read the retained worktree.
        # No ambiguous replay of a failed CLI session or automatic quota fallback.
        sid = str(uuid.uuid4())
        command = base_command(m) + ["--model", m["requested_model"], "--session-id", sid,
                    "--no-session-persistence", "--print", "--verbose", "--output-format", "stream-json"]
        if a.dry_run:
            print(json.dumps(dict(command=command, cwd=m["worktree"], model=m["requested_model"],
                                  funding_observed=bool(m.get("funding")), model_called=False)))
            return
        funding_ready(m)
        rnd = len(m["rounds"]) + 1
        if resume:
            (run_dir / f"brief-{rnd}.md").write_text(brief)
        prompt = PREAMBLE + original + ("\n\nREVIEW FEEDBACK (retain completed work):\n" + brief if resume else "")
        m["funding"]["used_for_submission"] = True
        m["state"] = "running"
        m["rounds"].append(dict(round=rnd, session_id=sid, status="STARTING", seconds=0, usage={}))
        worker.save(m)  # launch provenance survives even a killed coordinator
        started = time.monotonic()
        code, status, result, models, report, error = None, "ERROR", {}, [], "", ""
        try:
            stream_path = run_dir / f"stream-{rnd}.jsonl"
            with tempfile.TemporaryFile() as prompt_file, stream_path.open("wb") as out, (run_dir / f"stderr-{rnd}.txt").open("wb") as err:
                prompt_file.write(prompt.encode()); prompt_file.seek(0)
                proc = subprocess.Popen(command, stdin=prompt_file, stdout=out, stderr=err,
                                        cwd=m["worktree"], env=safe_env(), start_new_session=True)
                try:
                    code = watch_process(proc, stream_path, sid, m["worktree"], a.timeout)
                except subprocess.TimeoutExpired:
                    error = "timeout"
                except KeyboardInterrupt:
                    error = "interrupted"
                finally:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait(timeout=10)
            output = (run_dir / f"stream-{rnd}.jsonl").read_text(errors="replace")
            status, result, models, report = parse_output(output, sid, code, m["worktree"])
        except Exception as e:
            error = type(e).__name__ + ": " + str(e)
        finally:
            swept = worker.sweep_until_quiet(m["worktree"])
        if error:
            status = error if error in ("timeout", "interrupted") else "ERROR"
        m["rounds"][-1].update(status=status, seconds=round(time.monotonic() - started, 1),
                              usage=result.get("usage") or {}, observed_models=models, exit=code,
                              error=error, swept_pids=swept)
        m["observed_models"] = sorted(set(m["observed_models"] + models))
        events = worker.guard_events(m["id"])
        m["guard"] = {"allowed": sum(e.get("decision") == "allow" for e in events),
                      "denied": [f"{e.get('tool')}: {e.get('reason')}" for e in events if e.get("decision") == "deny"]}
        m["state"] = "finished"
        worker.save(m)
        cap = worker.capture(m, rnd)
        m["rounds"][-1].update({k: cap[k] for k in ("tree", "sha256", "paths", "flags")})
        worker.save(m)
        print(json.dumps(dict(run=m["id"], executor="claude-local", requested_model=m["requested_model"],
                              observed_models=models, status=status, error=error, report=report[-6000:],
                              patch_sha256=cap["sha256"], diffstat=cap["diffstat"], flags=cap["flags"],
                              guard_denied=m["guard"]["denied"], swept_pids=swept), ensure_ascii=False, indent=2))
        if status != "SUCCESS":
            raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--repo", required=True); p.add_argument("--brief", required=True)
    p.add_argument("--base", default="HEAD"); p.add_argument("--model")
    p.add_argument("--venv", default=""); p.add_argument("--platform", choices=("codex", "claude", "headless"), default="codex")
    p.add_argument("--coordinator-model", default="current"); p.add_argument("--task-id")
    p.set_defaults(fn=cmd_prepare)
    p = sub.add_parser("observe-funding")
    p.add_argument("run_id"); p.add_argument("--remaining", type=float, required=True)
    p.add_argument("--observed-at", required=True); p.add_argument("--expires-at", required=True)
    p.add_argument("--extra-usage-off", action="store_true", required=True)
    p.add_argument("--evidence", choices=("account-panel", "user-statement"), required=True)
    p.set_defaults(fn=cmd_funding)
    for name in ("run", "resume"):
        p = sub.add_parser(name); p.add_argument("run_id")
        if name == "resume": p.add_argument("--brief", required=True)
        p.add_argument("--timeout", type=int, default=1200); p.add_argument("--dry-run", action="store_true")
        p.set_defaults(fn=cmd_invoke)
    args = parser.parse_args()
    try:
        args.fn(args)
    except (ValueError, OSError, subprocess.SubprocessError) as e:
        parser.exit(2, str(e) + "\n")


if __name__ == "__main__":
    main()
