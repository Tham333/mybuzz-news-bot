import os
import sqlite3
import hashlib
import requests
import html
import json
from datetime import datetime, timezone

from google import genai


# ==========================================
# MYBUZZ CONFIG
# ==========================================

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    "@mybuzzmy"
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

DB_FILE = "mybuzz.db"

MAX_GNEWS_ARTICLES = 10
MAX_POSTS = 1

GNEWS_URL = "https://gnews.io/api/v4/search"


# ==========================================
# DATABASE
# ==========================================

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
        """
        SELECT 1
        FROM articles
        WHERE article_hash = ?
        LIMIT 1
        """,
        (article_hash,)
    )

    result = cur.fetchone()

    conn.close()

    return result is not None


def save_article(article_hash, title, url):

    conn = sqlite3.connect(DB_FILE)

    conn.execute(
        """
        INSERT OR IGNORE INTO articles
        (article_hash, title, url, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            article_hash,
            title,
            url,
            datetime.now(timezone.utc).isoformat()
        )
    )

    conn.commit()
    conn.close()


# ==========================================
# CLEAN TEXT
# ==========================================

def clean_text(text):

    if not text:
        return ""

    return " ".join(
        html.unescape(str(text)).split()
    ).strip()


# ==========================================
# GNEWS
# ==========================================

def get_news():

    if not GNEWS_API_KEY:
        raise RuntimeError(
            "GNEWS_API_KEY is missing"
        )

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
            "GNews rate limit reached (429)"
        )

    if response.status_code == 403:
        raise RuntimeError(
            "GNews quota reached (403)"
        )

    response.raise_for_status()

    data = response.json()

    return data.get("articles", [])


# ==========================================
# GEMINI TRANSLATION
# ==========================================

def translate_news(title, description):

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is missing"
        )

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    prompt = f"""
You are the editor of a Malaysian news Telegram channel called MYBUZZ.

Translate and rewrite the following English news into natural,
short and easy-to-read Chinese and Bahasa Melayu.

IMPORTANT:
- Do NOT invent facts.
- Keep names, places, dates and numbers accurate.
- Keep the meaning of the original news.
- Make the title attractive but factual.
- Chinese should be natural Malaysian Chinese.
- Malay should be natural Bahasa Melayu used in Malaysia.
- Keep the summary short.
- Do not use markdown.
- Return ONLY valid JSON.

Required JSON format:

{{
  "chinese_title": "...",
  "chinese_summary": "...",
  "malay_title": "...",
  "malay_summary": "..."
}}

English title:
{title}

English description:
{description}
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    text = response.text.strip()

    # Remove possible markdown code fences
    if text.startswith("```"):
        text = text.replace(
            "```json",
            ""
        ).replace(
            "```",
            ""
        ).strip()

    data = json.loads(text)

    return data


# ==========================================
# TELEGRAM
# ==========================================

def send_photo(photo_url, caption):

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing"
        )

    telegram_url = (
        "https://api.telegram.org/"
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


# ==========================================
# CATEGORY
# ==========================================

def get_category(title, description):

    text = (
        f"{title} {description}"
    ).lower()

    if any(x in text for x in [
        "food",
        "restaurant",
        "cafe",
        "chef",
        "dining",
        "recipe",
        "donut",
        "dessert"
    ]):
        return "🍩"

    if any(x in text for x in [
        "celebrity",
        "actor",
        "actress",
        "singer",
        "concert",
        "movie",
        "film",
        "music",
        "entertainment"
    ]):
        return "🎬"

    if any(x in text for x in [
        "technology",
        "iphone",
        "android",
        "apple",
        "samsung",
        "artificial intelligence",
        "ai",
        "gadget",
        "software"
    ]):
        return "💻"

    if any(x in text for x in [
        "viral",
        "trending",
        "tiktok",
        "instagram",
        "social media",
        "shocking"
    ]):
        return "🔥"

    return "🇲🇾"


# ==========================================
# CREATE TELEGRAM CAPTION
# ==========================================

def create_caption(
    article,
    translation
):

    title = clean_text(
        article.get("title", "")
    )

    description = clean_text(
        article.get("description", "")
    )

    url = article.get("url", "")

    emoji = get_category(
        title,
        description
    )

    chinese_title = clean_text(
        translation.get(
            "chinese_title",
            title
        )
    )

    chinese_summary = clean_text(
        translation.get(
            "chinese_summary",
            description
        )
    )

    malay_title = clean_text(
        translation.get(
            "malay_title",
            title
        )
    )

    malay_summary = clean_text(
        translation.get(
            "malay_summary",
            description
        )
    )

    caption = (
        f"{emoji} "
        f"<b>{html.escape(chinese_title)}</b>"
        f"\n\n"

        f"🇨🇳 "
        f"{html.escape(chinese_summary)}"
        f"\n\n"

        f"🇲🇾 "
        f"<b>{html.escape(malay_title)}</b>"
        f"\n\n"

        f"{html.escape(malay_summary)}"
        f"\n\n"

        f'👉 <a href="{html.escape(url)}">'
        f"点击阅读完整新闻"
        f"</a>"
        f"\n"

        f'👉 <a href="{html.escape(url)}">'
        f"Klik untuk baca berita penuh"
        f"</a>"
    )

    return caption


# ==========================================
# MAIN
# ==========================================

def main():

    print("================================")
    print("MYBUZZ NEWS BOT V4")
    print("================================")

    init_db()

    if not GNEWS_API_KEY:
        print("ERROR: GNEWS_API_KEY missing")
        return

    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN missing")
        return

    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY missing")
        return

    print("GNews API: OK")
    print("Gemini API: OK")
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

        description = clean_text(
            article.get("description", "")
        )

        url = clean_text(
            article.get("url", "")
        )

        image_url = clean_text(
            article.get("image", "")
        )

        if not title or not url:
            continue

        if not image_url:

            print(
                f"No image, skipping: {title}"
            )

            continue

        article_hash = hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()

        if already_posted(article_hash):

            print(
                f"Already posted: {title}"
            )

            continue

        print(
            f"Translating: {title}"
        )

        try:

            translation = translate_news(
                title,
                description
            )

        except Exception as e:

            print(
                f"Gemini error: {e}"
            )

            continue

        caption = create_caption(
            article,
            translation
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
