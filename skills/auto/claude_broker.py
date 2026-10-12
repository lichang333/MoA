#!/usr/bin/env python3
"""Trusted stdio MCP tools for claude-local. No native CLI tools are enabled.

The broker owns every file operation and test subprocess. It never imports a
project module; candidate code only runs through the existing macOS sandbox.
Launch with Python -I so workspace/PYTHONPATH customizations cannot run here.
"""
import json
import os
from pathlib import Path
import resource
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import agy_guard as guard
import agy_worker as worker

MAX_BYTES = 1_000_000
MAX_MESSAGE = 4_000_000
SERVER = "auto_worker"


def tool(name, description, properties, required):
    return dict(name=name, description=description, inputSchema=dict(
        type="object", properties=properties, required=required, additionalProperties=False))


STRING = {"type": "string"}
TOOLS = [
    tool("list_directory", "List one workspace directory; metadata/secrets excluded.", {"path": STRING}, ["path"]),
    tool("read_file", "Read UTF-8 text, at most 500 lines per call; offset is a zero-based line index.",
         {"path": STRING, "offset": {"type": "integer", "minimum": 0}}, ["path"]),
    tool("write_file", "Write a UTF-8 workspace file, at most 1 MB. No control files or secrets.",
         {"path": STRING, "content": STRING}, ["path", "content"]),
    tool("edit_file", "Replace exactly one occurrence of old_text. Read the current file first.",
         {"path": STRING, "old_text": STRING, "new_text": STRING}, ["path", "old_text", "new_text"]),
    tool("run_tests", "Run python -m pytest|unittest|py_compile or node --test|--check in the network-denied sandbox. No shell operators or installs.",
         {"command": STRING}, ["command"]),
]
TOOL_NAMES = ["mcp__" + SERVER + "__" + t["name"] for t in TOOLS]


class Broker:
    def __init__(self, config):
        if set(config) != {"root", "gitdir", "venv", "run_id"}:
            raise ValueError("invalid broker configuration")
        self.root = os.path.realpath(config["root"])
        if (not worker.under_base(self.root) or not os.path.isdir(self.root) or
                os.path.realpath(config["gitdir"]) != os.path.join(self.root, ".git")):
            raise ValueError("broker requires an isolated worker repository")
        self.config = config
        self.ctx = {"root": self.root, "art": "", "venv": config["venv"], "allow_agy_paths": False}

    def path(self, value, write=False):
        if not isinstance(value, str) or not value or "\0" in value:
            raise guard.Deny("invalid path")
        path = os.path.realpath(os.path.join(self.root, value))
        if not guard.within(path, self.root):
            raise guard.Deny("path outside worker repository")
        if any(p in guard.PROTECTED_DIRS for p in guard.rel_parts(path, self.root)):
            raise guard.Deny("metadata/dependency directories are unavailable to file tools")
        (guard.check_write if write else guard.check_read)(path, self.ctx)
        if os.path.isfile(path) and os.stat(path).st_nlink != 1:
            raise guard.Deny("hard links are unavailable")
        return Path(path)

    def read(self, path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
                raise guard.Deny("only regular text files up to 1 MB are supported")
            data = f.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES or b"\0" in data:
            raise guard.Deny("file too large or binary")
        return data.decode("utf-8")

    def write(self, path, content):
        data = content.encode("utf-8")
        if len(data) > MAX_BYTES or b"\0" in data:
            raise guard.Deny("content too large or binary")
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
        fd, temporary = tempfile.mkstemp(prefix=".auto-write-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return "File saved."

    def run_tests(self, command):
        argv = shlex.split(command)
        # File tools cover inspection. Do not expose git-object or arbitrary
        # recursive shell reads as a second route around file path policy.
        if not argv or argv[0] not in ("python", "python3", "pytest", "node"):
            raise guard.Deny("only sandboxed test/check runners are available")
        wrapped = guard.check_command({"CommandLine": command, "Cwd": self.root}, self.ctx)
        env = worker.min_env(AUTO_WORKER="1", AUTO_WORKER_GITDIR=self.config["gitdir"],
                             AUTO_WORKER_VENV=self.config["venv"])
        def limits():
            resource.setrlimit(resource.RLIMIT_FSIZE, (8_000_000, 8_000_000))
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            proc = subprocess.Popen(shlex.split(wrapped), cwd=self.root, env=env,
                                    stdout=out, stderr=err, start_new_session=True, preexec_fn=limits)
            try:
                code = proc.wait(timeout=180)
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=10)
                worker.sweep_until_quiet(self.root)
            out.seek(0); err.seek(0)
            return json.dumps(dict(exit=code, stdout=out.read(50_000).decode(errors="replace"),
                                   stderr=err.read(50_000).decode(errors="replace")))

    def call(self, name, args):
        schema = next((t["inputSchema"] for t in TOOLS if t["name"] == name), None)
        if schema is None or not isinstance(args, dict):
            raise guard.Deny("unknown tool or invalid arguments")
        if set(args) - set(schema["properties"]) or set(schema["required"]) - set(args):
            raise guard.Deny("unknown or missing fields")
        for key, value in args.items():
            expected = schema["properties"][key]["type"]
            if (expected == "string" and not isinstance(value, str)) or (
                    expected == "integer" and (type(value) is not int or value < 0)):
                raise guard.Deny("invalid field type")
        if name == "run_tests":
            return self.run_tests(args["command"])
        path = self.path(args["path"], write=name in ("write_file", "edit_file"))
        if name == "list_directory":
            rows = []
            for p in sorted(path.iterdir()):
                try:
                    checked = self.path(str(p))
                except guard.Deny:
                    continue
                rows.append(p.name + ("/" if checked.is_dir() else ""))
                if len(rows) >= 500:
                    rows.append("[truncated]"); break
            return "\n".join(rows)
        if name == "read_file":
            lines = self.read(path).splitlines(keepends=True)
            offset = args.get("offset", 0)
            return "".join(lines[offset:offset + 500])[:50_000]
        if name == "write_file":
            return self.write(path, args["content"])
        old = args["old_text"]
        text = self.read(path)
        if not old or text.count(old) != 1:
            raise guard.Deny("old_text must match exactly once")
        return self.write(path, text.replace(old, args["new_text"], 1))

    def handle(self, request):
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            raise ValueError("invalid JSON-RPC request")
        method, params = request.get("method"), request.get("params", {})
        if "id" not in request:
            return None  # notifications never perform file or command operations
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in ("2024-11-05", "2025-03-26", "2025-06-18") else "2025-06-18"
            result = dict(protocolVersion=version, capabilities={"tools": {}},
                          serverInfo={"name": SERVER, "version": "1.0.0"})
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name, args = params.get("name"), params.get("arguments", {})
            try:
                text = self.call(name, args)
                result = {"content": [{"type": "text", "text": text}]}
                decision, reason = "allow", None
            except Exception as e:
                reason = str(e) if isinstance(e, guard.Deny) else "operation failed: " + type(e).__name__
                result = {"isError": True, "content": [{"type": "text", "text": reason}]}
                decision = "deny"
            guard.log(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), run=self.config["run_id"],
                           executor="claude-local", tool=name, decision=decision, reason=reason))
        else:
            return {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32601, "message": "method unavailable"}}
        return {"jsonrpc": "2.0", "id": request["id"], "result": result}


def main():
    broker = Broker(json.loads(Path(sys.argv[1]).read_text()))
    while True:
        line = sys.stdin.buffer.readline(MAX_MESSAGE + 1)
        if not line:
            return
        if len(line) > MAX_MESSAGE:
            raise ValueError("request too large")
        request = None
        try:
            request = json.loads(line)
            response = broker.handle(request)
        except Exception:
            response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                        "error": {"code": -32600, "message": "invalid request"}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
