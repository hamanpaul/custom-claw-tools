---
name: obs-auto-moc
description: "建立 review-first 的 Obsidian MOC manifest、proposal 與 preview。預設不改 live MOC，只有明確要求時才 apply。"
---

# Obs Auto MOC Skill

當使用者要檢查、重建、預覽或套用 Obsidian `MOC.md` 時，使用這個 skill。

## 固定路徑

- project root: `/home/haman/custom-claw-tools/obs-auto-moc`
- repo skill copy: `/home/haman/custom-claw-tools/obs-auto-moc/SKILL.md`
- live skill path: `/home/haman/.picoclaw/workspace/skills/obs-auto-moc/SKILL.md`
- live wrapper path: `/home/haman/.picoclaw/workspace/bin/obs-auto-moc`
- artifacts root: `/home/haman/.picoclaw/workspace/notes/claw/moc`
- proposal root: `/home/haman/.picoclaw/workspace/notes/claw/moc/proposals`
- manifest path: `/home/haman/.picoclaw/workspace/notes/claw/moc/index-manifest.jsonl`
- preview path: `/home/haman/.picoclaw/workspace/notes/claw/moc/MOC.preview.md`
- status path: `/home/haman/.picoclaw/workspace/notes/claw/moc/last-run.json`
- live MOC path: `/home/haman/.picoclaw/workspace/notes/MOC.md`
- sync config root: `/home/haman/.config/obsidian-headless/sync`

## 何時使用這個 skill

當任務符合以下情況時，使用 `obs-auto-moc`：

- 想先 review 再決定是否更新 `MOC.md`
- 想檢查哪些筆記是 orphan、哪些 frontmatter 不完整
- 想看新的 `MOC.preview.md`
- 想在 PicoClaw 內安全觸發 MOC 重建
- 想在不直接覆寫 live MOC 的前提下產出 proposal artifact

## 不要用在這些情況

- 不要在未經使用者明確確認前直接套用 `--apply`
- 不要假裝 frontmatter 永遠完整或格式正確
- 不要在 proposal mode 寫入大量筆記
- 不要繞過 sync config 去硬編碼不可信的 vault path

## 角色分工

### PicoClaw

- 判斷使用者是要 preview、stats，還是 explicit apply
- 透過 `exec` 呼叫 live wrapper
- 讀回 proposal、preview 或 stats
- 誠實回報 malformed notes、缺欄位與 unresolved links

### obs-auto-moc

- 從 sync config 解出 vault path
- 掃描 Markdown、Frontmatter 與 wikilinks
- 產出 manifest、proposal 與 preview
- 只有在 `--apply` 時才原子更新 live `MOC.md`

## 必要流程

1. 預設先跑 preview build
   - 使用：
     - `/home/haman/.picoclaw/workspace/bin/obs-auto-moc build`
   - 這一步會更新 manifest、proposal 與 `MOC.preview.md`
   - 這一步**不會**改寫 live `MOC.md`

2. 先讀結果
   - 讀 `last-run.json`
   - 讀最新 proposal
   - 必要時讀 `MOC.preview.md`

3. 只有在使用者明確要求「套用」時，才執行：
   - `/home/haman/.picoclaw/workspace/bin/obs-auto-moc build --apply`

4. 回覆要精簡
   - 說明這次是否只是 preview
   - 列出 proposal / preview 路徑
   - 列出最重要的 warning
   - 若有 apply，明確說 live `MOC.md` 已更新

## root-note pipeline scaffold

目前 repo 內已加入第一版 script-side scaffold，對應 `root-note -> PicoClaw -> destination MOC` 流程：

- `monitor-root-note`：掃描 `root-note/`，只對變更檔案產出 PicoClaw handoff artifact
- `apply-picoclaw-report --report <file>`：吃結構化 PicoClaw 完成回報，更新 pipeline state，並刷新 touched destination MOC
- `queue-picoclaw-report --report <file> [--run-pipeline]`：驗證回報後先放入 report inbox，必要時立刻跑一輪 pipeline
- `refresh-destination-mocs`：直接重建 `TechVault` / `WorkVault` / `PersonalVault` 的 `MOC.md`
- `dispatch-picoclaw-handoff --handoff <file>`：把 handoff job 直接交給 live PicoClaw，擷取結構化 report，再餵回 pipeline
- `run-pipeline-once`：先吃 report inbox 裡的 PicoClaw 完成回報，再從 `root-note/` 產出下一個 handoff job；若 auto-dispatch 開啟，會立刻把 handoff 送進 live PicoClaw
- `listen --host 127.0.0.1 --port 45460 --run-pipeline`：提供 loopback `GET /health` 與 `POST /picoclaw-report` callback ingestion
- handoff artifact 的 `callback_contract.endpoint` 預設會指向 `http://127.0.0.1:45460/picoclaw-report`
- handoff artifact 會附上 `vault_path` 與 destination root paths，讓 PicoClaw 在回報前先建立目的筆記

注意：

- Stage 2 agent 由 live PicoClaw 執行，不是在 `obs-auto-moc` 內執行
- Stage 2 規則入口已對齊到 pi3 notes 內的 `ObsToolsVault/README.md`，更細的遷移規則在 `ObsToolsVault/specs/`
- pi3 上已啟用 user-level `obs-auto-moc-listener.service` + `obs-auto-moc-pipeline.timer`
- `bin/obs-auto-moc-runner` 預設會開 `OBS_AUTO_MOC_AUTO_DISPATCH=1`，並使用 `cron:obs-auto-moc` session 自動把 handoff 送進 PicoClaw
- `bin/obs-auto-moc-listen` / `bin/obs-auto-moc-runner` 支援 `OBS_AUTO_MOC_SYNC_ROOT`、`OBS_AUTO_MOC_VAULT_PATH`、`OBS_AUTO_MOC_AUTO_DISPATCH`、`OBS_AUTO_MOC_PICOCLAW_SESSION` 等環境覆寫，可先對暫時 vault 做 smoke 再切回 live notes

## 常用指令

### Preview build

```bash
/home/haman/.picoclaw/workspace/bin/obs-auto-moc build
```

### Stats

```bash
/home/haman/.picoclaw/workspace/bin/obs-auto-moc stats
```

### Apply

```bash
/home/haman/.picoclaw/workspace/bin/obs-auto-moc build --apply
```

## Guardrails

- 預設是 review-first，不是 auto-apply。
- 若 `last-run.json` 顯示 parse errors、missing schema fields 或 unresolved links，要誠實說明。
- 若 sync config 缺失或有多份 config，直接回報錯誤，不要猜路徑。
- 除了 `notes/MOC.md` 的 explicit apply 之外，不要改寫 vault 內其他筆記。
- `notes/claw/moc` 是 artifact root；preview/proposal 都先寫這裡。
