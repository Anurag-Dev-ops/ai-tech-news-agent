import feedparser

RSS_URL = "https://news.google.com/rss/search?q=artificial+intelligence+robotics+technology"

def fetch_news():
    feed = feedparser.parse(RSS_URL)

    articles = []

    for entry in feed.entries[:10]:
        articles.append({
            "title": entry.title,
            "link": entry.link
        })

    return articles