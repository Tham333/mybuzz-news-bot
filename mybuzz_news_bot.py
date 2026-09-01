import os
import json
import logging
import hashlib
import re
import html
from datetime import datetime, timezone

import requests
from openai import OpenAI


# ============================================================
# MYBUZZ NEWS BOT
# ============================================================
#
# GitHub Actions
#       ↓
# mybuzz_news_bot.py
#       ↓
# GNews
#       ↓
# Duplicate Check
#       ↓
# Groq AI
#       ↓
# Telegram
#
# ============================================================


BOT_NAME = "MYBUZZ BOT"


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID"
)


# ============================================================
# API CONFIG
# ============================================================

GNEWS_BASE_URL = (
    "https://gnews.io/api/v4"
)

GROQ_BASE_URL = (
    "https://api.groq.com/openai/v1"
)

GROQ_MODEL = "openai/gpt-oss-20b"


# ============================================================
# STORAGE
# ============================================================

POSTED_FILE = "posted.json"
STATE_FILE = "bot_state.json"


# ============================================================
# LIMITS
# ============================================================

REQUEST_TIMEOUT = 20

MAX_GNEWS_ARTICLES = 10

MAX_POSTED = 1000


# ============================================================
# HEADERS
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "MYBUZZ-News-Bot/1.0"
    )
}


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(BOT_NAME)


# ============================================================
# VALIDATION
# ============================================================

if not GNEWS_API_KEY:
    raise RuntimeError(
        "GNEWS_API_KEY is missing."
    )

if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY is missing."
    )

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is missing."
    )

if not TELEGRAM_CHAT_ID:
    raise RuntimeError(
        "TELEGRAM_CHAT_ID is missing."
    )


# ============================================================
# GROQ CLIENT
# ============================================================

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url=GROQ_BASE_URL,
)


# ============================================================
# CLEAN TEXT
# ============================================================

def clean_text(text):

    if not text:
        return ""

    text = html.unescape(
        str(text)
    )

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


# ============================================================
# NORMALIZE URL
# ============================================================

def normalize_url(url):

    if not url:
        return ""

    url = str(url).strip()

    url = url.split("#")[0]

    return url


# ============================================================
# ARTICLE ID
# ============================================================

def article_id(article):

    link = normalize_url(
        article.get("link", "")
    )

    if link:

        return hashlib.sha256(
            link.encode("utf-8")
        ).hexdigest()

    title = clean_text(
        article.get("title", "")
    ).lower()

    source = clean_text(
        article.get("source", "")
    ).lower()

    raw = (
        source
        + "|"
        + title
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


# ============================================================
# LOAD POSTED
# ============================================================

def load_posted():

    if not os.path.exists(
        POSTED_FILE
    ):
        return []

    try:

        with open(
            POSTED_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(
            data,
            list
        ):

            return data

        if isinstance(
            data,
            dict
        ):

            return data.get(
                "posted",
                []
            )

    except Exception as e:

        logger.warning(
            "Could not read posted.json: %s",
            e
        )

    return []


# ============================================================
# SAVE POSTED
# ============================================================

def save_posted(posted):

    try:

        posted = posted[
            -MAX_POSTED:
        ]

        with open(
            POSTED_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                posted,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        logger.error(
            "Could not save posted.json: %s",
            e
        )


# ============================================================
# LOAD STATE
# ============================================================

def load_state():

    default_state = {
        "counter": 0
    }

    if not os.path.exists(
        STATE_FILE
    ):
        return default_state

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(
            data,
            dict
        ):

            counter = data.get(
                "counter",
                0
            )

            try:

                counter = int(
                    counter
                )

            except Exception:

                counter = 0

            return {
                "counter": counter
            }

    except Exception as e:

        logger.warning(
            "Could not read bot_state.json: %s",
            e
        )

    return default_state


# ============================================================
# SAVE STATE
# ============================================================

def save_state(state):

    try:

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

    except Exception as e:

        logger.error(
            "Could not save bot_state.json: %s",
            e
        )


# ============================================================
# ADVANCE COUNTER
# ============================================================

def advance_counter(state):

    counter = state.get(
        "counter",
        0
    )

    state["counter"] = (
        int(counter) + 1
    )

    save_state(state)


# ============================================================
# GNEWS REQUEST
# ============================================================

def gnews_request(params):

    params = dict(params)

    params["apikey"] = (
        GNEWS_API_KEY
    )

    try:

        response = requests.get(
            GNEWS_BASE_URL + "/search",
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
        )

        logger.info(
            "GNews HTTP status: %s",
            response.status_code
        )

        if not response.ok:

            logger.error(
                "GNews error: %s",
                response.text[:1000]
            )

            return []

        data = response.json()

        return data.get(
            "articles",
            []
        )

    except Exception as e:

        logger.error(
            "GNews request failed: %s",
            e
        )

        return []


# ============================================================
# FETCH MALAYSIA NEWS
# ============================================================

def fetch_news():

    logger.info(
        "Fetching Malaysia news..."
    )

    params = {

        "q": (
            "Malaysia OR Malaysian"
        ),

        "lang": "en",

        "country": "my",

        "max": MAX_GNEWS_ARTICLES,

    }

    articles = gnews_request(
        params
    )

    results = []

    for item in articles:

        title = clean_text(
            item.get(
                "title",
                ""
            )
        )

        description = clean_text(
            item.get(
                "description",
                ""
            )
        )

        url = normalize_url(
            item.get(
                "url",
                ""
            )
        )

        image = normalize_url(
            item.get(
                "image",
                ""
            )
        )

        published_at = clean_text(
            item.get(
                "publishedAt",
                ""
            )
        )

        source_data = item.get(
            "source",
            {}
        )

        if isinstance(
            source_data,
            dict
        ):

            source = clean_text(
                source_data.get(
                    "name",
                    ""
                )
            )

        else:

            source = ""

        if not title or not url:
            continue

        results.append({

            "type": "NEWS",

            "source": (
                source
                or "GNews"
            ),

            "title": title,

            "description":
                description,

            "link": url,

            "image": image,

            "publishedAt":
                published_at,

        })

    logger.info(
        "GNews usable articles: %s",
        len(results)
    )

    return results


# ============================================================
# FIND NEWS PAGE IMAGE
# ============================================================

def find_image_from_page(url):

    if not url:
        return ""

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
        )

        if not response.ok:
            return ""

        page = response.text

        patterns = [

            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',

            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',

            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',

            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',

        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                page,
                re.IGNORECASE
            )

            if match:

                image = html.unescape(
                    match.group(1).strip()
                )

                if image.startswith(
                    "http"
                ):

                    return image

    except Exception as e:

        logger.warning(
            "News page image failed: %s",
            e
        )

    return ""


# ============================================================
# SELECT NEWS
# ============================================================

def select_news(posted_set):

    articles = fetch_news()

    for article in articles:

        aid = article_id(
            article
        )

        if aid in posted_set:

            logger.info(
                "Duplicate news skipped: %s",
                article["title"]
            )

            continue

        image = article.get(
            "image",
            ""
        )

        if not image:

            logger.info(
                "GNews has no image. Checking article page..."
            )

            image = find_image_from_page(
                article["link"]
            )

        if not image:

            logger.warning(
                "News has no image. Trying next article..."
            )

            continue

        article["image"] = image

        return article

    return None


# ============================================================
# GENERATE AI CONTENT
# ============================================================

def generate_ai_content(article):

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

    source = clean_text(
        article.get(
            "source",
            ""
        )
    )

    prompt = f"""
You are the MYBUZZ Malaysia content editor.

Create one short bilingual Malaysian Telegram post from the news below.

SOURCE:
{source}

TITLE:
{title}

CONTENT:
{description}

RULES:
1. Do NOT invent facts.
2. Keep factual information accurate.
3. Chinese must be Simplified Chinese.
4. Malay must be natural Malaysian Malay.
5. Keep both versions short (1-2 sentences).
6. Do not include URLs.
7. Do not use Markdown.
8. Do not add hashtags.
9. Do not mention AI.
10. Return ONLY valid JSON.

OUTPUT EXACTLY THIS JSON (NO OTHER TEXT):

{{"zh_title":"...","zh_body":"...","ms_title":"...","ms_body":"..."}}
"""

    try:

        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are a JSON generator. Return ONLY valid JSON. No other text."},
                {"role": "user", "content": prompt}
            ]
        )

        output = (
            response
            .choices[0]
            .message
            .content
            .strip()
        )

        # 尝试提取 JSON
        json_match = re.search(r'\{[^{}]*\}', output)
        if json_match:
            output = json_match.group()
        else:
            start = output.find('{')
            end = output.rfind('}') + 1
            if start != -1 and end > start:
                output = output[start:end]

        if not output:
            logger.error("No JSON found in AI response")
            return None

        data = json.loads(output)

        required = [
            "zh_title",
            "zh_body",
            "ms_title",
            "ms_body",
        ]

        for key in required:
            if not data.get(key):
                raise ValueError(
                    f"Missing AI field: {key}"
                )

        return data

    except json.JSONDecodeError as e:
        logger.error(
            "JSON decode error: %s",
            e
        )
        logger.info(
            "Raw output: %s",
            output[:500] if output else "(empty)"
        )
        return None

    except Exception as e:

        logger.error(
            "Groq AI failed: %s",
            e
        )

        return None


# ============================================================
# TELEGRAM CAPTION
# ============================================================

def escape_html(text):

    return html.escape(
        str(text),
        quote=False
    )


def build_caption(
    article,
    ai
):

    zh_title = escape_html(
        ai["zh_title"].strip()
    )

    zh_body = escape_html(
        ai["zh_body"].strip()
    )

    ms_title = escape_html(
        ai["ms_title"].strip()
    )

    ms_body = escape_html(
        ai["ms_body"].strip()
    )

    link = article.get(
        "link",
        ""
    )

    caption = (

        f"🇲🇾 MYBuzz NEWS\n\n"

        f"🇨🇳 {zh_title}\n"
        f"{zh_body}\n\n"

        f"🇲🇾 {ms_title}\n"
        f"{ms_body}\n\n"

        f"👉 点击阅读完整新闻\n"
        f"{link}\n\n"

        f"👉 Klik untuk baca berita penuh\n"
        f"{link}"

    )

    return caption


# ============================================================
# TELEGRAM SEND PHOTO
# ============================================================

def send_photo(
    image_url,
    caption
):

    api_url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendPhoto"
    )

    try:

        response = requests.post(

            api_url,

            data={

                "chat_id":
                    TELEGRAM_CHAT_ID,

                "photo":
                    image_url,

                "caption":
                    caption,

                "parse_mode":
                    "HTML",

            },

            timeout=REQUEST_TIMEOUT

        )

        logger.info(
            "Telegram photo HTTP status: %s",
            response.status_code
        )

        if response.ok:

            logger.info(
                "Telegram photo sent successfully."
            )

            return True

        logger.error(
            "Telegram photo failed: %s",
            response.text[:2000]
        )

        return False

    except Exception as e:

        logger.error(
            "Telegram photo exception: %s",
            e
        )

        return False


# ============================================================
# TELEGRAM SEND MESSAGE
# ============================================================

def send_message(
    caption
):

    api_url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    try:

        response = requests.post(

            api_url,

            data={

                "chat_id":
                    TELEGRAM_CHAT_ID,

                "text":
                    caption,

                "parse_mode":
                    "HTML",

                "disable_web_page_preview":
                    False,

            },

            timeout=REQUEST_TIMEOUT

        )

        logger.info(
            "Telegram message HTTP status: %s",
            response.status_code
        )

        if response.ok:

            logger.info(
                "Telegram message sent successfully."
            )

            return True

        logger.error(
            "Telegram message failed: %s",
            response.text[:2000]
        )

        return False

    except Exception as e:

        logger.error(
            "Telegram message exception: %s",
            e
        )

        return False


# ============================================================
# SEND TELEGRAM
# ============================================================

def send_to_telegram(
    article,
    ai
):

    caption = build_caption(
        article,
        ai
    )

    image_url = article.get(
        "image",
        ""
    )

    if image_url:

        success = send_photo(
            image_url,
            caption
        )

        if success:
            return True

        logger.warning(
            "Photo failed. Falling back to text."
        )

    return send_message(
        caption
    )


# ============================================================
# MAIN
# ============================================================

def main():

    logger.info(
        "======================================"
    )

    logger.info(
        "MYBUZZ BOT START"
    )

    logger.info(
        "======================================"
    )

    # --------------------------------------------------------
    # LOAD DATABASE
    # --------------------------------------------------------

    posted = load_posted()

    posted_set = set(
        posted
    )

    logger.info(
        "Posted database: %s items",
        len(posted)
    )

    # --------------------------------------------------------
    # DETERMINE MODE
    # --------------------------------------------------------

    # 直接使用 NEWS 模式
    logger.info(
        "Selected mode: NEWS"
    )

    article = select_news(
        posted_set
    )

    if not article:

        logger.warning(
            "No new Malaysia news with image available."
        )

        return

    # --------------------------------------------------------
    # LOG
    # --------------------------------------------------------

    logger.info(
        "Selected type: NEWS"
    )

    logger.info(
        "Selected title: %s",
        article.get(
            "title"
        )
    )

    logger.info(
        "Selected source: %s",
        article.get(
            "source"
        )
    )

    logger.info(
        "Selected image: %s",
        article.get(
            "image"
        )
    )

    # --------------------------------------------------------
    # AI
    # --------------------------------------------------------

    ai = generate_ai_content(
        article
    )

    if not ai:

        logger.error(
            "AI failed. Nothing sent."
        )

        return

    logger.info(
        "AI content generated."
    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    success = send_to_telegram(
        article,
        ai
    )

    if not success:

        logger.error(
            "Telegram send failed."
        )

        # Do not mark as posted.
        return

    # --------------------------------------------------------
    # MARK POSTED
    # --------------------------------------------------------

    aid = article_id(
        article
    )

    if aid not in posted_set:

        posted.append(
            aid
        )

        save_posted(
            posted
        )

    # --------------------------------------------------------
    # FINISH
    # --------------------------------------------------------

    logger.info(
        "======================================"
    )

    logger.info(
        "MYBUZZ BOT FINISHED"
    )

    logger.info(
        "Successfully sent: 1"
    )

    logger.info(
        "Type: NEWS"
    )

    logger.info(
        "======================================")


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    main()
