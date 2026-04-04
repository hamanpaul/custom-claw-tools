# fami-ghome 任務

## 1. Repo 與設定骨架

- [x] 新增 `fami-ghome/.gitignore`
- [x] 新增 `fami-ghome/config/.env.example`
- [x] 重新整理 `docs/spec.md`、`docs/plan.md`、`docs/todo.md`
- [x] 將任務檔名稱統一為 `docs/task.md`

## 2. Config 與 secret handling

- [ ] 建立 env loader，支援 `config/.env`
- [ ] 建立 `data/` 與 `logs/` 的 runtime 建立邏輯
- [ ] 定義 token store 格式與加密方式
- [ ] 定義 session store 格式
- [ ] 實作 `AUTH_ADMIN_PASSWORD_HASH` 驗證流程
- [ ] 驗證 `ACCOUNT_LINKING_ALLOWED_REDIRECT_URIS`

## 3. Famiclean adapter

- [ ] 建立 `fami-ghome` 對 `famiclean-skill` wrapper 的 adapter
- [ ] 支援 `read-temp`
- [ ] 支援 `read-gas`
- [ ] 支援 `set-temp`
- [ ] 將 wrapper timeout、stderr、invalid JSON 轉成統一錯誤

## 4. OAuth 與 cloud fulfillment

- [ ] 實作 `GET /oauth/authorize`
- [ ] 實作 `POST /oauth/token`
- [ ] 實作 authorization code 產生與過期機制
- [ ] 實作 access token / refresh token 產生、儲存、刷新
- [ ] 實作 `POST /fulfillment`
- [ ] 實作 `SYNC`
- [ ] 實作 `QUERY`
- [ ] 實作 `EXECUTE`
- [ ] 將 `SetTemperature` 映射到 `famiclean-skill set-temp`

## 5. Google Home 接入

- [ ] 在 `Google Home Developer Console` 建立 `Cloud-to-cloud` integration
- [ ] 設定 app display name 與 icon
- [ ] 設定 account linking 的 client id、client secret、authorize URL、token URL
- [ ] 設定 cloud fulfillment URL
- [ ] 跑 `Google Home Test Suite`
- [ ] 在 Google Home app 以 `[test] <Display Name>` 完成 linking
- [ ] 驗證手機 Google Home App 能查詢與設定水溫

## 6. Local Home

- [ ] 定義 local metadata 與 local device id
- [ ] 建立 Local Home app
- [ ] 驗證 Nest Mini / Google Home hub 與 Orangepi3 同網段時可走 local path
- [ ] 驗證 local path 失敗時自動回退 cloud path

## 7. 部署

- [ ] 提供 Orangepi3 service 部署說明
- [ ] 定義 Picoclaw 如何呼叫 `fami-ghome` 的內部診斷 API 或延用 `famiclean-skill`
- [ ] 新增 Dockerfile
- [ ] 新增容器部署說明
- [ ] 定義 HTTPS 暴露方式與 healthcheck

## 8. 驗收

- [ ] 本機 mock 測試通過
- [ ] 真實熱水器 `QUERY` 通過
- [ ] 真實熱水器 `EXECUTE set temperature` 通過
- [ ] Google Home app 操作通過
- [ ] Local Home 至少一次成功執行
