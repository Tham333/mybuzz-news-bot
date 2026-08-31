import os
import re
import json
import time
import hashlib
import logging
import html
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import feedparser
import requests
from groq import Groq


# ============================================================
# MYBUZZ V6
# Malaysia News Telegram Bot
# ============================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

# Groq model
GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "llama-3.1-8b-instant"
).strip()

# Maximum news per run
MAX_NEWS = int(os.getenv("MAX_NEWS", "5"))

# How old a news item can be
MAX_AGE_HOURS = int(os.getenv("MAX_AGE_HOURS", "24"))

# Request timeout
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

# State file
STATE_FILE = "posted.json"

# Malaysia timezone
MY_TZ = timezone(timedelta(hours=8))


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("MYBUZZ-V6")


# ============================================================
# RSS SOURCES
# ============================================================

RSS_FEEDS = [
    {
        "name": "Malay Mail",
        "url": "https://www.malaymail.com/feed/rss/malaysia",
    },
    {
        "name": "The Star",
        "url": "https://www.thestar.com.my/rss/News",
    },
    {
        "name": "New Straits Times",
        "url": "https://www.nst.com.my/feed",
    },
    {
        "name": "The Edge Malaysia",
        "url": "https://theedgemalaysia.com/rss.xml",
    },
    {
        "name": "Bernama",
        "url": "https://bernama.com/en/rss/news.php",
    },
]


# ============================================================
# BASIC VALIDATION
# ============================================================

def validate_config():
    missing = []

    if not BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")

    if not CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY")

    if missing:
        logger.error(
            "Missing GitHub Secrets: %s",
            ", ".join(missing)
        )
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
        )


# ============================================================
# STATE
# ============================================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "posted_urls": [],
            "posted_hashes": []
        }

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {
                "posted_urls": [],
                "posted_hashes": []
            }

        data.setdefault("posted_urls", [])
        data.setdefault("posted_hashes", [])

        return data

    except Exception as e:
        logger.warning(
            "Could not read state file: %s",
            e
        )

        return {
            "posted_urls": [],
            "posted_hashes": []
        }


def save_state(state):
    # Keep state small
    state["posted_urls"] = state["posted_urls"][-500:]
    state["posted_hashes"] = state["posted_hashes"][-500:]

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_text(text):
    if not text:
        return ""

    text = html.unescape(text)

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def normalize_url(url):
    if not url:
        return ""

    url = url.strip()

    # Remove common tracking parameters
    url = re.sub(
        r"[?&](utm_[^&]+|fbclid|gclid)=[^&]+",
        "",
        url,
        flags=re.IGNORECASE
    )

    return url.rstrip("?")


def article_hash(title):
    normalized = re.sub(
        r"\s+",
        " ",
        title.lower().strip()
    )

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()


# ============================================================
# DATE
# ============================================================

def parse_entry_date(entry):
    candidates = [
        entry.get("published"),
        entry.get("updated"),
        entry.get("created"),
    ]

    for value in candidates:
        if not value:
            continue

        try:
            dt = parsedate_to_datetime(value)

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            return dt.astimezone(MY_TZ)

        except Exception:
            pass

    return datetime.now(MY_TZ)


def is_recent(dt):
    now = datetime.now(MY_TZ)

    age = now - dt

    return age.total_seconds() <= MAX_AGE_HOURS * 3600


# ============================================================
# RSS
# ============================================================

def fetch_feed(source):
    logger.info(
        "Fetching RSS: %s",
        source["name"]
    )

    try:
        response = requests.get(
            source["url"],
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent":
                    "MYBUZZ-NewsBot/6.0"
            }
        )

        response.raise_for_status()

        feed = feedparser.parse(
            response.content
        )

        results = []

        for entry in feed.entries:

            title = clean_text(
                entry.get("title", "")
            )

            summary = clean_text(
                entry.get(
                    "summary",
                    entry.get(
                        "description",
                        ""
                    )
                )
            )

            link = normalize_url(
                entry.get("link", "")
            )

            if not title or not link:
                continue

            published_at = parse_entry_date(
                entry
            )

            if not is_recent(
                published_at
            ):
                continue

            results.append({
                "source": source["name"],
                "title": title,
                "summary": summary,
                "url": link,
                "published_at": published_at.isoformat(),
            })

        logger.info(
            "%s: %d recent articles",
            source["name"],
            len(results)
        )

        return results

    except Exception as e:
        logger.warning(
            "RSS failed [%s]: %s",
            source["name"],
            e
        )

        return []


def collect_news():
    all_news = []

    for source in RSS_FEEDS:
        articles = fetch_feed(source)
        all_news.extend(articles)

    return all_news


# ============================================================
# DUPLICATE FILTER
# ============================================================

def filter_duplicates(news, state):
    seen_urls = set(
        state.get("posted_urls", [])
    )

    seen_hashes = set(
        state.get("posted_hashes", [])
    )

    unique = []

    local_urls = set()
    local_hashes = set()

    for article in news:

        url = article["url"]

        h = article_hash(
            article["title"]
        )

        if url in seen_urls:
            continue

        if h in seen_hashes:
            continue

        if url in local_urls:
            continue

        if h in local_hashes:
            continue

        local_urls.add(url)
        local_hashes.add(h)

        article["hash"] = h

        unique.append(article)

    return unique


# ============================================================
# SORT NEWS
# ============================================================

def sort_news(news):
    return sorted(
        news,
        key=lambda x: x.get(
            "published_at",
            ""
        ),
        reverse=True
    )


# ============================================================
# GROQ
# ============================================================

def get_groq_client():
    return Groq(
        api_key=GROQ_API_KEY
    )


def groq_generate(prompt):
    client = get_groq_client()

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are MYBUZZ Malaysia news editor. "
                        "Be accurate, concise and neutral. "
                        "Never invent facts."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.2,
            max_tokens=1200,
        )

        if not response.choices:
            return ""

        content = (
            response.choices[0]
            .message
            .content
        )

        if not content:
            return ""

        return content.strip()

    except Exception as e:
        logger.error(
            "Groq API failed: %s",
            e
        )

        # V6 intentionally does NOT keep retrying.
        return ""


# ============================================================
# AI NEWS PROCESSING
# ============================================================

def process_article(article):

    title = article["title"]
    summary = article["summary"]
    source = article["source"]

    prompt = f"""
Create MYBUZZ content from the following Malaysian news article.

SOURCE:
{source}

TITLE:
{title}

SUMMARY:
{summary}

Return EXACTLY this JSON structure:

{{
  "title_en": "...",
  "title_ms": "...",
  "title_zh": "...",
  "summary_en": "...",
  "summary_ms": "...",
  "summary_zh": "..."
}}

Rules:

1. Do not invent facts.
2. Keep the headline short.
3. English must sound natural.
4. Bahasa Melayu must sound natural for Malaysia.
5. Chinese must be simplified Chinese.
6. Summary should be 1-2 short sentences.
7. Do not add emojis.
8. Do not include URLs.
9. Do not use markdown.
"""

    result = groq_generate(
        prompt
    )

    if not result:
        return None

    # Remove markdown fences if model adds them
    result = re.sub(
        r"^```json\s*",
        "",
        result,
        flags=re.IGNORECASE
    )

    result = re.sub(
        r"\s*```$",
        "",
        result
    )

    try:
        data = json.loads(result)

    except Exception:
        logger.warning(
            "Invalid Groq JSON for: %s",
            title
        )
        return None

    required = [
        "title_en",
        "title_ms",
        "title_zh",
        "summary_en",
        "summary_ms",
        "summary_zh",
    ]

    for key in required:
        if not data.get(key):
            logger.warning(
                "Missing AI field: %s",
                key
            )
            return None

    return data


# ============================================================
# TELEGRAM
# ============================================================

def telegram_url():
    return (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}"
        f"/sendMessage"
    )


def send_telegram(message):
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    try:
        response = requests.post(
            telegram_url(),
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            logger.error(
                "Telegram failed: %s %s",
                response.status_code,
                response.text[:500]
            )

            return False

        data = response.json()

        if not data.get("ok"):
            logger.error(
                "Telegram API error: %s",
                data
            )
            return False

        return True

    except Exception as e:
        logger.error(
            "Telegram request failed: %s",
            e
        )

        return False


# ============================================================
# MESSAGE FORMAT
# ============================================================

def safe_html(text):
    return html.escape(
        str(text),
        quote=False
    )


def build_message(article, ai):
    source = safe_html(
        article["source"]
    )

    title_en = safe_html(
        ai["title_en"]
    )

    title_ms = safe_html(
        ai["title_ms"]
    )

    title_zh = safe_html(
        ai["title_zh"]
    )

    summary_en = safe_html(
        ai["summary_en"]
    )

    summary_ms = safe_html(
        ai["summary_ms"]
    )

    summary_zh = safe_html(
        ai["summary_zh"]
    )

    original_url = html.escape(
        article["url"],
        quote=True
    )

    message = f"""
🇲🇾 <b>MYBUZZ</b>

<b>🇬🇧 {title_en}</b>
{summary_en}

<b>🇲🇾 {title_ms}</b>
{summary_ms}

<b>🇨🇳 {title_zh}</b>
{summary_zh}

━━━━━━━━━━━━━━

🔗 👇 <b>Read the full story / Baca berita penuh / 阅读完整新闻</b>

👉 <a href="{original_url}">{source}｜Full Report / Laporan Penuh / 完整报道</a>
"""

    return message.strip()


# ============================================================
# TELEGRAM MESSAGE LIMIT
# ============================================================

def telegram_safe_length(text):
    # Telegram message max is around 4096 chars.
    # Keep a safe margin.
    return len(text) <= 3900


# ============================================================
# MAIN
# ============================================================

def main():

    logger.info(
        "======================================"
    )

    logger.info(
        "MYBUZZ V6 START"
    )

    logger.info(
        "======================================"
    )

    validate_config()

    state = load_state()

    news = collect_news()

    logger.info(
        "Total RSS articles: %d",
        len(news)
    )

    if not news:
        logger.info(
            "No recent news found."
        )
        return

    news = filter_duplicates(
        news,
        state
    )

    news = sort_news(
        news
    )

    logger.info(
        "New articles after duplicate filter: %d",
        len(news)
    )

    if not news:
        logger.info(
            "No new articles."
        )
        return

    selected = news[:MAX_NEWS]

    logger.info(
        "Selected %d articles.",
        len(selected)
    )

    sent_count = 0

    for index, article in enumerate(
        selected,
        start=1
    ):

        logger.info(
            "[%d/%d] Processing: %s",
            index,
            len(selected),
            article["title"]
        )

        ai = process_article(
            article
        )

        if not ai:
            logger.warning(
                "Skipping article because AI processing failed."
            )
            continue

        message = build_message(
            article,
            ai
        )

        if not telegram_safe_length(
            message
        ):
            logger.warning(
                "Message too long. Skipping."
            )
            continue

        success = send_telegram(
            message
        )

        if success:

            state["posted_urls"].append(
                article["url"]
            )

            state["posted_hashes"].append(
                article["hash"]
            )

            save_state(
                state
            )

            sent_count += 1

            logger.info(
                "Telegram sent successfully."
            )

            # Avoid sending too fast
            time.sleep(2)

        else:
            logger.error(
                "Telegram send failed."
            )

    save_state(
        state
    )

    logger.info(
        "======================================"
    )

    logger.info(
        "MYBUZZ V6 FINISHED | Sent: %d",
        sent_count
    )

    logger.info(
        "======================================"
    )


if __name__ == "__main__":
    main()
