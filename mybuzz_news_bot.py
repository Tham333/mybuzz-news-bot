````python
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
# Cloudflare Worker
#       ↓
# GitHub Actions
#       ↓
# mybuzz_news_bot.py
#       ↓
#
# GNews
# Wikivoyage
# Wikimedia
#       ↓
# Duplicate Check
#       ↓
# Groq AI
#       ↓
# Telegram
#
# 每次运行只发送 1 条
#
# ============================================================


BOT_NAME = "MYBUZZ NEWS BOT"

REQUEST_TIMEOUT = 20

MAX_HISTORY = 1000

POSTED_FILE = "posted.json"


# ============================================================
# ENV
# ============================================================

GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# ============================================================
# CHECK ENV
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
# GROQ
# ============================================================

GROQ_BASE_URL = (
    "https://api.groq.com/openai/v1"
)

GROQ_MODEL = "openai/gpt-oss-20b"


client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url=GROQ_BASE_URL,
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(BOT_NAME)


# ============================================================
# POSTED STORAGE
# ============================================================

def load_posted():

    if not os.path.exists(POSTED_FILE):
        return []

    try:

        with open(
            POSTED_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
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


def save_posted(posted):

    try:

        unique = []

        seen = set()

        for item in posted:

            if item in seen:
                continue

            seen.add(item)

            unique.append(item)

        unique = unique[-MAX_HISTORY:]

        with open(
            POSTED_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                unique,
                f,
                ensure_ascii=False,
                indent=2
            )

        logger.info(
            "Saved duplicate history: %s",
            len(unique)
        )

    except Exception as e:

        logger.error(
            "Could not save posted.json: %s",
            e
        )


# ============================================================
# NORMALIZE TEXT
# ============================================================

def normalize_text(text):

    text = str(text or "")

    text = html.unescape(text)

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = text.lower()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# ARTICLE ID
# ============================================================

def article_id(article):

    url = normalize_text(
        article.get("url", "")
    )

    title = normalize_text(
        article.get("title", "")
    )

    source = normalize_text(
        article.get("source", "")
    )

    raw = (
        url
        + "|"
        + title
        + "|"
        + source
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


# ============================================================
# TITLE ID
# ============================================================

def title_id(title):

    normalized = normalize_text(
        title
    )

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()


# ============================================================
# GNEWS
# ============================================================

def fetch_gnews():

    logger.info(
        "======================================"
    )

    logger.info(
        "Fetching GNews Malaysia..."
    )

    logger.info(
        "======================================"
    )

    url = (
        "https://gnews.io/api/v4/search"
    )

    params = {

        "q":
            "Malaysia",

        "lang":
            "en",

        "country":
            "my",

        "max":
            10,

        "apikey":
            GNEWS_API_KEY
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent":
                    "MYBUZZ-News-Bot/1.0"
            }
        )

        response.raise_for_status()

        data = response.json()

        articles = data.get(
            "articles",
            []
        )

        result = []

        for article in articles:

            title = (
                article.get("title")
                or ""
            ).strip()

            description = (
                article.get("description")
                or ""
            ).strip()

            url_value = (
                article.get("url")
                or ""
            ).strip()

            source_data = (
                article.get("source")
                or {}
            )

            source_name = (
                source_data.get("name")
                or "GNews"
            )

            image = (
                article.get("image")
                or ""
            ).strip()

            published = (
                article.get("publishedAt")
                or ""
            )

            if not title:
                continue

            if not url_value:
                continue

            result.append({

                "type":
                    "news",

                "source":
                    source_name,

                "title":
                    title,

                "description":
                    description,

                "url":
                    url_value,

                "image":
                    image,

                "publishedAt":
                    published
            })

        logger.info(
            "GNews returned %s articles.",
            len(result)
        )

        return result

    except Exception as e:

        logger.error(
            "GNews failed: %s",
            e
        )

        return []


# ============================================================
# WIKIVOYAGE
# ============================================================

def fetch_wikivoyage():

    logger.info(
        "Fetching Wikivoyage Malaysia..."
    )

    url = (
        "https://en.wikivoyage.org/w/api.php"
    )

    params = {

        "action":
            "query",

        "generator":
            "search",

        "gsrsearch":
            "Malaysia travel Kuala Lumpur Penang Langkawi",

        "gsrnamespace":
            0,

        "gsrlimit":
            10,

        "prop":
            "extracts|info",

        "exintro":
            1,

        "explaintext":
            1,

        "inprop":
            "url",

        "format":
            "json"
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent":
                    "MYBUZZ-News-Bot/1.0"
            }
        )

        response.raise_for_status()

        data = response.json()

        pages = (
            data
            .get("query", {})
            .get("pages", {})
        )

        result = []

        for page in pages.values():

            title = (
                page.get("title")
                or ""
            ).strip()

            extract = (
                page.get("extract")
                or ""
            ).strip()

            page_url = (
                page.get("fullurl")
                or ""
            ).strip()

            if not title:
                continue

            if not page_url:
                continue

            result.append({

                "type":
                    "travel",

                "source":
                    "Wikivoyage",

                "title":
                    title,

                "description":
                    extract,

                "url":
                    page_url,

                "image":
                    "",

                "publishedAt":
                    ""
            })

        logger.info(
            "Wikivoyage returned %s articles.",
            len(result)
        )

        return result

    except Exception as e:

        logger.error(
            "Wikivoyage failed: %s",
            e
        )

        return []


# ============================================================
# WIKIMEDIA / MALAYSIA FOOD
# ============================================================

def fetch_wikimedia_food():

    logger.info(
        "Fetching Wikimedia Malaysia food..."
    )

    url = (
        "https://commons.wikimedia.org/w/api.php"
    )

    params = {

        "action":
            "query",

        "generator":
            "search",

        "gsrsearch":
            "Malaysian food nasi lemak char kway teow laksa",

        "gsrnamespace":
            6,

        "gsrlimit":
            10,

        "prop":
            "imageinfo",

        "iiprop":
            "url",

        "format":
            "json"
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent":
                    "MYBUZZ-News-Bot/1.0"
            }
        )

        response.raise_for_status()

        data = response.json()

        pages = (
            data
            .get("query", {})
            .get("pages", {})
        )

        result = []

        for page in pages.values():

            title = (
                page.get("title")
                or ""
            ).strip()

            image_url = ""

            image_info = (
                page.get("imageinfo")
                or []
            )

            if image_info:

                image_url = (
                    image_info[0]
                    .get("url")
                    or ""
                )

            if not title:
                continue

            if not image_url:
                continue

            page_id = page.get(
                "pageid",
                ""
            )

            page_url = (
                "https://commons.wikimedia.org/"
                "wiki/"
                + title.replace(
                    " ",
                    "_"
                )
            )

            result.append({

                "type":
                    "food",

                "source":
                    "Wikimedia Commons",

                "title":
                    title.replace(
                        "File:",
                        ""
                    ),

                "description":
                    "Malaysian food and culinary content.",

                "url":
                    page_url,

                "image":
                    image_url,

                "publishedAt":
                    "",

                "pageid":
                    page_id
            })

        logger.info(
            "Wikimedia returned %s food items.",
            len(result)
        )

        return result

    except Exception as e:

        logger.error(
            "Wikimedia failed: %s",
            e
        )

        return []


# ============================================================
# REMOVE DUPLICATES
# ============================================================

def remove_duplicates(
    articles,
    posted
):

    posted_set = set(posted)

    result = []

    seen_ids = set()

    seen_titles = set()

    for article in articles:

        aid = article_id(
            article
        )

        tid = title_id(
            article.get(
                "title",
                ""
            )
        )

        if aid in posted_set:
            continue

        if tid in posted_set:
            continue

        if aid in seen_ids:
            continue

        if tid in seen_titles:
            continue

        seen_ids.add(aid)

        seen_titles.add(tid)

        result.append(
            article
        )

    return result


# ============================================================
# AI GENERATION
# ============================================================

def generate_content(article):

    article_type = article.get(
        "type",
        "news"
    )

    source = article.get(
        "source",
        ""
    )

    title = article.get(
        "title",
        ""
    )

    description = article.get(
        "description",
        ""
    )

    if article_type == "news":

        instruction = """
This is Malaysian current news.

Write a concise MYBUZZ news post.

Do not invent facts.
Do not add information that is not in the source.
Keep names, locations and numbers accurate.
"""

    elif article_type == "travel":

        instruction = """
This is Malaysian travel content.

Turn it into a useful short travel post
for Malaysian readers.

Do not invent facts.
Focus on the destination, attraction,
travel value and useful information.
"""

    else:

        instruction = """
This is Malaysian food content.

Turn it into an interesting short food post
for Malaysian readers.

Do not invent facts.
Focus on the food, origin or cultural value
when supported by the source.
"""

    prompt = f"""
You are the MYBUZZ Malaysia editor.

{instruction}

Create TWO languages:

1. Simplified Chinese
2. Malaysian Malay

Return ONLY valid JSON.

Required format:

{{
  "zh_title": "...",
  "zh_body": "...",
  "ms_title": "...",
  "ms_body": "..."
}}

Rules:

- Chinese must be natural Simplified Chinese.
- Malay must be natural Malaysian Malay.
- Keep both versions concise.
- No Markdown.
- No emojis.
- Do not include URLs.
- Do not say "Chinese version".
- Do not say "Malay version".
- Do not create fake quotes.
- Do not exaggerate.
- Do not mention information that is not supported.

SOURCE:
{source}

TITLE:
{title}

CONTENT:
{description}
"""

    try:

        response = client.responses.create(
            model=GROQ_MODEL,
            input=prompt
        )

        output = (
            response.output_text
            .strip()
        )

        if output.startswith("```"):

            output = re.sub(
                r"^```(?:json)?",
                "",
                output,
                flags=re.IGNORECASE
            )

            output = re.sub(
                r"```$",
                "",
                output
            ).strip()

        data = json.loads(
            output
        )

        required = [

            "zh_title",
            "zh_body",
            "ms_title",
            "ms_body"
        ]

        for key in required:

            if not data.get(key):

                raise ValueError(
                    f"Missing AI field: {key}"
                )

        return data

    except Exception as e:

        logger.error(
            "AI generation failed: %s",
            e
        )

        return None


# ============================================================
# TELEGRAM HTML ESCAPE
# ============================================================

def escape_html(text):

    return html.escape(
        str(text or ""),
        quote=True
    )


# ============================================================
# BUILD TELEGRAM MESSAGE
# ============================================================

def build_message(
    article,
    ai
):

    article_type = article.get(
        "type",
        "news"
    )

    if article_type == "news":

        prefix = "MYBUZZ NEWS"

    elif article_type == "travel":

        prefix = "MYBUZZ TRAVEL"

    else:

        prefix = "MYBUZZ FOOD"

    source = escape_html(
        article.get(
            "source",
            ""
        )
    )

    url = escape_html(
        article.get(
            "url",
            ""
        )
    )

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

    message = (

        f"<b>{prefix}</b>\n\n"

        f"<b>🇨🇳 {zh_title}</b>\n"
        f"{zh_body}\n\n"

        f"<b>🇲🇾 {ms_title}</b>\n"
        f"{ms_body}\n\n"

        f"📰 Source / Sumber: "
        f"{source}\n\n"

        f'👉 <a href="{url}">'
        f"查看完整内容 / Baca selanjutnya"
        f"</a>"
    )

    return message


# ============================================================
# TELEGRAM SEND MESSAGE
# ============================================================

def send_message(
    message
):

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    payload = {

        "chat_id":
            TELEGRAM_CHAT_ID,

        "text":
            message,

        "parse_mode":
            "HTML",

        "disable_web_page_preview":
            False
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        logger.info(
            "Telegram HTTP status: %s",
            response.status_code
        )

        if response.ok:

            logger.info(
                "Telegram message sent."
            )

            return True

        logger.error(
            "Telegram failed: %s",
            response.text
        )

        return False

    except Exception as e:

        logger.error(
            "Telegram exception: %s",
            e
        )

        return False


# ============================================================
# TELEGRAM SEND PHOTO
# ============================================================

def send_photo(
    image_url,
    caption
):

    if not image_url:

        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendPhoto"
    )

    payload = {

        "chat_id":
            TELEGRAM_CHAT_ID,

        "photo":
            image_url,

        "caption":
            caption,

        "parse_mode":
            "HTML"
    }

    try:

        response = requests.post(
            url,
            data=payload,
            timeout=REQUEST_TIMEOUT
        )

        logger.info(
            "Telegram photo HTTP status: %s",
            response.status_code
        )

        if response.ok:

            logger.info(
                "Telegram photo sent."
            )

            return True

        logger.warning(
            "Telegram photo failed: %s",
            response.text
        )

        return False

    except Exception as e:

        logger.warning(
            "Telegram photo exception: %s",
            e
        )

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    logger.info(
        "======================================"
    )

    logger.info(
        "MYBUZZ NEWS BOT START"
    )

    logger.info(
        "======================================"
    )

    posted = load_posted()

    logger.info(
        "Existing duplicate records: %s",
        len(posted)
    )


    # ========================================================
    # 1. NEWS FIRST
    # ========================================================

    news = fetch_gnews()

    news = remove_duplicates(
        news,
        posted
    )

    logger.info(
        "New news after duplicate check: %s",
        len(news)
    )


    # ========================================================
    # 2. IF NEWS AVAILABLE
    # ========================================================

    if news:

        selected = news[0]

        logger.info(
            "Selected NEWS: %s",
            selected["title"]
        )

    else:

        logger.info(
            "No new news."
        )

        # ====================================================
        # 3. TRAVEL
        # ====================================================

        travel = fetch_wikivoyage()

        travel = remove_duplicates(
            travel,
            posted
        )

        logger.info(
            "New travel content: %s",
            len(travel)
        )

        if travel:

            selected = travel[0]

            logger.info(
                "Selected TRAVEL: %s",
                selected["title"]
            )

        else:

            # ================================================
            # 4. FOOD
            # ================================================

            food = fetch_wikimedia_food()

            food = remove_duplicates(
                food,
                posted
            )

            logger.info(
                "New food content: %s",
                len(food)
            )

            if food:

                selected = food[0]

                logger.info(
                    "Selected FOOD: %s",
                    selected["title"]
                )

            else:

                logger.info(
                    "No new content available."
                )

                logger.info(
                    "MYBUZZ FINISHED | Sent: 0"
                )

                return


    # ========================================================
    # AI
    # ========================================================

    ai = generate_content(
        selected
    )

    if not ai:

        logger.error(
            "AI failed. Nothing will be sent."
        )

        return


    # ========================================================
    # TELEGRAM MESSAGE
    # ========================================================

    message = build_message(
        selected,
        ai
    )


    # ========================================================
    # SEND
    # ========================================================

    success = False

    image_url = selected.get(
        "image",
        ""
    )


    if image_url:

        success = send_photo(
            image_url,
            message
        )

        if not success:

            logger.warning(
                "Photo failed."
            )

            logger.info(
                "Trying normal message..."
            )

            success = send_message(
                message
            )

    else:

        success = send_message(
            message
        )


    # ========================================================
    # SAVE DUPLICATE ONLY AFTER SUCCESS
    # ========================================================

    if success:

        aid = article_id(
            selected
        )

        tid = title_id(
            selected.get(
                "title",
                ""
            )
        )

        posted.append(
            aid
        )

        posted.append(
            tid
        )

        save_posted(
            posted
        )

        logger.info(
            "Article marked as posted."
        )

        logger.info(
            "TYPE: %s",
            selected.get(
                "type"
            )
        )

        logger.info(
            "TITLE: %s",
            selected.get(
                "title"
            )
        )

        logger.info(
            "MYBUZZ FINISHED | Sent: 1"
        )

    else:

        logger.error(
            "Telegram failed."
        )

        logger.error(
            "Article NOT marked as posted."
        )

        logger.info(
            "MYBUZZ FINISHED | Sent: 0"
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
````
