# picoclaw-ops-companion

`picoclaw-ops-companion` 是一個放在 `custom-claw-tools` 內的 companion 專案，目標是在**不改變 PicoClaw 權限**的前提下，補上系統向工作與研究任務的安全執行面。

它的定位不是替 PicoClaw 擴權，而是把職責拆成兩層：

- `PicoClaw`：Telegram 對話入口、需求整理、approval relay、結果摘要
- `picoclaw-ops-companion`：受控的 backend executor，負責 request 驗證、2FA、Copilot session 建立、工具執行與 audit

## 為什麼需要這個專案

目前 live PicoClaw 受到 workspace/policy 邊界限制，不適合直接做以下任務：

- `npm` 安裝或管理使用者態套件
- `git` / `gh` research 與 repository 維運
- 需要跳出 PicoClaw workspace 的檔案與 repo 操作
- 需要較強審計與 approval 的高風險任務

與其擴大 PicoClaw 權限，這個專案改採「front desk + backend executor」模型，讓 PicoClaw 保持保守權限，而把高能力操作移到 companion backend。

## 架構概要

1. 使用者透過 Telegram 對 PicoClaw 發起任務。
2. PicoClaw 只接受結構化 request，將任務交給 companion。
3. companion 對 request 做 schema 驗證、風險分級與 policy 判定。
4. 低風險任務可直接進入受限的 Copilot session 或 wrapper。
5. 高風險任務會先產生 approval job。
6. PicoClaw 透過 Telegram 把 approval job 發回給使用者。
7. 使用者以 `/approve <job-id> <totp>` 或 `/reject <job-id>` 回覆。
8. companion 驗證 Telegram sender、TOTP、nonce、TTL、job 綁定後，才真正執行。
9. companion 將結果、audit log、錯誤資訊寫回 workspace，供 PicoClaw 摘要回報。

## 角色分工

### PicoClaw

- 保持唯一對外 bot 身份
- 接收使用者請求
- 顯示 approval job 摘要
- 轉送 `/approve` / `/reject`
- 讀取 companion 結果並摘要給使用者

### Companion server

- 驗證 request schema
- 套用風險分級與 allowlist policy
- 管理 approval job 與 2FA
- 建立 GitHub Copilot SDK session
- 執行 `git` / `gh` / `npm` / research 任務
- 寫出 result / log / audit artifact

## 安全原則

- 不將原始自由文字直接 passthrough 成 Copilot prompt
- 只接受明確定義的 request schema
- 高風險任務一定需要 approval job
- 2FA 固定採：Telegram sender allowlist + TOTP
- approval 必須綁定 job id、nonce、TTL、job hash
- backend 不直接在 Telegram 對外發話
- Copilot session 必須限制 `availableTools` / `excludedTools`
- 預設拒絕危險操作，例如廣域 shell、`rm`、`chmod`、未核准的 `git push`

## 技術方向

- 語言：Node.js / TypeScript
- AI runtime：GitHub Copilot SDK
- 執行模式：以 pi3 使用者態為主，優先使用本機 `stdio`，必要時才考慮 loopback server
- Approval channel：沿用 PicoClaw Telegram channel
- 目標 repo：`/home/haman/custom-claw-tools/picoclaw-ops-companion`

## 預計目錄結構

```text
picoclaw-ops-companion/
  README.md
  docs/
    plan.md
    spec.md
    todo.md
  src/
  package.json
  tsconfig.json
```

## 使用方式（目前 MVP slice）

### 初始化目錄

```bash
npm run dev -- bootstrap
```

### Intake 結構化 request

```bash
npm run dev -- intake --request ./request.json
```

也可以從 stdin 讀入：

```bash
cat request.json | npm run dev -- intake --request -
```

當前會完成：

- request schema 驗證
- risk classification
- approval job 生成（僅 high risk）
- request / decision / result / audit artifact 落盤
- `execute --request-id` 可執行已處於 `ready_for_execution` 的 request

### 高風險任務

- companion 先建立 approval job JSON
- PicoClaw 可直接取用其中的 `/approve <job-id> <totp>` 與 `/reject <job-id>`
- 可透過 relay command 進一步處理：

```bash
npm run dev -- decision --sender telegram:<PRIMARY_USER_ID> --text "/approve <job-id> 123456"
npm run dev -- decision --sender telegram:<PRIMARY_USER_ID> --text "/reject <job-id>"
```

- `approve` 需要配置 `PICOCLAW_TOTP_SECRET`
- 真正執行 layer 仍在下一個 Milestone 串接

### 低風險 execution（目前支援 `workspace_analysis`）

```bash
npm run dev -- execute --request-id <request-id>
```

- 目前真的有實作的 allowlisted execution wrapper 是 `workspace_analysis`
- 其他 request type 會明確寫回 `not implemented`，不會假裝成功

## 部署與前置需求

- pi3 已安裝並可使用：`git`、`gh`、`node`、`npm`、`copilot`
- 需要在使用者手機上配置 TOTP authenticator
- `gh auth` 需要補修復或提供 relay fallback
- 若 GitHub 直推不通，保留 bundle / relay push 流程

## 已知限制

- Copilot SDK 目前仍屬 technical preview
- ACP / server 模式仍有 preview 性質
- pi3 對 GitHub 直連可能不穩，push 需要 fallback
- serialwrap 仍有 prompt timeout 問題，實機開發需保守操作

## 文件導覽

- `docs/plan.md`：實作分階段計畫
- `docs/spec.md`：整體系統規格與資料模型
- `docs/todo.md`：落地工作拆解
