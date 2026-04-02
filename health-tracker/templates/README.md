# health-tracker 模板

這個目錄保存 `health-tracker` 的 repo 版模板。

## 模板用途

- `raw-record-template.md`：建立單筆原始紀錄
- `daily-log-template.md`：建立每日健康日誌
- `reports/monthly-report-template.md`：建立健康月報
- `reports/quarterly-report-template.md`：建立健康季報
- `reports/yearly-report-template.md`：建立健康年報

## live 同步目標

這些模板應同步到：

- `/home/haman/.picoclaw/workspace/notes/claw/health/templates`

同步後，PicoClaw 應優先用 live 模板建立新日誌或報表。

## canonical 落點

routine outputs 應固定落在以下路徑：

- raw：`notes/claw/health/raw/YYYY/MM/DD/<timestamp>-<record-type>-<source>.md`
- daily：`notes/claw/health/daily/YYYY-MM-DD.md`
- monthly：`notes/claw/health/reports/monthly/YYYY-MM.md`
- quarterly：`notes/claw/health/reports/quarterly/YYYY-QN.md`
- yearly：`notes/claw/health/reports/yearly/YYYY.md`

一般記錄流程不要另外建立 `notes/claw/health/*.md` top-level 檔案。既有 top-level legacy 檔案只能當參考來源，不能當新的 routine 輸出目標。

GarminDB integration 也必須遵守同一套 canonical 落點；Garmin 匯入只能更新既有 `raw/` 與 `daily/`，不能另建一棵平行的 `garmin/` 或 `health/` 匯入目錄。

## 變數解析規則

- `captured_at`：ISO 8601 with offset，例如 `2026-04-02T11:35:19+08:00`
- `local_date`：`YYYY-MM-DD`
- `date`：`YYYY-MM-DD`
- `weekday`：`週一`、`週二`、`週三`、`週四`、`週五`、`週六`、`週日`
- `year`：4 位數年份，例如 `2026`
- `month`：2 位數月份，例如 `04`
- `quarter`：`1` 到 `4`
- raw 檔名中的 `<timestamp>`：由 `captured_at` 正規化後的 `YYYYMMDDTHHMMSSZZ`

建立新檔時，先決定一次 `captured_at` 與 `local_date`，再用同一組值解析標題、欄位與檔名；不要在同一次寫入流程內混用不同格式。
