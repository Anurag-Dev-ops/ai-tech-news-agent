# runner.py
"""
Minimal, modular starter for:
- fetching RSS feeds
- extracting article text
- calling an LLM to filter+rank+summarize
- sending top-5 as a Telegram push notification
Run: pip install -r requirements.txt
Then: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, LLM_API_KEY must be set as env vars.
"""

import os
import time
import hashlib
import logging
from typing import List, Dict, Optional
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
import json

# --- CONFIG ------------------------------------------------------------
RSS_FEEDS = [
    # add the feeds you trust
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://news.ycombinator.com/rss",
    "https://arxiv.org/rss/cs.RO",  # robotics
    "https://arxiv.org/rss/cs.AI",
    # add more specific feeds like IEEE Spectrum RSS etc.
]

# Environment config: set these safely in your environment or .env
LLM_API_KEY = os.getenv("LLM_API_KEY")  # required
LLM_API_HOST = os.getenv("LLM_API_HOST", "https://api.openai.com/v1/chat/completions")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # numeric user id or channel id
DEDUP_FILE = os.getenv("DEDUP_FILE", "seen.json")

MAX_CANDIDATES = 40  # how many recent articles to consider
TOP_K = 5

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("news-agent")

# --- UTIL: DEDUPE STORAGE ----------------------------------------------
def load_seen():
    if os.path.exists(DEDUP_FILE):
        with open(DEDUP_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen(seen_set):
    with open(DEDUP_FILE, "w") as f:
        json.dump(list(seen_set), f)

# --- FETCHER: RSS -----------------------------------------------------
def fetch_rss_items(feeds: List[str], max_items=MAX_CANDIDATES) -> List[Dict]:
    items = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries:
                items.append({
                    "title": e.get("title", ""),
                    "link": e.get("link", ""),
                    "published": e.get("published", ""),
                    "summary": e.get("summary", "")[:1000]
                })
        except Exception as e:
            logger.warning("Failed feed %s: %s", url, e)
    # sort by published if available
    def time_key(i):
        try:
            return time.mktime(feedparser.parse(i.get("link","")).updated_parsed)
        except Exception:
            return 0
    # prefer newest-ish, but keep stable list
    items = [i for i in items if i.get("link")]
    unique = {}
    for it in items:
        unique[it["link"]] = it
    items = list(unique.values())[:max_items]
    return items

# --- PARSER: extract main text ----------------------------------------
def extract_article_text(url: str, max_chars=5000) -> str:
    """
    Best-effort extraction: try requests + soup to get main paragraphs.
    For robust extraction, swap to newspaper3k or readability-lxml.
    """
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent":"news-agent/1.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # simple heuristic: collect text from p tags within article or body
        article = soup.find("article")
        if article:
            ps = article.find_all("p")
        else:
            ps = soup.body.find_all("p") if soup.body else []
        text = "\n\n".join(p.get_text().strip() for p in ps if p.get_text().strip())
        text = text.strip()
        if not text:
            # fallback: meta description or longest text block
            desc = soup.find("meta", attrs={"name":"description"}) or soup.find("meta", attrs={"property":"og:description"})
            if desc and desc.get("content"):
                text = desc["content"]
        return text[:max_chars]
    except Exception as e:
        logger.warning("Failed to fetch article %s: %s", url, e)
        return ""

# --- LLM client wrapper ------------------------------------------------
def call_llm_system(messages: List[Dict], max_tokens=512, temperature=0.0) -> Dict:
    """
    Generic OpenAI-compatible chat completion call.
    Adapt LLM_API_HOST if using a different provider. Expects environment variables set.
    """
    if not LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY not set in environment")
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type":"application/json"}
    payload = {
        "model": "gpt-4o-mini",  # placeholder, swap with your model id
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    resp = requests.post(LLM_API_HOST, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()

# --- FILTER & SUMMARIZE -----------------------------------------------
PROMPT_SYSTEM = """
You are a strict filter and summarizer whose job is to:
1) Mark whether the article is relevant to AI, robotics, or core technology updates (yes/no).
2) If yes, provide a concise 2-sentence context + a 1-line bullet summary (max 30 words).
3) Provide a numeric importance score 0-10 (10 most important) and up to 2 short reasons (source-based).
4) Always output JSON with keys: relevant (true/false), score (float), summary (string), evidence (one short quote from the article), url (string).
Rules: do not hallucinate; only use the article content and title provided.
"""

def evaluate_articles_with_llm(candidates: List[Dict]) -> List[Dict]:
    """
    Send batched calls to LLM. For cost reasons, we summarize each candidate quickly.
    Return list of dicts: {link, title, summary, score, relevant, evidence}
    """
    results = []
    for c in candidates:
        title = c["title"]
        url = c["link"]
        text = c.get("text", "")
        # build prompt - keep it short. Provide the article title + first 1200 chars of text.
        messages = [
            {"role":"system", "content": PROMPT_SYSTEM},
            {"role":"user", "content": f"TITLE: {title}\nURL: {url}\n\nARTICLE:\n{text[:1500]}\n\nRespond in strict JSON."}
        ]
        try:
            rsp = call_llm_system(messages, max_tokens=300)
            # parse response text
            content = rsp["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            parsed["link"] = url
            parsed["title"] = title
            results.append(parsed)
        except Exception as e:
            logger.warning("LLM failure for %s: %s", url, e)
            # fallback: mark not relevant
            results.append({"link": url, "title": title, "relevant": False, "score": 0.0, "summary": "", "evidence": ""})
    return results

# --- NOTIFIER: Telegram ------------------------------------------------
def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram config missing")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode":"Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        logger.warning("Failed to send telegram: %s", e)
        return False

# --- ORCHESTRATION ----------------------------------------------------
def run_once():
    logger.info("Starting fetch run: %s", datetime.utcnow().isoformat())
    seen = load_seen()
    items = fetch_rss_items(RSS_FEEDS, max_items=MAX_CANDIDATES)
    # attach extracted text
    candidates = []
    for it in items:
        link = it["link"]
        if link in seen:
            continue
        text = extract_article_text(link)
        if not text:
            # skip if no content
            continue
        # create a small fingerprint
        fid = hashlib.sha256((link + it["title"]).encode()).hexdigest()
        candidates.append({"link": link, "title": it["title"], "text": text, "fid": fid})

    if not candidates:
        logger.info("No new candidates")
        return

    llm_results = evaluate_articles_with_llm(candidates)

    # filter and sort
    relevant = [r for r in llm_results if r.get("relevant")]
    relevant_sorted = sorted(relevant, key=lambda r: r.get("score", 0), reverse=True)[:TOP_K]

    if not relevant_sorted:
        logger.info("No relevant articles found")
        # mark candidates seen to avoid repetition
        for c in candidates:
            seen.add(c["link"])
        save_seen(seen)
        return

    # prepare message
    lines = []
    header = f"Top {len(relevant_sorted)} AI/Robotics/Tech updates • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    lines.append(header)
    for i, r in enumerate(relevant_sorted, start=1):
        s = r.get("summary", "").strip().replace("\n", " ")
        url = r.get("url") or r.get("link")
        score = r.get("score", 0)
        ev = r.get("evidence", "")
        lines.append(f"{i}. {s}\n{url} (score {score:.1f})")
        if ev:
            lines.append(f"   quote: \"{ev[:120]}\"")
    message = "\n\n".join(lines)
    # send
    ok = send_telegram(message)
    if ok:
        logger.info("Notification sent, marking seen")
        # mark all candidates we considered as seen to avoid duplicate notification
        for c in candidates:
            seen.add(c["link"])
        save_seen(seen)
    else:
        logger.warning("Failed to notify")

# --- SCHEDULER --------------------------------------------------------
def schedule_main():
    scheduler = BlockingScheduler()
    # run twice a day by default; adjust cron as needed
    scheduler.add_job(run_once, "cron", hour="8,20", minute=0)  # 08:00 and 20:00 UTC
    logger.info("Scheduler started. Next runs at 08:00 and 20:00 (UTC)")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Exiting scheduler")

if __name__ == "__main__":
    # quick local run if you want immediate test
    run_once()
    # To enable scheduler, uncomment below:
    # schedule_main()