# Implementation plan

## 目標

在不調整 PicoClaw 權限的前提下，建立一個可長期維運的 companion backend，讓 Telegram / PicoClaw 可以安全地驅動系統向任務、GitHub research 與 repo 維運工作。

## 里程碑

### Milestone 1：docs-first project bootstrap

- 建立 `picoclaw-ops-companion/`
- 撰寫 `README.md`
- 撰寫 `docs/plan.md`
- 撰寫 `docs/spec.md`
- 撰寫 `docs/todo.md`
- 從 pi3 commit
- push 到 GitHub（必要時 relay）

### Milestone 2：runtime bootstrap

- 初始化 TypeScript 專案
- 安裝 GitHub Copilot SDK 與必要依賴
- 建立 `src/` 基本骨架
- 建立 config / env loading 基礎
- 建立 logging 與 job storage 基礎

### Milestone 3：request 與 policy 核心

- 定義 request schema
- 定義 risk classification
- 定義 approval job schema
- 定義 allowlisted task types
- 定義 `availableTools` / `excludedTools` policy

### Milestone 4：approval 與 relay

- 實作 Telegram approval relay 協定
- 實作 TOTP 驗證
- 實作 nonce / TTL / replay 防護
- 實作 `/approve` / `/reject` 對應流程

### Milestone 5：Copilot session runner

- 建立受限的 Copilot SDK session
- 串接 allowlisted wrapper / tool policy
- 串接 `git` / `gh` / `npm` / research flows
- 實作結果與 audit artifact 輸出

### Milestone 6：驗證與部署

- 驗證 representative tasks
- 驗證 approval 與拒絕流程
- 驗證 GitHub relay fallback
- 整理 deployment 步驟與 operational notes

## 主要風險

- Copilot SDK / ACP preview 變動
- pi3 GitHub 網路不穩
- serialwrap 對長指令與大輸出不穩
- approval / policy 若設計過寬，會把風險轉移到 backend

## 設計原則

- 先 docs，後 runtime
- 先最小可行 request types，後面再擴大
- 不做 raw prompt passthrough
- 高風險任務預設需要 approval
- deployment 與 fallback 一開始就納入設計
