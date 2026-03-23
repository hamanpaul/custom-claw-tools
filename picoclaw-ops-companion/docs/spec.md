# Specification

## 1. 系統目標

`picoclaw-ops-companion` 的目標是提供一個受控的 backend execution layer，讓 PicoClaw 能在不擴權的情況下，安全地驅動系統向任務與研究工作。

## 2. 非目標

以下項目不在 MVP 目標內：

- 直接讓 Copilot backend 擁有 Telegram bot 身份
- 將所有 shell 指令都暴露給使用者自由輸入
- 讓 PicoClaw 直接跳出 workspace 執行未受控動作
- 依賴 root / sudo 作為日常操作基礎

## 3. 核心角色

### 使用者

- 從 Telegram 發起 request
- 對高風險任務做最終核准

### PicoClaw

- 收 request
- 顯示 approval job
- relay `/approve` / `/reject`
- 回報執行摘要

### Companion backend

- 驗證 schema
- 風險分級
- 2FA 驗證
- 建立 Copilot session
- 執行 allowlisted 任務
- 保存 result / audit

## 4. Request 模型

MVP request 應使用結構化格式，而不是自由 prompt：

```json
{
  "requestId": "req-20260323-001",
  "type": "github_research",
  "scope": "repo",
  "target": {
    "repo": "owner/name"
  },
  "payload": {
    "query": "open issues about serialwrap prompt timeout"
  },
  "requestedBy": "telegram:<PRIMARY_USER_ID>"
}
```

### MVP request types

- `github_research`
- `repo_relay_push`
- `npm_install_package`
- `workspace_analysis`

## 5. Risk classification

### Low

- 只讀 research
- 不改檔、不對外發送、不安裝套件

### Medium

- 寫 workspace artifact
- 建立 bundle、產生本地檔案

### High

- `git push`
- `npm install -g` 或改變使用者環境
- 廣域 shell 或碰觸 workspace 外 repo
- 任何對外發送與狀態改變動作

## 6. Approval job 模型

高風險任務需先生成 approval job：

```json
{
  "jobId": "job-20260323-001",
  "requestId": "req-20260323-001",
  "risk": "high",
  "summary": {
    "action": "git push origin main",
    "cwd": "/home/haman/custom-claw-tools/picoclaw-ops-companion",
    "sideEffects": ["remote write"]
  },
  "nonce": "A7K9",
  "ttlSeconds": 300,
  "status": "pending"
}
```

## 7. 2FA 與 approval 流程

### 第一因子

- Telegram sender allowlist

### 第二因子

- 使用者手機上的 TOTP

### 核准命令

```text
/approve <job-id> <totp>
```

### 驗證條件

- sender 正確
- job 存在且狀態為 pending
- 未逾時
- TOTP 驗證成功
- nonce / job 綁定仍有效
- job 未被使用過

### 拒絕命令

```text
/reject <job-id>
```

## 8. Copilot session policy

每個 request 不直接繼承全域權限，而是依 task type 決定：

- `cwd`
- `availableTools`
- `excludedTools`
- 可存取路徑
- 可使用的 wrappers

### 範例

`github_research`：

- 允許：`gh` 查詢、受限 web / MCP
- 禁止：`git push`、`npm install`、廣域 shell

`repo_relay_push`：

- 允許：bundle 檢查、git remote 查詢、經 approval 後的 push wrapper
- 禁止：任意 shell

## 9. Artifact 與 storage

MVP 預計使用 workspace 內的結構化目錄：

```text
notes/ops-companion/
  requests/
  approvals/
  results/
  logs/
```

每次 request 都應產生：

- request artifact
- decision / risk artifact
- result artifact
- audit log

## 10. GitHub 與 network fallback

若 pi3 無法直連 GitHub：

- companion 在 pi3 產出 bundle / artifact
- 外部 relay 協助 push / fetch / research
- 整體流程仍需寫入 audit

## 11. 部署模型

MVP 傾向：

- user-level process 或 user-level service
- 以 TypeScript / Node.js 執行
- 初期可先用手動啟動驗證，再補 systemd user service

## 12. 可觀測性

至少應有：

- request log
- approval log
- execution log
- error log
- result summary
- relay fallback log
