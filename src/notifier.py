import requests
import os

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_message(articles):

    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram config missing:", BOT_TOKEN, CHAT_ID)
        return

    if not articles:
        message = "No major AI / Tech news found."
    else:
        message = "🚀 Top AI / Robotics / Tech News\n\n"

        for article in articles[:5]:
            message += f"• {article['title']}\n{article['link']}\n\n"

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }

    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Telegram error:", e)