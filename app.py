import os
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")  # 可選，防止亂打你的 endpoint


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


def format_message(parsed: dict) -> str:
    lines = ["💳 *中國信託刷卡通知*", ""]

    if parsed["amount"]:
        lines.append(f"💵*消費金額：* NT\\${parsed['amount']}")

    if parsed["date"] and parsed["time"]:
        lines.append(f"📅*交易時間：* {parsed['date']} {parsed['time']}")

    if parsed["card_type"]:
        if parsed["card_type"] == "附卡":
            lines.append(f"💳*卡別：* 中信uniopen聯名卡附卡 | 卡末4碼：1931")

        # emoji = "🔴" if parsed["card_type"] == "附卡" else "🔵"
        # lines.append(f"{emoji} {parsed['card_type']}")

    # 如果解析失敗就直接顯示原文
    if not any([parsed["date"], parsed["amount"], parsed["card_type"]]):
        lines.append(parsed["raw"])

    return "\n".join(lines)


def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2",
    }
    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


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

    # 取消交易：直接轉發原始訊息
    if "取消交易" in text:
        safe_text = text.replace("【", "\\[").replace("】", "\\]")  # 解決MarkdownV2 的特殊字元問題
        message = f"🔔 *中國信託信用卡取消交易通知* 🔔\n{safe_text}"
    else:
        parsed = parse_notification(text)
        if parsed["card_type"] == "正卡":
            return jsonify({"status": "ignored"}), 200
        message = format_message(parsed)

    try:
        send_telegram(message)
    except Exception as e:
        app.logger.error(f"Telegram send failed: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
