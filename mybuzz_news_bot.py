import os
import sqlite3
import hashlib
import requests
import html
import json
import time

from datetime import datetime, timezone
from google import genai


# =========================================================
# CONFIG
# =========================================================

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


# =========================================================
# DATABASE
# =========================================================

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

    cursor = conn.execute(
        """
        SELECT 1
        FROM articles
        WHERE article_hash = ?
        LIMIT 1
        """,
        (article_hash,)
    )

    result = cursor.fetchone()

    conn.close()

    return result is not None


def save_article(
    article_hash,
    title,
    url
):

    conn = sqlite3.connect(DB_FILE)

    conn.execute(
        """
        INSERT OR IGNORE INTO articles
        (
            article_hash,
            title,
            url,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            article_hash,
            title,
            url,
            datetime.now(
                timezone.utc
            ).isoformat()
        )
    )

    conn.commit()
    conn.close()


# =========================================================
# CLEAN TEXT
# =========================================================

def clean_text(text):

    if not text:
        return ""

    text = html.unescape(
        str(text)
    )

    text = " ".join(
        text.split()
    )

    return text.strip()


# =========================================================
# GNEWS
# =========================================================

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

    return data.get(
        "articles",
        []
    )


# =========================================================
# CATEGORY
# =========================================================

def get_category(
    title,
    description
):

    text = (
        f"{title} {description}"
    ).lower()

    food_words = [
        "food",
        "restaurant",
        "cafe",
        "chef",
        "dining",
        "recipe",
        "donut",
        "dessert",
        "bakery",
        "cooking"
    ]

    entertainment_words = [
        "celebrity",
        "actor",
        "actress",
        "singer",
        "concert",
        "movie",
        "film",
        "music",
        "entertainment",
        "k-pop"
    ]

    tech_words = [
        "technology",
        "tech",
        "iphone",
        "android",
        "apple",
        "samsung",
        "google",
        "artificial intelligence",
        "ai",
        "gadget",
        "software"
    ]

    viral_words = [
        "viral",
        "trending",
        "tiktok",
        "instagram",
        "social media",
        "shocking",
        "video"
    ]

    if any(
        word in text
        for word in food_words
    ):
        return "🍩"

    if any(
        word in text
        for word in entertainment_words
    ):
        return "🎬"

    if any(
        word in text
        for word in tech_words
    ):
        return "💻"

    if any(
        word in text
        for word in viral_words
    ):
        return "🔥"

    return "🇲🇾"


# =========================================================
# GEMINI TRANSLATION
# =========================================================

def translate_news(
    title,
    description
):

    if not GEMINI_API_KEY:

        raise RuntimeError(
            "GEMINI_API_KEY is missing"
        )

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    prompt = f"""
You are the professional editor of a Malaysian news Telegram channel called MYBUZZ.

Rewrite this English news into natural Malaysian Chinese and Bahasa Melayu.

Rules:

1. Do not invent information.
2. Keep names, locations, dates and numbers accurate.
3. Keep the meaning of the original article.
4. Make the Chinese title short, natural and attractive.
5. Make the Malay title natural for Malaysian readers.
6. Chinese should be easy-to-read Malaysian Chinese.
7. Malay should be natural Bahasa Melayu Malaysia.
8. Keep each summary short.
9. Do not mention that you are translating.
10. Do not use Markdown.
11. Return ONLY valid JSON.

JSON format:

{{
  "chinese_title": "中文标题",
  "chinese_summary": "中文摘要",
  "malay_title": "Tajuk Bahasa Melayu",
  "malay_summary": "Ringkasan Bahasa Melayu"
}}

English title:
{title}

English description:
{description}
"""

    # Try Gemini
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    if not response or not response.text:

        raise RuntimeError(
            "Gemini returned empty response"
        )

    text = response.text.strip()

    # Remove markdown code fences
    if text.startswith("```"):

        text = text.replace(
            "```json",
            ""
        )

        text = text.replace(
            "```",
            ""
        )

        text = text.strip()

    try:

        result = json.loads(text)

    except json.JSONDecodeError:

        # Try extracting JSON object
        start = text.find("{")
        end = text.rfind("}")

        if start == -1 or end == -1:

            raise RuntimeError(
                "Gemini returned invalid JSON"
            )

        json_text = text[
            start:end + 1
        ]

        result = json.loads(
            json_text
        )

    return result


# =========================================================
# TELEGRAM
# =========================================================

def send_photo(
    image_url,
    caption
):

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
        "photo": image_url,
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
            f"Telegram API error: {result}"
        )


# =========================================================
# TELEGRAM CAPTION
# =========================================================

def create_caption(
    article,
    translation
):

    title = clean_text(
        article.get(
            "title",
            ""
        )
    )

    description = clean_text(
        article.get(
            "description",
            ""
        )
    )

    url = clean_text(
        article.get(
            "url",
            ""
        )
    )

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

    # Limit text
    if len(chinese_summary) > 220:

        chinese_summary = (
            chinese_summary[:220]
            .rstrip()
            + "..."
        )

    if len(malay_summary) > 220:

        malay_summary = (
            malay_summary[:220]
            .rstrip()
            + "..."
        )

    safe_url = html.escape(
        url,
        quote=True
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

        f'👉 <a href="{safe_url}">'
        f"点击阅读完整新闻"
        f"</a>"
        f"\n"

        f'👉 <a href="{safe_url}">'
        f"Klik untuk baca berita penuh"
        f"</a>"
    )

    return caption


# =========================================================
# MAIN
# =========================================================

def main():

    print(
        "================================"
    )

    print(
        "MYBUZZ NEWS BOT V4.1"
    )

    print(
        "================================"
    )

    init_db()

    # ---------------------------------
    # Check API keys
    # ---------------------------------

    if not GNEWS_API_KEY:

        print(
            "ERROR: GNEWS_API_KEY missing"
        )

        return

    if not TELEGRAM_BOT_TOKEN:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN missing"
        )

        return

    if not GEMINI_API_KEY:

        print(
            "ERROR: GEMINI_API_KEY missing"
        )

        return

    print(
        "GNews API: OK"
    )

    print(
        "Gemini API: OK"
    )

    print(
        f"Telegram: {TELEGRAM_CHAT_ID}"
    )

    print("")

    # ---------------------------------
    # Get news
    # ---------------------------------

    print(
        "Fetching Malaysia news..."
    )

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

    if not articles:

        print(
            "No articles found."
        )

        return

    # ---------------------------------
    # Find suitable article
    # ---------------------------------

    selected = None

    for article in articles:

        title = clean_text(
            article.get(
                "title",
                ""
            )
        )

        url = clean_text(
            article.get(
                "url",
                ""
            )
        )

        image_url = clean_text(
            article.get(
                "image",
                ""
            )
        )

        if not title or not url:

            continue

        article_hash = hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()

        if already_posted(
            article_hash
        ):

            print(
                f"Already posted: {title}"
            )

            continue

        if not image_url:

            print(
                f"No image: {title}"
            )

            continue

        selected = (
            article,
            article_hash
        )

        break

    if not selected:

        print(
            "No suitable new article found."
        )

        return

    article, article_hash = selected

    title = clean_text(
        article.get(
            "title",
            ""
        )
    )

    description = clean_text(
        article.get(
            "description",
            ""
        )
    )

    image_url = clean_text(
        article.get(
            "image",
            ""
        )
    )

    print("")
    print(
        f"Selected: {title}"
    )

    # ---------------------------------
    # Gemini
    # ---------------------------------

    print(
        "Translating with Gemini..."
    )

    try:

        translation = translate_news(
            title,
            description
        )

        print(
            "Gemini translation: OK"
        )

    except Exception as e:

        print(
            f"Gemini error: {e}"
        )

        return

    # ---------------------------------
    # Create Telegram message
    # ---------------------------------

    caption = create_caption(
        article,
        translation
    )

    print(
        "Sending Telegram message..."
    )

    # ---------------------------------
    # Send
    # ---------------------------------

    try:

        send_photo(
            image_url,
            caption
        )

        save_article(
            article_hash,
            title,
            article.get(
                "url",
                ""
            )
        )

        print(
            "Telegram: SUCCESS"
        )

    except Exception as e:

        print(
            f"Telegram error: {e}"
        )

        return

    print("")
    print(
        "================================"
    )

    print(
        "Finished. Sent 1 article."
    )

    print(
        "================================"
    )


if __name__ == "__main__":

    main()
