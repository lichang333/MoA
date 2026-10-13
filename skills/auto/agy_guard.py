#!/usr/bin/env python3
"""PreToolUse guard for Antigravity (agy) workers launched by Claude's /auto skill.

Registered globally in ~/.gemini/config/hooks.json, but INERT unless the agy process
was started with AUTO_WORKER=1: it then answers "ask", which agy treats as "use the
normal permission rules" (verified), so the user's own agy sessions are unaffected.

In worker mode the agent runs with --dangerously-skip-permissions (headless agy
auto-denies every shell command otherwise and aborts the run), so THIS is the only
gate. Policy:
  * default-deny: unknown tools, network tools, MCP, browser
  * file reads/writes only inside AUTO_WORKER_ROOT (plus agy's own artifact dir);
    no writes to control files (.git, .claude, .agents, AGENTS.md, ...), no secrets
  * shell: one simple command (no pipes/chaining/redirects), from an allowlist of
    read-only tools + test runners, path arguments confined to the worktree, and
    rewritten to run inside the macOS sandbox (run_sandboxed.sh: no network, writes
    only to the worktree + $TMPDIR)
  * any error in this script -> deny (and agy itself treats no/invalid output as deny)
Every worker-mode decision is appended to logs/guard.jsonl for review.
"""
import json
import os
import re
import shlex
import sys
import time
import unicodedata

SKILL_DIR = os.path.dirname(os.path.realpath(__file__))
LOG = os.path.join(SKILL_DIR, "logs", "guard.jsonl")
SANDBOX = os.path.join(SKILL_DIR, "run_sandboxed.sh")
HOME = os.path.realpath(os.path.expanduser("~"))
AGY_BUILTIN = os.path.join(HOME, ".gemini", "antigravity-cli", "builtin")
GEMINI_DIR = os.path.join(HOME, ".gemini")

READ_TOOLS = {"view_file", "list_dir", "grep_search", "find_by_name",
              "view_file_outline", "view_code_item", "codebase_search", "command_status"}
WRITE_TOOLS = {"write_to_file", "replace_file_content", "multi_replace_file_content"}

# Directory components and file names that a worker may never write at any depth.
# Compared case- and normalization-insensitively: APFS is
# case-insensitive, so ".GIT" IS ".git" (a rewritten .git pointer file would hijack every
# host-side git command run in the worktree).
PROTECTED_DIRS = {".git", ".claude", ".codex", ".agents", ".agent", "_agents", "_agent",
                  ".gemini", ".github", ".vscode", ".idea", "venv", ".venv", "node_modules"}
PROTECTED_NAMES = {"agents.md", "gemini.md", "claude.md", ".git", ".gitmodules", ".gitignore",
                   ".gitattributes", ".envrc", ".flaskenv", ".pre-commit-config.yaml",
                   "sitecustomize.py", "usercustomize.py"}
PROTECTED_SUFFIXES = (".pth",)
SECRET_RE = re.compile(r"(^|/)(\.env(\.(?!example$)[^/]+)?|id_[a-z0-9]+|[^/]+\.(pem|key|p12|db|sqlite3?)"
                       r"|login\.txt|[^/]+\.secret|\.netrc|\.git-credentials)$", re.I)

READONLY_CMDS = {"ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg", "find",
                 "tree", "pwd", "diff", "file", "stat", "sort", "uniq", "cut", "echo", "true",
                 "basename", "dirname", "realpath", "which", "nl", "comm"}
PATTERN_FIRST = {"grep", "egrep", "fgrep", "rg"}   # first positional is a pattern, not a path
GIT_SUBCMDS = {"status", "diff", "log", "show", "blame", "ls-files", "grep", "rev-parse", "shortlog"}
BAD_ARGS = {
    "find": {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"},
    "rg": {"--pre", "--pre-glob", "-z", "--search-zip"},
    "sort": {"-o", "--output", "--compress-program"},
    "tail": {"-f", "-F", "--follow"},
    "git": {"-c", "--exec-path", "--output", "--config-env", "--ext-diff", "--no-index", "-o",
            "--open-files-in-pager", "--textconv"},
    "diff": {"--to-file", "--from-file"},
    "tree": {"-o"},
    # Everything allowed runs sandboxed anyway; these are defence in depth.
    "node": {"--require", "-r", "--import", "--loader", "--experimental-loader", "--env-file",
             "--test-reporter-destination", "--eval", "-e", "--print", "-p", "--inspect", "--inspect-brk"},
}
PREFIX_BANNED = {"git": ("-O",)}   # git grep -O<pager>
PYTEST_BANNED = {"-p", "-c", "-o", "--rootdir", "--confcutdir", "--basetemp", "--override-ini",
                 "--config-file", "--import-mode"}
ALLOWED_HELP = ("allowed: read-only tools (ls cat head tail wc grep rg find diff sort ...), "
                "git status/diff/log/show/blame/ls-files/grep, "
                "python -m pytest|py_compile|unittest, node --test|--check, "
                "node node_modules/<pkg>/<script> (e.g. vitest, tsc) when the run provides node_modules. "
                "One simple command per call: no pipes, ;, &&, redirects, $(), env-var prefixes. "
                "Paths must stay inside the worktree. Use your file tools to edit.")


class Deny(Exception):
    pass


def real(p):
    return os.path.realpath(os.path.expanduser(p))


def within(path, root):
    path = real(path)
    return path == root or path.startswith(root + os.sep)


def norm(name):
    return unicodedata.normalize("NFC", name).casefold()


def rel_parts(path, root):
    return [norm(x) for x in os.path.relpath(real(path), root).split(os.sep)]


def check_read(path, ctx):
    p = real(path)
    if SECRET_RE.search(p):
        raise Deny(f"reading secret-looking file {path} is not allowed")
    if within(p, ctx["root"]) or (ctx.get("allow_agy_paths", True) and (
            within(p, AGY_BUILTIN) or (ctx["art"] and within(p, ctx["art"])))):
        return
    raise Deny(f"read outside the worktree: {path} (worktree is {ctx['root']})")


def check_write(path, ctx):
    p = real(path)
    if ctx["art"] and within(p, ctx["art"]):
        return
    if not within(p, ctx["root"]):
        raise Deny(f"write outside the worktree: {path} (worktree is {ctx['root']})")
    parts = rel_parts(p, ctx["root"])
    if (any(part in PROTECTED_DIRS for part in parts) or parts[-1] in PROTECTED_NAMES
            or parts[-1].endswith(PROTECTED_SUFFIXES)):
        raise Deny(f"{os.path.relpath(p, ctx['root'])} is a protected control file; do not modify it")
    if SECRET_RE.search(p):
        raise Deny(f"writing secret-looking file {path} is not allowed")
    if os.path.isfile(p) and os.stat(p).st_nlink > 1:
        raise Deny(f"{path} is a hard link; refusing to write through it")


PATH_KEY_RE = re.compile(r"path|file|dir|cwd|uri", re.I)


def path_values(args):
    """String arguments under path-like keys (TargetFile, AbsolutePath, SearchPath, Cwd, ...)."""
    out = []
    for k, v in (args or {}).items():
        if not PATH_KEY_RE.search(k) or k in ("CodeContent", "ReplacementContent", "ReplacementChunks"):
            continue
        for x in (v if isinstance(v, list) else [v]):
            if isinstance(x, str) and x:
                out.append(x[len("file://"):] if x.startswith("file://") else x)
    return out


def check_command(args, ctx):
    cl = args.get("CommandLine")
    cwd = args.get("Cwd") or ctx["root"]
    if not isinstance(cl, str) or not cl.strip():
        raise Deny("empty command")
    if not within(cwd, ctx["root"]):
        raise Deny(f"command cwd {cwd} is outside the worktree")
    cwd = real(cwd)
    # Detect unquoted shell operators; we never hand the original string to a shell.
    lex = shlex.shlex(cl, posix=True, punctuation_chars=";&|<>()")
    lex.whitespace_split = True
    try:
        toks = list(lex)
    except ValueError as e:
        raise Deny(f"could not parse command: {e}")
    if any(t and set(t) <= set(";&|<>()") for t in toks) or "\n" in cl:
        raise Deny("pipes, chaining, redirects and subshells are not allowed. " + ALLOWED_HELP)
    argv = shlex.split(cl)
    if any(t.startswith("$(") or "`" in t for t in argv):
        raise Deny("command substitution is not allowed")
    if "=" in argv[0]:
        raise Deny("env-var prefixes are not allowed. " + ALLOWED_HELP)

    venv = ctx["venv"]
    cmd0 = argv[0]
    name = os.path.basename(cmd0)
    if "/" in cmd0:   # explicit path: only the worktree venv's python/pytest
        if not (venv and real(os.path.join(cwd, cmd0)) in {real(os.path.join(venv, "bin", n)) for n in ("python", "python3", "pytest")}):
            raise Deny(f"running {cmd0} is not allowed. " + ALLOWED_HELP)
        name = "pytest" if name == "pytest" else "python"

    rest = argv[1:]
    if name in READONLY_CMDS:
        bad = BAD_ARGS.get(name, set())
        if any(a in bad or a.split("=", 1)[0] in bad for a in rest):
            raise Deny(f"that {name} option can write or execute; not allowed")
        final = [name] + rest
        pos = rest
    elif name == "git":
        if not rest or rest[0] not in GIT_SUBCMDS:
            raise Deny("only read-only git subcommands are allowed: " + ", ".join(sorted(GIT_SUBCMDS)))
        if any(a in BAD_ARGS["git"] or a.split("=", 1)[0] in BAD_ARGS["git"]
               or a.startswith(PREFIX_BANNED["git"]) for a in rest):
            raise Deny("that git option is not allowed")
        final, pos = ["git"] + rest, rest[1:]
    elif name in ("python", "python3", "pytest"):
        if name == "pytest":
            rest = ["-m", "pytest"] + rest
        if len(rest) < 2 or rest[0] != "-m" or rest[1] not in ("pytest", "py_compile", "unittest"):
            raise Deny("python may only run `-m pytest`, `-m py_compile` or `-m unittest`. " + ALLOWED_HELP)
        if rest[1] == "pytest":
            for a in rest[2:]:
                key = a.split("=", 1)[0]
                if key in PYTEST_BANNED or (a.startswith(("-p", "-c", "-o")) and not a.startswith("--")):
                    raise Deny("pytest plugin/rootdir/config overrides are not allowed")
        elif rest[1] == "unittest":
            # -p is a filename pattern, -c catches Ctrl-C. They are not pytest
            # plugin/config flags. Still check compact discovery directory args.
            for a in rest[2:]:
                if a.startswith(("-s", "-t")) and len(a) > 2 and not a.startswith("--"):
                    check_read(os.path.join(cwd, a[2:]), ctx)
        py = os.path.join(venv, "bin", "python") if venv else "python3"
        final, pos = [py] + rest, rest[2:]
    elif name == "node" and rest and not rest[0].startswith("-"):
        # A project tool from the run's read-only node_modules clone (vitest, tsc, ...). It
        # executes worktree code no more than `node --test` does, and runs sandboxed the same way.
        script = real(os.path.join(cwd, rest[0]))
        if not (within(script, ctx["root"]) and rel_parts(script, ctx["root"])[0] == "node_modules"
                and os.path.isfile(script)):
            raise Deny("node may only run `--test`, `--check` or a tool script under ./node_modules. " + ALLOWED_HELP)
        final, pos = ["node"] + rest, rest[1:]
    elif name == "node":
        if not rest or rest[0] not in ("--test", "--check"):
            raise Deny("node may only run `--test`, `--check` or a tool script under ./node_modules. " + ALLOWED_HELP)
        if any(a in BAD_ARGS["node"] or a.split("=", 1)[0] in BAD_ARGS["node"] for a in rest):
            raise Deny("that node option loads or runs extra code; not allowed")
        final, pos = ["node"] + rest, rest[1:]
    else:
        raise Deny(f"`{name}` is not on the worker allowlist. " + ALLOWED_HELP)

    # Path arguments: everything positional (and --opt=value values) must resolve inside the worktree.
    skip_pattern = name in PATTERN_FIRST and not any(a in ("-e", "--regexp", "-f", "--file") or a.startswith(("--regexp=", "--file=")) for a in rest)
    skip_next = False
    expanded = []
    for i, a in enumerate(pos):
        if skip_next:
            skip_next = False
            if name in PATTERN_FIRST and pos[i - 1] in ("-e", "--regexp"):
                expanded.append(a)
                continue
        if name in PATTERN_FIRST and a in ("-e", "--regexp"):
            skip_next = True
            expanded.append(a)
            continue
        if a.startswith("-"):
            val = a.split("=", 1)[1] if "=" in a else None
            if val and ("/" in val or val.startswith((".", "~"))):
                check_read(os.path.join(cwd, val), ctx)
            expanded.append(a)
            continue
        if skip_pattern:
            skip_pattern = False
            expanded.append(a)
            continue
        # Globs stay literal (we never hand the line to a shell); just keep them inside the worktree.
        check_read(os.path.join(cwd, os.path.expanduser(a)), ctx)
        expanded.append(a)
    final = final[:len(final) - len(pos)] + expanded
    return f"{shlex.quote(SANDBOX)} {shlex.quote(ctx['root'])} " + " ".join(shlex.quote(x) for x in final)


def decide(payload):
    tc = payload.get("toolCall") or {}
    name = tc.get("name") or ""
    args = tc.get("args") or {}
    root_env = os.environ.get("AUTO_WORKER_ROOT", "")
    if not root_env or not os.path.isdir(root_env):
        raise Deny("AUTO_WORKER_ROOT is not set to an existing directory")
    root = real(root_env)
    if root in (HOME, "/") or not within(root, root):
        raise Deny("refusing an unsafe AUTO_WORKER_ROOT")
    art = payload.get("artifactDirectoryPath") or ""
    art = real(art) if art and within(art, GEMINI_DIR) else ""
    venv = os.environ.get("AUTO_WORKER_VENV", "")
    ctx = {"root": root, "art": art, "venv": real(venv) if venv and os.path.isdir(venv) else ""}

    if name == "run_command":
        if args.get("IsDaemon") or args.get("RunPersistent"):
            raise Deny("daemon/persistent commands are not allowed; run it in the foreground")
        new = check_command(args, ctx)
        return {"decision": "allow", "overwrite": {"CommandLine": new}}
    if name in WRITE_TOOLS:
        paths = path_values(args)
        if not args.get("TargetFile"):
            raise Deny(f"{name} without an absolute target path")
        for p in paths:
            check_write(p, ctx)
        return {"decision": "allow"}
    if name == "manage_task":   # agy's own background-command control: inspect or stop only
        if str(args.get("Action", "")).lower() in ("status", "list", "terminate", "kill", "stop", "cancel"):
            return {"decision": "allow"}
        raise Deny("manage_task may only inspect or stop your own background commands")
    if name in READ_TOOLS:
        for p in path_values(args):
            check_read(p, ctx)
        return {"decision": "allow"}
    raise Deny(f"tool `{name}` is not available to /auto workers (no network, browser, MCP or "
               "unknown tools). Work only with the files in the worktree.")


def log(entry):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        if os.path.exists(LOG) and os.path.getsize(LOG) > 5_000_000:
            os.replace(LOG, LOG + ".1")
        with open(LOG, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main():
    if os.environ.get("AUTO_WORKER") != "1":
        print(json.dumps({"decision": "ask"}))
        return
    payload = {}
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        out = decide(payload)
    except Deny as e:
        out = {"decision": "deny", "reason": f"/auto guard: {e}"}
    except Exception as e:  # fail closed
        out = {"decision": "deny", "reason": f"/auto guard internal error ({type(e).__name__}); action denied"}
    tc = payload.get("toolCall") or {}
    a = {k: v for k, v in (tc.get("args") or {}).items()
         if k not in ("CodeContent", "ReplacementContent", "ReplacementChunks", "toolAction", "toolSummary")}
    log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": os.environ.get("AUTO_RUN_ID", ""),
         "conv": payload.get("conversationId"), "tool": tc.get("name"), "args": a,
         "decision": out["decision"], "reason": out.get("reason"),
         "rewritten": (out.get("overwrite") or {}).get("CommandLine")})
    print(json.dumps(out))


if __name__ == "__main__":
    main()
