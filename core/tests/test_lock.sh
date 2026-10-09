#!/bin/sh
# Regression tests for core/pipeline-lock.sh (scratch git repo; no data repo touched).
#   sh core/tests/test_lock.sh
set -u
LOCK="$(cd "$(dirname "$0")/.." && pwd)/pipeline-lock.sh"
FAILS=0
d=$(mktemp -d) && git -C "$d" init -q
s="$d/stage.sh"   # a pipeline entry point: takes the lock, reports whether it got re-executed
printf 'D=%s\n. %s\necho "ran $1 lock=$GE_PIPELINE_LOCK"\n' "$d" "$LOCK" > "$s"
ok() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1 (got: $2)"; FAILS=$((FAILS + 1)); fi; }

ok "free lock: the script runs under it, args intact" "$(sh "$s" a 2>&1)" "ran a lock=$d/.git/ge-pipeline.lock"
flock "$d/.git/ge-pipeline.lock" sleep 3 &
sleep 0.5
LOCK_WAIT=0 sh "$s" b >/dev/null 2>&1
ok "held lock: a second run gives up after LOCK_WAIT (exit 75)" "$?" 75
ok "nested run (lock inherited) does not wait" "$(GE_PIPELINE_LOCK=x LOCK_WAIT=0 sh "$s" c 2>&1)" "ran c lock=x"
ok "a waiting run proceeds once the holder finishes" "$(LOCK_WAIT=10 sh "$s" d 2>/dev/null)" "ran d lock=$d/.git/ge-pipeline.lock"
wait

rm -rf "$d"
echo "$FAILS failure(s)"
[ "$FAILS" = 0 ]
