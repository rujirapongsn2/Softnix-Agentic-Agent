#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
API_BASE="${API_BASE:-http://127.0.0.1:8787}"
HEALTH_URL="$API_BASE/health"

log() {
  printf "[core-memory-test] %s\n" "$*"
}

fail() {
  printf "[core-memory-test][FAIL] %s\n" "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

json_get() {
  local expr="$1"
  local payload="${2:-}"
  python - "$expr" "$payload" <<'PY'
import json
import sys
expr = sys.argv[1]
payload = sys.argv[2]
if not payload:
    raise SystemExit("empty JSON payload")
data = json.loads(payload)
obj = data
for part in expr.split('.'):
    if part.isdigit():
        obj = obj[int(part)]
    else:
        obj = obj[part]
if isinstance(obj, (dict, list)):
    print(json.dumps(obj, ensure_ascii=False))
else:
    print(obj)
PY
}

backend_started_by_script=0
backend_pid=""
backend_cmd=""

cleanup() {
  if [ "$backend_started_by_script" = "1" ] && [ -n "$backend_pid" ]; then
    log "stopping backend pid=$backend_pid"
    kill "$backend_pid" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

wait_health() {
  local retries=40
  local i
  for i in $(seq 1 "$retries"); do
    if curl -sS "$HEALTH_URL" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

start_backend_if_needed() {
  if curl -sS "$HEALTH_URL" >/dev/null 2>&1; then
    log "backend already running at $API_BASE"
    return 0
  fi

  if command -v softnix >/dev/null 2>&1; then
    backend_cmd="softnix api serve --host 127.0.0.1 --port 8787"
  elif [ -x "$ROOT_DIR/.venv/bin/softnix" ]; then
    backend_cmd="$ROOT_DIR/.venv/bin/softnix api serve --host 127.0.0.1 --port 8787"
  elif command -v uv >/dev/null 2>&1; then
    backend_cmd="uv run softnix api serve --host 127.0.0.1 --port 8787"
  else
    fail "unable to start backend automatically (need softnix/.venv/bin/softnix/uv)"
  fi

  log "starting backend via: $backend_cmd"
  (
    cd "$ROOT_DIR"
    eval "$backend_cmd"
  ) >/tmp/softnix-core-memory-test.log 2>&1 &
  backend_pid="$!"
  backend_started_by_script=1

  if ! wait_health; then
    fail "backend did not become healthy (see /tmp/softnix-core-memory-test.log)"
  fi
}

post_run() {
  local task="$1"
  local payload
  payload=$(python - "$task" <<'PY'
import json
import sys
print(json.dumps({"task": sys.argv[1], "provider": "openai", "max_iters": 1}, ensure_ascii=False))
PY
)
  curl -sS -X POST "$API_BASE/runs" -H 'Content-Type: application/json' -d "$payload"
}

wait_run_done() {
  local run_id="$1"
  local retries=80
  local i
  for i in $(seq 1 "$retries"); do
    local out status
    out=$(curl -sS "$API_BASE/runs/$run_id")
    status=$(json_get "status" "$out")
    case "$status" in
      completed|failed|canceled)
        printf "%s" "$out"
        return 0
        ;;
    esac
    sleep 0.4
  done
  fail "run $run_id did not finish in time"
}

contains_pending_key() {
  local run_id="$1"
  local target_key="$2"
  local out
  out=$(curl -sS "$API_BASE/runs/$run_id/memory/pending")
  python - "$target_key" "$out" <<'PY'
import json
import sys
key = sys.argv[1]
payload = sys.argv[2]
items = json.loads(payload).get("items", [])
print("yes" if any(x.get("target_key") == key for x in items) else "no")
PY
}

require_cmd curl
require_cmd python

start_backend_if_needed

system_config=$(curl -sS "$API_BASE/system/config")
workspace=$(json_get "workspace" "$system_config")
[ -n "$workspace" ] || fail "workspace is empty from /system/config"

profile_file="$workspace/PROFILE.md"
session_file="$workspace/SESSION.md"

log "workspace=$workspace"
mkdir -p "$workspace"

test_id="oneclick_$(date +%s)"
key_explicit="response.tone.${test_id}"
key_ttl="response.verbosity.${test_id}"

log "Case A: explicit memory"
out=$(post_run "จำไว้ว่า ${key_explicit} = concise")
run_id=$(json_get "run_id" "$out")
wait_run_done "$run_id" >/dev/null
[ -f "$profile_file" ] || fail "PROFILE.md not found at $profile_file"
grep -q "key:${key_explicit}" "$profile_file" || fail "explicit key missing in PROFILE.md"
log "PASS A"

log "Case B: TTL memory"
out=$(post_run "remember ${key_ttl} = concise for 8h")
run_id=$(json_get "run_id" "$out")
wait_run_done "$run_id" >/dev/null
grep -q "key:${key_ttl}" "$profile_file" || fail "ttl key missing in PROFILE.md"
grep -q "key:${key_ttl}.*ttl:8h" "$profile_file" || fail "ttl:8h missing for ${key_ttl}"
log "PASS B"

log "Case C: inferred pending"
out=$(post_run "ช่วยสรุปสั้นๆ และขอเป็นข้อๆ")
run_id=$(json_get "run_id" "$out")
wait_run_done "$run_id" >/dev/null
p1=$(contains_pending_key "$run_id" "response.verbosity")
p2=$(contains_pending_key "$run_id" "response.format.default")
if [ "$p1" != "yes" ] && [ "$p2" != "yes" ]; then
  fail "no inferred pending keys found"
fi
[ -f "$session_file" ] || fail "SESSION.md not found at $session_file"
log "PASS C"

log "Case D: confirm pending response.verbosity"
out=$(post_run "ยืนยันให้จำ response.verbosity")
run_id=$(json_get "run_id" "$out")
wait_run_done "$run_id" >/dev/null
grep -q "key:response.verbosity" "$profile_file" || fail "response.verbosity not promoted to PROFILE.md"
p_after=$(contains_pending_key "$run_id" "response.verbosity")
[ "$p_after" = "no" ] || fail "response.verbosity pending still exists after confirm"
log "PASS D"

log "Case E: reject pending response.format.default"
out=$(post_run "ไม่ต้องจำ response.format.default")
run_id=$(json_get "run_id" "$out")
wait_run_done "$run_id" >/dev/null
p_after_reject=$(contains_pending_key "$run_id" "response.format.default")
[ "$p_after_reject" = "no" ] || fail "response.format.default pending still exists after reject"
log "PASS E"

log "All core memory one-click checks passed"
log "Latest run_id=$run_id"
log "PROFILE=$profile_file"
log "SESSION=$session_file"
log "Tip: inspect audit at $ROOT_DIR/.softnix/runs/<run_id>/memory_audit.jsonl"
