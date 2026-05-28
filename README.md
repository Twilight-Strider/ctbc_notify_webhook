# 中信附卡刷卡通知轉發到 Telegram

## 背景

中國信託信用卡的附卡消費通知只會發送給正卡人，附卡人無從得知自己的刷卡狀況。本專案透過以下路徑解決這個問題：

```
正卡人 Home Bank App 收到推播通知
  → Android 手機上的 Notification Forwarder 攔截
  → POST 到中繼伺服器（Railway）
  → Python 解析金額、時間、附卡/正卡
  → 推送到 Telegram Bot
  → 附卡人備機收到完整通知
```

---

## 程式說明

### 啟動時載入設定（環境變數）
- `TELEGRAM_TOKEN`：Bot 的身份憑證
- `TELEGRAM_SUBSCRIBERS`：訂閱者清單，格式為 `chat_id:角色`，多人用逗號分隔，例如 `123456:附卡,789012:全部`
- `WEBHOOK_SECRET`：防止陌生人亂打你的 endpoint

### `load_subscribers()`
從環境變數讀取訂閱者設定，回傳一個字典，例如：
```python
{"6125036159": "附卡", "8065049962": "全部"}
```

### `parse_notification(text)`
收到原始通知文字，用正則表達式拆出四個欄位：
- 日期、時間（`2026/05/27 14:51`）
- 金額（`71`）
- 卡別（`附卡` 或 `正卡`）

### `format_message(parsed)`
把解析結果組成格式化的 Telegram 訊息。如果三個欄位都解析失敗，直接顯示原始文字當備用。

### `escape_md(text)`
跳脫 MarkdownV2 的所有特殊字元，避免 Telegram 回傳 400 Bad Request。所有從外部來的變數（金額、日期、時間）都必須經過這個函數處理。

### `send_telegram_to(chat_id, message)`
推送訊息給指定的單一 chat_id。

### `send_to_subscribers(message, card_type)`
根據每個訂閱者的角色設定決定是否推送：

| 角色 | 附卡消費 | 正卡消費 | 取消交易 |
|---|---|---|---|
| `附卡` | ✅ 收到 | ❌ 跳過 | ✅ 收到 |
| `全部` | ✅ 收到 | ✅ 收到 | ✅ 收到 |

### `/ctbc-webhook`（主要路由）
Notification Forwarder 打來的入口，判定邏輯如下：

```
收到請求
  ↓
驗證 X-Secret → 不對 → 401 拒絕
  ↓ 對
檢查有無「刷卡通知」關鍵字 → 沒有 → ignored
  ↓ 有
檢查有無「取消交易」
  ↓ 有                          ↓ 沒有
組取消交易訊息              parse_notification() 解析
card_type = None            取得 card_type（附卡/正卡/None）
  ↓                              ↓
  └──────────────┬───────────────┘
                 ↓
        send_to_subscribers(message, card_type)
                 ↓
        逐一檢查每個訂閱者
                 ↓
        role == "全部" → 推送
        role == "附卡" 且 card_type != "正卡" → 推送
        role == "附卡" 且 card_type == "正卡" → 跳過
```

### `/health`
簡單的健康檢查端點，回傳 `{"status": "ok"}`，可用來確認服務是否正常運作。


## 事前準備

- 正卡人 Android 手機已安裝 **中國信託 Home Bank App** 並開啟消費推播通知
- 附卡人備機已安裝 **Telegram**
- 一個 **GitHub 帳號**（放程式碼）
- 一個 **Railway 帳號**（跑伺服器，免費額度足夠）

---

## 第一步：建立 Telegram Bot

1. 在 Telegram 搜尋 `@BotFather`，傳送 `/newbot`
2. 依指示設定 Bot 名稱與 username（username 必須以 `bot` 結尾）
3. 完成後取得 **Bot Token**，格式如下：
   ```
   1234567890:ABCDefGhIJKlmNoPQRsTUVwxyZ
   ```
4. 在**附卡人的備機**找到剛建立的 Bot，傳任意一則訊息（例如 `hi`）
5. 在瀏覽器開啟以下網址取得 **chat_id**：
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
6. 在回傳的 JSON 中找到 `"chat":{"id":` 後面的數字，即為 chat_id

> ⚠️ 如果 `getUpdates` 回傳空陣列，確認備機已傳過訊息給 Bot，並先執行一次 `deleteWebhook`：
> ```
> https://api.telegram.org/bot<TOKEN>/deleteWebhook
> ```

---

## 第二步：部署中繼伺服器到 Railway

### 2-1. 建立 GitHub repo

1. 在 GitHub 建立一個新的 **private** repo（建議 private，保護 token 安全）
2. 將以下四個檔案推上去：
   - `app.py`
   - `requirements.txt`
   - `Dockerfile`
   - `docker-compose.yml`（Railway 實際上不需要此檔，但留著備用）

### 2-2. 在 Railway 部署

1. 登入 [railway.app](https://railway.app)
2. 點選 **New Project** → **Deploy from GitHub repo**
3. 選擇剛建立的 repo
4. Railway 會自動偵測 Dockerfile 並開始 build

### 2-3. 設定環境變數

部署完成後，進入專案的 **Variables** 頁面，新增以下三個變數：

| Key | Value |
|---|---|
| `TELEGRAM_TOKEN` | 第一步取得的 Bot Token |
| `TELEGRAM_SUBSCRIBERS` | 訂閱者清單，格式：`chat_id:角色`，多人用逗號分隔。角色填 `附卡`（只收附卡通知）或 `全部`（正附卡都收）。例如：`6125036159:附卡,8065049962:全部` |
| `WEBHOOK_SECRET` | 自訂一串隨機英數字，例如 `ctbc2026xyz`（用來防止別人亂打你的 endpoint） |

### 2-4. 取得公開網域

進入專案的 **Settings → Networking → Public Networking**，Railway 會提供一個網域，格式如下：
```
https://xxxx.railway.app
```

記下這個網域，下一步會用到。

---

## 第三步：安裝 Notification Forwarder（正卡人手機）

### 3-1. 下載安裝

從 GitHub Releases 下載 APK：
```
https://github.com/ItsAzni/NotificationForwarder/releases/tag/v1.0
```

安裝時需要允許「安裝不明來源應用程式」。

### 3-2. 授予權限

1. 開啟 App → 點選 **Open Access Settings**
2. 在系統通知存取設定中，找到 **Notification Forwarder** 並開啟
3. 回到 App → 點選 **Open Battery Settings**
4. 找到 Notification Forwarder，設定電池優化為**不限制**

> ⚠️ 電池優化這步非常重要，否則 Android 會在背景把 App 殺掉，導致通知漏接。

### 3-3. 設定 Webhook

切換到 **Webhook** 頁面，填入以下內容：

| 欄位 | 值 |
|---|---|
| Webhook URL | `https://xxxx.railway.app/ctbc-webhook` |
| HTTP method | `POST` |
| Auth mode | `NONE` |
| Custom headers | `Content-Type: application/json`（換行）`X-Secret: 你設的WEBHOOK_SECRET` |
| Query params | 空白 |
| Payload template | 見下方 |

**Payload template：**
```json
{
  "title": "{title}",
  "text": "{text}"
}
```

填完後按 **Save Webhook Settings**。

### 3-4. 設定 Filter（只轉發中信通知）

切換到 **Filter** 頁面，依照你的 App 版本選擇對應的設定方式：

**版本 A：有 App filter 選擇介面**

- **App filter**：選擇「中國信託銀行（Home Bank）」
- **Text contains**：留空

**版本 B：Package name 白名單模式（Filter mode 下拉選單）**

- **Filter mode**：選 `WHITELIST`
- **Packages list**：填入以下 package name：
  ```
  com.chinatrust.mobilebank
  ```
  （可從 Play Store 連結確認：`https://play.google.com/store/apps/details?id=com.chinatrust.mobilebank`）
- **Max retries** / **Batch size**：維持預設（10 / 20）
- 按 **Save Filter & Retry**

> ℹ️ Text contains 或 Packages list 的過濾只是讓 Notification Forwarder 只轉發中信的通知。正卡/附卡的推送邏輯由伺服器的 `send_to_subscribers()` 根據每個訂閱者的角色設定決定，不在手機端過濾。

---

## 第四步：測試

### 方法 A：Test Webhook（快速確認連線）

在 Notification Forwarder 的 Webhook 頁面按 **Test Webhook**。

> ⚠️ 測試訊息內容是假的（`This is a test payload`），不含「刷卡通知」關鍵字，所以伺服器會回傳 `{"status":"ignored"}`，**不會**推送到 Telegram。這是正常的，代表過濾邏輯正常運作。去 Railway 的 HTTP Logs 確認有出現 200 回應即代表連線成功。

### 方法 B：模擬真實通知（完整測試）

用以下指令發送一筆模擬的刷卡通知，確認備機 Telegram 能收到完整格式的訊息。

**Windows（PowerShell）：**
```powershell
$body = [System.Text.Encoding]::UTF8.GetBytes('{"title":"中國信託銀行","text":"【刷卡通知】您於2026/05/27 14:51中信卡消費$71元(附卡)"}')
Invoke-WebRequest -Uri "https://你的網域/ctbc-webhook" -Method POST -Headers @{"Content-Type"="application/json"; "X-Secret"="你的WEBHOOK_SECRET"} -Body $body -UseBasicParsing
```

**macOS / Linux（Terminal）：**
```bash
curl -X POST "https://你的網域/ctbc-webhook" \
  -H "Content-Type: application/json" \
  -H "X-Secret: 你的WEBHOOK_SECRET" \
  -d '{"title":"中國信託銀行","text":"【刷卡通知】您於2026/05/27 14:51中信卡消費$71元(附卡)"}'
```

回傳 `{"status":"ok"}` 且備機 Telegram 收到訊息即代表成功。

### 方法 C：在手機 Payload template 填入模擬資料

在 Notification Forwarder 的 Webhook 頁面，把 Payload template 暫時改成固定內容：

**測試附卡：**
```json
{
  "title": "中國信託銀行",
  "text": "【刷卡通知】您於2026/05/27 14:51中信卡消費$71元(附卡)"
}
```

**測試正卡：**
```json
{
  "title": "中國信託銀行",
  "text": "【刷卡通知】您於2026/05/27 14:51中信卡消費$71元(正卡)"
}
```

按 **Test Webhook** 觸發，確認各訂閱者收到（或跳過）的行為正確。

> ⚠️ 測試完成後記得把 Payload template 改回正常格式，否則之後所有真實通知都會推送這筆假資料：
> ```json
> {
>   "title": "{title}",
>   "text": "{text}"
> }
> ```

### 方法 C：在手機 Payload template 填入模擬資料

在 Notification Forwarder 的 Webhook 頁面，把 Payload template 暫時改成固定內容：

**測試附卡：**
```json
{
  "title": "中國信託銀行",
  "text": "【刷卡通知】您於2026/05/27 14:51中信卡消費$71元(附卡)"
}
```

**測試正卡：**
```json
{
  "title": "中國信託銀行",
  "text": "【刷卡通知】您於2026/05/27 14:51中信卡消費$71元(正卡)"
}
```

按 **Test Webhook** 觸發，確認各訂閱者收到（或跳過）的行為正確。

> ⚠️ 測試完成後記得把 Payload template 改回正常格式，否則之後所有真實通知都會推送這筆假資料：
> ```json
> {
>   "title": "{title}",
>   "text": "{text}"
> }
> ```

### 成功後的訊息樣式

```
🔔 中國信託刷卡通知 🔔

💵 消費金額：NT$71
🗓 交易時間：2026/05/27 14:51
💳 卡別：中信uniopen聯名卡附卡
🔢 卡末4碼：1931
```

---

## 資料流與隱私說明

```
Home Bank App（正卡人手機）
  → Notification Forwarder（本地攔截，開源）
  → Railway 伺服器（你自己的程式，不經過任何第三方）
  → Telegram Bot API（官方端點）
  → 附卡人 Telegram
```

- Notification Forwarder 完全開源（MIT License），不上傳任何資料到第三方
- Railway 上跑的是你自己的程式，原始碼完全可審計
- 通知內容只經過 Telegram 官方伺服器，不經過任何其他服務

---

## 通知解析原理

`app.py` 使用**正則表達式（regex）**從通知文字中提取結構化資訊。概念是「描述一個文字的形狀，然後從字串裡找符合的部分」。

原始通知文字：
```
【刷卡通知】您於2026/05/27 14:51中信卡消費$71元(附卡)
```

### 提取日期與時間

```python
re.search(r"(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2})", text)
```

| 片段 | 意思 |
|---|---|
| `\d{4}` | 4 個數字（年） |
| `/` | 斜線 |
| `\d{2}` | 2 個數字（月） |
| `/` | 斜線 |
| `\d{2}` | 2 個數字（日） |
| `\s+` | 一個或多個空白 |
| `\d{2}:\d{2}` | 2個數字:2個數字（時間） |

對應到：`2026/05/27 14:51`。外面的 `(...)` 是捕獲群組，`.group(1)` 拿日期，`.group(2)` 拿時間。

### 提取金額

```python
re.search(r"\$(\d+(?:\.\d+)?)", text)
```

| 片段 | 意思 |
|---|---|
| `\$` | 錢字號（需要跳脫，因為 `$` 在 regex 有特殊意義） |
| `\d+` | 一個或多個數字 |
| `(?:\.\d+)?` | 可選的小數點部分（`?` 代表可有可無） |

對應到 `$71` 或 `$71.50` 都能正確抓取，`.group(1)` 拿到純數字 `71`。

### 提取附卡／正卡

```python
re.search(r"\((附卡|正卡)\)", text)
```

| 片段 | 意思 |
|---|---|
| `\(` | 左括號（需要跳脫） |
| `附卡\|正卡` | 附卡**或**正卡 |
| `\)` | 右括號 |

對應到 `(附卡)` 或 `(正卡)`，`.group(1)` 拿到括號內的文字。

### 解析結果

三段 regex 跑完後產生結構化資料：

```python
{
    "date": "2026/05/27",
    "time": "14:51",
    "amount": "71",
    "card_type": "附卡"
}
```

再由 `format_message()` 組成最終推送到 Telegram 的訊息。

### 取消交易的處理

取消交易通知格式不同（無金額、無時間），程式偵測到「取消交易」關鍵字後會跳過解析，直接轉發原始文字：

```python
if "取消交易" in text:
    message = f"🔔 中信通知\n\n{text}"
else:
    parsed = parse_notification(text)
    message = format_message(parsed)
```

---

## 常見問題

**Q：Notification Forwarder 被系統殺掉怎麼辦？**

除了關閉電池優化之外，部分品牌（小米 MIUI、OPPO ColorOS、vivo Funtouch）需要額外開啟「自啟動」權限，請在手機的電池或權限管理設定中找到對應選項。

**Q：Railway 免費額度夠用嗎？**

這個服務非常輕量，一個月的刷卡通知數量遠低於 Railway 的免費額度限制。

**Q：通知解析失敗怎麼辦？**

如果中信更改推播通知的文字格式，正則表達式可能會失效。此時備機仍會收到通知，但只會顯示原始文字而非格式化內容。可以到 Railway 的 Logs 頁面確認錯誤訊息，並更新 `app.py` 中的正則表達式。

---

## 檔案說明

| 檔案 | 說明 |
|---|---|
| `app.py` | 主程式，Flask webhook 伺服器 |
| `requirements.txt` | Python 套件清單 |
| `Dockerfile` | Docker 容器設定 |
| `docker-compose.yml` | 本地或 TrueNAS 部署用（Railway 不需要） |
