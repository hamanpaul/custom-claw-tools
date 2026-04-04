# fami-ghome TODO

## 尚未定案但不阻塞 v1

- 確認是否要在 v1 實作 `OnOff`，或先維持純 `TemperatureControl`
- 確認是否需要 `Report State` 與 `Request Sync`
- 確認是否提供一個給 Picoclaw / NAS dashboard 使用的 `gas_total_m3` 內部 API
- 確認 Local Home discovery 最終採用的 metadata 與 scan 策略
- 確認是否需要把 Local Home app 與 cloud service 拆成不同 runtime

## 安全與憑證

- 定義 `TOKEN_ENCRYPTION_KEY` 輪替策略
- 定義 `AUTH_ADMIN_PASSWORD_HASH` 產生方式與輪替流程
- 定義 Google redirect URI allowlist 的變更流程
- 決定 Docker secrets 與 `config/.env` 兩種模式是否都要正式支援

## 部署與營運

- 決定 Orangepi3 是否直接對外提供 HTTPS，或交給反向代理 / tunnel
- 決定 Docker 版是否要求 `host network`
- 決定是否在 Docker 版一併打包 Local Home app
- 決定 log rotation 與 token/state 備份方式

## 功能擴充

- 若 Google Home 原生 UI 仍不適合呈現瓦斯總量，設計獨立 dashboard 或 internal API
- 若日後要支援多 Google 帳號共享同一家庭，需要新增 user mapping 與 revocation model
- 若日後要支援多台 Famiclean，需重新定義 `agentUserId -> devices[]` 關係
