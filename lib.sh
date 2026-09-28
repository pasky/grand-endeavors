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

# Write-scope guard (cooperative, not isolation): a pi stage may only change
# $ALLOWED. Checks committed changes since the stage began, uncommitted changes,
# and edits to files that were ALREADY dirty (by content hash). Files in
# $APPEND_ONLY must keep their previous content as a prefix (e.g. the metric
# registry: rows may be added, never edited). Gitignored paths are invisible to
# git, so staging directories are out of scope by construction.
_dirty_hashes() {
	git status --porcelain --untracked-files=all | cut -c4- | while read -r f; do
		[ -f "$f" ] && echo "$f $(git hash-object "$f")" || echo "$f -"
	done
}

guard_paths() {  # $1 pre-HEAD, $2 pre-dirty "path hash" lines, $3 label, $4 append-only snapshot dir
	changed="$( { git diff --name-only "$1" HEAD; git status --porcelain --untracked-files=all | cut -c4-; } | sort -u)"
	bad=""
	for f in $changed; do
		ok=""
		for a in $ALLOWED; do
			case "$a" in */) case "$f" in "$a"*) ok=1 ;; esac ;; *) [ "$f" = "$a" ] && ok=1 ;; esac
		done
		[ -n "$ok" ] && continue
		now="$f $( [ -f "$f" ] && git hash-object "$f" || echo -)"
		printf '%s\n' "$2" | grep -qxF -- "$now" || bad="$bad $f"   # new change, or a dirty file edited further
	done
	for f in ${APPEND_ONLY:-}; do
		old="$4/$(echo "$f" | tr / _)"
		[ -f "$old" ] || continue
		n="$(wc -c < "$old")"
		if [ ! -f "$f" ] || ! head -c "$n" "$f" | cmp -s - "$old"; then
			bad="$bad $f(append-only:existing-rows-changed)"
		fi
	done
	if [ -n "$bad" ]; then
		echo "ERROR: stage '$3' modified files outside its allowed scope:$bad" >&2
		echo "       inspect/revert them (git status; git log $1..HEAD), then rerun." >&2
		exit 1
	fi
}

# Run one pi stage (saved, named session) under the write-scope guard. The guard
# also runs when pi fails, so a crashed stage cannot leave unchecked edits.
pi_run() {
	label="$1"; prompt="$2"
	echo ">>> [$RUN_NAME] $label"
	pre_head="$(git rev-parse HEAD)"
	pre_dirty="$(_dirty_hashes)"
	ao_dir="$(mktemp -d)"
	for f in ${APPEND_ONLY:-}; do [ -f "$f" ] && cp "$f" "$ao_dir/$(echo "$f" | tr / _)"; done
	mkdir -p "$SESS_DIR"
	rc=0
	# </dev/null: pi must not consume the caller's stdin (loops reading files)
	pi -p --approve --session-dir "$SESS_DIR" --name "$RUN_NAME-$label" "$prompt" </dev/null || rc=$?
	guard_paths "$pre_head" "$pre_dirty" "$label" "$ao_dir"
	rm -rf "$ao_dir"
	[ "$rc" = 0 ] || { echo "ERROR: stage '$label' failed (pi exit $rc)" >&2; exit "$rc"; }
}
