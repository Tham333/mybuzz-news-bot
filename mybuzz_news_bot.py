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

# Current Groq production model
GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-20b"
).strip()

MAX_NEWS = int(os.getenv("MAX_NEWS", "5"))
MAX_AGE_HOURS = int(os.getenv("MAX_AGE_HOURS", "24"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

STATE_FILE = "posted.json"

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
# CONFIG VALIDATION
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
            "Missing secrets: %s",
            ", ".join(missing)
        )

        raise RuntimeError(
            "Missing required secrets: "
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

        data.setdefault(
            "posted_urls",
            []
        )

        data.setdefault(
            "posted_hashes",
            []
        )

        return data

    except Exception as e:

        logger.warning(
            "Could not read posted.json: %s",
            e
        )

        return {
            "posted_urls": [],
            "posted_hashes": []
        }


def save_state(state):

    state["posted_urls"] = (
        state.get("posted_urls", [])
        [-500:]
    )

    state["posted_hashes"] = (
        state.get("posted_hashes", [])
        [-500:]
    )

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
# DATE HELPERS
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

            dt = parsedate_to_datetime(
                value
            )

            if dt.tzinfo is None:

                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            return dt.astimezone(
                MY_TZ
            )

        except Exception:
            continue

    return datetime.now(MY_TZ)


def is_recent(dt):

    now = datetime.now(MY_TZ)

    age = now - dt

    return (
        age.total_seconds()
        <= MAX_AGE_HOURS * 3600
    )


# ============================================================
# RSS FETCH
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
                entry.get(
                    "title",
                    ""
                )
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
                entry.get(
                    "link",
                    ""
                )
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
                "published_at":
                    published_at.isoformat()
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

        articles = fetch_feed(
            source
        )

        all_news.extend(
            articles
        )

    return all_news


# ============================================================
# DUPLICATE FILTER
# ============================================================

def filter_duplicates(
    news,
    state
):

    posted_urls = set(
        state.get(
            "posted_urls",
            []
        )
    )

    posted_hashes = set(
        state.get(
            "posted_hashes",
            []
        )
    )

    unique = []

    local_urls = set()
    local_hashes = set()

    for article in news:

        url = article["url"]

        h = article_hash(
            article["title"]
        )

        if url in posted_urls:
            continue

        if h in posted_hashes:
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
# SORT
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
# GROQ CLIENT
# ============================================================

def get_groq_client():

    return Groq(
        api_key=GROQ_API_KEY
    )


# ============================================================
# GROQ MODEL CHECK
# ============================================================

def check_groq_model():

    logger.info(
        "Checking Groq model: %s",
        GROQ_MODEL
    )

    try:

        client = get_groq_client()

        response = client.chat.completions.create(

            model=GROQ_MODEL,

            messages=[
                {
                    "role": "user",
                    "content":
                        "Reply with exactly: OK"
                }
            ],

            temperature=0,

            max_tokens=5
        )

        if not response.choices:

            logger.error(
                "Groq model returned no choices."
            )

            return False

        logger.info(
            "Groq model check: OK"
        )

        return True

    except Exception as e:

        logger.error(
            "Groq model check FAILED: %s",
            e
        )

        return False


# ============================================================
# GROQ GENERATE
# ============================================================

def groq_generate(prompt):

    try:

        client = get_groq_client()

        response = client.chat.completions.create(

            model=GROQ_MODEL,

            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are MYBUZZ Malaysia "
                        "news editor. "
                        "Be accurate, concise "
                        "and neutral. "
                        "Never invent facts."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],

            temperature=0.2,

            max_tokens=1200
        )

        if not response.choices:

            return ""

        content = (
            response
            .choices[0]
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

        # V6 does not repeatedly retry.
        return ""


# ============================================================
# AI ARTICLE PROCESSING
# ============================================================

def process_article(article):

    title = article["title"]
    summary = article["summary"]
    source = article["source"]

    prompt = f"""
Create MYBUZZ content from the following
Malaysian news article.

SOURCE:
{source}

TITLE:
{title}

SUMMARY:
{summary}

Return ONLY valid JSON.

Required structure:

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
2. Keep headlines short.
3. English must sound natural.
4. Bahasa Melayu must sound natural for Malaysia.
5. Chinese must be Simplified Chinese.
6. Summary must be 1-2 short sentences.
7. Do not add emojis.
8. Do not use markdown.
9. Do not include URLs.
10. Do not mention AI.
11. Keep the meaning faithful to the source.
12. Do not exaggerate the news.
"""

    result = groq_generate(
        prompt
    )

    if not result:

        return None

    result = result.strip()

    # Remove markdown code fences
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

        data = json.loads(
            result
        )

    except Exception:

        logger.warning(
            "Invalid JSON from Groq: %s",
            article["title"]
        )

        return None

    required_fields = [
        "title_en",
        "title_ms",
        "title_zh",
        "summary_en",
        "summary_ms",
        "summary_zh"
    ]

    for field in required_fields:

        if not data.get(field):

            logger.warning(
                "Missing AI field: %s",
                field
            )

            return None

    return data


# ============================================================
# TELEGRAM
# ============================================================

def telegram_api_url():

    return (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/sendMessage"
    )


def send_telegram(message):

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:

        response = requests.post(
            telegram_api_url(),
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:

            logger.error(
                "Telegram HTTP error: %s",
                response.status_code
            )

            logger.error(
                response.text[:1000]
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
# HTML
# ============================================================

def safe_html(text):

    return html.escape(
        str(text),
        quote=False
    )


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def build_message(
    article,
    ai
):

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

🇬🇧 <b>{title_en}</b>
{summary_en}

🇲🇾 <b>{title_ms}</b>
{summary_ms}

🇨🇳 <b>{title_zh}</b>
{summary_zh}

━━━━━━━━━━━━━━

🔗 👇 <b>Read the full story / Baca berita penuh / 阅读完整新闻</b>

👉 <a href="{original_url}">{source}｜Full Report / Laporan Penuh / 完整报道</a>
"""

    return message.strip()


# ============================================================
# TELEGRAM LENGTH
# ============================================================

def telegram_safe_length(message):

    return len(message) <= 3900


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
        "Groq model: %s",
        GROQ_MODEL
    )

    logger.info(
        "======================================"
    )

    # --------------------------------------------------------
    # Validate secrets
    # --------------------------------------------------------

    validate_config()

    # --------------------------------------------------------
    # Check Groq before downloading news
    # --------------------------------------------------------

    if not check_groq_model():

        logger.error(
            "Groq model is unavailable."
        )

        logger.error(
            "MYBUZZ V6 stopped before "
            "processing news."
        )

        return

    # --------------------------------------------------------
    # Load state
    # --------------------------------------------------------

    state = load_state()

    # --------------------------------------------------------
    # Fetch RSS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Remove duplicates
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Select news
    # --------------------------------------------------------

    selected = news[
        :MAX_NEWS
    ]

    logger.info(
        "Selected %d articles.",
        len(selected)
    )

    # --------------------------------------------------------
    # Process and send
    # --------------------------------------------------------

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
                "AI processing failed. "
                "Skipping article."
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
                "Telegram message too long. "
                "Skipping."
            )

            continue

        success = send_telegram(
            message
        )

        if success:

            state[
                "posted_urls"
            ].append(
                article["url"]
            )

            state[
                "posted_hashes"
            ].append(
                article["hash"]
            )

            save_state(
                state
            )

            sent_count += 1

            logger.info(
                "Telegram sent successfully."
            )

            # Small delay between messages
            time.sleep(2)

        else:

            logger.error(
                "Telegram send failed."
            )

    # --------------------------------------------------------
    # Save state
    # --------------------------------------------------------

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


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
