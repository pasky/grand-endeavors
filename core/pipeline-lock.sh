# One pipeline run at a time per data checkout: gather.sh, assess.sh, bulletin.sh,
# roundup.sh and collect.sh all commit to the data repo, and gather's write-scope guard
# would see another run's commits as its agents' doing. Sourced BEFORE the caller
# changes directory, with D = the data repo and the caller's "$@". It re-executes the
# calling script under flock(1); nested runs (gather.sh -> assess.sh) inherit
# GE_PIPELINE_LOCK and skip it. The lock file lives in the checkout's own git dir, so
# separate worktrees don't block each other. -o: the locked fd is not passed to the
# script, so a stray agent process cannot keep holding the lock.
# ENV: LOCK_WAIT=seconds to wait for a running pipeline (default 10800 = 3 h; exit 75).
if [ -z "${GE_PIPELINE_LOCK:-}" ]; then
	GE_PIPELINE_LOCK="$(git -C "$D" rev-parse --absolute-git-dir)/ge-pipeline.lock"
	export GE_PIPELINE_LOCK
	_script="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
	flock -n "$GE_PIPELINE_LOCK" true \
		|| echo ">>> another pipeline run holds $GE_PIPELINE_LOCK; waiting (LOCK_WAIT=${LOCK_WAIT:-10800}s)" >&2
	exec flock -o -w "${LOCK_WAIT:-10800}" -E 75 "$GE_PIPELINE_LOCK" sh "$_script" "$@"
fi
