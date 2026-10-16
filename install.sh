#!/bin/bash
# Install platform-specific entry points with one shared implementation.
# Existing files and links are backed up outside the skill discovery directories.
set -euo pipefail
exec python3 - "$0" "$@" <<'PY'
import argparse
import copy
import datetime
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description="Install MoA skills for Codex, Claude, and Gemini (agy).")
    parser.add_argument("--platform", choices=("codex", "claude", "gemini", "all"), default="all",
                        help="which platform to install (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="preview changes without writing files or reading API keys")
    args = parser.parse_args(sys.argv[2:])
    repo = Path(sys.argv[1]).resolve().parent
    user_home = Path.home()
    destinations = {"codex": user_home / ".agents/skills",
                    "claude": user_home / ".claude/skills",
                    "gemini": user_home / ".gemini/config/skills"}
    platforms = tuple(destinations) if args.platform == "all" else (args.platform,)
    links = [(repo / "platforms" / platform / "skills" / skill,
              destinations[platform] / skill)
             for platform in platforms for skill in ("moa", "auto")]

    # Detach the old Claude -> Codex link before Codex gets its own entry point.
    # Only this recognized legacy chain is migrated when Claude was not selected.
    legacy_claude = destinations["claude"] / "moa"
    if args.platform == "codex" and legacy_claude.is_symlink():
        old_target = Path(os.path.abspath(legacy_claude.parent / os.readlink(legacy_claude)))
        if old_target == destinations["codex"] / "moa":
            links.insert(0, (repo / "platforms/claude/skills/moa", legacy_claude))
            print("migration: detach legacy Claude -> Codex shared skill link")

    # Complete the read-only preflight before making any changes. In particular,
    # never replace a malformed hook config or partially install around it.
    for target, _ in links:
        if not (target / "SKILL.md").is_file():
            raise ValueError(f"missing skill entry point: {target / 'SKILL.md'}")
    guard = repo / "skills/auto/agy_guard.py"
    if not guard.is_file():
        raise ValueError(f"missing worker guard: {guard}")
    hook_key = "claude-auto-worker-guard"
    template_path = repo / "hooks/agy-hooks.json"
    template = json.loads(template_path.read_text())
    if not isinstance(template, dict) or not isinstance(template.get(hook_key), dict):
        raise ValueError(f"invalid guard hook template: {template_path}")
    own_hook = copy.deepcopy(template[hook_key])
    guard_commands = [hook for event in own_hook.get("PreToolUse", [])
                      for hook in event.get("hooks", []) if hook.get("type") == "command"]
    if len(guard_commands) != 1:
        raise ValueError(f"expected one guard command in: {template_path}")
    guard_commands[0]["command"] = shlex.quote(str(guard))

    hooks_path = user_home / ".gemini/config/hooks.json"
    hooks_exist = os.path.lexists(hooks_path)
    current_hooks = json.loads(hooks_path.read_text()) if hooks_exist else {}
    if not isinstance(current_hooks, dict):
        raise ValueError(f"hook config must contain a JSON object: {hooks_path}")
    merged_hooks = dict(current_hooks)
    merged_hooks[hook_key] = own_hook
    env_path = repo / "skills/moa/.env"
    example_path = repo / "skills/moa/.env.example"
    env_exists = os.path.lexists(env_path)
    previous_env = None
    if not env_exists:
        # Resolve the old runner before replacing any links. The entry point may
        # live in another checkout or itself link to a shared implementation.
        for platform in platforms:
            previous_runner = destinations[platform] / "moa/moa_runner.py"
            if previous_runner.is_file():
                candidate = previous_runner.resolve().parent / ".env"
                if candidate.is_file():
                    previous_env = candidate
                    break
    if not env_exists and previous_env is None and not example_path.is_file():
        raise ValueError(f"missing API key example: {example_path}")

    backup = None

    def backup_path(path):
        nonlocal backup
        label = str(path.relative_to(user_home)).replace(os.sep, "_")
        if args.dry_run:
            print(f"would back up {path} outside the skill directories")
            return None
        if backup is None:
            backup_root = user_home / ".local/share/moa-install-backups"
            backup_root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-")
            backup = Path(tempfile.mkdtemp(prefix=stamp, dir=backup_root))
        return backup / label

    # Copy before relinking: a non-symlink old skill directory may be moved into
    # the backup directory below. Never inspect or print credential contents.
    if not env_exists:
        if previous_env is not None:
            if args.dry_run:
                print(f"would copy existing API configuration from {previous_env} to {env_path}")
            else:
                shutil.copy2(previous_env, env_path)
                print(f"copied existing API configuration from {previous_env} to {env_path}")
        elif args.dry_run:
            print("would create skills/moa/.env from .env.example")
        else:
            shutil.copyfile(example_path, env_path)
            print("created skills/moa/.env from .env.example — fill in your keys")

    for target, path in links:
        if path.is_symlink() and path.resolve() == target.resolve():
            print(f"ok      {path}")
            continue
        if os.path.lexists(path):
            saved_path = backup_path(path)
            if not args.dry_run:
                shutil.move(str(path), str(saved_path))
                print(f"backup  {path} -> {saved_path}")
        if args.dry_run:
            print(f"would link {path} -> {target}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(target, target_is_directory=True)
            print(f"linked  {path} -> {target}")

    if merged_hooks == current_hooks:
        print(f"ok      {hooks_path}")
    elif args.dry_run:
        if hooks_exist:
            backup_path(hooks_path)
        print(f"would register guard in {hooks_path}: {guard}")
    else:
        if hooks_exist:
            saved_path = backup_path(hooks_path)
            shutil.copy2(hooks_path, saved_path)
            print(f"backup  {hooks_path} -> {saved_path}")
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replacement avoids leaving a truncated config on interruption.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=hooks_path.parent,
                                             prefix=".moa-hooks-", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(merged_hooks, handle, indent=2)
                handle.write("\n")
            if hooks_exist:
                shutil.copymode(hooks_path, temporary)
            os.replace(temporary, hooks_path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        print(f"updated {hooks_path} (guard hook registered)")

    if args.dry_run:
        print("Dry run complete; no files changed.")
    else:
        print(f"Installed platform: {args.platform}. Shared implementation: {repo / 'skills'}")


try:
    main()
except (OSError, ValueError, RuntimeError) as error:
    print(f"Installation failed: {error}", file=sys.stderr)
    sys.exit(1)
PY
