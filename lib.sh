# Shared plumbing for gather.sh / bulletin.sh (POSIX sh; source it, don't run it).
# Callers set: SECTION, SESS_DIR, RUN_NAME, ALLOWED (space-separated paths the
# pi agents may modify; entries ending in "/" are prefixes). Paths never contain
# whitespace (our naming convention).

set -eu
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
AGENT_DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
SECTIONS="robots-software robots-hardware rockets fusion health climate knowledge-beyond society-cohesion"

require_section() {
	case " $SECTIONS " in *" $1 "*) : ;; *) echo "ERROR: unknown section '$1' (one of: $SECTIONS)" >&2; exit 1 ;; esac
	case "$1" in *[!a-z-]*) echo "ERROR: bad section '$1'" >&2; exit 1 ;; esac
}

require_clean() {
	if [ -z "${ALLOW_DIRTY:-}" ] && [ -n "$(git status --porcelain)" ]; then
		echo "ERROR: git worktree not clean. Commit/stash first, or set ALLOW_DIRTY=1." >&2
		git status --short >&2
		exit 1
	fi
}

tool_versions() {  # manifest/state lines
	echo "pi_version:    $(pi --version 2>&1 | head -1)"
	echo "agent_commit:  $(git -C "$AGENT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
	git -C "$AGENT_DIR" diff --quiet 2>/dev/null && echo "agent_dirty:   no" || echo "agent_dirty:   YES"
	echo "settings_sha:  $(sha256sum "$AGENT_DIR/settings.json" 2>/dev/null | cut -c1-16)"
	echo "spec_commit:   $(git rev-parse HEAD)"
}

# Commit ONLY the given paths (those that exist); "nothing to commit" is fine.
commit() {
	msg="$1"; shift
	paths=""
	for p in "$@"; do [ -e "$p" ] && paths="$paths $p"; done
	[ -n "$paths" ] || return 0
	git add $paths
	if git diff --cached --quiet -- $paths; then
		echo "    (nothing to commit for: $msg)"
		return 0
	fi
	git commit -q -m "$msg" -- $paths
}

# Write-scope guard: a pi stage may only change $ALLOWED (committed or not);
# paths already dirty before the stage are ignored.
guard_paths() {
	changed="$( { git diff --name-only "$1" HEAD; git status --porcelain --untracked-files=all | cut -c4-; } | sort -u)"
	bad=""
	for f in $changed; do
		ok=""
		for a in $ALLOWED; do
			case "$a" in */) case "$f" in "$a"*) ok=1 ;; esac ;; *) [ "$f" = "$a" ] && ok=1 ;; esac
		done
		[ -n "$ok" ] || printf '%s\n' "$2" | grep -qxF -- "$f" || bad="$bad $f"
	done
	if [ -n "$bad" ]; then
		echo "ERROR: stage '$3' modified files outside its allowed scope:$bad" >&2
		echo "       inspect/revert them (git status; git log $1..HEAD), then rerun." >&2
		exit 1
	fi
}

# Run one pi stage (saved, named session) under the write-scope guard.
pi_run() {
	label="$1"; prompt="$2"
	echo ">>> [$RUN_NAME] $label"
	pre_head="$(git rev-parse HEAD)"
	pre_dirty="$(git status --porcelain --untracked-files=all | cut -c4-)"
	mkdir -p "$SESS_DIR"
	# </dev/null: pi must not consume the caller's stdin (loops reading files)
	pi -p --approve --session-dir "$SESS_DIR" --name "$RUN_NAME-$label" "$prompt" </dev/null
	guard_paths "$pre_head" "$pre_dirty" "$label"
}
