import os
import sqlite3
import hashlib
import requests
import html
import json

from datetime import datetime, timezone
from google import genai


# =========================================================
# MYBUZZ NEWS BOT
# =========================================================

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "@mybuzzmy")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

DB_FILE = "mybuzz.db"

# 每次运行最多发 1 条
MAX_POSTS = 1

# GNews 每次最多抓 10 条
MAX_GNEWS_ARTICLES = 10

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


def save_article(article_hash, title, url):

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
            datetime.now(timezone.utc).isoformat()
        )
    )

    conn.commit()
    conn.close()


# =========================================================
# TEXT CLEAN
# =========================================================

def clean_text(text):

    if not text:
        return ""

    text = html.unescape(str(text))

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

    return data.get("articles", [])


# =========================================================
# CATEGORY
# =========================================================

def get_category(title, description):

    text = (
        f"{title} {description}"
    ).lower()

    # Food
    if any(word in text for word in [
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
    ]):
        return "🍩"

    # Entertainment
    if any(word in text for word in [
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
    ]):
        return "🎬"

    # Tech
    if any(word in text for word in [
        "technology",
        "tech",
        "iphone",
        "android",
        "apple",
        "samsung",
        "google",
        "artificial intelligence",
        " ai ",
        "gadget",
        "software"
    ]):
        return "💻"

    # Viral
    if any(word in text for word in [
        "viral",
        "trending",
        "tiktok",
        "instagram",
        "social media",
        "shocking"
    ]):
        return "🔥"

    # General Malaysia
    return "🇲🇾"


# =========================================================
# GEMINI
# =========================================================

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

Rewrite the following English news into TWO languages:

1. Malaysian Chinese
2. Bahasa Melayu Malaysia

IMPORTANT RULES:

- Do not invent facts.
- Do not add information that is not in the original.
- Keep names accurate.
- Keep locations accurate.
- Keep dates accurate.
- Keep numbers accurate.
- Make the Chinese title short and attractive.
- Make the Malay title natural.
- Make both summaries short.
- Use natural Malaysian Chinese.
- Use natural Malaysian Bahasa Melayu.
- Do not mention AI.
- Do not mention translation.
- Do not use Markdown.
- Return ONLY valid JSON.

Required format:

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
        model="gemini-3.6-flash",
        contents=prompt
    )

    if not response:

        raise RuntimeError(
            "Gemini returned no response"
        )

    text = response.text

    if not text:

        raise RuntimeError(
            "Gemini returned empty text"
        )

    text = text.strip()

    # Remove Markdown code block if Gemini adds it
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

    # Try JSON directly
    try:

        return json.loads(text)

    except json.JSONDecodeError:

        pass

    # Try extracting JSON
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:

        raise RuntimeError(
            "Gemini returned invalid JSON"
        )

    json_text = text[
        start:end + 1
    ]

    return json.loads(json_text)


# =========================================================
# TELEGRAM
# =========================================================

def send_photo(image_url, caption):

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
# TELEGRAM MESSAGE
# =========================================================

def create_caption(article, translation):

    title = clean_text(
        article.get("title", "")
    )

    description = clean_text(
        article.get("description", "")
    )

    url = clean_text(
        article.get("url", "")
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

    # Limit summary length
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
        f"\n\n"

        f'👉 <a href="{safe_url}">'
        f"Klik untuk baca berita penuh"
        f"</a>"
    )

    return caption


# =========================================================
# MAIN
# =========================================================

def main():

    print("================================")
    print("MYBUZZ NEWS BOT V5")
    print("================================")

    init_db()

    # -----------------------------------------
    # Check API
    # -----------------------------------------

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

    print("GNews API: OK")
    print("Gemini API: OK")
    print(
        f"Telegram: {TELEGRAM_CHAT_ID}"
    )

    print("")

    # -----------------------------------------
    # Fetch news
    # -----------------------------------------

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

    # -----------------------------------------
    # Select article
    # -----------------------------------------

    selected_article = None
    selected_hash = None

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

        if not title:

            continue

        if not url:

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

        selected_article = article
        selected_hash = article_hash

        break

    if not selected_article:

        print(
            "No suitable new article found."
        )

        return

    article = selected_article

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

    article_url = clean_text(
        article.get(
            "url",
            ""
        )
    )

    print("")
    print(
        f"Selected: {title}"
    )

    # -----------------------------------------
    # Gemini
    # -----------------------------------------

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

    # -----------------------------------------
    # Create message
    # -----------------------------------------

    caption = create_caption(
        article,
        translation
    )

    # -----------------------------------------
    # Send Telegram
    # -----------------------------------------

    print(
        "Sending Telegram message..."
    )

    try:

        send_photo(
            image_url,
            caption
        )

        save_article(
            selected_hash,
            title,
            article_url
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
    print("================================")
    print("Finished. Sent 1 article.")
    print("================================")


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    main()
