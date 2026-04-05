# gws-claw

`gws-claw` 是整理 **Google Workspace CLI (`gws`) 在 PicoClaw / pi3 上的使用與授權流程** 的子專案。

目前先採 **docs-first scaffold**，目的有兩個：

1. 把 `gws auth setup` / `gws auth login` / `Test users` 的設定方式固定下來
2. 把未來若要做 `gws` 自動化時，會用到的 OAuth / 檔案路徑 / 帳號限制規則先記錄清楚

目前 repo 內 **尚未**加入 `gws` 專用 runtime、wrapper 或 systemd service。

## 目前先看這份文件

- `docs/gws-auth-setup.md`

## 邊界

- `gws` 的 OAuth client / refresh token / credentials 都不進版控
- 目前以 **單機 operator 使用** 為主，不做 multi-user shared auth
- 哪些 Google 帳號能登入 `gws`，是由 **Google Cloud OAuth consent screen / Audience / Test users** 決定，不是由 repo 內程式決定
