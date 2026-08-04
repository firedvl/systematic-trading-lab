#!/usr/bin/env bash
set -euo pipefail
umask 077

session_name="${TRADING_LAB_SCREEN_NAME:-systematic-trading-lab-observation}"
script_path="$(realpath -- "${BASH_SOURCE[0]}")"
repository="$(dirname -- "$(dirname -- "$script_path")")"

usage() {
  echo "usage: $0 start CAMPAIGN_ID RUNTIME [INTERVAL_SECONDS] | status | stop" >&2
}

require_screen() {
  command -v screen >/dev/null || { echo "error: GNU screen is required" >&2; exit 2; }
  [[ "$session_name" =~ ^[A-Za-z0-9_.-]{1,64}$ ]] || {
    echo "error: invalid screen session name" >&2
    exit 2
  }
}

session_exists() {
  screen -list 2>/dev/null | awk -v expected=".$session_name" \
    '$1 ~ /^[0-9]+[.]/ && substr($1, index($1, ".")) == expected { found = 1 } END { exit !found }'
}

validate_run() {
  campaign_id="$1"
  runtime="$(realpath -e -- "$2")"
  interval="$3"
  [[ "$campaign_id" =~ ^[A-Za-z0-9_.:-]{1,128}$ ]] || {
    echo "error: invalid campaign ID" >&2
    exit 2
  }
  [[ -x "$runtime" ]] || { echo "error: runtime is not executable" >&2; exit 2; }
  runtime_venv="$(dirname -- "$(dirname -- "$runtime")")"
  build_directory="$(dirname -- "$runtime_venv")"
  build_commit="$(basename -- "$build_directory")"
  [[ "$(basename -- "$runtime_venv")" == "verified-venv" \
    && "$build_commit" =~ ^[0-9a-f]{40}$ \
    && "$(dirname -- "$build_directory")" == "$repository/.trading-lab/runtime-builds" ]] || {
    echo "error: runtime must be an exact project-local verified build" >&2
    exit 2
  }
  [[ "$interval" =~ ^[0-9]+$ ]] && ((interval >= 60 && interval <= 900)) || {
    echo "error: interval must be between 60 and 900 seconds" >&2
    exit 2
  }
  runtime_python="$(dirname -- "$runtime")/python"
  [[ -x "$runtime_python" ]] || {
    echo "error: runtime Python is missing beside trading-lab" >&2
    exit 2
  }
  command -v flock >/dev/null || { echo "error: flock is required" >&2; exit 2; }
}

json_is_complete() {
  "$runtime_python" -c \
    'import json, sys; raise SystemExit(not json.load(sys.stdin).get("campaign_complete", False))'
}

run_loop() {
  validate_run "$1" "$2" "$3"
  cd -- "$repository"
  mkdir -p -- .trading-lab
  exec 9>.trading-lab/paper-observation-screen.lock
  flock -n 9 || { echo "error: another observation loop holds the lock" >&2; exit 2; }
  trap 'echo "observation loop stopped at $(date --iso-8601=seconds)"' EXIT

  while true; do
    cycle_started="$(date +%s)"
    set +e
    assessment="$("$runtime" paper assess-observation "$campaign_id" 2>&1)"
    assessment_status=$?
    set -e
    if ((assessment_status > 1)); then
      printf '%s\n' "$assessment" >&2
      exit "$assessment_status"
    fi
    if printf '%s' "$assessment" | json_is_complete; then
      printf '%s\n' "$assessment"
      echo "campaign complete; observation loop exiting"
      return 0
    fi

    set +e
    result="$("$runtime" paper record-observation "$campaign_id" 2>&1)"
    result_status=$?
    set -e
    printf '%s %s\n%s\n' "$(date --iso-8601=seconds)" "sample exit=$result_status" "$result"
    if ((result_status > 1)); then
      exit "$result_status"
    fi
    delay=$((cycle_started + interval - $(date +%s)))
    ((delay > 0)) && sleep "$delay"
  done
}

require_screen
command_name="${1:-}"
case "$command_name" in
  start)
    [[ $# -ge 3 && $# -le 4 ]] || { usage; exit 2; }
    validate_run "$2" "$3" "${4:-600}"
    session_exists && { echo "error: screen session already exists" >&2; exit 2; }
    screen -DmS "$session_name" "$script_path" run "$campaign_id" "$runtime" "$interval"
    sleep 1
    session_exists || { echo "error: observation screen exited during startup" >&2; exit 2; }
    echo "started screen session: $session_name"
    echo "attach: screen -r $session_name"
    ;;
  run)
    [[ $# -eq 4 ]] || { usage; exit 2; }
    run_loop "$2" "$3" "$4"
    ;;
  status)
    [[ $# -eq 1 ]] || { usage; exit 2; }
    if session_exists; then
      echo "running: $session_name"
    else
      echo "stopped: $session_name"
      exit 1
    fi
    ;;
  stop)
    [[ $# -eq 1 ]] || { usage; exit 2; }
    if session_exists; then
      screen -S "$session_name" -X quit
      echo "stopped: $session_name"
    else
      echo "already stopped: $session_name"
    fi
    ;;
  *)
    usage
    exit 2
    ;;
esac
