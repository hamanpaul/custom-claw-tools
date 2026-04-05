# `gws` 在 PicoClaw / pi3 上的登入與 Google 帳號授權

這份文件整理目前 PicoClaw 上安裝的 `gws`（Google Workspace CLI）該如何：

1. 建立 OAuth 設定
2. 完成登入
3. 指定哪些 Google 帳號可以登入

---

## 目前狀態

目前 PicoClaw / pi3 上的 `gws` 已安裝，但尚未完成登入設定。

已知狀態：

- `gws` binary：`/home/haman/.local/bin/gws`
- `gws auth status`：`auth_method = none`
- `~/.config/gws/client_secret.json`：不存在
- `~/.config/gws/credentials.enc`：不存在

也就是說，現在還沒有 OAuth client，也沒有登入後保存的 refresh token。

---

## 最簡單的登入方式

如果機器上已有 `gcloud`，而且你能操作對應的 GCP project，最簡單的做法是：

```bash
gws auth setup --project <YOUR_GCP_PROJECT_ID> --login
```

這個流程會：

1. 準備 `gws` 使用的 GCP project / OAuth client
2. 接著執行 `gws auth login`

如果你想自己掌控 OAuth consent screen、test users、branding，建議改走手動設定。

---

## 手動設定流程

### 1. 先準備一個 GCP project

建議為 `gws` 另外使用一個專用 project，不要跟其他生產用途混在一起。

| 用途 | 位置 | URL |
| --- | --- | --- |
| 建立 / 選擇 GCP project | Google Cloud Console | https://console.cloud.google.com/ |

### 2. 設定 OAuth consent screen

`gws` 能不能讓某個 Google 帳號登入，**不是**在 `gws` CLI 裡設定，而是看 OAuth consent screen 的 audience / test users。

| 位置 | 要設定什麼 | URL |
| --- | --- | --- |
| Google Auth platform > Branding | App name、support email、developer contact | https://console.developers.google.com/auth/branding |
| Google Auth platform > Audience | 選 `External` 或 `Internal` | https://console.developers.google.com/auth/audience |
| Google Auth platform > Audience > Test users | 加入允許登入的 Google 帳號 email | https://console.developers.google.com/auth/audience |
| Google Workspace docs | OAuth consent / scope 說明 | https://developers.google.com/workspace/guides/configure-oauth-consent |

### 3. 建立 OAuth client

建立一個 **Desktop app** 類型的 OAuth client，給 `gws auth login` 使用。

| 位置 | 要設定什麼 | URL |
| --- | --- | --- |
| APIs & Services > Credentials | 建立 OAuth client | https://console.cloud.google.com/apis/credentials |

建立完成後，下載 JSON 檔。

### 4. 把 client JSON 放到 `gws` 預設位置

`gws` 預設會從以下位置讀 OAuth client 設定：

| 檔案 | 路徑 | 用途 |
| --- | --- | --- |
| OAuth client config | `~/.config/gws/client_secret.json` | Google Cloud Console 下載的 client ID / secret |
| Encrypted credentials | `~/.config/gws/credentials.enc` | 登入後保存的 refresh token |
| Token cache | `~/.config/gws/token_cache.json` | access token cache |

把下載的 JSON 放到：

```bash
mkdir -p ~/.config/gws
cp /path/to/client_secret.json ~/.config/gws/client_secret.json
chmod 600 ~/.config/gws/client_secret.json
```

### 5. 執行登入

```bash
gws auth login
```

登入成功後，用下面指令確認：

```bash
gws auth status
```

---

## 哪些 Google 帳號可以登入

### 情境 A：`External` + `Testing`

這是最適合目前開發中的方式。

- 只有你加到 **Test users** 的 Google 帳號可以登入
- 很適合個人 Gmail 或少數測試帳號

### 情境 B：`Internal`

- 只有同一個 Google Workspace 組織內的帳號可以登入
- 適合公司內部 Workspace 網域

### 情境 C：`External` + Published

- 原則上任何 Google 帳號都可能登入
- 但通常會碰到 app verification / scope 審核等要求

**實務建議：** 如果你現在只是要讓自己的帳號在 PicoClaw 上用 `gws`，請選：

1. `External`
2. `Testing`
3. 把你自己的 Google 帳號加到 **Test users**

---

## `gws` 相關常用指令

| 指令 | 用途 |
| --- | --- |
| `gws auth setup --project <id> --login` | 自動準備 project / OAuth client 並登入 |
| `gws auth login` | 用現有 OAuth client 做登入 |
| `gws auth status` | 顯示目前登入狀態 |
| `gws auth logout` | 清除登入狀態 |
| `gws drive files list --params '{"pageSize": 5}'` | 登入後做最小 smoke test |

---

## 也可以用環境變數提供 client ID / secret

如果你不想把 `client_secret.json` 放在預設位置，也可以用環境變數：

```bash
export GOOGLE_WORKSPACE_CLI_CLIENT_ID="123456789.apps.googleusercontent.com"
export GOOGLE_WORKSPACE_CLI_CLIENT_SECRET="GOCSPX-..."
gws auth login
```

`gws` 查找 OAuth client 的優先順序：

1. `GOOGLE_WORKSPACE_CLI_CLIENT_ID` / `GOOGLE_WORKSPACE_CLI_CLIENT_SECRET`
2. `~/.config/gws/client_secret.json`

---

## 目前建議做法

若你只是要在 PicoClaw 上先把 `gws` 用起來，建議順序：

1. 建一個專用 GCP project
2. OAuth consent 選 `External`
3. 狀態先維持 `Testing`
4. 把要用的 Google 帳號加入 `Test users`
5. 建立 **Desktop app** OAuth client
6. 放到 `~/.config/gws/client_secret.json`
7. 跑 `gws auth login`
8. 用 `gws auth status` 與 `gws drive files list --params '{"pageSize": 5}'` 驗證

一句話版：

> `gws` 支援哪些 Google 帳號，是由 **GCP OAuth consent screen 的 Audience / Test users** 決定，不是由 `gws` 本身設定 allowlist。
