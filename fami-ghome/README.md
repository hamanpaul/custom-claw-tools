# fami-ghome

`fami-ghome` 是把 `famiclean-skill` 接到 Google Home 的子專案。
它的角色是 `cloud-to-cloud fulfillment + Local Home bridge`，不直接重寫 Famiclean UDP 協議。

這個專案採用以下原則：

- Google 方向使用 `Google Home Developer Console` 的 `Cloud-to-cloud` 與 `Local Home SDK`
- 不使用 `Nest Device Access / SDM` 當作本專案的主要整合面
- `famiclean-skill` 仍是唯一直接連到熱水器 LAN/UDP 協議的元件
- 主部署路徑是 `Orangepi3 + Picoclaw`
- 次部署路徑是 `Docker / NAS`
- 所有實際 secret、token、session、log、state 都不進版控

請先閱讀：

- `docs/spec.md`
- `docs/plan.md`
- `docs/task.md`
- `docs/todo.md`
