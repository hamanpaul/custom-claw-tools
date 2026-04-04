# fami-ghome

`fami-ghome` 是把 `famiclean-skill` 接到 Google Home 的子專案。
它的角色是 `cloud-to-cloud fulfillment + Local Home bridge`，不直接重寫 Famiclean UDP 協議。

## 目前狀態

目前 repo 已包含第一個 **Cloud MVP**：

- Python runtime：`fami_ghome/`
- HTTP service：
  - `GET /healthz`
  - `GET /oauth/authorize`
  - `POST /oauth/token`
  - `POST /fulfillment`
  - `GET /internal/state`
- `famiclean-skill` wrapper adapter
- stdlib `unittest` coverage
- `bin/fami-ghome`
- `systemd/fami-ghome.service`

尚未完成的部分：

- Google Home Developer Console 實際建置與 linking
- Google Home Test Suite
- Local Home JS app
- Nest / Google Home hub 真機 Local Home end-to-end

這個專案採用以下原則：

- Google 方向使用 `Google Home Developer Console` 的 `Cloud-to-cloud` 與 `Local Home SDK`
- 不使用 `Nest Device Access / SDM` 當作本專案的主要整合面
- `famiclean-skill` 仍是唯一直接連到熱水器 LAN/UDP 協議的元件
- 主部署路徑是 `Orangepi3 + Picoclaw`
- 次部署路徑是 `Docker / NAS`
- 所有實際 secret、token、session、log、state 都不進版控

## 專案結構

- `fami_ghome/`: Python runtime
- `tests/`: stdlib `unittest`
- `bin/fami-ghome`: shell wrapper
- `systemd/fami-ghome.service`: pi3 service scaffold
- `config/.env.example`: repo-safe runtime template

## Runtime config

從 template 開始：

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/fami-ghome
cp config/.env.example config/.env
```

最少要填的欄位：

- `ACCOUNT_LINKING_CLIENT_ID`
- `ACCOUNT_LINKING_CLIENT_SECRET`
- `ACCOUNT_LINKING_ALLOWED_REDIRECT_URIS`
- `AUTH_ADMIN_USERNAME`
- `AUTH_ADMIN_PASSWORD_HASH`
- `SESSION_SECRET`
- `TOKEN_ENCRYPTION_KEY`
- `INTERNAL_API_TOKEN`

若要產生 `AUTH_ADMIN_PASSWORD_HASH`：

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/fami-ghome
./bin/fami-ghome hash-password
```

`config/.env.example` 預設以 **同一個 monorepo 下的 sibling `famiclean-skill/`** 為參照。若日後拆 repo 或換部署路徑，需同步調整：

- `FAMICLEAN_HOME`
- `FAMICLEAN_WRAPPER`
- `FAMICLEAN_ENV_FILE`

## Commands

啟動 service：

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/fami-ghome
./bin/fami-ghome serve
```

產生管理密碼雜湊：

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/fami-ghome
./bin/fami-ghome hash-password
```

## Validation

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/fami-ghome
python3 -m py_compile fami_ghome/*.py tests/*.py
python3 -m unittest discover -s tests
```

## pi3 deployment scaffold

建議在 pi3 以 user service 方式部署：

```bash
cd /home/haman/custom-claw-tools/fami-ghome
chmod +x bin/fami-ghome
cp systemd/fami-ghome.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now fami-ghome.service
```

## Local Home boundary

目前 repo 只修正了 Local Home 的**架構方向**，還沒有實作 JS app：

- Google Home / Nest hub 上的 Local Home app 應執行在 hub 端
- 它必須透過 LAN 協定打到 Orangepi3 上的 local gateway / proxy
- 不應把 Local Home app 寫成直接呼叫同機 `famiclean-skill`

請先閱讀：

- `docs/spec.md`
- `docs/plan.md`
- `docs/task.md`
- `docs/todo.md`
