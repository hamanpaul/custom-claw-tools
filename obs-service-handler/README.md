# obs-service-handler

`obs-service-handler` 是從 `orangepi3` 目前正在運作的 Obsidian sync 背景服務匯出的可部署快照，目的是把 `ob sync --continuous` 相關的 user-level systemd unit、helper script、incident log hardening 與部署文件集中管理。

## 目錄結構

- `bin/`
  - `obsidian_sync_common.sh`
  - `obsidian_sync_guard.sh`
  - `obsidian_sync_healthcheck.sh`
  - `obsidian_git_backup.sh`
- `systemd/`
  - `obsidian-sync.service`
  - `obsidian-sync-healthcheck.service`
  - `obsidian-sync-healthcheck.timer`
  - `obsidian-git-backup.service`
  - `obsidian-git-backup.timer`
- `docs/`
  - `plan.md`
  - `todo.md`

## 依賴元件

部署前請先確認以下元件已安裝：

- Linux（需支援 user-level systemd）
- `git`
- Node.js（目前實機是 `v22.x`）
- `obsidian-headless`，也就是 `ob` CLI
  - 範例：`npm install -g obsidian-headless`
- `~/.config/obsidian-headless/auth_token`
- `~/.config/obsidian-headless/sync/<vault-id>/config.json`
- 若要啟用 Git backup，還需要可用的 GitHub SSH key / repo 權限

目前 `orangepi3` 上的 `ob` 位置是：

- `/home/haman/.nvm/versions/node/v22.20.0/bin/ob`

## 部署方式

1. 把 `bin/*.sh` 複製到 `~/.local/bin/`
2. 把 `systemd/*.service` 與 `systemd/*.timer` 複製到 `~/.config/systemd/user/`
3. 確認 `obsidian-headless` 的 sync config 已存在，且 `vaultPath` 正確
4. 重新載入 user systemd：
   - `systemctl --user daemon-reload`
5. 啟用服務 / timer：
   - `systemctl --user enable --now obsidian-sync.service`
   - `systemctl --user enable --now obsidian-sync-healthcheck.timer`
   - 若需要 Git backup，再啟用 `obsidian-git-backup.timer`

## 使用與驗證

常用檢查指令：

- `systemctl --user status obsidian-sync.service`
- `systemctl --user status obsidian-sync-healthcheck.timer`
- `tail -f ~/.local/state/obsidian-automation/obsidian-sync-guard.log`
- `tail -f ~/.local/state/obsidian-automation/obsidian-sync-healthcheck.log`
- `systemctl --user start obsidian-sync-healthcheck.service`

incident log 會寫到：

- `~/.picoclaw/workspace/ob-log/`

## 目前 hardening 行為

- vault path 一律從 `~/.config/obsidian-headless/sync/*/config.json` 解析
- 明確 auth/config 失敗會 fail-close
- terminal auth/config failure 會透過 `RestartPreventExitStatus=41 42` 停止無限重啟
- healthcheck 會檢查：
  - service inactive
  - main pid / runner pid 不存在
  - zombie process
  - lock / runner mismatch
  - active runner 與 loaded vault path 是否一致
- incident log 會包含：
  - config file
  - loaded vault path
  - main pid / runner pid / process state
  - matching runners
  - lock path / lock age / lock stat
  - detail tail

## 實機部署備註

目前 `orangepi3` 的有效 vault path 是：

- `/home/haman/.picoclaw/workspace/notes`

目前 `orangepi3` 的 source-of-truth sync config 是：

- `/home/haman/.config/obsidian-headless/sync/cd1f2e7aef3c5227a8fc0c74b13808f9/config.json`

另外，這輪維運過程也確認 `serialwrap` 在日常操作下仍可能掉到 `ATTACHED/PROMPT_TIMEOUT`；相關追蹤已開在：

- `hamanpaul/serialwrap#14`
