#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/obsidian_sync_common.sh"

SYNC_UNIT="${SYNC_UNIT:-obsidian-sync.service}"
CONFIG_DIR="${CONFIG_DIR:-.obsidian}"
LOG_PATH="${LOG_PATH:-$STATE_DIR/obsidian-sync-healthcheck.log}"
RESTART_STAMP="${RESTART_STAMP:-$STATE_DIR/obsidian-sync-last-restart.epoch}"
STALE_LOCK_SECS="${STALE_LOCK_SECS:-15}"
RESTART_COOLDOWN_SECS="${RESTART_COOLDOWN_SECS:-30}"
STALL_THRESHOLD_SECS="${STALL_THRESHOLD_SECS:-900}"

ensure_runtime_dirs
exec >>"$LOG_PATH" 2>&1

recently_restarted() {
  if [ ! -f "$RESTART_STAMP" ]; then
    return 1
  fi
  local last now
  last="$(cat "$RESTART_STAMP" 2>/dev/null || echo 0)"
  now="$(date +%s)"
  [ "$(( now - last ))" -lt "$RESTART_COOLDOWN_SECS" ]
}

remove_stale_lock() {
  local age
  age="$(lock_age "$LOCK_PATH")"
  if [ "$age" -ge "$STALE_LOCK_SECS" ]; then
    log "removing stale lock (${age}s): $LOCK_PATH"
    rm -rf "$LOCK_PATH"
  fi
}

restart_sync() {
  local reason="$1"
  if has_terminal_stop_flag; then
    log "terminal stop flag present; skip restart: $reason"
    return 0
  fi
  if recently_restarted; then
    log "skip restart due to cooldown: $reason"
    return 0
  fi
  date +%s >"$RESTART_STAMP"
  log "restarting $SYNC_UNIT: $reason (loaded path: ${LOADED_VAULT_PATH:-unknown})"
  systemctl --user restart "$SYNC_UNIT"
}

if ! resolve_sync_config; then
  write_incident_log 'healthcheck-config-invalid' terminal_config
  set_terminal_stop_flag 'healthcheck-config-invalid' terminal_config "${RESOLVE_SYNC_CONFIG_ERROR:-unknown}"
  if systemctl --user --quiet is-active "$SYNC_UNIT"; then
    log "stopping $SYNC_UNIT due to terminal config error"
    systemctl --user stop "$SYNC_UNIT" || true
  fi
  exit 0
fi

LOCK_PATH="${LOCK_PATH:-$LOADED_VAULT_PATH/$CONFIG_DIR/.sync.lock}"
set_default_sync_progress_log_path
log "healthcheck loaded config: $LOADED_CONFIG_FILE"
log "healthcheck loaded path: $LOADED_VAULT_PATH"
if [ -n "${SYNC_PROGRESS_LOG_PATH:-}" ]; then
  log "healthcheck loaded progress log: $SYNC_PROGRESS_LOG_PATH"
fi

if [ ! -f "$AUTH_TOKEN_PATH" ] && [ -z "${OBSIDIAN_AUTH_TOKEN:-}" ]; then
  write_incident_log 'healthcheck-auth-token-missing' terminal_auth
  set_terminal_stop_flag 'healthcheck-auth-token-missing' terminal_auth 'missing token file and OBSIDIAN_AUTH_TOKEN'
  if systemctl --user --quiet is-active "$SYNC_UNIT"; then
    log "stopping $SYNC_UNIT due to terminal auth error"
    systemctl --user stop "$SYNC_UNIT" || true
  fi
  exit 0
fi

if has_terminal_stop_flag; then
  log "terminal stop flag present; keeping $SYNC_UNIT down"
  if systemctl --user --quiet is-active "$SYNC_UNIT"; then
    systemctl --user stop "$SYNC_UNIT" || true
  fi
  exit 0
fi

if ! systemctl --user --quiet is-active "$SYNC_UNIT"; then
  write_incident_log 'service-inactive' transient
  remove_stale_lock
  restart_sync 'service inactive'
  exit 0
fi

main_pid="$(systemctl --user show --property=MainPID --value "$SYNC_UNIT")"
main_state="$(process_state "$main_pid")"
MAIN_PID="$main_pid"
if [ -z "$main_pid" ] || [ "$main_pid" = "0" ] || [ "$main_state" = "missing" ]; then
  write_incident_log 'main-pid-missing' transient
  remove_stale_lock
  restart_sync 'missing main pid'
  exit 0
fi
if [[ "$main_state" == Z* ]]; then
  write_incident_log 'main-pid-zombie' transient
  remove_stale_lock
  restart_sync "main pid zombie ($main_state)"
  exit 0
fi

runner_pid="$(read_runner_pid)"
runner_state="$(process_state "$runner_pid")"
matching_runners="$(list_vault_runner_entries || true)"
if [ -z "$runner_pid" ] || [ "$runner_state" = "missing" ]; then
  recovered_runner_pid=""
  if [ -n "$matching_runners" ]; then
    recovered_runner_pid="$(printf '%s
' "$matching_runners" | awk 'NR==1 {print $1}')"
  fi
  if [ -n "$recovered_runner_pid" ]; then
    runner_pid="$recovered_runner_pid"
    printf '%s
' "$runner_pid" >"$RUNNER_PID_FILE"
    runner_state="$(process_state "$runner_pid")"
    log "recovered runner pid file from active sync process: $runner_pid"
  else
    write_incident_log 'runner-pid-missing' transient
    remove_stale_lock
    restart_sync 'runner pid missing'
    exit 0
  fi
fi
if [[ "$runner_state" == Z* ]]; then
  write_incident_log 'runner-pid-zombie' transient
  remove_stale_lock
  restart_sync "runner zombie ($runner_state)"
  exit 0
fi
if [ -z "$matching_runners" ] || ! printf '%s
' "$matching_runners" | awk '{print $1}' | grep -qx "$runner_pid"; then
  write_incident_log 'runner-path-mismatch' transient
  restart_sync 'runner path mismatch'
  exit 0
fi

age="$(lock_age "$LOCK_PATH")"
if [ "$age" -ge 0 ] && [ "$age" -gt "$STALE_LOCK_SECS" ]; then
  write_incident_log 'stale-lock-detected' transient
  remove_stale_lock
  restart_sync "stale lock age ${age}s"
  exit 0
fi

progress_probe="$(sync_progress_probe_path || true)"
progress_age=-1
if [ -n "$progress_probe" ]; then
  progress_age="$(file_age "$progress_probe")"
  if [ "$progress_age" -ge 0 ] && [ "$progress_age" -gt "$STALL_THRESHOLD_SECS" ]; then
    SYNC_PROGRESS_LOG_PATH="$progress_probe"
    write_incident_log 'sync-progress-stalled' transient
    remove_stale_lock
    restart_sync "sync progress stalled (${progress_age}s): $progress_probe"
    exit 0
  fi
fi

log "health ok: main_pid=$main_pid main_state=$main_state runner_pid=$runner_pid runner_state=$runner_state path=$LOADED_VAULT_PATH lock_age=$age"
