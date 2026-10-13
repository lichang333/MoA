#!/bin/bash
# Run a command inside the /auto sandbox: no network, writes only to ROOT (minus control
# files) and a private ROOT.tmp, nothing under $HOME or the shared temp dirs readable
# except ROOT/GITDIR/VENV/ROOT.tmp,
# and a scrubbed environment (no tokens from the caller's env reach worker code).
# AUTO_SANDBOX_ROOT marks every sandboxed process so agy_worker.py can sweep leftovers.
# Usage: run_sandboxed.sh <root> <cmd> [args...]
# GITDIR comes from AUTO_WORKER_GITDIR when set (agy_worker.py records it at worktree
# creation); it is only derived from ROOT for Claude's own runs, never for worker runs,
# because a worker could otherwise steer it through the worktree's .git file.
set -euo pipefail
[[ $# -ge 2 ]] || { echo "usage: $0 <root> <cmd> [args...]" >&2; exit 2; }
SKILL_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
ROOT="$(realpath "$1")"; shift
H="$(realpath "$HOME")"
case "$ROOT" in "$H"|/|/Users|/private|/private/var|/private/tmp|"$H/Documents"|"$H/Desktop")
  echo "run_sandboxed: refusing ROOT=$ROOT" >&2; exit 2;; esac

if [[ -n "${AUTO_WORKER_GITDIR:-}" ]]; then
  GITDIR="$AUTO_WORKER_GITDIR"
elif [[ "${AUTO_WORKER:-}" == 1 ]]; then
  echo "run_sandboxed: worker mode requires AUTO_WORKER_GITDIR" >&2; exit 2
else
  GITDIR="$(git -c core.fsmonitor= -c core.hooksPath=/dev/null -C "$ROOT" \
            rev-parse --path-format=absolute --git-common-dir)" \
    || { echo "run_sandboxed: cannot resolve git dir for $ROOT" >&2; exit 2; }
fi
GITDIR="$(realpath "$GITDIR")"
# A git common dir is <repo>/.git; anything else (e.g. $HOME) would re-open the read denies.
[[ "$(basename "$GITDIR")" == ".git" && -d "$GITDIR" ]] \
  || { echo "run_sandboxed: refusing GITDIR=$GITDIR" >&2; exit 2; }

VENV="${AUTO_WORKER_VENV:-}"
if [[ -n "$VENV" && -d "$VENV" ]]; then VENV="$(realpath "$VENV")"; else VENV=/nonexistent; fi

# Private temp dir per worktree (not the shared $TMPDIR, which holds other workers' trees).
# TMP and BUSY sit beside ROOT. Sandboxed code may write inside TMP but never replace TMP itself
# (sandbox.sb), and cannot touch BUSY at all; still refuse anything but a real dir / regular file.
TMP="$ROOT.tmp"; BUSY="$ROOT.busy"
[[ -L "$TMP" ]] && { echo "run_sandboxed: refusing symlinked TMP $TMP" >&2; exit 2; }
mkdir -p "$TMP"
[[ -d "$TMP" && "$(realpath "$TMP")" == "$TMP" ]] || { echo "run_sandboxed: refusing TMP $TMP" >&2; exit 2; }
[[ -L "$BUSY" || ( -e "$BUSY" && ! -f "$BUSY" ) ]] && { echo "run_sandboxed: refusing BUSY $BUSY" >&2; exit 2; }
# Held open across exec and fork by the command and its children: agy_worker.py lists the holders
# (lsof) to tell a long-running command from a stalled worker and to find leftovers.
exec 9>>"$BUSY"

P=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
[[ "$VENV" != /nonexistent ]] && P="$VENV/bin:$P"
exec /usr/bin/env -i PATH="$P" HOME="$H" USER="${USER:-}" LOGNAME="${LOGNAME:-}" \
  LANG="${LANG:-en_US.UTF-8}" TERM="${TERM:-dumb}" TMPDIR="$TMP/" SHELL=/bin/bash \
  GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 XDG_CONFIG_HOME=/nonexistent PAGER=cat GIT_PAGER=cat \
  AUTO_SANDBOX_ROOT="$ROOT" \
  /usr/bin/sandbox-exec -f "$SKILL_DIR/sandbox.sb" \
  -D ROOT="$ROOT" -D GITDIR="$GITDIR" -D VENV="$VENV" -D TMP="$TMP" -D HOME="$H" "$@"
