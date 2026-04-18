#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/obsidian_sync_common.sh"

CONFIG_DIR="${CONFIG_DIR:-.obsidian}"
LOG_PATH="${LOG_PATH:-$STATE_DIR/obsidian-sync-guard.log}"
FLOCK_PATH="${FLOCK_PATH:-$STATE_DIR/obsidian-sync-guard.flock}"
OB_BIN="${OB_BIN:-}"
OB_NODE_BIN="${OB_NODE_BIN:-}"
STALE_LOCK_SECS="${STALE_LOCK_SECS:-15}"
PRESTART_HANDOFF_WAIT_SECS="${PRESTART_HANDOFF_WAIT_SECS:-20}"
PRESTART_POLL_INTERVAL_SECS="${PRESTART_POLL_INTERVAL_SECS:-2}"

ensure_runtime_dirs
MAIN_PID=$$
exec > >(tee -a "$LOG_PATH") 2>&1

exec 9>"$FLOCK_PATH"
if ! flock -n 9; then
  log "another obsidian sync guard instance is already running"
  exit 0
fi

if [ -n "${OB_BIN:-}" ] && [ ! -x "$OB_BIN" ]; then
  OB_BIN=""
fi
if [ -z "${OB_BIN:-}" ]; then
  OB_BIN="$(command -v ob || true)"
fi
if [ -z "${OB_BIN:-}" ] || [ ! -x "$OB_BIN" ]; then
  write_incident_log 'ob-binary-missing' terminal_config
  set_terminal_stop_flag 'ob-binary-missing' terminal_config 'ob binary not found'
  exit "$TERMINAL_CONFIG_RC"
fi
if [ -z "${OB_NODE_BIN:-}" ]; then
  candidate_node="$(dirname "$OB_BIN")/node"
  if [ -x "$candidate_node" ]; then
    OB_NODE_BIN="$candidate_node"
  fi
fi

if ! resolve_sync_config; then
  write_incident_log 'sync-config-invalid' terminal_config
  set_terminal_stop_flag 'sync-config-invalid' terminal_config "${RESOLVE_SYNC_CONFIG_ERROR:-unknown}"
  exit "$TERMINAL_CONFIG_RC"
fi

LOCK_PATH="${LOCK_PATH:-$LOADED_VAULT_PATH/$CONFIG_DIR/.sync.lock}"
log "loaded sync config: $LOADED_CONFIG_FILE"
log "loaded vault path: $LOADED_VAULT_PATH"
log "loaded vault id: ${LOADED_VAULT_ID:-}"
log "loaded vault name: ${LOADED_VAULT_NAME:-}"

if [ ! -f "$AUTH_TOKEN_PATH" ] && [ -z "${OBSIDIAN_AUTH_TOKEN:-}" ]; then
  write_incident_log 'auth-token-missing' terminal_auth
  set_terminal_stop_flag 'auth-token-missing' terminal_auth 'missing token file and OBSIDIAN_AUTH_TOKEN'
  exit "$TERMINAL_AUTH_RC"
fi

clear_terminal_stop_flag

prepare_start_state() {
  local entries age deadline
  entries="$(list_vault_runner_entries || true)"
  if [ -n "$entries" ]; then
    log "existing runner detected before start; waiting for handoff"
    deadline=$(( $(date +%s) + PRESTART_HANDOFF_WAIT_SECS ))
    while [ -n "$entries" ]; do
      if [ "$(date +%s)" -ge "$deadline" ]; then
        write_incident_log 'preexisting-runner-still-active' transient
        log "matching runner still active after ${PRESTART_HANDOFF_WAIT_SECS}s wait"
        printf '%s
' "$entries"
        return 75
      fi
      sleep "$PRESTART_POLL_INTERVAL_SECS"
      entries="$(list_vault_runner_entries || true)"
    done
  fi
  if [ -e "$LOCK_PATH" ]; then
    age="$(lock_age "$LOCK_PATH")"
    if [ "$age" -lt "$STALE_LOCK_SECS" ]; then
      write_incident_log 'lock-runner-mismatch' transient
      log "removing orphan lock with no matching runner (${age}s): $LOCK_PATH"
    else
      log "removing stale lock (${age}s): $LOCK_PATH"
    fi
    rm -rf "$LOCK_PATH"
  fi
}

prepare_start_state

TMP_OUTPUT="$(mktemp)"
trap 'rm -f "$TMP_OUTPUT" "$RUNNER_PID_FILE"' EXIT

log "starting continuous sync for $LOADED_VAULT_PATH"
if [ -n "${OB_NODE_BIN:-}" ]; then
  "$OB_NODE_BIN" "$OB_BIN" sync --continuous --path "$LOADED_VAULT_PATH" > >(tee -a "$TMP_OUTPUT") 2>&1 &
else
  "$OB_BIN" sync --continuous --path "$LOADED_VAULT_PATH" > >(tee -a "$TMP_OUTPUT") 2>&1 &
fi
RUNNER_PID=$!
printf '%s
' "$RUNNER_PID" >"$RUNNER_PID_FILE"
set +e
wait "$RUNNER_PID"
rc=$?
set -e
rm -f "$RUNNER_PID_FILE"
classification="$(classify_ob_failure "$TMP_OUTPUT")"
case "$classification" in
  clean_shutdown)
    log "sync runner exited due to clean shutdown"
    exit 0
    ;;
  terminal_auth)
    write_incident_log 'auth-terminal-failure' terminal_auth "$TMP_OUTPUT"
    set_terminal_stop_flag 'auth-terminal-failure' terminal_auth "see ${LAST_INCIDENT_LOG:-incident log}"
    exit "$TERMINAL_AUTH_RC"
    ;;
  terminal_config)
    write_incident_log 'sync-config-terminal-failure' terminal_config "$TMP_OUTPUT"
    set_terminal_stop_flag 'sync-config-terminal-failure' terminal_config "see ${LAST_INCIDENT_LOG:-incident log}"
    exit "$TERMINAL_CONFIG_RC"
    ;;
  *)
    write_incident_log 'sync-transient-failure' transient "$TMP_OUTPUT"
    log "transient sync failure (rc=$rc); allowing systemd retry"
    exit "${rc:-75}"
    ;;
esac
