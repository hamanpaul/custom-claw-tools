# Delivery todo

## Phase 0：docs-first

- 建立 `picoclaw-ops-companion/`
- 撰寫 `README.md`
- 撰寫 `docs/plan.md`
- 撰寫 `docs/spec.md`
- 撰寫 `docs/todo.md`
- 從 pi3 commit
- push 到 GitHub（必要時 relay）

## Phase 1：runtime bootstrap

- 初始化 `package.json`
- 安裝 TypeScript 與 GitHub Copilot SDK
- 建立 `tsconfig.json`
- 建立 `src/` 骨架
- 建立 lint / build / run 指令
- 建立 config loading 與 log helper

## Phase 2：request intake 與 policy

- 定義 request schema
- 定義 task types
- 定義 risk classifier
- 定義 approval job schema
- 定義 artifact storage layout

## Phase 3：2FA 與 Telegram relay

- 定義 TOTP secret provisioning 方式
- 實作 approval job TTL / nonce / replay 防護
- 實作 `/approve` / `/reject` 解析
- 定義 PicoClaw relay 到 backend 的介面
- 定義 approval summary 格式

## Phase 4：Copilot execution layer

- 建立 Copilot SDK client / session helper
- 定義 `availableTools` / `excludedTools`
- 建立 allowlisted wrappers
- 串接 `git` / `gh` / `npm` / research flows
- 實作 failure handling 與 audit logging

## Phase 5：validation

- 驗證低風險 read-only research
- 驗證高風險 approval / reject
- 驗證 `npm install agent-browser`
- 驗證 GitHub repo relay push
- 驗證錯誤路徑與 replay 防護

## Phase 6：deployment

- 決定是手動啟動還是 user-level service
- 補部署說明
- 補操作手冊
- 補 incident / troubleshooting notes
