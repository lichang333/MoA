#!/bin/bash
# Link this repo's skills into place and register the /auto guard with Antigravity (agy).
# Idempotent. Never deletes: anything in the way is moved to a backup dir OUTSIDE the
# skill directories (a stale copy left next to the link would load as a duplicate skill).
set -euo pipefail
REPO="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
BACKUP="$HOME/.local/share/moa-install-backups/$(date +%Y%m%d-%H%M%S)"

link() {  # link <target> <link-path>
  local target="$1" path="$2"
  if [[ -L "$path" && "$(realpath "$path")" == "$(realpath "$target")" ]]; then
    echo "ok      $path"; return
  fi
  if [[ -e "$path" || -L "$path" ]]; then
    mkdir -p "$BACKUP"
    local dest="$BACKUP/$(echo "${path#$HOME/}" | tr / _)"
    mv "$path" "$dest"
    echo "backup  $path -> $dest"
  fi
  mkdir -p "$(dirname "$path")"
  ln -s "$target" "$path"
  echo "linked  $path -> $target"
}

# Skills. ~/.claude/skills/moa has always pointed at ~/.agents/skills/moa; keep that chain.
link "$REPO/skills/moa"  "$HOME/.agents/skills/moa"
link "$REPO/skills/auto" "$HOME/.claude/skills/auto"
[[ -e "$HOME/.claude/skills/moa" ]] || ln -s ../../.agents/skills/moa "$HOME/.claude/skills/moa"

# moa API keys stay local (gitignored).
if [[ ! -f "$REPO/skills/moa/.env" ]]; then
  cp "$REPO/skills/moa/.env.example" "$REPO/skills/moa/.env"
  echo "created skills/moa/.env from .env.example — fill in your keys"
fi

# Register the /auto guard as an agy PreToolUse hook (merged into any existing hooks.json).
python3 - "$REPO/hooks/agy-hooks.json" "$HOME/.gemini/config/hooks.json" "$BACKUP" <<'PY'
import json, os, shutil, sys
tpl_path, hooks_path, backup = sys.argv[1:]
tpl = json.load(open(tpl_path))
cur = json.load(open(hooks_path)) if os.path.exists(hooks_path) else {}
merged = dict(cur, **tpl)
if merged == cur:
    print(f"ok      {hooks_path}")
else:
    if os.path.exists(hooks_path):
        os.makedirs(backup, exist_ok=True)
        shutil.copy2(hooks_path, os.path.join(backup, "gemini_config_hooks.json"))
    os.makedirs(os.path.dirname(hooks_path), exist_ok=True)
    with open(hooks_path, "w") as f:
        json.dump(merged, f, indent=2)
        f.write("\n")
    print(f"updated {hooks_path} (guard hook registered)")
PY

echo
echo "Check: python3 $REPO/skills/auto/test_guard.py && python3 $REPO/skills/auto/test_worker.py"
