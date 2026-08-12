#!/usr/bin/env bash
set -euo pipefail
umask 077

session_name="${TRADING_LAB_SCREEN_NAME:-systematic-trading-lab-observation}"
script_path="$(realpath -- "${BASH_SOURCE[0]}")"
repository="$(dirname -- "$(dirname -- "$script_path")")"

usage() {
  echo "usage: $0 start|run CAMPAIGN_ID RUNTIME WHEEL MANIFEST TRADING_LAB_HOME [INTERVAL_SECONDS] | status | stop" >&2
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

supervisor_command() {
  local campaign_id="$1"
  local runtime="$2"
  local wheel="$3"
  local manifest="$4"
  local home="$5"
  local interval="$6"
  supervisor=(
    env
    -u APCA_API_KEY_ID
    -u APCA_API_SECRET_KEY
    TRADING_LAB_MODE=paper
    TRADING_LAB_HOME="$home"
    TRADING_LAB_PAPER_ACTIVATION_ID=
    TRADING_LAB_PAPER_CODE_COMMIT=
    "$runtime"
    paper supervise-observation "$campaign_id"
    --runtime "$runtime"
    --wheel "$wheel"
    --manifest "$manifest"
    --repository "$repository"
    --risk-config "$repository/config/risk/alpaca-paper-v1.json"
    --interval-seconds "$interval"
  )
}

command_name="${1:-}"
case "$command_name" in
  start|run)
    [[ $# -ge 6 && $# -le 7 ]] || { usage; exit 2; }
    supervisor_command "$2" "$3" "$4" "$5" "$6" "${7:-600}"
    if [[ "$command_name" == run ]]; then
      cd -- "$repository"
      exec "${supervisor[@]}"
    fi
    require_screen
    session_exists && { echo "error: screen session already exists" >&2; exit 2; }
    cd -- "$repository"
    "${supervisor[@]}" --check >/dev/null
    screen -DmS "$session_name" "${supervisor[@]}"
    sleep 1
    session_exists || { echo "error: observation screen exited during startup" >&2; exit 2; }
    echo "started screen session: $session_name"
    echo "attach: screen -r $session_name"
    ;;
  status)
    [[ $# -eq 1 ]] || { usage; exit 2; }
    require_screen
    if session_exists; then
      echo "running: $session_name"
    else
      echo "stopped: $session_name"
      exit 1
    fi
    ;;
  stop)
    [[ $# -eq 1 ]] || { usage; exit 2; }
    require_screen
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
