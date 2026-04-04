# fami-ghome

`fami-ghome` 是把 `famiclean-skill` 接到 Google Home 的子專案。
它的角色是 `cloud-to-cloud fulfillment + Local Home bridge`，不直接重寫 Famiclean UDP 協議。

## 目前狀態

目前這個子專案仍是 **docs/config scaffold**：

- 已整理規格、計畫、任務與待辦文件
- 已提供 `.gitignore` 與 `config/.env.example`
- 尚未加入 runtime、OAuth server、fulfillment service、Local Home app、測試或部署檔

因此目前 repo 內的文件描述的是 **目標設計與後續 phase**，不是已完成能力。

這個專案採用以下原則：

- Google 方向使用 `Google Home Developer Console` 的 `Cloud-to-cloud` 與 `Local Home SDK`
- 不使用 `Nest Device Access / SDM` 當作本專案的主要整合面
- `famiclean-skill` 仍是唯一直接連到熱水器 LAN/UDP 協議的元件
- 主部署路徑是 `Orangepi3 + Picoclaw`
- 次部署路徑是 `Docker / NAS`
- 所有實際 secret、token、session、log、state 都不進版控

## 設定骨架

- `config/.env.example` 目前預設以 **同一個 monorepo 下的 sibling `famiclean-skill/`** 為參照
- 實際使用時請複製成 `config/.env`
- 若 `fami-ghome` 日後被拆到別的 repo 或部署路徑，需同步調整：
  - `FAMICLEAN_HOME`
  - `FAMICLEAN_WRAPPER`
  - `FAMICLEAN_ENV_FILE`

請先閱讀：

- `docs/spec.md`
- `docs/plan.md`
- `docs/task.md`
- `docs/todo.md`
