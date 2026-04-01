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
- 執行模式：以 pi3 使用者態為主；目前已提供 `127.0.0.1` loopback listener，Copilot SDK session 仍以本機 process / CLI server 執行
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
  skills/
    ops-companion/
      SKILL.md
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

### 啟動 loopback listener

如果要讓其他本機程序（例如 PicoClaw relay / wrapper）透過 `127.0.0.1` 打 companion，可直接啟動：

```bash
npm run dev -- listen --host 127.0.0.1 --port 45450
```

可用 endpoint：

- `GET /health`
- `POST /intake`
- `POST /decision`
- `POST /execute`

### PicoClaw relay wrapper（Phase 1 bridge）

如果要讓 live PicoClaw 直接走 companion，而不是手組 `curl`，可用 repo 內的 relay wrapper：

```bash
cd /home/haman/custom-claw-tools/picoclaw-ops-companion
chmod +x bin/picoclaw-ops-relay
```

目前支援：

- `health`
- `status --request-id <request-id>`
- `execute --request-id <request-id>`
- `decision --sender <telegram:id> --text "</approve ...>" [--auto-execute]`
- `intake-file --request-file <path> [--auto-execute]`
- `intake-json --request-json <json> [--auto-execute]`
- `workspace-analysis --sender <telegram:id> --path <path> --prompt <text> [--scope <notes|workspace|repo>] [--write-artifacts] [--request-id <request-id>] [--no-execute]`
- `github-research --sender <telegram:id> --query <text> [--scope <repo|org|user|global>] [--repo <owner/name>] [--owner <owner>] [--mode <generic|issues|pull_requests|code|repositories>] [--limit <n>] [--request-id <request-id>] [--no-execute]`
- `repo-relay-push --sender <telegram:id> --repo-path <path> [--remote <name>] [--branch <name>] [--revision <rev>] [--transport <relay|bundle>] [--request-id <request-id>] [--no-execute]`
- `npm-install-package --sender <telegram:id> --project-path <path> --package <name> [--package <name> ...] [--scope <project|user>] [--dev] [--global] [--request-id <request-id>] [--no-execute]`

範例：直接讓 companion 分析目前 notes tree（low risk，會自動 `intake -> execute`）：

```bash
bin/picoclaw-ops-relay workspace-analysis \
  --sender telegram:<PRIMARY_USER_ID> \
  --path /home/haman/.picoclaw/workspace/notes \
  --prompt "Summarize the top-level notes layout for troubleshooting."
```

範例：直接走 GitHub research（low risk，會自動 `intake -> execute`）：

```bash
bin/picoclaw-ops-relay github-research \
  --sender telegram:<PRIMARY_USER_ID> \
  --repo hamanpaul/custom-claw-tools \
  --query "recent obs-auto-moc and ops-companion related commits" \
  --mode code
```

範例：relay `/approve` 指令，並在批准後自動接 `execute`：

```bash
bin/picoclaw-ops-relay decision \
  --sender telegram:<PRIMARY_USER_ID> \
  --text "/approve <job-id> 123456" \
  --auto-execute
```

wrapper 會回傳：

- 原始 `request` / `intake` / `decision` / `execute`
- `status` summary（包含 request/result/approval/audit artifact paths）

helper wrappers 另外也已補齊：

- `ops-repo-relay-push`
- `ops-npm-install-package`

目前已驗證的可用鏈路：

- `workspace_analysis`
- `github_research`
- `repo_relay_push`
- `npm_install_package`

其中：

- `repo_relay_push`
  - `transport=relay`：會真的執行 `git push`
  - `transport=bundle`：會產出 `.bundle` artifact 供後續 relay / handoff
- `npm_install_package`
  - `scope=project`：可直接執行專案內 `npm install`
  - `scope=project` 不可搭配 `--global`
  - `scope=user` 必須搭配 `--global`，且仍需 approval，批准後才執行

也就是說：

- `--scope project --global` 是無效組合
- `--scope user` 若沒帶 `--global` 也會被拒絕

### PicoClaw MCP bridge

pi3 live gateway 現在也可直接透過 MCP 連到 companion：

- MCP server wrapper：`bin/picoclaw-ops-mcp`
- PicoClaw 看到的工具名稱格式：`mcp_opscompanion_<tool>`

目前 MCP 工具有：

- `mcp_opscompanion_health`
- `mcp_opscompanion_notes_analysis`
- `mcp_opscompanion_workspace_analysis`
- `mcp_opscompanion_github_research`
- `mcp_opscompanion_repo_relay_push`
- `mcp_opscompanion_npm_install_package`
- `mcp_opscompanion_approve_job`
- `mcp_opscompanion_reject_job`
- `mcp_opscompanion_request_status`
- `mcp_opscompanion_execute_request`

live 驗證狀態：

- pi3 gateway 已完成 `initialize -> tools/list`
- 顯式 MCP smoke 已驗證 `health`
- 自然語言 heartbeat smoke 已驗證會選到 `workspace_analysis`
- high-risk request 現在也可直接透過 MCP 建立 approval job
- pi3 直接 MCP smoke 已驗證 `repo_relay_push -> approve_job -> ready_for_execution`

MCP server 目前同時支援：

- PicoClaw stdio transport 使用的 ndjson framing
- 傳統 `Content-Length` framing smoke 測試

這個相容性很重要，因為 live PicoClaw stdio MCP client 實際上是走 newline-delimited JSON。

最簡單的 health probe：

```bash
curl http://127.0.0.1:45450/health
```

### 讓 loopback listener 開機常駐

repo 內提供 user-level systemd unit：

- `systemd/picoclaw-ops-companion-listener.service`
- `bin/picoclaw-ops-companion-listen`

部署到 pi3 後可用：

```bash
cd /home/haman/custom-claw-tools/picoclaw-ops-companion
chmod +x bin/picoclaw-ops-companion-listen
cp systemd/picoclaw-ops-companion-listener.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now picoclaw-ops-companion-listener.service
```

驗證：

```bash
systemctl --user status picoclaw-ops-companion-listener.service
curl http://127.0.0.1:45450/health
```

範例：把 request 丟進 loopback intake

```bash
curl -X POST http://127.0.0.1:45450/intake \
  -H 'content-type: application/json' \
  --data @request.json
```

### TOTP secret 工具

最簡單的做法，直接一步到位產生並寫入 `~/.config/picoclaw-ops-companion/totp.secret`：

```bash
npm run totp-gen -- --account-name PaulClaw
```

這個指令會：

- 產生新的 base32 secret
- 建立 `~/.config/picoclaw-ops-companion/`
- 把 secret 寫到 `~/.config/picoclaw-ops-companion/totp.secret`
- 把目錄權限收斂到 `0700`
- 把 secret file 權限收斂到 `0600`
- 同時把 `otpauth://`、manual entry 參數、secret file 路徑印到 stdout

如果 `totp.secret` 已經存在，`totp-gen` 會**預設拒絕覆蓋**，避免你不小心把手機上已經在用的 2FA secret 換掉。

真的要換掉舊 secret 時，再明確加：

```bash
npm run totp-gen -- --account-name PaulClaw --force
```

如果你想用自己先產生好的 base32 secret，也可以直接一步寫入：

```bash
npm run totp-gen -- --account-name PaulClaw --secret <YOUR_BASE32_SECRET>
```

如果你只想看 provisioning JSON、**不想落檔**，才用原本的 `totp`：

```bash
npm run dev -- totp --account-name PaulClaw
```

這個工具會輸出：

- 正規化後的 base32 secret
- `otpauth://` URI
- Authenticator app 手動輸入所需參數
- 建議的 secret file 路徑
- 建議使用的 env 名稱：`PAULCALW_SECRET`

#### 建議的實際操作步驟（從零開始）

1. 在 pi 上進到專案目錄：

```bash
cd /home/haman/custom-claw-tools/picoclaw-ops-companion
```

2. 一步產生並寫入 secret file：

```bash
npm run totp-gen -- --account-name PaulClaw
```

3. 指令輸出會直接告訴你：

- `secretFile.path`
- `secret`
- `otpauthUri`
- `manualEntry`

4. 在手機 Authenticator app 加入新的 TOTP：

- 若 app 支援手動輸入：
  - 帳號名稱：可自訂，例如 `PaulClaw`
  - secret：填剛剛輸出的 `secret`
  - 類型：`TOTP`
  - 演算法：`SHA1`
  - 位數：`6`
  - 週期：`30`
- 若 app 支援 `otpauth://` 匯入，則可使用輸出裡的 `otpauthUri`

5. 存好 `~/.config/picoclaw-ops-companion/totp.secret` 之後，companion 會**預設自動從這個檔案讀 secret**，所以通常**不需要再手動 `export PAULCALW_SECRET=...`**

6. 只有在你想臨時覆蓋 secret、或做特殊除錯時，才需要用 env：

```bash
export PAULCALW_SECRET="$(cat ~/.config/picoclaw-ops-companion/totp.secret)"
```

7. 之後收到高風險 approval job 時，就能用手機 App 上顯示的 6 位數 TOTP 回：

```text
/approve <job-id> <totp>
```

#### 進階模式：只輸出、不落檔

如果你只是想先看 JSON、不想直接寫入 `~/.config`，才用這個：

```bash
npm run dev -- totp --account-name PaulClaw
```

### 高風險任務

- companion 先建立 approval job JSON
- PicoClaw 可直接取用其中的 `/approve <job-id> <totp>` 與 `/reject <job-id>`
- 可透過 relay command 進一步處理：

```bash
npm run dev -- decision --sender telegram:<PRIMARY_USER_ID> --text "/approve <job-id> 123456"
npm run dev -- decision --sender telegram:<PRIMARY_USER_ID> --text "/reject <job-id>"
```

- `approve` 會優先讀 `~/.config/picoclaw-ops-companion/totp.secret`，也仍支援 `PAULCALW_SECRET` / `PICOCLAW_TOTP_SECRET`
- 高風險 request 現在可透過 relay 或 MCP 建立 approval job
- 高風險 execution layer 已實作：
  - `repo_relay_push` 可執行 `relay` push 或產生 `bundle` artifact
  - `npm_install_package` 可執行專案 scope install，user/global install 仍需 approval
### 低風險 execution（目前支援 `workspace_analysis` 與 `github_research`）

```bash
npm run dev -- execute --request-id <request-id>
```

- `workspace_analysis` 仍走本地 deterministic wrapper
- `github_research` 會建立受限的 GitHub Copilot SDK session，並只放行 companion 自訂的 read-only GitHub search tool
- 已支援的 request type 會寫出 result / artifact / audit；不支援的 request type 仍會明確回報失敗，不會假裝成功

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
- `skills/ops-companion/SKILL.md`：repo 內追蹤的 PicoClaw skill 文案，對應 live `~/.picoclaw/workspace/skills/ops-companion/SKILL.md`
