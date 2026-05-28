import os
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")  # 可選，防止亂打你的 endpoint

# 訂閱者設定：chat_id -> 接收類型（"附卡" 或 "全部"）
# 從環境變數 TELEGRAM_SUBSCRIBERS 讀取，格式：chat_id1:附卡,chat_id2:全部
def load_subscribers() -> dict:
    raw = os.environ.get("TELEGRAM_SUBSCRIBERS", "")
    subscribers = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" not in entry:
            continue
        chat_id, role = entry.split(":", 1)
        subscribers[chat_id.strip()] = role.strip()
    return subscribers


def parse_notification(text: str) -> dict:
    """
    解析中信通知文字，例如：
    【刷卡通知】您於2026/05/27 14:51中信卡消費$71元(附卡)
    """
    result = {
        "raw": text,
        "date": None,
        "time": None,
        "amount": None,
        "card_type": None,
    }

    # 提取日期時間：2026/05/27 14:51
    dt_match = re.search(r"(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2})", text)
    if dt_match:
        result["date"] = dt_match.group(1)
        result["time"] = dt_match.group(2)

    # 提取金額：$71
    amount_match = re.search(r"\$(\d+(?:\.\d+)?)", text)
    if amount_match:
        result["amount"] = amount_match.group(1)

    # 提取附卡/正卡
    card_match = re.search(r"\((附卡|正卡)\)", text)
    if card_match:
        result["card_type"] = card_match.group(1)

    return result


# MarkdownV2 要求所有特殊字元前面加反斜線
# 否則 Telegram 會回 400 Bad Request
def escape_md(text: str) -> str:
    """跳脫 MarkdownV2 所有特殊字元"""
    special = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([' + re.escape(special) + r'])', r'\\\1', text)


def format_message(parsed: dict) -> str:
    lines = ["🔔 *中國信託刷卡通知* 🔔", ""]

    # 所有從外部來的變數都要跳脫，避免 MarkdownV2 解析錯誤
    if parsed["amount"]:
        lines.append(f"💵 *消費金額：*NT\\${escape_md(parsed['amount'])}")

    if parsed["date"] and parsed["time"]:
        lines.append(f"📅 *交易時間：*{escape_md(parsed['date'])} {escape_md(parsed['time'])}")

    if parsed["card_type"]:
        if parsed["card_type"] == "附卡":
            lines.append(f"💳 *卡別：*中信uniopen聯名卡 \\| 附卡")
            lines.append(f"🏦 *卡末四碼：*1931")
        else:
            lines.append(f"💳 *卡別：*中信uniopen聯名卡 \\| 正卡")
            lines.append(f"🏦 *卡末四碼：*6020")

        #兩層跳脫：
            # 第一層：Python 字串本身
            # 在 Python 字串裡，\ 是跳脫字元。所以 \\ 在 Python 字串裡代表「一個真正的反斜線 \」。
            # 第二層：MarkdownV2 語法
            # Telegram MarkdownV2 要求特殊字元前面加一個反斜線 \，所以 \| 才能讓 Telegram 把 | 當成普通字元顯示。

    # 如果解析失敗就直接顯示原文
    if not any([parsed["date"], parsed["amount"], parsed["card_type"]]):
        lines.append(escape_md(parsed["raw"]))

    return "\n".join(lines)


def send_telegram_to(chat_id: str, message: str):
    """推送訊息給指定的 chat_id"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "MarkdownV2",
    }
    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def send_to_subscribers(message: str, card_type: str):
    """
    根據每個訂閱者的設定決定是否推送
    card_type: "附卡"、"正卡"、或 None（取消交易等無卡別通知）
    """
    subscribers = load_subscribers()
    for chat_id, role in subscribers.items():
        # 全部：正卡附卡都推
        if role == "全部":
            send_telegram_to(chat_id, message)
        # 附卡：只推附卡和無卡別通知（取消交易）
        elif role == "附卡" and card_type != "正卡":
            send_telegram_to(chat_id, message)


@app.route("/ctbc-webhook", methods=["POST"])
def webhook():
    # 可選的 secret 驗證
    if WEBHOOK_SECRET:
        secret = request.headers.get("X-Secret", "")
        if secret != WEBHOOK_SECRET:
            return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text", "")
    title = data.get("title", "")

    # 只處理中信刷卡通知
    if "刷卡通知" not in text and "刷卡通知" not in title:
        return jsonify({"status": "ignored"}), 200

    # 取消交易：直接轉發原始訊息，card_type 設為 None
    if "取消交易" in text:
        safe_text = text.replace("【", "\\[").replace("】", "\\]")  # 解決 MarkdownV2 的特殊字元問題
        message = f"🔔 *中國信託信用卡取消交易通知* 🔔\n{safe_text}"
        card_type = None
    else:
        parsed = parse_notification(text)
        message = format_message(parsed)
        card_type = parsed["card_type"]

    try:
        send_to_subscribers(message, card_type)
    except Exception as e:
        app.logger.error(f"Telegram send failed: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
