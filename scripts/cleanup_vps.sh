#!/usr/bin/env bash
set -euo pipefail
umask 077

execute=false
delete_repository=false
session_name="${TRADING_LAB_SCREEN_NAME:-systematic-trading-lab-observation}"
script_path="$(realpath -- "${BASH_SOURCE[0]}")"
repository="$(dirname -- "$(dirname -- "$script_path")")"

usage() {
  cat >&2 <<'EOF'
usage: cleanup_vps.sh [--execute] [--delete-repository]

Default: show the project-local runtime data that would be removed.
--execute: perform the cleanup.
--delete-repository: remove the validated repository too; requires --execute.
EOF
}

while (($#)); do
  case "$1" in
    --execute) execute=true ;;
    --delete-repository) delete_repository=true ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
  shift
done

repository="$(realpath -e -- "$repository")"
case "$repository" in
  /|/home|/root|/opt|/srv|/usr|/var|"$HOME")
    echo "error: refusing broad cleanup target: $repository" >&2
    exit 2
    ;;
esac
[[ -d "$repository/.git" && -f "$repository/pyproject.toml" ]] || {
  echo "error: cleanup target is not the trading-lab repository" >&2
  exit 2
}
grep -Fq 'name = "systematic-trading-lab"' "$repository/pyproject.toml" || {
  echo "error: project marker does not match" >&2
  exit 2
}
[[ "$session_name" =~ ^[A-Za-z0-9_.-]{1,64}$ ]] || {
  echo "error: invalid screen session name" >&2
  exit 2
}

session_exists() {
  screen -list 2>/dev/null | awk -v expected=".$session_name" \
    '$1 ~ /^[0-9]+[.]/ && substr($1, index($1, ".")) == expected { found = 1 } END { exit !found }'
}

runtime_targets=(
  "$repository/.env"
  "$repository/.trading-lab"
  "$repository/.venv"
  "$repository/.mypy_cache"
  "$repository/.pytest_cache"
  "$repository/.ruff_cache"
  "$repository/build"
  "$repository/dist"
  "$repository/src/systematic_trading_lab.egg-info"
)

echo "screen session: $session_name"
if $delete_repository; then
  echo "delete repository: $repository"
else
  echo "delete project-local runtime data:"
  printf '  %s\n' "${runtime_targets[@]}"
  echo "  $repository/**/__pycache__"
  echo "  $repository/**/*.py[co]"
fi
echo "not removed: broker or GitHub records, backups, SSH logs, system journals, or shell history"

$execute || { echo "dry run only; add --execute to proceed"; exit 0; }

if command -v screen >/dev/null && session_exists; then
  screen -S "$session_name" -X quit
  for _ in {1..10}; do
    session_exists || break
    sleep 1
  done
  session_exists && { echo "error: screen session did not stop" >&2; exit 2; }
fi

if $delete_repository; then
  cd /
  rm -rf -- "$repository"
  echo "removed repository and all project-local data: $repository"
  exit 0
fi

for target in "${runtime_targets[@]}"; do
  [[ "$target" == "$repository/"* ]] || { echo "error: target escaped repository" >&2; exit 2; }
  rm -rf -- "$target"
done
find "$repository" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$repository" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
command -v screen >/dev/null && screen -wipe >/dev/null 2>&1 || true
echo "removed project-local runtime data; source checkout retained: $repository"
