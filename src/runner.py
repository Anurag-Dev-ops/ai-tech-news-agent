from fetcher import fetch_news
from llm_filter import filter_ai_news
from notifier import send_notification

def run():
    news = fetch_news()
    filtered = filter_ai_news(news)

    if filtered:
        send_notification(filtered)

if __name__ == "__main__":
    run()