# fami-ghome 規格

## 1. 目標與定位

`fami-ghome` 是 `famiclean-skill` 的 Google Home adapter。

- 它負責 `Google Home Developer Console` 的 `Cloud-to-cloud` 與 `Local Home` 對接
- 它不直接重寫 Famiclean UDP client，所有實機控制都委派給 `famiclean-skill`
- 第一版只支援 `單一家庭 / 單一 Google Home / 單一 Famiclean 熱水器`
- 第一版主要目標是「查詢目前設定溫度」與「設定目標溫度」
- `總瓦斯用量` 先保留在內部診斷 API、Picoclaw、日誌與後續擴充，不要求在 Google Home 原生 UI 中呈現

重要邊界：

- 本專案使用 `Google Home Developer Console`
- 本專案不使用 `Nest Device Access / SDM` 作為主要整合面

## 2. 系統架構

### 2.1 元件角色

- `famiclean-skill`
  - 唯一直接處理 Famiclean UDP 協議的元件
  - 已提供 `read-gas`、`read-temp`、`set-temp`
- `fami-ghome`
  - 對 Google 提供 OAuth、Cloud fulfillment、Local Home metadata
  - 對內呼叫 `famiclean-skill` wrapper
- `Google Home`
  - 透過 `SYNC` / `QUERY` / `EXECUTE` 呼叫 `fami-ghome`
- `Nest / Google Home hub`
  - 在已完成 cloud-to-cloud 後，可透過 `Local Home SDK` 走本地執行路徑

### 2.2 資料流

#### Cloud path

1. Google Home 對 `fami-ghome` 發送 `SYNC` / `QUERY` / `EXECUTE`
2. `fami-ghome` 將查詢或控制轉成 `famiclean-skill` wrapper 呼叫
3. `famiclean-skill` 對熱水器執行 UDP 操作並回傳 JSON
4. `fami-ghome` 將結果轉成 Google Smart Home response

#### Local path

1. Google Home hub 先透過 cloud project 知道本地裝置 metadata
2. Hub 在 LAN 內找到 `fami-ghome` local app
3. Local app 仍呼叫 `famiclean-skill`
4. 若 local path 失敗，系統可回退到 cloud path

## 3. Smart Home 模型

### 3.1 裝置模型

- Device type: `action.devices.types.WATERHEATER`
- 第一版 traits:
  - `action.devices.traits.TemperatureControl`
- 暫不實作：
  - `action.devices.traits.OnOff`

原因：

- Famiclean 已驗證的能力是水溫 setpoint 讀寫
- `OnOff` 尚未對實機做完關機語意驗證
- 若 Google 要求執行 `OnOff`，第一版回 `functionNotSupported`

### 3.2 溫度控制模型

- 溫度單位固定 `C`
- 溫控範圍：
  - `minThresholdCelsius = 35`
  - `maxThresholdCelsius = 50`
  - `temperatureStepCelsius = 1`
- 第一版狀態欄位：
  - `online`
  - `temperatureSetpointCelsius`
- 第一版命令：
  - `action.devices.commands.SetTemperature`

### 3.3 Google Home 不直接承載的資料

以下資料由 `fami-ghome` 保留在內部 state / 診斷 API，不要求映射成 Google 原生 UI：

- `gas_total_m3`
- `remaining_to_next_threshold_m3`
- `current_threshold_m3`
- `last_notification_subject`

## 4. 內部介面契約

### 4.1 `famiclean-skill` wrapper 契約

`fami-ghome` 只允許透過 wrapper 呼叫 `famiclean-skill`：

- `read-gas`
- `read-temp`
- `set-temp <celsius>`

不得在 `fami-ghome` 中重新複製 UDP 協議邏輯。

### 4.2 `fami-ghome` service 契約

第一版固定提供以下內部能力：

- `read_snapshot()`
  - 回傳 `{ device, gas, temp, checked_at }`
- `get_google_state()`
  - 以 `read_snapshot()` 轉成 Google `QUERY` state
- `set_target_temp(target_celsius)`
  - 呼叫 `famiclean-skill set-temp`
  - 以讀回結果建立 `EXECUTE` response

### 4.3 HTTP endpoints

第一版固定保留以下 routes：

- `GET /healthz`
  - service 自身健康檢查
- `GET /oauth/authorize`
  - Google account linking 授權入口
- `POST /oauth/token`
  - OAuth token exchange / refresh
- `POST /fulfillment`
  - Google `SYNC` / `QUERY` / `EXECUTE`
- `GET /internal/state`
  - 內部診斷 API，需帶 `INTERNAL_API_TOKEN`

## 5. OAuth 與機敏設定規劃

### 5.1 OAuth 模型

Google Smart Home 僅支援 `OAuth 2.0 authorization code flow`。
第一版採 `單戶自用` 模型：

- 只有一個本地管理帳號登入授權頁
- `agentUserId` 固定映射到單一家庭識別
- 不做多租戶資料表
- 不做多 Google 使用者授權委派

### 5.2 機敏資訊分級

高敏感：

- `ACCOUNT_LINKING_CLIENT_SECRET`
- `SESSION_SECRET`
- `TOKEN_ENCRYPTION_KEY`
- refresh token store
- password hash source material

中敏感：

- `ACCOUNT_LINKING_CLIENT_ID`
- `ACCOUNT_LINKING_ALLOWED_REDIRECT_URIS`
- `GOOGLE_SERVICE_ACCOUNT_FILE`
- `INTERNAL_API_TOKEN`

低敏感：

- `GOOGLE_CLOUD_PROJECT_ID`
- `GOOGLE_HOME_PROJECT_ID`
- `PUBLIC_BASE_URL`
- `FAMICLEAN_HOME`

### 5.3 Secret 存放原則

- 實際值只放 `config/.env`
- `config/.env` 必須被 `.gitignore` 忽略
- `AUTH_ADMIN_PASSWORD_HASH` 只存 hash，不存明文密碼
- token、session、state 放 `data/`
- log 放 `logs/`
- 不得把 secret 放在：
  - git repo
  - Picoclaw prompt / 指令列參數
  - Docker image layer

### 5.4 `.env.example` 契約

`config/.env.example` 必須只放欄位名稱與安全預設值，不放任何真實 credential。

關鍵欄位：

- 路徑類：
  - `FAMICLEAN_HOME`
  - `FAMICLEAN_WRAPPER`
  - `FAMICLEAN_ENV_FILE`
  - `STATE_DIR`
  - `LOG_DIR`
- runtime 類：
  - `FAMI_GHOME_HOST`
  - `FAMI_GHOME_PORT`
  - `PUBLIC_BASE_URL`
  - `TIMEZONE`
  - `LOG_LEVEL`
  - `MAX_TEMP_CELSIUS`
- Google / account linking 類：
  - `GOOGLE_CLOUD_PROJECT_ID`
  - `GOOGLE_HOME_PROJECT_ID`
  - `GOOGLE_HOME_FULFILLMENT_URL`
  - `ACCOUNT_LINKING_CLIENT_ID`
  - `ACCOUNT_LINKING_CLIENT_SECRET`
  - `ACCOUNT_LINKING_ALLOWED_REDIRECT_URIS`
- 本地授權頁帳號：
  - `AUTH_ADMIN_USERNAME`
  - `AUTH_ADMIN_PASSWORD_HASH`
- 加密與 session：
  - `SESSION_SECRET`
  - `TOKEN_ENCRYPTION_KEY`
- token policy：
  - `AUTHORIZATION_CODE_TTL_SECONDS`
  - `ACCESS_TOKEN_TTL_SECONDS`
  - `REFRESH_TOKEN_TTL_DAYS`
- Local Home：
  - `LOCAL_HOME_ENABLED`
  - `LOCAL_HOME_DEVICE_ID`
  - `LOCAL_HOME_SCAN_PORT`
  - `LOCAL_HOME_LISTEN_HOST`
  - `LOCAL_HOME_LISTEN_PORT`

### 5.5 Secret 產生與保管規則

- `ACCOUNT_LINKING_CLIENT_ID`
  - 由本專案自行定義與保管
  - 填入 `Google Home Developer Console` 的 account linking 設定
  - 不應誤用 Google Cloud OAuth client id
- `ACCOUNT_LINKING_CLIENT_SECRET`
  - 由本專案自行產生的高熵 secret
  - 僅保存於 `config/.env` 與你的 password manager
- `AUTH_ADMIN_PASSWORD_HASH`
  - 只接受 `argon2id` 或等級相近的密碼雜湊
  - 不得保存明文
- `SESSION_SECRET`
  - 至少 32 bytes 隨機值
- `TOKEN_ENCRYPTION_KEY`
  - 至少 32 bytes 隨機值
  - 用於保護 refresh token / session store
- `ACCOUNT_LINKING_ALLOWED_REDIRECT_URIS`
  - 只允許 `Google Home Developer Console` 提供的 redirect URI
  - 不接受萬用字元

若你手上已經有其他 Google 專案的 `OAuth client id`，預設不要重用，除非已確認那組就是供本專案 account linking 使用。

## 6. Git 與檔案結構規範

### 6.1 `.gitignore`

`fami-ghome/.gitignore` 必須至少忽略：

- `config/.env`
- `config/*.local.*`
- `data/`
- `logs/`
- `*.sqlite3`
- `*.db`
- `*.pem`
- `*.key`
- `*.p12`
- `__pycache__/`
- `*.pyc`
- `node_modules/`
- `dist/`

### 6.2 建議目錄責任

- `config/`
  - 可追蹤的 template 與不可追蹤的 local config
- `docs/`
  - 規格、計畫、任務、待辦
- `data/`
  - token store、session store、cache、state
- `logs/`
  - fulfillment log、auth log、local home log

## 7. 測試規劃

### 7.1 本機測試

- 使用 mock `famiclean-skill` 或測試 wrapper 輸出驗證：
  - `SYNC`
  - `QUERY`
  - `EXECUTE`
- 驗證 OAuth authorize / token / refresh 流程
- 驗證錯誤情境：
  - wrapper timeout
  - wrapper 回傳非 JSON
  - 溫度超出範圍
  - Google redirect URI 不在 allowlist

### 7.2 Google Home 測試

在 `Google Home Developer Console` 進行：

1. 建立 `Cloud-to-cloud` integration
2. 設定 app display name 與 icon
3. 設定 account linking：
   - client id
   - client secret
   - authorize URL
   - token URL
4. 設定 cloud fulfillment URL
5. 到 `Test` 頁面跑 `Google Home Test Suite`
6. 用同一 Google 帳號在 Google Home app 搜尋 `[test] <Display Name>` 並完成 linking

### 7.3 Local Home 測試

- Google Home hub 與 Orangepi3 必須在同一個 LAN
- 先完成 cloud project linking，再測 Local Home
- 驗證：
  - hub 能發現 local app
  - 設溫命令走 local path
  - local path 失敗時能回退 cloud path

## 8. 部署規劃

### 8.1 Orangepi3 + Picoclaw 主路徑

第一版主路徑：

- `famiclean-skill` 與 `fami-ghome` 同機部署在 Orangepi3
- `fami-ghome` 透過本機 wrapper 呼叫 `famiclean-skill`
- Picoclaw 繼續直接呼叫 `fami-claw`，不改變既有熱水器技能入口
- `fami-ghome` 以背景 service 執行，對外提供 HTTPS webhook

必要條件：

- 必須有可從公網存取的 HTTPS URL
- 可透過：
  - 反向代理
  - Caddy / Nginx
  - Cloudflare Tunnel
  - 其他 TLS termination 方式

### 8.2 Docker 次路徑

Docker 版只當第二優先部署：

- container 內跑 `fami-ghome`
- 以 bind mount 或 secret file 提供 `config/.env`
- 若 container 內也要直接呼叫 `famiclean-skill`，需保證：
  - wrapper path 可用
  - UDP/LAN 可達
  - 優先使用固定 `DEVICE_IP`
- 若要用 discovery broadcast，Linux host 上優先考慮 `host network`

### 8.3 Picoclaw 邊界

- Picoclaw 不保存 Google OAuth secret
- Picoclaw 只做：
  - 直接呼叫 `famiclean-skill`
  - 或呼叫 `fami-ghome` 的內部診斷 API
- Google Home 與 Picoclaw 是平行入口，不互相持有對方 secret

### 8.4 具體部署契約

Orangepi3 service 最低要求：

- service 名稱固定為 `fami-ghome.service`
- 使用獨立系統使用者執行，不用 `root`
- `WorkingDirectory` 指向 `fami-ghome` 專案根目錄
- `EnvironmentFile` 指向 `config/.env`
- `Restart=always`
- `config/.env` 權限至少收斂到只有 service 使用者可讀

Docker 最低要求：

- image 不得 `COPY config/.env`
- secrets 透過 `env_file`、bind mount 或 secret file 注入
- `data/` 與 `logs/` 必須掛載為 volume
- 若 container 內要呼叫 sibling 的 `famiclean-skill` wrapper，需明確掛載兩個專案目錄
- 對 Google 提供的公開入口應由反向代理或 tunnel 提供 TLS

## 9. 參考文件

- https://developers.home.google.com/cloud-to-cloud
- https://developers.home.google.com/cloud-to-cloud/primer/account-linking
- https://developers.home.google.com/cloud-to-cloud/project/authorization
- https://developers.home.google.com/cloud-to-cloud/guides/waterheater
- https://developers.home.google.com/cloud-to-cloud/traits/temperaturecontrol
- https://developers.home.google.com/local-home/overview
