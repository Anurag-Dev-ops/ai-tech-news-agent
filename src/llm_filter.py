KEYWORDS = [
    "ai",
    "artificial intelligence",
    "robot",
    "robotics",
    "machine learning",
    "deep learning",
    "llm",
    "nvidia",
    "openai",
    "semiconductor",
]


def filter_news(articles):

    filtered = []

    for article in articles:

        text = (article["title"] + article.get("summary", "")).lower()

        if any(keyword in text for keyword in KEYWORDS):
            filtered.append(article)

    return filtered