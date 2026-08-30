import os
import sqlite3
import hashlib
import requests
import html
import re
from datetime import datetime, timezone

# =========================
# MYBUZZ CONFIG
# =========================

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "@mybuzzmy")

DB_FILE = "mybuzz.db"

# 每次运行最多发送 1 条
MAX_POSTS = 1

# GNews 每次只请求一次
GNEWS_MAX_ARTICLES = 10

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
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def already_posted(article_hash):
    conn = sqlite3.connect(DB_FILE)

    cur = conn.execute(
        "SELECT 1 FROM articles WHERE article_hash = ? LIMIT 1",
        (article_hash,)
    )

    result = cur.fetchone()

    conn.close()

    return result is not None


def save_article(article_hash, title, url):
    conn = sqlite3.connect(DB_FILE)

    conn.execute("""
        INSERT OR IGNORE INTO articles
        (article_hash, title, url, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        article_hash,
        title,
        url,
        datetime.now(timezone.utc).isoformat()
    ))

    conn.commit()
    conn.close()


# =========================
# CLEAN TEXT
# =========================

def clean_text(text):
    if not text:
        return ""

    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = " ".join(text.split())

    return text.strip()


# =========================
# GNEWS
# =========================

def get_news():

    if not GNEWS_API_KEY:
        raise RuntimeError(
            "GNEWS_API_KEY is missing"
        )

    params = {
        "q": "Malaysia",
        "lang": "en",
        "country": "my",
        "max": GNEWS_MAX_ARTICLES,
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
            "GNews rate limit reached (429)"
        )

    if response.status_code == 403:
        raise RuntimeError(
            "GNews quota reached (403)"
        )

    response.raise_for_status()

    data = response.json()

    return data.get("articles", [])


# =========================
# CATEGORY
# =========================

def classify_article(article):

    text = (
        clean_text(article.get("title", "")) +
        " " +
        clean_text(article.get("description", ""))
    ).lower()

    entertainment = [
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

    food = [
        "food",
        "restaurant",
        "cafe",
        "chef",
        "dining",
        "recipe",
        "menu",
        "eat",
        "donut",
        "dessert"
    ]

    tech = [
        "technology",
        "technology",
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

    viral = [
        "viral",
        "trending",
        "tiktok",
        "instagram",
        "social media",
        "video",
        "shocking",
        "surprise"
    ]

    if any(x in text for x in entertainment):
        return "🎬"

    if any(x in text for x in food):
        return "🍩"

    if any(x in text for x in tech):
        return "💻"

    if any(x in text for x in viral):
        return "🔥"

    return "🇲🇾"


# =========================
# TELEGRAM
# =========================

def send_photo(photo_url, caption):

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing"
        )

    telegram_url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    )

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": "HTML"
    }

    response = requests.post(
        telegram_url,
        data=data,
        timeout=30
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram error: {result}"
        )


# =========================
# MESSAGE
# =========================

def create_caption(article):

    title = clean_text(
        article.get("title", "")
    )

    description = clean_text(
        article.get("description", "")
    )

    url = article.get("url", "")

    emoji = classify_article(article)

    # 限制摘要长度
    if len(description) > 220:
        description = (
            description[:220].rstrip() +
            "..."
        )

    # 简单英文 → 中文/马来文处理
    # 当前版本先保持内容准确，
    # 后续可以接 AI 翻译 API。
    chinese_title = title
    malay_title = title

    chinese_description = description
    malay_description = description

    caption = (
        f"{emoji} <b>{html.escape(chinese_title)}</b>\n\n"

        f"🇨🇳 {html.escape(chinese_description)}\n\n"

        f"🇲🇾 <b>{html.escape(malay_title)}</b>\n\n"

        f"{html.escape(malay_description)}\n\n"

        f'👉 <a href="{html.escape(url)}">'
        f"点击阅读完整新闻"
        f"</a>\n"

        f'👉 <a href="{html.escape(url)}">'
        f"Klik untuk baca berita penuh"
        f"</a>"
    )

    return caption


# =========================
# MAIN
# =========================

def main():

    print("================================")
    print("MYBUZZ NEWS BOT V3")
    print("================================")

    init_db()

    if not GNEWS_API_KEY:
        print("ERROR: GNEWS_API_KEY missing")
        return

    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN missing")
        return

    print("GNews API: OK")
    print(
        f"Telegram: {TELEGRAM_CHAT_ID}"
    )

    print("")
    print("Fetching Malaysia news...")

    try:
        articles = get_news()

    except Exception as e:
        print(
            f"GNews error: {e}"
        )
        return

    print(
        f"Found {len(articles)} articles"
    )

    sent = 0

    for article in articles:

        if sent >= MAX_POSTS:
            break

        title = clean_text(
            article.get("title", "")
        )

        url = clean_text(
            article.get("url", "")
        )

        image_url = clean_text(
            article.get("image", "")
        )

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

        # 没图片就跳过
        if not image_url:

            print(
                f"No image, skipping: {title}"
            )

            continue

        caption = create_caption(
            article
        )

        try:

            send_photo(
                image_url,
                caption
            )

            save_article(
                article_hash,
                title,
                url
            )

            sent += 1

            print(
                f"POSTED: {title}"
            )

        except Exception as e:

            print(
                f"Telegram error: {e}"
            )

    print("")
    print("================================")
    print(
        f"Finished. Sent {sent} article."
    )
    print("================================")


if __name__ == "__main__":
    main()
