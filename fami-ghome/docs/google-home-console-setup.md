# Google Home Console / `.env` 設定對照

這份文件是給 `fami-ghome` 的 **Cloud-to-Cloud** 設定使用。

先記住一件最容易搞混的事：

- `ACCOUNT_LINKING_CLIENT_ID`
- `ACCOUNT_LINKING_CLIENT_SECRET`

**不是** Google Cloud OAuth client。

在這個專案裡，它們是你自己定義的一組值，然後 **同時填進**：

1. Google Home Developer Console 的 **Account linking**
2. `fami-ghome/config/.env`

因此，`fami-ghome` 目前**不用**先去 Google Cloud Console 建 OAuth client，才能完成 account linking 設定。

## 建議先備順序

1. 在 Google Home Developer Console 建一個新的 `fami-ghome` project。
2. 把 `fami-ghome` 部署成可從外網連到的 **HTTPS** 服務。
3. 填好 `config/.env`。
4. 回 Google Home Developer Console 填 fulfillment / account linking。
5. 把 Google 顯示的 redirect URI 貼回 `.env`。

---

## 1. Google Home Developer Console 要填的

| 位置 | 欄位 | 要填什麼 | URL |
| --- | --- | --- | --- |
| Google Home Developer Console > Create project | Project name | 自訂名稱，例如 `fami-ghome-prod` | https://console.home.google.com/ |
| Google Home Developer Console > Project details | `GOOGLE_HOME_PROJECT_ID` | 把 Home project ID 抄回 `config/.env` | https://console.home.google.com/ |
| Google Home Developer Console > Cloud-to-cloud > Fulfillment | Fulfillment URL | `https://<你的公開網域>/fulfillment`；同時填到 `.env` 的 `GOOGLE_HOME_FULFILLMENT_URL` | https://console.home.google.com/ |
| Google Home Developer Console > Account linking | Client ID | 跟 `.env` 的 `ACCOUNT_LINKING_CLIENT_ID` 填同一個值；這個值由你自己定義 | https://console.home.google.com/ |
| Google Home Developer Console > Account linking | Client secret | 跟 `.env` 的 `ACCOUNT_LINKING_CLIENT_SECRET` 填同一個值；這個值由你自己產生 | https://console.home.google.com/ |
| Google Home Developer Console > Account linking | Authorization URL | `https://<你的公開網域>/oauth/authorize` | https://console.home.google.com/ |
| Google Home Developer Console > Account linking | Token URL | `https://<你的公開網域>/oauth/token` | https://console.home.google.com/ |
| Google Home Developer Console / Google 提供 | Redirect URI | 把 Google 給你的 redirect URI 貼到 `.env` 的 `ACCOUNT_LINKING_ALLOWED_REDIRECT_URIS`。通常會是 `https://oauth-redirect.googleusercontent.com/r/<PROJECT_ID>`；測試時可能還要加 sandbox URI。**以 Console 顯示為準** | https://developers.home.google.com/cloud-to-cloud/project/authorization |

---

## 2. `config/.env` 要填的

| `.env` 欄位 | 填什麼 | 來源 / 申請網址 |
| --- | --- | --- |
| `PUBLIC_BASE_URL` | `fami-ghome` 對外可達的 **HTTPS** base URL，例如 `https://ghome.example.com` | 你的部署位置；不是 Google 申請值 |
| `GOOGLE_HOME_FULFILLMENT_URL` | `${PUBLIC_BASE_URL}/fulfillment` | 同上 |
| `GOOGLE_HOME_PROJECT_ID` | Google Home Developer Console 的 project ID | https://console.home.google.com/ |
| `GOOGLE_CLOUD_PROJECT_ID` | 綁到這個 Home project 的 GCP project ID | https://console.cloud.google.com/ |
| `ACCOUNT_LINKING_CLIENT_ID` | 你自己定義的固定字串，例如 `fami-ghome-client` | 無申請網址；自行定義 |
| `ACCOUNT_LINKING_CLIENT_SECRET` | 你自己產生的高熵 secret | 無申請網址；可用 `openssl rand -hex 32` |
| `ACCOUNT_LINKING_ALLOWED_REDIRECT_URIS` | Google Home Console 顯示的 redirect URI；可用空白或逗號分隔多個值 | https://developers.home.google.com/cloud-to-cloud/project/authorization |
| `AUTH_ADMIN_USERNAME` | 你登入 `/oauth/authorize` 頁面的帳號，例如 `admin` | 無申請網址；自行定義 |
| `AUTH_ADMIN_PASSWORD_HASH` | 用 `./bin/fami-ghome hash-password` 產生的密碼 hash | 本機產生 |
| `SESSION_SECRET` | 隨機 secret | 無申請網址；可用 `openssl rand -hex 32` |
| `TOKEN_ENCRYPTION_KEY` | 隨機 secret | 無申請網址；可用 `openssl rand -hex 32` |
| `INTERNAL_API_TOKEN` | 提供 `/internal/state` 使用的內部 token | 無申請網址；可用 `openssl rand -hex 32` |
| `FAMICLEAN_HOME` | `../famiclean-skill` 或你的實際部署路徑 | 本機路徑 |
| `FAMICLEAN_WRAPPER` | `../famiclean-skill/skills/fami-claw-skill/fami-claw` 或你的實際部署路徑 | 本機路徑 |
| `FAMICLEAN_ENV_FILE` | `../famiclean-skill/config/.env` 或你的實際部署路徑 | 本機路徑 |
| `DEVICE_IP` / `DEVICE_MAC` / `BROADCAST_IP` / `FAMICLEAN_PORT` | 你現有 `famiclean-skill` 那套裝置參數 | 直接抄現有部署值 |

---

## 3. 目前先不要填或先留空的

| 欄位 | 目前怎麼做 | 原因 |
| --- | --- | --- |
| `GOOGLE_HOME_LOCAL_APP_ID` | 先留空 | Local Home JS app 還沒做 |
| `LOCAL_HOME_ENABLED` | `false` | 目前只做 Cloud-to-Cloud |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | 先留空 | 目前 MVP 不需要；要做 HomeGraph / report state 再補 |

---

## 4. 你現在最常用到的命令

產生管理者密碼 hash：

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/fami-ghome
./bin/fami-ghome hash-password
```

產生隨機 secret：

```bash
openssl rand -hex 32
```

---

## 5. 最後再看一次：哪些值要在兩邊填同一份

以下欄位要 **Google Home Developer Console** 和 **`config/.env`** 彼此對齊：

| 欄位 | Google Home Developer Console | `config/.env` |
| --- | --- | --- |
| Project ID | Home project details | `GOOGLE_HOME_PROJECT_ID` |
| Fulfillment URL | Cloud-to-cloud > Fulfillment URL | `GOOGLE_HOME_FULFILLMENT_URL` |
| Client ID | Account linking > Client ID | `ACCOUNT_LINKING_CLIENT_ID` |
| Client secret | Account linking > Client secret | `ACCOUNT_LINKING_CLIENT_SECRET` |
| Redirect URI | Google 顯示 / 文件規則 | `ACCOUNT_LINKING_ALLOWED_REDIRECT_URIS` |

如果你只想先做 MVP，請先把注意力放在：

1. `PUBLIC_BASE_URL`
2. `GOOGLE_HOME_FULFILLMENT_URL`
3. `ACCOUNT_LINKING_CLIENT_ID`
4. `ACCOUNT_LINKING_CLIENT_SECRET`
5. `ACCOUNT_LINKING_ALLOWED_REDIRECT_URIS`
6. `AUTH_ADMIN_USERNAME`
7. `AUTH_ADMIN_PASSWORD_HASH`
8. `SESSION_SECRET`
9. `TOKEN_ENCRYPTION_KEY`
10. `INTERNAL_API_TOKEN`
