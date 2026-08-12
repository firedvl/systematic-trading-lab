#!/usr/bin/env bash
set -euo pipefail
umask 077

unit_name="systematic-trading-lab-paper-observation.service"
unit_path="/etc/systemd/system/$unit_name"
script_path="$(realpath -- "${BASH_SOURCE[0]}")"
repository="$(dirname -- "$(dirname -- "$script_path")")"

usage() {
  cat >&2 <<EOF
usage:
  $0 render|check|install CAMPAIGN_ID RUNTIME WHEEL MANIFEST TRADING_LAB_HOME SERVICE_USER SERVICE_GROUP [INTERVAL_SECONDS]
  $0 status | logs | uninstall
EOF
}

fail() {
  echo "error: $*" >&2
  exit 2
}

validate_fixed_inputs() {
  [[ $# -ge 7 && $# -le 8 ]] || { usage; exit 2; }
  campaign_id="$1"
  runtime="$2"
  wheel="$3"
  manifest="$4"
  trading_home="$5"
  service_user="$6"
  service_group="$7"
  interval="${8:-600}"

  [[ "$campaign_id" =~ ^[A-Za-z0-9_.:-]{1,128}$ ]] || fail "invalid campaign ID"
  [[ "$service_user" =~ ^[a-z_][a-z0-9_-]*$ ]] || fail "invalid service user"
  [[ "$service_group" =~ ^[a-z_][a-z0-9_-]*$ ]] || fail "invalid service group"
  if [[ ! "$interval" =~ ^[0-9]+$ ]] || ((interval < 60 || interval > 900)); then
    fail "interval must be between 60 and 900 seconds"
  fi

  for path in "$repository" "$runtime" "$wheel" "$manifest" "$trading_home"; do
    [[ "$path" =~ ^/[A-Za-z0-9_./:-]+$ ]] || fail "paths must be absolute and systemd-safe"
  done
  [[ -d "$repository/.git" && -f "$repository/pyproject.toml" ]] || \
    fail "repository marker is missing"
  grep -Fq 'name = "systematic-trading-lab"' "$repository/pyproject.toml" || \
    fail "repository marker is invalid"
  [[ -f "$runtime" && -x "$runtime" && ! -L "$runtime" ]] || fail "runtime is invalid"
  [[ -f "$wheel" && ! -L "$wheel" && "$wheel" == *.whl ]] || fail "wheel is invalid"
  [[ -f "$manifest" && ! -L "$manifest" ]] || fail "manifest is invalid"
  [[ -f "$repository/config/risk/alpaca-paper-v1.json" \
    && ! -L "$repository/config/risk/alpaca-paper-v1.json" ]] || fail "risk configuration is invalid"
  [[ -d "$trading_home" && ! -L "$trading_home" ]] || fail "TRADING_LAB_HOME is invalid"

  runtime="$(realpath -- "$runtime")"
  wheel="$(realpath -- "$wheel")"
  manifest="$(realpath -- "$manifest")"
  trading_home="$(realpath -- "$trading_home")"
  build_directory="$(dirname -- "$(dirname -- "$(dirname -- "$runtime")")")"
  build_commit="$(basename -- "$build_directory")"
  [[ "$(basename -- "$(dirname -- "$(dirname -- "$runtime")")")" == verified-venv \
    && "$build_commit" =~ ^[0-9a-f]{40}$ \
    && "$(dirname -- "$build_directory")" == "$repository/.trading-lab/runtime-builds" \
    && "$(dirname -- "$wheel")" == "$build_directory" \
    && "$manifest" == "$build_directory/runtime-build-manifest.json" ]] || \
    fail "runtime artifacts must be one exact project-local verified build"
  [[ "$trading_home" == "$repository/.trading-lab" ]] || \
    fail "TRADING_LAB_HOME must be the project-local .trading-lab directory"
  command -v git >/dev/null || fail "Git is required"
  [[ "$(git -C "$repository" rev-parse --verify HEAD)" == "$build_commit" ]] || \
    fail "repository commit differs from the verified runtime"
  git -C "$repository" ls-files --error-unmatch config/risk/alpaca-paper-v1.json >/dev/null \
    || fail "risk configuration is not tracked"
  git -C "$repository" diff --quiet HEAD -- config/risk/alpaca-paper-v1.json \
    || fail "risk configuration differs from the runtime commit"
}

render_unit() {
  cat <<EOF
[Unit]
Description=Systematic Trading Lab broker-read-only paper observation
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=900
StartLimitBurst=3

[Service]
Type=exec
User=$service_user
Group=$service_group
WorkingDirectory=$repository
Environment=TRADING_LAB_MODE=paper
Environment=TRADING_LAB_HOME=$trading_home
Environment=TRADING_LAB_PAPER_ACTIVATION_ID=
Environment=TRADING_LAB_PAPER_CODE_COMMIT=
Environment=PATH=/usr/local/bin:/usr/bin:/bin
ExecStart=$runtime paper supervise-observation $campaign_id --runtime $runtime --wheel $wheel --manifest $manifest --repository $repository --risk-config $repository/config/risk/alpaca-paper-v1.json --interval-seconds $interval
Restart=on-failure
RestartPreventExitStatus=2
RestartSec=30
TimeoutStopSec=30
KillMode=control-group
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$trading_home
ReadOnlyPaths=$build_directory
CapabilityBoundingSet=
RestrictSUIDSGID=yes
LockPersonality=yes
ProtectClock=yes
ProtectHostname=yes
ProtectKernelLogs=yes
ProtectKernelModules=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes
RestrictRealtime=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
SystemCallArchitectures=native
StandardOutput=journal
StandardError=journal
SyslogIdentifier=systematic-trading-lab-paper-observation

[Install]
WantedBy=multi-user.target
EOF
}

preflight() {
  id "$service_user" >/dev/null 2>&1 || fail "service user does not exist"
  [[ "$(id -gn "$service_user")" == "$service_group" ]] || fail "service group is not primary"
  command -v gh >/dev/null || fail "GitHub CLI is required for runtime verification"
  case "$(command -v gh)" in
    /usr/local/bin/gh|/usr/bin/gh|/bin/gh) ;;
    *) fail "GitHub CLI must be installed in the service PATH" ;;
  esac
  command -v runuser >/dev/null || fail "runuser is required"
  service_home="$(getent passwd "$service_user" | cut -d: -f6)"
  [[ -n "$service_home" ]] || fail "service user home is missing"
  command=(
    env -i
    HOME="$service_home"
    PATH=/usr/local/bin:/usr/bin:/bin
    TRADING_LAB_MODE=paper
    TRADING_LAB_HOME="$trading_home"
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
    --check
  )
  cd -- "$repository"
  if [[ "$(id -un)" == "$service_user" ]]; then
    "${command[@]}"
  elif ((EUID == 0)); then
    runuser -u "$service_user" -- "${command[@]}"
  else
    fail "run check or install as root or the service user"
  fi
}

command_name="${1:-}"
case "$command_name" in
  render|check|install)
    shift
    validate_fixed_inputs "$@"
    if [[ "$command_name" == render ]]; then
      render_unit
      exit 0
    fi
    preflight
    [[ "$command_name" == check ]] && exit 0
    ((EUID == 0)) || fail "install must run as root"
    [[ ! -e "$unit_path" ]] || fail "$unit_path already exists; uninstall it first"
    if command -v screen >/dev/null \
      && "$repository/scripts/paper_observation_screen.sh" status >/dev/null 2>&1; then
      fail "stop the GNU Screen observer before installing systemd supervision"
    fi
    command -v systemd-analyze >/dev/null || fail "systemd-analyze is required"
    temporary_directory="$(mktemp -d)"
    temporary_unit="$temporary_directory/$unit_name"
    trap 'rm -rf -- "$temporary_directory"' EXIT
    render_unit >"$temporary_unit"
    systemd-analyze verify "$temporary_unit"
    install -o root -g root -m 0644 "$temporary_unit" "$unit_path"
    systemctl daemon-reload
    systemctl enable --now "$unit_name"
    echo "installed and boot-enabled: $unit_name"
    ;;
  status)
    [[ $# -eq 1 ]] || { usage; exit 2; }
    systemctl is-enabled "$unit_name" || true
    systemctl is-active "$unit_name" || true
    systemctl status --no-pager "$unit_name" || true
    ;;
  logs)
    [[ $# -eq 1 ]] || { usage; exit 2; }
    journalctl -u "$unit_name" -n 100 --no-pager
    ;;
  uninstall)
    [[ $# -eq 1 ]] || { usage; exit 2; }
    ((EUID == 0)) || fail "uninstall must run as root"
    if ! systemctl disable --now "$unit_name" 2>/dev/null \
      && systemctl is-active --quiet "$unit_name"; then
      fail "$unit_name could not be stopped"
    fi
    if systemctl is-active --quiet "$unit_name"; then
      fail "$unit_name is still active"
    fi
    rm -f -- "$unit_path"
    systemctl daemon-reload
    systemctl reset-failed "$unit_name" 2>/dev/null || true
    echo "disabled and removed: $unit_name"
    ;;
  *)
    usage
    exit 2
    ;;
esac
