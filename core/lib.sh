# Shared plumbing for gather/gather.sh, gather/assess.sh, views/bulletin.sh (POSIX sh;
# source it from a script one directory below the repo root).
# TWO repositories (DESIGN.md §7): the mechanism ($ROOT: code, prompts, README,
# rubric) and the data ($D: ledger, registry, bulletins; $GE_DATA, default
# $ROOT/data). Scripts run with cwd = $D, so every data path is repo-relative and
# pi agents work inside the data repo; code is invoked as $ROOT/<dir>/<tool>.
# Callers set: SECTION, SESS_DIR, RUN_NAME, ALLOWED (space-separated DATA-repo
# paths the pi agents may modify; entries ending in "/" are prefixes). Agents may
# modify NOTHING in the mechanism repo. Paths never contain whitespace.

set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
D="$(cd "${GE_DATA:-$ROOT/data}" 2>/dev/null && pwd)" \
	|| { echo "ERROR: data repo not found at ${GE_DATA:-$ROOT/data} (set GE_DATA)" >&2; exit 1; }
export GE_DATA="$D"
git -C "$D" rev-parse --git-dir >/dev/null 2>&1 || { echo "ERROR: $D is not a git repository" >&2; exit 1; }
cd "$D"
AGENT_DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
SECTIONS="robots-software robots-hardware rockets fusion health climate knowledge-beyond society-cohesion"

require_section() {
	case " $SECTIONS " in *" $1 "*) : ;; *) echo "ERROR: unknown section '$1' (one of: $SECTIONS)" >&2; exit 1 ;; esac
	case "$1" in *[!a-z-]*) echo "ERROR: bad section '$1'" >&2; exit 1 ;; esac
}

require_clean() {  # both repos: data (commits go there) and mechanism (provenance)
	for repo in "$D" "$ROOT"; do
		if [ -z "${ALLOW_DIRTY:-}" ] && [ -n "$(git -C "$repo" status --porcelain)" ]; then
			echo "ERROR: $repo not clean. Commit/stash first, or set ALLOW_DIRTY=1." >&2
			git -C "$repo" status --short >&2
			exit 1
		fi
	done
}

tool_versions() {  # manifest/state lines
	echo "pi_version:    $(pi --version 2>&1 | head -1)"
	echo "agent_commit:  $(git -C "$AGENT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
	git -C "$AGENT_DIR" diff --quiet 2>/dev/null && echo "agent_dirty:   no" || echo "agent_dirty:   YES"
	echo "settings_sha:  $(sha256sum "$AGENT_DIR/settings.json" 2>/dev/null | cut -c1-16)"
	echo "mechanism_commit: $(git -C "$ROOT" rev-parse HEAD)$(git -C "$ROOT" diff --quiet HEAD 2>/dev/null || echo ' (dirty)')"
	echo "data_commit:   $(git -C "$D" rev-parse HEAD)"
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
# registry: rows may be added, never edited); the baseline is $APPEND_ONLY_BASE
# (a directory of copies taken by the caller, e.g. at run start, so a later stage
# may still remove an earlier stage's unaccepted additions), else the content
# before each stage. Gitignored paths are invisible to
# git, so staging directories are out of scope by construction.
_dirty_hashes() {  # $1 = repo dir
	git -C "$1" status --porcelain --untracked-files=all --no-renames | cut -c4- | while read -r f; do
		[ -f "$1/$f" ] && echo "$f $(git -C "$1" hash-object "$f")" || echo "$f -"
	done
}

guard_paths() {  # $1 pre-HEAD, $2 pre-dirty "path hash" lines, $3 label, $4 append-only snapshot dir,
	           # $5 repo dir (default: cwd), $6 allowed list (default: $ALLOWED)
	repo="${5:-.}"; allowed="${6-$ALLOWED}"
	# every path changed since the stage began, PLUS every path that was dirty
	# before it (so restoring/deleting a pre-dirty file is caught too). --no-renames: a
	# rename is its delete + add (porcelain "old -> new" would word-split; diff
	# --name-only would hide a protected file renamed into an allowed path)
	changed="$( { git -C "$repo" diff --name-only --no-renames "$1" HEAD; git -C "$repo" status --porcelain --untracked-files=all --no-renames | cut -c4-;
		printf '%s\n' "$2" | cut -d' ' -f1; } | grep -v '^$' | sort -u)"
	bad=""
	for f in $changed; do
		ok=""
		for a in $allowed; do
			case "$a" in */) case "$f" in "$a"*) ok=1 ;; esac ;; *) [ "$f" = "$a" ] && ok=1 ;; esac
		done
		[ -n "$ok" ] && continue
		now="$f $( [ -f "$repo/$f" ] && git -C "$repo" hash-object "$f" || echo -)"
		printf '%s\n' "$2" | grep -qxF -- "$now" || bad="$bad $f"   # new change, or a dirty file edited further
	done
	for f in ${APPEND_ONLY:-}; do
		old="${APPEND_ONLY_BASE:-$4}/$(echo "$f" | tr / _)"
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
	pre_dirty="$(_dirty_hashes .)"
	m_head="$(git -C "$ROOT" rev-parse HEAD)"
	m_dirty="$(_dirty_hashes "$ROOT")"
	ao_dir="$(mktemp -d)"
	for f in ${APPEND_ONLY:-}; do [ -f "$f" ] && cp "$f" "$ao_dir/$(echo "$f" | tr / _)"; done
	mkdir -p "$SESS_DIR"
	rc=0
	# </dev/null: pi must not consume the caller's stdin (loops reading files)
	pi -p --approve --session-dir "$SESS_DIR" --name "$RUN_NAME-$label" "$prompt" </dev/null || rc=$?
	guard_paths "$pre_head" "$pre_dirty" "$label" "$ao_dir"
	_ao="${APPEND_ONLY:-}"; APPEND_ONLY=""   # (prefix assignments on functions are not portable)
	guard_paths "$m_head" "$m_dirty" "$label (mechanism repo)" "$ao_dir" "$ROOT" ""
	APPEND_ONLY="$_ao"
	rm -rf "$ao_dir"
	[ "$rc" = 0 ] || { echo "ERROR: stage '$label' failed (pi exit $rc)" >&2; exit "$rc"; }
}
