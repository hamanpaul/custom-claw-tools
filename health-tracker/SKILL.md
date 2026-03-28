---
name: health-tracker
description: "追蹤活動、睡眠、飲食、訓練、用藥、檢驗與身體組成資料。保守估算熱量與營養，並將每日紀錄與彙總報表寫入 notes/claw/health。"
---

# Health Tracker Skill

當使用者要記錄、整理或分析健康資料時使用此 skill。資料來源可包含健康 connector、Telegram 圖片或文字、手動筆記、健檢報告，或身體組成紀錄。

## 固定路徑

- live skill path: `/home/haman/.picoclaw/workspace/skills/health-tracker/SKILL.md`
- repo copy path: `/home/haman/custom-claw-tools/health-tracker/SKILL.md`
- repo templates root: `/home/haman/custom-claw-tools/health-tracker/templates`
- health root: `/home/haman/.picoclaw/workspace/notes/claw/health`
- raw root: `/home/haman/.picoclaw/workspace/notes/claw/health/raw`
- daily root: `/home/haman/.picoclaw/workspace/notes/claw/health/daily`
- reports root: `/home/haman/.picoclaw/workspace/notes/claw/health/reports`
- live templates root: `/home/haman/.picoclaw/workspace/notes/claw/health/templates`
- skill-local template mirror: `/home/haman/.picoclaw/workspace/skills/health-tracker/templates`

## 何時使用這個 skill

當任務符合以下情況時，使用 `health-tracker`：

- 要記錄餐盤照片、重訓截圖、用藥筆記、檢驗報告、睡眠資料或身體組成更新
- 要做每日健康追蹤或狀態檢視
- 要看熱量預算、剩餘熱量、蛋白質目標進度或營養缺口
- 要產生月報、季報或年報
- 需要把健康相關 artifacts 寫入 `notes/claw/health`

## 不要用在這些情況

- 緊急症狀或急性風險判斷
- 診斷、治療決策或調藥建議
- 在沒有證據時編造數據
- 假裝目前環境已經有不存在的健康 API

## 資料來源規則

- 若目前環境可用，優先使用 `gws-compatible health connector`
- **不要**捏造像 `gws fit`、`gws health`、`gws sleep` 這種不存在的指令
- 若 connector 不可用，依序退回：
  - Telegram 文字
  - Telegram 照片或截圖
  - 匯出的 CSV / JSON / PDF / text
  - 使用者手動輸入
  - `notes/claw/health` 內既有檔案
- 每一筆資料都要保留來源追溯資訊

## 語言規則

- 日誌、報表、欄位標題、摘要與缺資料說明預設使用 `zh-TW`
- 藥名、保健品名稱、檢驗項目、原始表格欄名可保留原文，再補上 `zh-TW` 說明
- 若來源內容是英文或 OCR 文字，raw record 保留原文，daily 與 report 用 `zh-TW` 整理
- 檔名可維持英文與日期格式，但檔案內容預設為 `zh-TW`

## 角色分工

### PicoClaw

- 辨識任務類型與日期範圍
- 收集可用輸入
- 讀取截圖、餐盤照片、文字筆記或報告
- 呼叫可用工具或 connector
- 將檔案寫入 `notes/claw/health`
- 回覆精簡摘要，並說明信心與缺資料情況

### health-tracker

- 將混合來源健康資料正規化為單一日紀錄
- 保守估算餐點內容
- 追蹤活動、睡眠、訓練、用藥、檢驗與身體組成
- 產生日報、月報、季報、年報
- 明確標示不確定性、缺值與待補資料

## 內部分工

### health-intake-normalizer

- 將每筆輸入分類為 `activity`、`sleep`、`meal`、`training`、`medication`、`lab`、`body-composition` 或 `general`
- 將時間轉成在地日期
- 保留來源類型與原始文字
- 分析前先存 raw capture

### meal-estimator

- 估算份量、熱量、三大營養素與可能的微量營養覆蓋
- 盡量依照食物外觀、份量線索與可見標示
- 將信心標記為 `high`、`medium` 或 `low`

### activity-sleep-analyzer

- 整理步數、距離、活動時間、運動與睡眠
- 若資料足夠，與近期 baseline 比較
- 對未知欄位保持明確，不補幻想值

### medication-lab-recorder

- 轉錄藥名、劑量、時間、檢驗值、單位、參考區間與身體組成指標
- 若畫面沒寫清楚，不可自行推定藥名、劑量或檢驗值
- 對不完整或模糊資訊加註

### report-builder

- 產生日報、月報、季報、年報
- 與前一期比較
- 標出缺資料、低信心估值與趨勢變化

## 必要流程

1. 先決定日期範圍
   - 若使用者有明確日期，就用該日期
   - 若是即時餐點或運動紀錄，預設為今天
   - 若日期不明，摘要中要直接說明

2. 先檢查模板
   - 若目標日誌或報表不存在，優先從對應模板建立
   - 優先使用 `live templates root`
   - 若 live templates 不存在，再依 `repo templates root` 的欄位結構建立

3. 先保存 raw 證據
   - 在做彙總前，先在 `raw/` 寫一筆原始紀錄
   - 保留原始文字、OCR 結果或 connector 輸出
   - 記錄來源、時間與信心

4. 更新 daily record
   - 將該輸入合併到對應日期的 daily 檔
   - 只更新相關區塊
   - 不要用較弱的猜測覆蓋較強的證據

5. 只估算能支撐的內容
   - 有標示、表格或明確數字時，用精確值
   - 沒有精確值時，才使用 heuristic
   - 所有估值都要附信心

6. 只在有需要時產生週期報表
   - daily: 當日追蹤
   - monthly: 月度趨勢與遵循情況
   - quarterly: 較廣的趨勢與一致性
   - yearly: 高層級長期變化

7. 回覆要精簡
   - 說明這次寫入了什麼
   - 列出最重要的計算值
   - 說明缺資料或低信心項目
   - 需要時附上檔案路徑

## 模板檔案

若要新建檔案，優先使用以下模板：

- canonical live template root：`/home/haman/.picoclaw/workspace/notes/claw/health/templates`
- skill-local template mirror：`/home/haman/.picoclaw/workspace/skills/health-tracker/templates`
- raw record template: `/home/haman/.picoclaw/workspace/notes/claw/health/templates/raw-record-template.md`
- daily log template: `/home/haman/.picoclaw/workspace/notes/claw/health/templates/daily-log-template.md`
- monthly report template: `/home/haman/.picoclaw/workspace/notes/claw/health/templates/reports/monthly-report-template.md`
- quarterly report template: `/home/haman/.picoclaw/workspace/notes/claw/health/templates/reports/quarterly-report-template.md`
- yearly report template: `/home/haman/.picoclaw/workspace/notes/claw/health/templates/reports/yearly-report-template.md`

若 live template 尚未同步，可參考 repo 版本：

- `/home/haman/custom-claw-tools/health-tracker/templates/raw-record-template.md`
- `/home/haman/custom-claw-tools/health-tracker/templates/daily-log-template.md`
- `/home/haman/custom-claw-tools/health-tracker/templates/reports/monthly-report-template.md`
- `/home/haman/custom-claw-tools/health-tracker/templates/reports/quarterly-report-template.md`
- `/home/haman/custom-claw-tools/health-tracker/templates/reports/yearly-report-template.md`

## Raw record 規格

每筆 raw record 至少保留：

- `captured_at`
- `local_date`
- `source_type` (`connector`, `telegram-photo`, `telegram-text`, `manual`, `lab-report`, `body-composition`, `import`)
- `source_ref`
- `record_type`
- `raw_text`
- `structured_fields`
- `confidence`
- `notes`

建議檔名格式：

- `raw/YYYY/MM/DD/<timestamp>-<record-type>-<source>.md`

## Daily record 規格

每份 daily 檔案應在有資料時包含以下區塊：

- date
- activity
  - steps
  - distance
  - active_minutes
  - exercise_sessions
  - estimated_calories_burned
- sleep
  - duration
  - bedtime
  - wake_time
  - awakenings
  - sleep_score_or_quality
- meals
  - meal_time
  - estimated_portion
  - estimated_calories
  - protein_g
  - carbs_g
  - fat_g
  - fiber_g
  - likely_micronutrient_notes
- training
  - exercise_name
  - sets
  - reps
  - load
  - tonnage_if_known
- medication
  - medication_name
  - dose
  - timing
  - adherence_note
- labs
  - test_name
  - value
  - unit
  - reference_range
  - flag_if_visible
- body_composition
  - weight
  - body_fat_percent
  - skeletal_muscle
  - bmi_if_given
- energy_budget
  - intake_kcal
  - target_kcal
  - remaining_kcal
  - protein_target_progress
- data_quality
  - missing_inputs
  - low_confidence_items
  - follow_up_needed

建議檔名格式：

- `daily/YYYY-MM-DD.md`

## 報表規格

### Monthly report

應包含：

- 平均步數
- 平均睡眠時數
- 訓練頻率
- 若資料足夠，平均熱量攝取
- 若資料足夠，平均蛋白質攝取
- 體重與體脂趨勢
- 遵循情況摘要
- 缺資料摘要
- 與前一月比較

建議檔名格式：

- `reports/monthly/YYYY-MM.md`

### Quarterly report

應包含：

- 每月趨勢表
- 活動量趨勢
- 睡眠趨勢
- 訓練一致性
- 體重 / 身體組成趨勢
- 熱量收支趨勢
- 飲食模式摘要
- 主要優點、缺口與注意事項
- 與前一季比較

建議檔名格式：

- `reports/quarterly/YYYY-QN.md`

### Yearly report

應包含：

- 年度總覽
- 主要趨勢變化
- 最穩定與最不穩定的面向
- 身體組成變化
- 訓練量模式
- 睡眠與活動模式
- 飲食模式摘要
- 資料完整度摘要
- 與前一年比較

建議檔名格式：

- `reports/yearly/YYYY.md`

## 餐點估算規則

使用以下信任順序：

1. 明確標示或已知營養表
2. 使用者明確提供重量或份量
3. 清晰照片且食物可辨識
4. 粗略 plate heuristic
5. unknown

### Portion heuristics

當沒有精確重量時，使用簡單視覺規則：

- 1 個手掌大小瘦蛋白 ~= 20-30 g 蛋白質
- 1 個拳頭大小熟澱粉 ~= 25-40 g 碳水
- 1 個拇指大小額外脂肪 ~= 7-12 g 脂肪
- 1 杯非澱粉類蔬菜通常熱量較低，除非明顯有大量油或醬

### Plate heuristic

若是一般餐盤照片且細節不足：

- 半盤蔬菜
- 四分之一盤蛋白質
- 四分之一盤澱粉

只有在畫面明顯不同時才調整。

### Mixed dishes

對湯品、咖哩、炒飯、便當、麵類、燴飯等混合料理：

- 採保守估算
- 明確註記隱藏油脂、醬料、糖分或裹粉不確定性
- 若食材不明，不要宣稱精確 macro

## 熱量與營養規則

- 蛋白質使用 `4 kcal/g`
- 碳水使用 `4 kcal/g`
- 脂肪使用 `9 kcal/g`
- 若總熱量由 macro 推回，需與上述係數一致
- `remaining_kcal = target_kcal - intake_kcal`
- 若目標熱量已含一般活動量，不要再重複扣抵活動消耗
- 若有額外運動消耗數值，要說明如何使用
- 若使用者沒有明確蛋白質目標，可用保守 heuristic 追蹤，但要明講這是 heuristic，不是處方
- 微量營養素盡量使用質性描述，除非來源很強：
  - `likely covered`
  - `possibly low`
  - `insufficient evidence`

建議追蹤的營養重點：

- protein
- fiber
- calcium
- iron
- magnesium
- potassium
- vitamin D
- vitamin C
- omega-3

## 睡眠規則

- 優先使用可信來源提供的明確睡眠時數或分數
- 若沒有分數，就用可得訊號摘要：
  - 總睡眠時數
  - 入睡時間一致性
  - 起床時間一致性
  - 若已知，夜間醒來次數
- 不要編造睡眠分期或 recovery score

## 訓練規則

- 畫面可見時，記錄確切的 sets、reps 與 load
- 若只有完成組數截圖，就只記錄畫面可見內容
- 只有在 sets、reps、load 都明確時才計算 tonnage
- 若動作名稱不清楚，保留原始標籤並註記模糊

## 信心規則

使用以下標記：

- `high`
  - 明確標示、明確份量、精確 connector 輸出，或清楚結構化報告
- `medium`
  - 清晰照片且食物可辨識，或運動數據可讀
- `low`
  - 部分畫面、隱藏食材、模糊截圖，或不完整報告

## Guardrails

- 不做疾病診斷
- 不建議調藥
- 不取代醫師、藥師或營養師
- 不捏造測量值、檢驗值或 connector 輸出
- 只要是估值，就要明講是估值
- 缺資料就要明講缺資料
- 保留絕對日期與單位
- 保留來源追溯資訊
- 若檢驗報告或用藥紀錄不完整，只記錄可見事實
- 若使用者提到急性危險症狀，要提醒盡快尋求專業協助

## 輸出風格

回覆時：

- 先講主要結果
- 顯示最重要數值
- 說明信心
- 列出缺資料
- 說明更新或建立了哪個檔案

保持簡短、結構化、誠實，並預設使用 `zh-TW`。
