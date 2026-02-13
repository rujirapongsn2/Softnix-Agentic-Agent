#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8787}"
PROVIDER="${PROVIDER:-openai}"
MODEL="${MODEL:-gpt-4o-mini}"
MAX_ITERS="${MAX_ITERS:-10}"
WORKSPACE="${WORKSPACE:-tmp}"
SKILLS_DIR="${SKILLS_DIR:-skillpacks}"
TASKS_FILE="${TASKS_FILE:-scripts/benchmark_tasks.txt}"
POLL_SEC="${POLL_SEC:-1}"
POLL_MAX="${POLL_MAX:-180}"

if [[ ! -f "$TASKS_FILE" ]]; then
  echo "tasks file not found: $TASKS_FILE" >&2
  exit 1
fi

ts="$(date +%Y%m%d_%H%M%S)"
out_dir=".softnix/benchmarks/$ts"
mkdir -p "$out_dir"
csv="$out_dir/results.csv"
echo "task_index,run_id,status,stop_reason,iteration,seconds" >"$csv"

run_task() {
  local idx="$1"
  local task="$2"
  local payload
  payload=$(printf '{"task":%s,"provider":%s,"model":%s,"max_iters":%s,"workspace":%s,"skills_dir":%s}' \
    "$(jq -Rn --arg x "$task" '$x')" \
    "$(jq -Rn --arg x "$PROVIDER" '$x')" \
    "$(jq -Rn --arg x "$MODEL" '$x')" \
    "$MAX_ITERS" \
    "$(jq -Rn --arg x "$WORKSPACE" '$x')" \
    "$(jq -Rn --arg x "$SKILLS_DIR" '$x')")

  local run_json run_id
  run_json="$(curl -sS -X POST "$BASE_URL/runs" -H 'Content-Type: application/json' -d "$payload")"
  run_id="$(echo "$run_json" | jq -r '.run_id // empty')"
  if [[ -z "$run_id" ]]; then
    echo "failed to start task[$idx]: $task"
    echo "$run_json"
    echo "$idx,,failed,start_failed,0,0" >>"$csv"
    return
  fi

  local status="" stop_reason="" iteration="0"
  local started now elapsed i
  started="$(date +%s)"
  for ((i=1; i<=POLL_MAX; i++)); do
    now="$(curl -sS "$BASE_URL/runs/$run_id")"
    status="$(echo "$now" | jq -r '.status // empty')"
    stop_reason="$(echo "$now" | jq -r '.stop_reason // empty')"
    iteration="$(echo "$now" | jq -r '.iteration // 0')"
    if [[ "$status" == "completed" || "$status" == "failed" || "$status" == "canceled" ]]; then
      break
    fi
    sleep "$POLL_SEC"
  done
  elapsed="$(( $(date +%s) - started ))"
  echo "$idx,$run_id,$status,$stop_reason,$iteration,$elapsed" >>"$csv"
  echo "[$idx] run_id=$run_id status=$status stop_reason=$stop_reason iter=$iteration sec=$elapsed"
}

idx=0
while IFS= read -r task || [[ -n "$task" ]]; do
  task="$(echo "$task" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  [[ -z "$task" ]] && continue
  [[ "${task:0:1}" == "#" ]] && continue
  idx=$((idx+1))
  run_task "$idx" "$task"
done <"$TASKS_FILE"

total="$(($(wc -l <"$csv") - 1))"
completed="$(awk -F',' 'NR>1 && $3=="completed" {c++} END{print c+0}' "$csv")"
failed="$(awk -F',' 'NR>1 && $3=="failed" {c++} END{print c+0}' "$csv")"
success_rate="$(awk -v c="$completed" -v t="$total" 'BEGIN{ if(t==0){print "0.00"} else {printf "%.2f", (c*100.0)/t} }')"

{
  echo "Benchmark summary"
  echo "results_csv=$csv"
  echo "total=$total"
  echo "completed=$completed"
  echo "failed=$failed"
  echo "success_rate_pct=$success_rate"
} | tee "$out_dir/summary.txt"

