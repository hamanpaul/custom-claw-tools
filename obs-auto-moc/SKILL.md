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
