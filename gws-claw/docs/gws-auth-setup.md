# `gws` 在 PicoClaw / pi3 上的登入與 Google 帳號授權

這份文件整理目前 PicoClaw 上安裝的 `gws`（Google Workspace CLI）該如何：

1. 建立 OAuth 設定
2. 完成登入
3. 指定哪些 Google 帳號可以登入

---

## 目前狀態

目前這份文件已包含一輪 **PicoClaw / pi3 遠端實測經驗**。

本輪已確認：

- `gws` 已安裝在 PicoClaw / pi3 上
- 可透過 **匯出的 `credentials.json`** 在遠端主機使用
- 啟用對應 Google API 後，`Drive` / `Calendar` 呼叫可正常成功

這份文件保留的是**通用流程與踩坑紀錄**，不包含任何真實帳號、token、project id 或其他機敏資訊。

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

## PicoClaw / pi3 遠端操作的實測重點

### 1. 不建議在 PicoClaw 上直接跑互動式 `gws auth login`，再用 Windows 瀏覽器去按同意

原因是 `Desktop app` OAuth flow 會把 callback 導到：

```text
http://localhost:<random-port>
```

如果 `gws auth login` 是在 **PicoClaw / pi3** 上跑，而你用的是 **Windows 本機瀏覽器** 打開 URL，
那 callback 會回到 **Windows 的 localhost**，不是 PicoClaw 的 localhost，最後就會出現 callback 失敗。

### 2. PicoClaw 比較穩的做法：先在本機登入，再把 credentials 帶去遠端

建議流程：

1. 在有瀏覽器的本機完成 `gws auth login`
2. 匯出憑證：

```bash
gws auth export --unmasked > credentials.json
```

3. 把 `credentials.json` 安全傳到 PicoClaw
4. 放到：

```bash
~/.config/gws/credentials.json
```

5. 在 PicoClaw 上指定：

```bash
export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=~/.config/gws/credentials.json
```

### 3. Windows PowerShell 匯出時要注意 UTF-8

這輪實測踩到一個很常見的坑：

- 在 Windows PowerShell 用 `>` 匯出 `credentials.json`
- 產出的檔案可能是 **UTF-16**
- `gws` 在 Linux / pi3 上讀取時會報：
  - `stream did not contain valid UTF-8`

因此，若你是在 Windows 產生檔案，請確認最後傳到 PicoClaw 的 `credentials.json` 是 **UTF-8 JSON**。

若需要在 PowerShell 直接存成 UTF-8，可用：

```powershell
gws auth export --unmasked | Set-Content -Encoding utf8 .\credentials.json
```

### 4. `client_secret.json` 跟 `credentials.json` 不一樣

| 檔案 | 用途 |
| --- | --- |
| `~/.config/gws/client_secret.json` | Google Cloud Console 下載的 OAuth client 設定 |
| `~/.config/gws/credentials.json` | `gws auth export --unmasked` 匯出的可用憑證 |

`client_secret.json` 不一定要刪；遠端 PicoClaw 若直接使用匯出的 `credentials.json`，可以保留兩者並共存。

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
| `gws auth export --unmasked > credentials.json` | 匯出可搬到遠端主機使用的憑證 |
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
6. 在本機完成 `gws auth login`
7. 匯出 `credentials.json`
8. 把 `credentials.json` 放到 PicoClaw 的 `~/.config/gws/`
9. 在 PicoClaw 設定 `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE`
10. 用 `gws auth status`、`gws drive files list --params '{"pageSize": 5}'`、`gws calendar calendarList list --params '{"maxResults": 5}'` 驗證

---

## 如果 `auth status` 正常，但 API 呼叫還是失敗

這通常不是登入壞掉，而是 **對應 Google API 還沒啟用**。

例如：

- `gws drive ...` 需要 **Google Drive API**
- `gws calendar ...` 需要 **Google Calendar API**

建議先從你要測的那個服務開始啟用，不需要一次把所有 API 都打開。

---

## 官方 `gws` skills

`gws` 專案本身有提供官方 skills，來源是：

- `googleworkspace/cli`
- skills.sh 搜尋可直接找到 `googleworkspace/cli@gws-*`

常用的官方 skills 包含：

| skill | 入口 |
| --- | --- |
| `googleworkspace/cli@gws-shared` | https://skills.sh/googleworkspace/cli/gws-shared |
| `googleworkspace/cli@gws-drive` | https://skills.sh/googleworkspace/cli/gws-drive |
| `googleworkspace/cli@gws-gmail` | https://skills.sh/googleworkspace/cli/gws-gmail |
| `googleworkspace/cli@gws-calendar` | https://skills.sh/googleworkspace/cli/gws-calendar |
| `googleworkspace/cli@gws-sheets` | https://skills.sh/googleworkspace/cli/gws-sheets |
| `googleworkspace/cli@gws-docs` | https://skills.sh/googleworkspace/cli/gws-docs |
| `googleworkspace/cli@gws-docs-write` | https://skills.sh/googleworkspace/cli/gws-docs-write |

安裝方式可用：

```bash
npx skills add googleworkspace/cli@gws-shared -g -y
npx skills add googleworkspace/cli@gws-drive -g -y
npx skills add googleworkspace/cli@gws-gmail -g -y
npx skills add googleworkspace/cli@gws-calendar -g -y
```

若要整套裝：

```bash
npx skills add https://github.com/googleworkspace/cli -g -y
```

`googleworkspace/cli` README 也提到其 skills 可配合 OpenClaw / 類似 skill-based agent 環境使用。  
不過 `gws` 專案本身同時也明講：**這不是 officially supported Google product**。

若要給 PicoClaw 用，建議安裝完成後確認：

1. `skills ls -g --json`
2. PicoClaw 的 skill 目錄下是否已出現對應 skill
3. `gws` 本身已先完成登入與 API 啟用

### PicoClaw 實測補充

這輪實測發現：

- `npx skills add ... -g -y` 會把 skills 裝到：
  - `~/.agents/skills/`
- PicoClaw 真正使用的 skills 目錄是：
  - `~/.picoclaw/workspace/skills/`

因此，如果你是要讓 **PicoClaw** 用，除了用 `skills add` 安裝外，還要把實際需要的 skill 同步到 PicoClaw 目錄。

這輪實際同步的是：

- `gws-shared`
- `gws-drive`
- `gws-gmail`
- `gws-calendar`

其中 `gws-drive` / `gws-gmail` / `gws-calendar` 的 `SKILL.md` 都會引用 `../gws-shared/SKILL.md`，所以 **`gws-shared` 應視為必要前置 skill**，不要只複製單一服務 skill。

PicoClaw 實際安裝 / 同步指令可用：

```bash
npx skills add googleworkspace/cli@gws-shared -g -y
npx skills add googleworkspace/cli@gws-drive -g -y
npx skills add googleworkspace/cli@gws-gmail -g -y
npx skills add googleworkspace/cli@gws-calendar -g -y

mkdir -p ~/.picoclaw/workspace/skills

for s in gws-shared gws-drive gws-gmail gws-calendar; do
  rm -rf ~/.picoclaw/workspace/skills/"$s"
  cp -a ~/.agents/skills/"$s" ~/.picoclaw/workspace/skills/"$s"
done
```

同步完成後可再確認：

```bash
npx skills ls -g --json
find ~/.picoclaw/workspace/skills -maxdepth 1 -mindepth 1 -type d \
  \( -name 'gws-shared' -o -name 'gws-drive' -o -name 'gws-gmail' -o -name 'gws-calendar' \) \
  | sort
```

一句話版：

> `gws` 支援哪些 Google 帳號，是由 **GCP OAuth consent screen 的 Audience / Test users** 決定，不是由 `gws` 本身設定 allowlist。
