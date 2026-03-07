from dotenv import load_dotenv
load_dotenv()
import os
import json
import logging
from datetime import datetime, UTC
from apscheduler.schedulers.blocking import BlockingScheduler

from src.fetcher import fetch_news
from src.llm_filter import filter_news
from src.notifier import send_message

# load environment variables

DEDUP_FILE = "seen.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-news-agent")


def load_seen():
    if os.path.exists(DEDUP_FILE):
        with open(DEDUP_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(DEDUP_FILE, "w") as f:
        json.dump(list(seen), f)


def run_once():
    logger.info("Starting run at %s", datetime.now(UTC))

    seen = load_seen()

    articles = fetch_news()

    # remove already seen links
    new_articles = [a for a in articles if a["link"] not in seen]

    if not new_articles:
        logger.info("No new articles")
        return

    filtered = filter_news(new_articles)

    send_message(filtered)

    for article in new_articles:
        seen.add(article["link"])

    save_seen(seen)

    logger.info("Run completed")


def schedule():
    scheduler = BlockingScheduler()

    scheduler.add_job(run_once, "interval", minutes=30)

    logger.info("Scheduler started (every 30 minutes)")
    scheduler.start()


if __name__ == "__main__":
    run_once()