#!/usr/bin/env bash
set -euo pipefail
umask 077

unit_name="systematic-trading-lab-paper-observation.service"
unit_path="/etc/systemd/system/$unit_name"
script_path="$(realpath -- "${BASH_SOURCE[0]}")"
repository="$(dirname -- "$(dirname -- "$script_path")")"
state_helper="$repository/scripts/migrate_paper_observation_state.py"
service_home="/var/lib/systematic-trading-lab"
github_config_parent="$service_home/.config"
github_config_dir="$github_config_parent/gh"
github_cache_parent="$service_home/.cache"
github_cache_dir="$github_cache_parent/gh"

usage() {
  cat >&2 <<EOF
usage:
  $0 render|check|install CAMPAIGN_ID RUNTIME WHEEL MANIFEST TRADING_LAB_HOME SERVICE_USER SERVICE_GROUP [INTERVAL_SECONDS]
  $0 check-state|migrate-state TRADING_LAB_HOME SERVICE_USER SERVICE_GROUP
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
  git_command=(
    env -i
    HOME=/nonexistent
    XDG_CONFIG_HOME=/nonexistent
    GIT_CONFIG_GLOBAL=/dev/null
    GIT_CONFIG_NOSYSTEM=1
    PATH=/usr/local/bin:/usr/bin:/bin
    git --no-replace-objects --git-dir "$repository/.git"
  )
  [[ "$("${git_command[@]}" rev-parse --verify HEAD)" == "$build_commit" ]] || \
    fail "repository commit differs from the verified runtime"
  "${git_command[@]}" cat-file blob \
    "$build_commit:config/risk/alpaca-paper-v1.json" \
    | cmp -s - "$repository/config/risk/alpaca-paper-v1.json" \
    || fail "risk configuration differs from the runtime commit"
}

state_check() {
  command -v python3 >/dev/null || fail "Python 3 is required for state ownership checks"
  [[ -f "$state_helper" && ! -L "$state_helper" ]] || fail "state migration helper is invalid"
  python3 "$state_helper" check \
    --repository "$repository" \
    --home "$trading_home" \
    --service-user "$service_user" \
    --service-group "$service_group"
}

render_unit() {
  cat <<EOF
[Unit]
Description=Systematic Trading Lab broker-read-only paper observation
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=900
StartLimitBurst=5

[Service]
Type=exec
User=$service_user
Group=$service_group
WorkingDirectory=$repository
Environment=TRADING_LAB_MODE=paper
Environment=TRADING_LAB_HOME=$trading_home
Environment=TRADING_LAB_PAPER_ACTIVATION_ID=
Environment=TRADING_LAB_PAPER_CODE_COMMIT=
Environment=HOME=$service_home
Environment=GH_CONFIG_DIR=$github_config_dir
Environment=XDG_CACHE_HOME=$service_home/.cache
Environment=GH_HOST=github.com
Environment=GH_PROMPT_DISABLED=1
Environment=GH_TOKEN=
Environment=GITHUB_TOKEN=
Environment=GH_ENTERPRISE_TOKEN=
Environment=GITHUB_ENTERPRISE_TOKEN=
Environment=PATH=/usr/local/bin:/usr/bin:/bin
ExecStart=$runtime paper supervise-observation $campaign_id --runtime $runtime --wheel $wheel --manifest $manifest --repository $repository --risk-config $repository/config/risk/alpaca-paper-v1.json --interval-seconds $interval
Restart=on-failure
RestartPreventExitStatus=2
RestartSec=60
TimeoutStopSec=30
KillMode=control-group
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$trading_home $github_cache_dir
ReadOnlyPaths=$repository $build_directory $github_config_dir
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
  [[ "$(getent passwd "$service_user" | cut -d: -f6)" == "$service_home" ]] || \
    fail "service user home must be $service_home"
  service_uid="$(id -u "$service_user")"
  service_gid="$(id -g "$service_user")"
  for directory in \
    "$service_home" \
    "$github_config_parent" \
    "$github_config_dir" \
    "$github_cache_parent" \
    "$github_cache_dir"; do
    [[ -d "$directory" && ! -L "$directory" ]] || fail "service GitHub directory is invalid: $directory"
    [[ "$(stat -c '%u:%g:%a' "$directory")" == "$service_uid:$service_gid:700" ]] || \
      fail "service GitHub directory must be service-owned with mode 0700: $directory"
  done
  service_environment=(
    env -i
    HOME="$service_home"
    GH_CONFIG_DIR="$github_config_dir"
    XDG_CACHE_HOME="$service_home/.cache"
    GH_HOST=github.com
    GH_PROMPT_DISABLED=1
    PATH=/usr/local/bin:/usr/bin:/bin
  )
  if [[ "$(id -un)" == "$service_user" ]]; then
    "${service_environment[@]}" gh auth status --hostname github.com >/dev/null
  elif ((EUID == 0)); then
    runuser -u "$service_user" -- \
      "${service_environment[@]}" gh auth status --hostname github.com >/dev/null
  else
    fail "run check or install as root or the service user"
  fi
  command=(
    "${service_environment[@]}"
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
    state_check
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
  check-state|migrate-state)
    [[ $# -eq 4 ]] || { usage; exit 2; }
    trading_home="$2"
    service_user="$3"
    service_group="$4"
    for path in "$repository" "$trading_home"; do
      [[ "$path" =~ ^/[A-Za-z0-9_./:-]+$ ]] || fail "paths must be absolute and systemd-safe"
    done
    [[ "$trading_home" == "$repository/.trading-lab" ]] || \
      fail "TRADING_LAB_HOME must be the project-local .trading-lab directory"
    [[ "$service_user" =~ ^[a-z_][a-z0-9_-]*$ ]] || fail "invalid service user"
    [[ "$service_group" =~ ^[a-z_][a-z0-9_-]*$ ]] || fail "invalid service group"
    command -v python3 >/dev/null || fail "Python 3 is required for state migration"
    [[ -f "$state_helper" && ! -L "$state_helper" ]] || fail "state migration helper is invalid"
    action=check
    [[ "$command_name" == migrate-state ]] && action=migrate
    python3 "$state_helper" "$action" \
      --repository "$repository" \
      --home "$trading_home" \
      --service-user "$service_user" \
      --service-group "$service_group"
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
