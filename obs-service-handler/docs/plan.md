# Plan snapshot

## 目標

把 `orangepi3` 上目前正在使用的 Obsidian sync 背景服務整理成可追蹤、可重用、可重新部署的一份 repo 內容，放到 `custom-claw-tools/obs-service-handler/`。

## 這幾輪工作的脈絡

### 1. PicoClaw model-switch 修復

- 修掉 `/switch model to gemini-3-flash-lite` 的壞路徑
- 補上 `openclaw` 端的 normalization / regression test
- live device 上把 `flash-lite` alias 收斂到穩定配置

### 2. Telegram session 盤點與 backlog 整理

- 從 PicoClaw 本地持久化 session 盤出實際對話
- 整理後續待辦與阻塞項

### 3. Obsidian sync hardening

- auth fail-close（只對明確 token / login / 401 / 403 類錯誤）
- path source-of-truth 改成 `obsidian-headless` sync config
- zombie / lock / runner mismatch 偵測
- incident log 寫到 `~/.picoclaw/workspace/ob-log/{date-time}.log`
- healthcheck 改成用 matching runners 來判定 active runner

## 這次 repo 匯出的內容

- `systemd/`：目前實機使用中的 unit / timer
- `bin/`：目前實機使用中的 helper scripts
- `README.md`：部署、使用、依賴元件說明
- `docs/plan.md`：本檔，記錄這幾輪工作的 plan snapshot
- `docs/todo.md`：記錄這幾輪工作的 todo snapshot

## 驗證摘要

- config source-of-truth 已驗證：
  - `config_file=/home/haman/.config/obsidian-headless/sync/cd1f2e7aef3c5227a8fc0c74b13808f9/config.json`
  - `vault_path=/home/haman/.picoclaw/workspace/notes`
- auth fail-close dry-run 已驗證：
  - 缺 token 時 `obsidian_sync_guard.sh` 回傳 `rc=41`
  - 會寫 terminal stop flag 與 incident log
- manual healthcheck 最新結果為 `health ok`
- `obsidian-sync.service` 最新狀態為：
  - `ActiveState=active`
  - `SubState=running`
  - `Result=success`
  - `NRestarts=0`

## 匯出後續

- 在 `orangepi3` 上建立 first commit
- 若 `orangepi3` 無法直接連到 GitHub，先保留本地 commit，再由其他可連外環境協助 push
