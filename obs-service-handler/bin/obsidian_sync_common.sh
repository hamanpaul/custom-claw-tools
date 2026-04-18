#!/usr/bin/env bash
set -euo pipefail

resolve_home_dir() {
  if [ -n "${HOME:-}" ]; then
    printf '%s\n' "$HOME"
    return 0
  fi
  getent passwd "$(id -un)" 2>/dev/null | awk -F: 'NR==1 {print $6}'
}

build_runtime_path() {
  local nvm_root="$HOME_DIR/.nvm/versions/node"
  local paths=("$HOME_DIR/.local/bin")
  if [ -d "$nvm_root" ]; then
    while IFS= read -r candidate; do
      paths+=("$candidate")
    done < <(find "$nvm_root" -mindepth 2 -maxdepth 2 -type d -name bin 2>/dev/null | sort -r)
  fi
  paths+=("/usr/local/bin" "/usr/bin" "/bin")
  local IFS=:
  printf '%s' "${paths[*]}"
}

HOME_DIR="$(resolve_home_dir)"
export HOME="$HOME_DIR"
export PATH="$(build_runtime_path):${PATH:-}"

STATE_DIR="${STATE_DIR:-$HOME/.local/state/obsidian-automation}"
INCIDENT_DIR="${INCIDENT_DIR:-$STATE_DIR/incidents}"
SYNC_ROOT="${SYNC_ROOT:-$HOME/.config/obsidian-headless/sync}"
AUTH_TOKEN_PATH="${AUTH_TOKEN_PATH:-$HOME/.config/obsidian-headless/auth_token}"
TERMINAL_STOP_FILE="${TERMINAL_STOP_FILE:-$STATE_DIR/obsidian-sync-terminal-stop.json}"
RUNNER_PID_FILE="${RUNNER_PID_FILE:-$STATE_DIR/obsidian-sync-runner.pid}"
TERMINAL_AUTH_RC="${TERMINAL_AUTH_RC:-41}"
TERMINAL_CONFIG_RC="${TERMINAL_CONFIG_RC:-42}"

ensure_runtime_dirs() {
  mkdir -p "$STATE_DIR" "$INCIDENT_DIR"
}

log() {
  printf '[%s] %s
' "$(date --iso-8601=seconds)" "$*"
}

slugify() {
  local input="${1:-incident}"
  input="$(printf '%s' "$input" | tr ' /:' '___' | tr -cd '[:alnum:]_.-')"
  printf '%s' "${input:-incident}"
}

resolve_sync_config() {
  local result rc
  set +e
  result="$(python3 - "$SYNC_ROOT" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1]).expanduser()
files = sorted(root.glob('*/config.json'))
if len(files) != 1:
    print(json.dumps({'ok': False, 'error': 'expected_single_config', 'count': len(files), 'files': [str(f) for f in files]}))
    raise SystemExit(2)
path = files[0]
try:
    data = json.loads(path.read_text(encoding='utf-8'))
except Exception as e:
    print(json.dumps({'ok': False, 'error': 'invalid_json', 'file': str(path), 'detail': str(e)}))
    raise SystemExit(2)
vault_path = str(data.get('vaultPath', '')).strip()
vault_id = str(data.get('vaultId', '')).strip()
vault_name = str(data.get('vaultName', '')).strip()
host = str(data.get('host', '')).strip()
if not vault_path:
    print(json.dumps({'ok': False, 'error': 'missing_vault_path', 'file': str(path)}))
    raise SystemExit(2)
print(json.dumps({'ok': True, 'file': str(path), 'vault_path': vault_path, 'vault_id': vault_id, 'vault_name': vault_name, 'host': host}))
PY
)"
  rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    RESOLVE_SYNC_CONFIG_ERROR="$result"
    return "$TERMINAL_CONFIG_RC"
  fi
  eval "$(python3 - "$result" <<'PY'
import json, shlex, sys
obj = json.loads(sys.argv[1])
for env_name, value in [
    ('LOADED_CONFIG_FILE', obj.get('file', '')),
    ('LOADED_VAULT_PATH', obj.get('vault_path', '')),
    ('LOADED_VAULT_ID', obj.get('vault_id', '')),
    ('LOADED_VAULT_NAME', obj.get('vault_name', '')),
    ('LOADED_VAULT_HOST', obj.get('host', '')),
]:
    print(f'export {env_name}={shlex.quote(value)}')
PY
)"
  return 0
}

process_state() {
  local pid="${1:-}"
  if [ -z "$pid" ] || [ ! -d "/proc/$pid" ]; then
    echo missing
    return 0
  fi
  ps -o stat= -p "$pid" 2>/dev/null | awk '{print $1}' || echo unknown
}

process_cmdline() {
  local pid="${1:-}"
  if [ -z "$pid" ] || [ ! -r "/proc/$pid/cmdline" ]; then
    return 0
  fi
  tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true
}

extract_cmd_path() {
  local cmdline="${1:-}"
  python3 - "$cmdline" <<'PY'
import shlex, sys
cmd = sys.argv[1]
try:
    parts = shlex.split(cmd)
except Exception:
    parts = cmd.split()
path = ''
for idx, token in enumerate(parts):
    if token == '--path' and idx + 1 < len(parts):
        path = parts[idx + 1]
        break
print(path)
PY
}

lock_age() {
  local lock_path="${1:-}"
  file_age "$lock_path"
}

file_age() {
  local file_path="${1:-}"
  if [ -z "$file_path" ] || [ ! -e "$file_path" ]; then
    echo -1
    return 0
  fi
  local now mtime
  now="$(date +%s)"
  mtime="$(stat -c %Y "$file_path" 2>/dev/null || echo 0)"
  echo "$(( now - mtime ))"
}

read_runner_pid() {
  if [ -f "$RUNNER_PID_FILE" ]; then
    cat "$RUNNER_PID_FILE" 2>/dev/null || true
  fi
}

list_vault_runner_entries() {
  if [ -z "${LOADED_VAULT_PATH:-}" ]; then
    return 0
  fi
  python3 - "$LOADED_VAULT_PATH" "$$" <<'PY'
import os, shlex, subprocess, sys

target = os.path.realpath(sys.argv[1])
current_shell = sys.argv[2]
try:
    out = subprocess.check_output(['ps', '-eo', 'pid=,args='], text=True)
except Exception:
    raise SystemExit(0)

for raw in out.splitlines():
    line = raw.strip()
    if not line:
        continue
    try:
        pid, args = line.split(None, 1)
    except ValueError:
        continue
    if pid == current_shell:
        continue
    try:
        parts = shlex.split(args)
    except Exception:
        parts = args.split()
    if not parts or 'sync' not in parts or '--path' not in parts:
        continue
    path = ''
    for idx, token in enumerate(parts):
        if token == '--path' and idx + 1 < len(parts):
            path = parts[idx + 1]
            break
    if not path or os.path.realpath(path) != target:
        continue
    first = os.path.basename(parts[0])
    second = os.path.basename(parts[1]) if len(parts) > 1 else ''
    if first != 'ob' and second != 'ob':
        continue
    print(f'{pid}   {args}')
PY
}

list_vault_runner_pids() {
  list_vault_runner_entries | awk '{print $1}'
}

set_default_sync_progress_log_path() {
  if [ -z "${SYNC_PROGRESS_LOG_PATH:-}" ] && [ -n "${LOADED_CONFIG_FILE:-}" ]; then
    SYNC_PROGRESS_LOG_PATH="$(dirname "$LOADED_CONFIG_FILE")/sync.log"
  fi
}

sync_progress_probe_path() {
  if [ -n "${SYNC_PROGRESS_LOG_PATH:-}" ] && [ -e "$SYNC_PROGRESS_LOG_PATH" ]; then
    printf '%s\n' "$SYNC_PROGRESS_LOG_PATH"
    return 0
  fi
  if [ -e "$STATE_DIR/obsidian-sync-guard.log" ]; then
    printf '%s\n' "$STATE_DIR/obsidian-sync-guard.log"
  fi
}

set_terminal_stop_flag() {
  ensure_runtime_dirs
  local reason="$1"
  local classification="$2"
  local detail="${3:-}"
  cat >"$TERMINAL_STOP_FILE" <<STOP
 timestamp=$(date --iso-8601=seconds)
 reason=$reason
 classification=$classification
 config_file=${LOADED_CONFIG_FILE:-}
 vault_path=${LOADED_VAULT_PATH:-}
 detail=$detail
STOP
}

clear_terminal_stop_flag() {
  rm -f "$TERMINAL_STOP_FILE"
}

has_terminal_stop_flag() {
  [ -f "$TERMINAL_STOP_FILE" ]
}

write_incident_log() {
  ensure_runtime_dirs
  local reason="$1"
  local classification="$2"
  local detail_file="${3:-}"
  local slug ts incident main_pid main_state runner_pid runner_state cmdline cmd_path matching_runners
  slug="$(slugify "$reason")"
  ts="$(date +%Y%m%d-%H%M%S)"
  incident="$INCIDENT_DIR/${ts}-${slug}.log"
  main_pid="${MAIN_PID:-}"
  main_state="$(process_state "$main_pid")"
  runner_pid="$(read_runner_pid)"
  runner_state="$(process_state "$runner_pid")"
  cmdline="$(process_cmdline "$runner_pid")"
  cmd_path="$(extract_cmd_path "$cmdline")"
  matching_runners="$(list_vault_runner_entries || true)"
  {
    echo "timestamp=$(date --iso-8601=seconds)"
    echo "reason=$reason"
    echo "classification=$classification"
    echo "config_file=${LOADED_CONFIG_FILE:-}"
    echo "vault_id=${LOADED_VAULT_ID:-}"
    echo "vault_name=${LOADED_VAULT_NAME:-}"
    echo "vault_host=${LOADED_VAULT_HOST:-}"
    echo "vault_path=${LOADED_VAULT_PATH:-}"
    echo "auth_token_path=$AUTH_TOKEN_PATH"
    echo "main_pid=${main_pid:-}"
    echo "main_state=${main_state:-}"
    echo "runner_pid=${runner_pid:-}"
    echo "runner_state=${runner_state:-}"
    echo "runner_cmd_path=${cmd_path:-}"
    echo "runner_cmdline=${cmdline:-}"
    if [ -n "$matching_runners" ]; then
      echo '--- matching_runners ---'
      printf '%s
' "$matching_runners"
    fi
    if [ -n "${LOCK_PATH:-}" ]; then
      echo "lock_path=$LOCK_PATH"
      echo "lock_age=$(lock_age "$LOCK_PATH")"
      if [ -e "$LOCK_PATH" ]; then
        stat -c 'lock_stat=%A %s %y %n' "$LOCK_PATH" 2>/dev/null || true
      fi
    fi
    if [ -n "${RESOLVE_SYNC_CONFIG_ERROR:-}" ]; then
      echo '--- resolve_sync_config_error ---'
      printf '%s
' "$RESOLVE_SYNC_CONFIG_ERROR"
    fi
    if [ -n "${SYNC_PROGRESS_LOG_PATH:-}" ]; then
      echo "sync_progress_log_path=$SYNC_PROGRESS_LOG_PATH"
      echo "sync_progress_log_age=$(file_age "$SYNC_PROGRESS_LOG_PATH")"
      if [ -e "$SYNC_PROGRESS_LOG_PATH" ]; then
        stat -c 'sync_progress_stat=%A %s %y %n' "$SYNC_PROGRESS_LOG_PATH" 2>/dev/null || true
      fi
    fi
    if [ -f "$TERMINAL_STOP_FILE" ]; then
      echo '--- terminal_stop_flag ---'
      cat "$TERMINAL_STOP_FILE"
    fi
    if [ -n "$detail_file" ] && [ -f "$detail_file" ]; then
      echo '--- detail_tail ---'
      tail -n 120 "$detail_file"
    fi
  } >"$incident"
  log "incident log written: $incident"
  LAST_INCIDENT_LOG="$incident"
}

classify_ob_failure() {
  local detail_file="$1"
  if [ ! -f "$detail_file" ]; then
    echo transient
    return 0
  fi
  if grep -Eiq 'missing obsidian auth token|login required|unauthorized|forbidden|authentication failed|invalid auth token|invalid token|expired token|401|403' "$detail_file"; then
    echo terminal_auth
    return 0
  fi
  if grep -Eiq 'No sync configuration found|expected_single_config|invalid_json|missing_vault_path|vault path missing|sync config' "$detail_file"; then
    echo terminal_config
    return 0
  fi
  if grep -Eiq 'Received signal to shut down' "$detail_file"; then
    echo clean_shutdown
    return 0
  fi
  echo transient
}
