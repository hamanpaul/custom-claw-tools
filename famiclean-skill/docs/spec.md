# Famiclean Skill Specification

## 1. Summary

本專案分兩階段：

1. 在 Orangepi3 上提供一個給 Picoclaw 使用的 Famiclean skill，支援：
   - 裝置 discovery
   - 查詢總瓦斯用量
   - 查詢目前設定溫度
   - 設定目標溫度
   - 每天 08:00 檢查瓦斯總用量，跨越固定 `20 M3` 門檻時通知
2. 研究如何把 Famiclean 納入 Google Home 生態，並比較：
   - 直接 Google Home / Google Smart Home 路線
   - 借道 Smart Life / Tuya 的路線

目前第一階段直接實作於：

- Skill: `skills/fami-claw-skill`
- CLI: `skills/fami-claw-skill/scripts/famiclean.py`
- Config template: `config/.env.example`
- Local runtime config: `config/.env`
- State: `data/famiclean-state.json`

## 2. Real-Device Protocol Facts

以下資訊來自 `logs/famiclean-real.pcap` 與 `logs/famiclean-real-summary.md`：

- Transport: UDP
- Port: `9999`
- Discovery request: `request_mac `
- Usage request: `request_usage `
- Status request: `request_data `
- Temperature control payload:

```text
control_type:waterheatersettemp:<TEMP>power:onmac:<MAC>min_flow:0wifi_reset:0lock:0bath_qty:0bath_qty_timer:0fcm_token:platform:androidpro_mode:0 
```

### 2.1 Discovery response

```text
{'mac':'345F455F1C98','control':'waterheater','_macback':'macback'}
```

### 2.2 Usage response

```text
{'waterflow_count':22.91,'heatvalue_count':414.52,'waterflow_total':37198.39,'heatvalue_total':741727.88,'usageback':'end'}
```

### 2.3 Status response

```text
{'hottemp':41,'coldtemp':20,'settemp':41,'waterflow':0.00,'errorcode':'','waterflow_count':0.00,'waterflow_total':37198.39,'heatvalue_count':0.00,'heatvalue_total':741727.88,'motor_steps':68,'ventilator_steps':20,'power':'on','mac':'345F455F1C98','control':'waterheater','_messageback':'msgback__eco0rssi-692','lock':'0','notice_bath':0}
```

### 2.4 Known protocol quirks

- `request_usage ` 的回應可能回到稍早 `request_mac ` 所使用的 source port。
- 因此 client 不能把 discovery 與 usage 拆成不同的一次性 UDP socket。
- 設定溫度後，實機 capture 中沒有立即 ACK；應以後續 `request_data ` 驗證。

## 3. Display-Value Conversion Rules

App UI 顯示的瓦斯值不是直接使用單一 raw 欄位；idle 與 active heating 的顯示口徑不同。

- idle 時：
  - `gas_total_m3 = round(heatvalue_total / 9100, 2)`
- active heating 時，為了對齊手機 app 的即時顯示：
  - `gas_total_m3 = round((request_usage.heatvalue_total + request_data.heatvalue_count) / 9100, 2)`
- `gas_count_m3 = round(request_data.heatvalue_count / 9100, 2)`
- `remaining_to_next_threshold_m3 = round(THRESHOLD_STEP_M3 - (gas_total_m3 % THRESHOLD_STEP_M3), 2)`

在目前 live 設定 `THRESHOLD_STEP_M3=20` 時，這等價於：

- `remaining_to_next_threshold_m3 = round(20 - (gas_total_m3 % 20), 2)`

已驗證例子：

- raw `heatvalue_total = 741727.88`
- display `gas_total_m3 = 81.51 M3`
- live heating 例：
  - `request_usage.heatvalue_total = 741727.88`
  - `request_data.heatvalue_count = 1956.29`
  - display `gas_total_m3 = round((741727.88 + 1956.29) / 9100, 2) = 81.72 M3`

這也是第一階段 skill 在判斷 `20 M3` 門檻時採用的值。

## 4. Phase 1 Skill Requirements

### 4.1 Device scope

- 第一階段只支援單一設備
- 預設設備由本機 `config/.env`（可由 `config/.env.example` 複製）中的 `DEVICE_IP` / `DEVICE_MAC` 指定
- 若未指定完整資訊，允許 broadcast discovery 補足

### 4.2 Supported actions

- `discover`
- `get-total-gas`
- `get-temp`
- `set-temp`
- `check-threshold`
- `剩餘瓦斯量` 問題應使用 `get-total-gas` 的結果回覆，並帶出 `remaining_to_next_threshold_m3`

### 4.3 Command contract

CLI entrypoint:

```bash
python skills/fami-claw-skill/scripts/famiclean.py <command>
```

PicoClaw live trigger entrypoint:

```bash
~/.picoclaw/workspace/skills/fami-claw-skill/fami-claw <command>
```

支援共用參數：

- `--home`
- `--env-file`
- `--device-ip`
- `--device-mac`
- `--broadcast-ip`
- `--port`
- `--timeout`
- `--json`

PicoClaw wrapper contract：

- 預設補上 `--json`
- 自動解析 project home；必要時可由 `FAMICLEAN_HOME` 覆蓋
- 接受別名：
  - `read-temp` -> `get-temp`
  - `water-temp` -> `get-temp`
  - `read-gas` -> `get-total-gas`
  - `remaining-gas` -> `get-total-gas`
  - `set-temperature` -> `set-temp`

### 4.4 Temperature safety rule

- 最高允許設定值：`50°C`
- 若要求值大於 `50°C`，直接拒絕並回報錯誤
- 若讀回狀態本身高於 `50°C`，僅回報，不自動改寫

### 4.5 Daily threshold rule

- 每天 `08:00` 執行檢查
- 使用 display `gas_total_m3` 判斷門檻
- 固定整數門檻：`20 / 40 / 60 / 80 / 100 ...`
- 例：若目前為 `81.51 M3`，下一個門檻是 `100 M3`

### 4.6 Bootstrap rule

第一次成功執行 `check-threshold` 時：

- 建立 state 檔
- 記錄當前整數門檻
- 不補發歷史通知

### 4.7 Multi-threshold jump rule

若兩次檢查之間一次跨過多個 20-M3 門檻：

- 單次檢查只送一則通知
- 內文列出本次跨越的所有門檻
- state 成功後一次推進到最高已跨越門檻

### 4.8 Notification rule

通知文案至少包含：

- `瓦斯用量已達臨界值`
- 目前總瓦斯用量
- 本次跨越門檻
- 設備 IP / MAC
- 檢查時間

第一階段通知通道：

- Telegram
- Email

若任一已配置通道失敗：

- 視為通知未完整成功
- 不推進 `last_notified_threshold_m3`
- 允許下次重試

## 5. Config And State

### 5.1 `config/.env.example` and local `config/.env`

- repo 只追蹤範本 `config/.env.example`
- 實際 runtime 設定請複製成未納版控的 `config/.env`

目前規格：

- `DEVICE_IP`
- `DEVICE_MAC`
- `BROADCAST_IP`
- `FAMICLEAN_PORT`
- `FAMICLEAN_TIMEOUT_SECONDS`
- `GAS_DIVISOR`
- `THRESHOLD_STEP_M3`
- `DAILY_CHECK_HOUR`
- `TIMEZONE`
- `MAX_TEMP_CELSIUS`
- `STATE_FILE`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `EMAIL_SMTP_HOST`
- `EMAIL_SMTP_PORT`
- `EMAIL_SMTP_USERNAME`
- `EMAIL_SMTP_PASSWORD`
- `EMAIL_USE_TLS`
- `EMAIL_FROM`
- `EMAIL_TO`

### 5.2 `data/famiclean-state.json`

預期保存：

- `bootstrapped_at`
- `last_checked_at`
- `last_seen_total_m3`
- `last_seen_raw_heatvalue_total`
- `last_notified_threshold_m3`
- `last_notified_at`
- `last_notification_subject`

## 6. Phase 2 Google Home Research

### 6.1 Direct Google Home route

目前官方文件顯示：

- Google Smart Home Cloud-to-cloud 支援 `action.devices.types.WATERHEATER`
- Water heater guide 指出可用 `OnOff`，且溫度控制應使用 `TemperatureControl`
- Device types and traits 表中，`WATERHEATER` 也列在可搭配 Local Home SDK 的裝置類型中

這代表「查/設水溫」這條能力，走 Google Smart Home 原生模型是有官方對應的。

### 6.2 Limits for gas-usage telemetry

Google Home 原生 trait 目前沒有明確對應「累積瓦斯用量 M3」這種數值：

- `SensorState` 支援的是特定 sensor 類型，例如 air quality、CO、smoke、water leak 等
- 這不是累積用量計量模型
- 因此 `總瓦斯用量` 很可能無法作為 Google Home 的一級原生數值卡片直接呈現

結論：

- `水溫讀寫`：適合走 Google Smart Home 原生裝置語意
- `瓦斯累積用量`：較可能需要保留在自家 skill / NAS dashboard / 自訂 API，而非期待 Google Home 原生完整承載

### 6.3 Local Home SDK implications

官方 Local Home 文件指出：

- 啟用 local fulfillment 的前提是已存在 cloud-to-cloud integration
- local fulfillment 會在 Google Home / Nest 裝置上執行本地 app，不是在 NAS 上執行
- Local Home 也支援 hub / bridge 形態的本地設備

結論：

- 若走 Google Smart Home + Local Home，NAS 不能完全取代 cloud backend
- NAS 可作為 LAN hub 或 partner backend 的一部分
- 但整體仍是「Cloud-to-cloud 為主、Local Home 補本地傳輸」的架構

### 6.4 NAS Docker route

若第二階段希望以 NAS 當智慧家庭區網中樞，較合理的規劃是：

- NAS 上跑自家 adapter / API / state / notification 服務
- 再選擇：
  - A. 做 Google Smart Home partner backend
  - B. 另做 bridge 轉成 Google 可接受的模型

### 6.5 Matter route caveat

Google Home 的 Matter supported devices 文件目前列出 thermostat 等類型，但未見 water heater。
因此「NAS 上直接做 Matter bridge，把 Famiclean 映射成原生 water heater」目前不是最穩的假設。

若未來真的走 Matter：

- 需重新確認 Google Home 當時支援的 Matter device types
- 需確認水溫控制與瓦斯用量是否都有合理語意映射

### 6.6 Smart Life / Tuya route

官方 Tuya 文件顯示兩件事：

- TuyaOS Link SDK 可把非 Tuya 原生設備接到 Tuya Cloud
- Tuya Matter interoperability 文件支援把 Tuya / Matter 裝置分享進 Google Home

但這不代表現有 Famiclean UDP 協議可以直接被 Smart Life 接走。中間仍需要：

- 做一個 Famiclean -> Tuya 的 adapter
- 或做一個自家的 bridge / gateway，再進 Tuya 生態

因此第二階段的 Tuya 路線定位為：

- 可行參考方案
- 不是第一時間最短路徑
- 是否值得做，要看 Google Home 原生路線對 `水溫` 與 `瓦斯用量` 的實際呈現能力

## 7. Recommended Phase 2 Direction

目前建議：

1. 先把第一階段 skill、CLI、通知、state 全部穩定
2. 第二階段優先研究 Google Smart Home Cloud-to-cloud + Local Home 的可達成程度
3. 若確認 Google Home 無法合理承載 `總瓦斯用量`，則保留：
   - Google Home 僅承載水溫相關控制
   - 瓦斯用量留在自家 skill / NAS dashboard
4. Tuya / Smart Life 路線只作為備援比較

## 8. Source Links

Google Home:

- https://developers.home.google.com/cloud-to-cloud/guides/waterheater
- https://developers.home.google.com/cloud-to-cloud/primer/device-types-and-traits
- https://developers.home.google.com/cloud-to-cloud/traits/temperaturecontrol
- https://developers.home.google.com/cloud-to-cloud/traits/sensorstate
- https://developers.home.google.com/local-home/overview
- https://developers.home.google.com/local-home/fulfillment-app
- https://developers.home.google.com/matter/supported-devices

Tuya:

- https://developer.tuya.com/en/docs/iot/tuya-matter-interoperability-certified-by-csa?id=Kdajjz0kd1eic
- https://developer.tuya.com/en/docs/iot-device-dev/TuyaOS-Link-SDK?id=Kdajfw5j5jze0
