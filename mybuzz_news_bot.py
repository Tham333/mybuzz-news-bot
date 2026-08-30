import os
import sqlite3
import hashlib
import requests
from datetime import datetime, timezone

# =========================
# CONFIG
# =========================

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "@mybuzzmy")

DB_FILE = "mybuzz.db"

MAX_GNEWS_ARTICLES = 10
MAX_TELEGRAM_POSTS = 5

GNEWS_URL = "https://gnews.io/api/v4/search"


# =========================
# DATABASE
# =========================

def init_db():
    conn = sqlite3.connect(DB_FILE)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            article_hash TEXT PRIMARY KEY,
            title TEXT,
            url TEXT,
            category TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def already_posted(article_hash):
    conn = sqlite3.connect(DB_FILE)

    cur = conn.execute(
        "SELECT article_hash FROM articles WHERE article_hash = ?",
        (article_hash,)
    )

    result = cur.fetchone()

    conn.close()

    return result is not None


def save_article(article_hash, title, url, category):
    conn = sqlite3.connect(DB_FILE)

    conn.execute("""
        INSERT OR IGNORE INTO articles
        (article_hash, title, url, category, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        article_hash,
        title,
        url,
        category,
        datetime.now(timezone.utc).isoformat()
    ))

    conn.commit()
    conn.close()


# =========================
# GNEWS
# =========================

def get_news():

    if not GNEWS_API_KEY:
        raise RuntimeError("GNEWS_API_KEY is missing")

    params = {
        "q": "Malaysia",
        "lang": "en",
        "country": "my",
        "max": MAX_GNEWS_ARTICLES,
        "sortby": "publishedAt",
        "apikey": GNEWS_API_KEY
    }

    response = requests.get(
        GNEWS_URL,
        params=params,
        timeout=30
    )

    if response.status_code == 429:
        raise RuntimeError(
            "GNews rate limit reached (429). Try again later."
        )

    if response.status_code == 403:
        raise RuntimeError(
            "GNews daily quota reached (403)."
        )

    response.raise_for_status()

    data = response.json()

    return data.get("articles", [])


# =========================
# CATEGORY
# =========================

def classify_article(article):

    text = (
        article.get("title", "") + " " +
        article.get("description", "")
    ).lower()

    entertainment_words = [
        "celebrity",
        "actor",
        "actress",
        "singer",
        "concert",
        "movie",
        "film",
        "music",
        "k-pop",
        "artist",
        "entertainment"
    ]

    food_words = [
        "food",
        "restaurant",
        "cafe",
        "recipe",
        "chef",
        "dining",
        "eat",
        "menu",
        "restaurant"
    ]

    tech_words = [
        "technology",
        "tech",
        "iphone",
        "android",
        "google",
        "apple",
        "samsung",
        "ai",
        "artificial intelligence",
        "gadget",
        "software"
    ]

    viral_words = [
        "viral",
        "trending",
        "social media",
        "tiktok",
        "instagram",
        "video",
        "shocking",
        "surprise"
    ]

    if any(word in text for word in entertainment_words):
        return "🎬 Entertainment"

    if any(word in text for word in food_words):
        return "🍜 Food"

    if any(word in text for word in tech_words):
        return "💻 Tech"

    if any(word in text for word in viral_words):
        return "🔥 Viral"

    return "📰 News"


# =========================
# TELEGRAM
# =========================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing"
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    response = requests.post(
        url,
        data=data,
        timeout=30
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram API error: {result}"
        )


# =========================
# MESSAGE
# =========================

def create_message(article, category):

    title = article.get("title", "").strip()
    description = (
        article.get("description") or ""
    ).strip()

    url = article.get("url", "")
    source = article.get("source", {}).get(
        "name",
        "News Source"
    )

    if len(description) > 280:
        description = (
            description[:280].rstrip() +
            "..."
        )

    message = (
        f"{category}\n\n"
        f"<b>{title}</b>\n\n"
    )

    if description:
        message += (
            f"{description}\n\n"
        )

    message += (
        f"📰 <i>{source}</i>\n\n"
        f"🔗 "
        f"<a href=\"{url}\">"
        f"Read Full Story"
        f"</a>\n\n"
        f"🇲🇾 <b>MYBUZZ</b>"
    )

    return message


# =========================
# MAIN
# =========================

def main():

    print("================================")
    print("MYBUZZ NEWS BOT V2")
    print("================================")

    init_db()

    if not GNEWS_API_KEY:
        print("ERROR: GNEWS_API_KEY missing")
        return

    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN missing")
        return

    print("GNews API: OK")
    print(f"Telegram: {TELEGRAM_CHAT_ID}")

    print("")
    print("Fetching Malaysia news...")

    try:
        articles = get_news()

    except Exception as e:
        print(f"GNews error: {e}")
        return

    print(
        f"Found {len(articles)} articles"
    )

    sent = 0

    for article in articles:

        if sent >= MAX_TELEGRAM_POSTS:
            break

        title = article.get(
            "title",
            ""
        ).strip()

        url = article.get(
            "url",
            ""
        ).strip()

        if not title or not url:
            continue

        article_hash = hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()

        if already_posted(article_hash):

            print(
                f"Already posted: {title}"
            )

            continue

        category = classify_article(
            article
        )

        message = create_message(
            article,
            category
        )

        try:

            send_telegram(message)

            save_article(
                article_hash,
                title,
                url,
                category
            )

            sent += 1

            print(
                f"POSTED [{category}] {title}"
            )

        except Exception as e:

            print(
                f"Telegram error: {e}"
            )

    print("")
    print("================================")
    print(
        f"Finished. Sent {sent} articles."
    )
    print("================================")


if __name__ == "__main__":
    main()
