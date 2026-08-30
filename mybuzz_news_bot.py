import os
import sqlite3
import hashlib
import requests
from datetime import datetime, timedelta, timezone

# =========================
# Configuration
# =========================

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "@mybuzzmy")

DB_FILE = "mybuzz.db"

# Number of articles to request
MAX_ARTICLES = 10

# =========================
# Categories
# =========================

CATEGORIES = {
    "news": {
        "emoji": "📰",
        "query": "Malaysia latest news",
    },
    "viral": {
        "emoji": "🔥",
        "query": "Malaysia viral trending",
    },
    "entertainment": {
        "emoji": "🎬",
        "query": "Malaysia entertainment celebrity",
    },
    "food": {
        "emoji": "🍜",
        "query": "Malaysia food restaurant",
    },
    "tech": {
        "emoji": "💻",
        "query": "Malaysia technology gadget",
    },
}

# =========================
# Database
# =========================

def init_db():
    conn = sqlite3.connect(DB_FILE)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_hash TEXT UNIQUE,
            title TEXT,
            url TEXT,
            category TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def article_exists(article_hash):
    conn = sqlite3.connect(DB_FILE)

    cur = conn.execute(
        "SELECT 1 FROM articles WHERE article_hash = ? LIMIT 1",
        (article_hash,)
    )

    result = cur.fetchone()

    conn.close()

    return result is not None


def save_article(article_hash, title, url, category):
    conn = sqlite3.connect(DB_FILE)

    conn.execute(
        """
        INSERT OR IGNORE INTO articles
        (article_hash, title, url, category, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            article_hash,
            title,
            url,
            category,
            datetime.now(timezone.utc).isoformat(),
        )
    )

    conn.commit()
    conn.close()


# =========================
# GNews
# =========================

def get_news(query):
    if not GNEWS_API_KEY:
        raise RuntimeError("GNEWS_API_KEY is missing")

    url = "https://gnews.io/api/v4/search"

    params = {
        "q": query,
        "lang": "en",
        "country": "my",
        "max": MAX_ARTICLES,
        "apikey": GNEWS_API_KEY,
    }

    response = requests.get(url, params=params, timeout=30)

    response.raise_for_status()

    data = response.json()

    return data.get("articles", [])


# =========================
# Text formatting
# =========================

def clean_text(text):
    if not text:
        return ""

    return " ".join(text.split())


def create_message(article, category):
    title = clean_text(article.get("title", ""))
    description = clean_text(article.get("description", ""))
    url = article.get("url", "")

    emoji = CATEGORIES[category]["emoji"]

    # Limit description length
    if len(description) > 300:
        description = description[:300].rstrip() + "..."

    message = (
        f"{emoji} <b>{category.upper()}</b>\n\n"
        f"<b>{title}</b>\n\n"
    )

    if description:
        message += f"{description}\n\n"

    message += (
        f"🔗 <b>อ่านเพิ่มเติม / Baca berita penuh</b>\n"
        f"👉 <a href=\"{url}\">Read Full Story</a>\n\n"
        f"🇲🇾 <b>MYBUZZ</b>"
    )

    return message


# =========================
# Telegram
# =========================

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
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
            f"Telegram error: {result}"
        )

    return result


# =========================
# Main
# =========================

def main():

    print("================================")
    print("MYBUZZ NEWS BOT")
    print("================================")

    print("Starting bot...")

    init_db()

    if not GNEWS_API_KEY:
        print("ERROR: GNEWS_API_KEY is missing")
        return

    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is missing")
        return

    print("GNews API: OK")
    print(f"Telegram Channel: {TELEGRAM_CHAT_ID}")

    total_sent = 0

    # Run all categories
    for category, config in CATEGORIES.items():

        print("")
        print(f"Fetching {category}...")

        try:
            articles = get_news(config["query"])

        except Exception as e:
            print(
                f"Failed to fetch {category}: {e}"
            )
            continue

        print(
            f"Found {len(articles)} articles"
        )

        # Only send first 2 new articles
        sent_for_category = 0

        for article in articles:

            if sent_for_category >= 2:
                break

            title = clean_text(
                article.get("title", "")
            )

            url = article.get("url", "")

            if not title or not url:
                continue

            # Create unique hash
            article_hash = hashlib.sha256(
                url.encode("utf-8")
            ).hexdigest()

            if article_exists(article_hash):
                print(
                    f"Already posted: {title}"
                )
                continue

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

                total_sent += 1
                sent_for_category += 1

                print(
                    f"Posted: {title}"
                )

            except Exception as e:

                print(
                    f"Telegram error: {e}"
                )

    print("")
    print("================================")
    print(
        f"Finished. Sent {total_sent} articles."
    )
    print("================================")


if __name__ == "__main__":
    main()
