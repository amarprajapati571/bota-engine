#!/usr/bin/env bash
#
# Offline smoke test — verifies every layer that does NOT need a trained model
# or a game screen:  baccarat engine, demo pipeline, local storage, API push.
#
#   bash scripts/smoke_test.sh
#
# It runs a throwaway mock backend and writes demo results to a temp file, so it
# never touches your real logs/results.jsonl.

set -u
cd "$(dirname "$0")/.." || exit 1

# Prefer the project venv if it exists.
PY="python3"
[ -x "./venv/bin/python" ] && PY="./venv/bin/python"

pass=0
fail=0
note() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }
ok()   { printf '   \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass + 1)); }
bad()  { printf '   \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail + 1)); }

note "Python"
echo "   using: $($PY --version 2>&1) [$PY]"

note "1. Baccarat engine unit tests"
if $PY tests/test_baccarat_engine.py >/tmp/smoke_tests.log 2>&1; then
  ok "engine rules ($(grep -c '... ok' /tmp/smoke_tests.log) checks)"
else
  bad "unit tests — see /tmp/smoke_tests.log"; cat /tmp/smoke_tests.log
fi

note "2. Demo pipeline (no model)"
if $PY main.py --demo >/tmp/smoke_demo.log 2>&1; then
  rounds=$(grep -c 'ROUND' /tmp/smoke_demo.log)
  [ "$rounds" -ge 3 ] && ok "demo produced $rounds rounds" || bad "expected 3 rounds, got $rounds"
else
  bad "demo failed — see /tmp/smoke_demo.log"; cat /tmp/smoke_demo.log
fi

note "3. Storage + API push (mock backend, no model)"
TMP_RESULTS="$(mktemp -d)/results.jsonl"
rm -f tools/received_rounds.jsonl
MOCK_API_PORT=8077 $PY tools/mock_api.py >/tmp/smoke_mock.log 2>&1 &
MOCK_PID=$!
sleep 1
RESULTS_FILE="$TMP_RESULTS" API_BASE_URL="http://localhost:8077" \
  $PY main.py --demo --send >/tmp/smoke_send.log 2>&1
sleep 1
kill "$MOCK_PID" 2>/dev/null

stored=$( [ -f "$TMP_RESULTS" ] && wc -l < "$TMP_RESULTS" || echo 0 )
recv=$(   [ -f tools/received_rounds.jsonl ] && wc -l < tools/received_rounds.jsonl || echo 0 )
[ "$stored" -eq 3 ] && ok "stored 3 rounds to results file" || bad "stored=$stored (expected 3) — /tmp/smoke_send.log"
[ "$recv" -eq 3 ]   && ok "backend received 3 rounds"       || bad "received=$recv (expected 3) — /tmp/smoke_mock.log"
rm -f tools/received_rounds.jsonl; rm -rf "$(dirname "$TMP_RESULTS")"

note "Summary"
printf '   %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ] && echo "   Offline pipeline OK. Next: --calibrate, --detect, then --live (need a model)." || true
exit "$fail"
