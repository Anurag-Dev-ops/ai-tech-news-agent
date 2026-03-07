import requests
import os

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_message(articles):

    if not articles:
        text = "No major AI news today."
    else:
        text = "Top AI / Tech News:\n\n"

        for a in articles[:5]:
            text += f"• {a['title']}\n{a['link']}\n\n"

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": text
    }

    requests.post(url, data=payload)