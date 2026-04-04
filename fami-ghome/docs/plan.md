# fami-ghome 計畫

## Summary

此計畫把 `fami-ghome` 拆成五個落地階段，目標是讓 Famiclean 熱水器能以 `Google Home Developer Console -> Cloud-to-cloud -> Local Home` 的標準路徑接入 Google Home。

計畫預設：

- `單一家庭 / 單一設備 / 單一管理帳號`
- 主部署路徑為 `Orangepi3 + Picoclaw`
- `famiclean-skill` 保持為唯一 UDP driver
- `fami-ghome` 先做 Google 橋接與 credential 邊界管理

## Phase 0：Repo 與設定整備

### 目標

建立可安全開發的 repo 骨架，先把 secret 邊界、忽略規則與設定模板固定下來。

### 工作

- 建立 `fami-ghome/.gitignore`
- 建立 `fami-ghome/config/.env.example`
- 定義 `config/`, `data/`, `logs/` 的責任
- 把 `Google Home Developer Console` 與 `Nest Device Access / SDM` 的用途明確切開
- 確認 `fami-ghome` 只經由 `famiclean-skill` wrapper 控制熱水器

### Exit criteria

- 真實 credential 不會被誤提交
- 所有必要 env keys 都有 template
- 後續實作者不需要再自行決定 secret 放哪裡

## Phase 1：Cloud fulfillment 與 OAuth

### 目標

做出最小可用的 cloud-to-cloud service，支援 account linking 與 Google intents。

### 工作

- 建立 HTTP service
- 實作 `GET /oauth/authorize`
- 實作 `POST /oauth/token`
- 實作 `POST /fulfillment`
- 建立 authorization code、access token、refresh token 的 state store
- 單戶自用授權頁只接受一組本地管理帳號
- 將 `read-temp` / `set-temp` 映射到 Google `QUERY` / `EXECUTE`

### Exit criteria

- 可以在本機以 mock 或真實 wrapper 跑完整 OAuth code flow
- `SYNC`, `QUERY`, `EXECUTE` 都能回傳合法 payload
- 超出溫度範圍與 wrapper 錯誤有明確錯誤碼

## Phase 2：Google Home 接入

### 目標

讓 `fami-ghome` 正式出現在 Google Home 測試清單中並可完成 linking。

### 工作

- 在 `Google Home Developer Console` 建立 `Cloud-to-cloud` integration
- 設定 app name、icon、account linking、fulfillment URL
- 將 `ACCOUNT_LINKING_CLIENT_ID / SECRET` 填入 console
- 在 Google Home app 搜尋 `[test] <Display Name>` 並完成 linking
- 跑 `Google Home Test Suite`

### Exit criteria

- Google Home app 能看到測試中的熱水器
- 可以從 Google Home App 與語音發出設溫指令
- Google 後台測試至少通過 `SYNC`, `QUERY`, `EXECUTE` 主路徑

## Phase 3：Local Home

### 目標

在 cloud flow 已穩定的前提下，加入本地執行路徑降低延遲。

### 工作

- 在 `SYNC` 中加入 local metadata
- 建立 local fulfillment app
- 讓 local app 委派到同機 `famiclean-skill`
- 驗證 Nest Mini / Google Home hub 與 Orangepi3 同網段時可走 local path
- 驗證 local path 失敗時能自動回退 cloud path

### Exit criteria

- 同網段環境下至少一次成功走 local execute
- Local Home 失敗時不影響原本 cloud control

## Phase 4：部署與營運

### 目標

把 `fami-ghome` 變成可持續運作的服務，而不是開發機上的臨時程式。

### 工作

- Orangepi3 上建立 service 啟動方式
- 定義與 Picoclaw 的整合邊界
- 提供 Dockerfile 與容器部署說明
- 定義 HTTPS 暴露方式
- 定義 log、healthcheck、token/state 備份與權限規範

### Exit criteria

- Orangepi3 可開機自動啟動
- Docker 版能在固定 env / mount 下啟動
- secret 不出現在 process list、image layer、repo

## Phase 5：後續擴充

### 目標

保留未來可擴展方向，但不阻塞第一版上線。

### 工作

- 評估是否加入 `OnOff`
- 評估是否加入 `Report State` / `Request Sync`
- 評估是否把 gas usage 以非 Google 原生 UI 方式呈現
- 評估從單戶自用升級到多帳號模型時的重構成本

### Exit criteria

- 後續風險與擴充點被清楚列在 `docs/todo.md`
