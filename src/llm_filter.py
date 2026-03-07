KEYWORDS = [
    "AI",
    "artificial intelligence",
    "robot",
    "robotics",
    "machine learning",
    "OpenAI",
    "Tesla",
    "Nvidia"
]

def filter_news(articles):
    filtered = []

    for article in articles:
        title = article["title"].lower()

        if any(keyword.lower() in title for keyword in KEYWORDS):
            filtered.append(article)

    return filtered