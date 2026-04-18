#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/obsidian_sync_common.sh"

export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new}"

HOST_LABEL="${HOST_LABEL:-$(hostname -s 2>/dev/null || echo local-host)}"
VAULT_PATH="${VAULT_PATH:-}"
GIT_DIR_PATH="${GIT_DIR_PATH:-$HOME/.local/share/obsidian-vault-backup.git}"
REMOTE_URL="${REMOTE_URL:-git@github-obsidian-backup:hamanpaul/obsidian_vault.git}"
BRANCH_NAME="${BRANCH_NAME:-main}"
STATE_DIR="${STATE_DIR:-$HOME/.local/state/obsidian-automation}"
LOG_PATH="${LOG_PATH:-$STATE_DIR/obsidian-git-backup.log}"
BOOTSTRAP_FORCE_PUSH="${BOOTSTRAP_FORCE_PUSH:-yes}"
GIT_USER_NAME="${GIT_USER_NAME:-$(git config --global user.name 2>/dev/null || echo haman)}"
GIT_USER_EMAIL="${GIT_USER_EMAIL:-$(git config --global user.email 2>/dev/null || echo "$(id -un)@$HOST_LABEL.local")}"
NO_CHANGES_RC=10

mkdir -p "$STATE_DIR" "$(dirname "$GIT_DIR_PATH")"
exec >>"$LOG_PATH" 2>&1

log() { printf '[%s] %s
' "$(date --iso-8601=seconds)" "$*"; }
die() { log "ERROR: $*"; exit 1; }
git_vault() { git --git-dir="$GIT_DIR_PATH" --work-tree="$VAULT_PATH" "$@"; }

resolve_vault_path() {
  if [ -n "${VAULT_PATH:-}" ]; then
    return 0
  fi
  if ! resolve_sync_config; then
    die "could not resolve sync config: ${RESOLVE_SYNC_CONFIG_ERROR:-unknown}"
  fi
  VAULT_PATH="$LOADED_VAULT_PATH"
}

[ -d "$HOME" ] || die "home path missing: $HOME"
resolve_vault_path
[ -d "$VAULT_PATH" ] || die "vault path missing: $VAULT_PATH"
command -v git >/dev/null 2>&1 || die "git not found"
command -v ssh >/dev/null 2>&1 || die "ssh not found"

sync_is_healthy() {
  if systemctl --user --quiet is-active obsidian-sync.service; then
    return 0
  fi
  log "skip backup: obsidian-sync.service is not active"
  return 1
}

git_dir_is_valid() {
  git --git-dir="$GIT_DIR_PATH" rev-parse --git-dir >/dev/null 2>&1
}

ensure_git_repo() {
  local initialized=0
  if ! git_dir_is_valid; then
    if [ -e "$GIT_DIR_PATH" ]; then
      log "resetting invalid external git dir: $GIT_DIR_PATH"
      rm -rf "$GIT_DIR_PATH"
    else
      log "initializing external git dir: $GIT_DIR_PATH"
    fi
    mkdir -p "$GIT_DIR_PATH"
    git --git-dir="$GIT_DIR_PATH" init --initial-branch "$BRANCH_NAME"
    initialized=1
  fi

  git_vault config core.worktree "$VAULT_PATH"
  git_vault config core.bare false
  git_vault config user.name "$GIT_USER_NAME"
  git_vault config user.email "$GIT_USER_EMAIL"
  git_vault config gc.auto 0

  if git_vault remote get-url origin >/dev/null 2>&1; then
    git_vault remote set-url origin "$REMOTE_URL"
  else
    git_vault remote add origin "$REMOTE_URL"
  fi

  echo "$initialized"
}

ensure_gitignore() {
  local gitignore="$VAULT_PATH/.gitignore"
  touch "$gitignore"
  local entry
  for entry in     '.obsidian/.sync.lock'     '.obsidian/.copilot-lock-test'
  do
    grep -Fxq "$entry" "$gitignore" || printf '%s
' "$entry" >>"$gitignore"
  done
}

remote_head_ref() {
  git_vault ls-remote --heads origin "$BRANCH_NAME" 2>/dev/null | awk 'NR==1 {print $1}'
}

has_remote_branch() {
  [ -n "$(remote_head_ref)" ]
}

has_upstream() {
  git_vault rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1
}

needs_push() {
  local local_head remote_head
  local_head="$(git_vault rev-parse --verify HEAD 2>/dev/null || true)"
  if [ -z "$local_head" ]; then
    log "no local commit yet"
    return 1
  fi

  remote_head="$(remote_head_ref)"
  if [ -n "$remote_head" ] && [ "$remote_head" = "$local_head" ]; then
    log "remote already matches local HEAD"
    return 1
  fi

  return 0
}

commit_changes() {
  local ts
  ts="$(date --iso-8601=seconds)"

  if ! git_vault add -A; then
    return 20
  fi

  if git_vault diff --cached --quiet; then
    log "no changes to commit"
    return "$NO_CHANGES_RC"
  fi

  log "creating backup commit at $ts"
  if ! git_vault commit     -m "backup: vault snapshot $ts"     -m "Automated backup from $HOST_LABEL after Obsidian Sync."     -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"; then
    return 30
  fi
}

push_changes() {
  local bootstrap="$1"
  local remote_head=""
  if has_remote_branch; then
    remote_head="$(remote_head_ref)"
  fi

  if [ -n "$remote_head" ] && [ "$BOOTSTRAP_FORCE_PUSH" = "yes" ] && { [ "$bootstrap" = "1" ] || ! has_upstream; }; then
    log "force-aligning remote $BRANCH_NAME from local bootstrap"
    git_vault push --force-with-lease="$BRANCH_NAME:$remote_head" -u origin "$BRANCH_NAME"
    return 0
  fi

  if [ -n "$remote_head" ]; then
    log "pushing backup commit to origin/$BRANCH_NAME"
    git_vault push -u origin "$BRANCH_NAME"
  else
    log "pushing first backup branch to origin/$BRANCH_NAME"
    git_vault push -u origin "$BRANCH_NAME"
  fi
}

main() {
  local bootstrap commit_rc=0

  if ! sync_is_healthy; then
    exit 0
  fi

  bootstrap="$(ensure_git_repo)"
  ensure_gitignore

  commit_changes || commit_rc=$?
  if [ "$commit_rc" -ne 0 ] && [ "$commit_rc" -ne "$NO_CHANGES_RC" ]; then
    die "git commit phase failed (rc=$commit_rc)"
  fi

  if ! needs_push; then
    exit 0
  fi

  push_changes "$bootstrap"
  log "git backup completed"
}

main
