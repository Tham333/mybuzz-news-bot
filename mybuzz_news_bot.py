import os
import json
import time
import hashlib
import logging
import html
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote

import requests
import feedparser
from openai import OpenAI


# ============================================================
# MYBUZZ NEWS BOT
# ============================================================
#
# FLOW
#
# GitHub Actions
#       ↓
# mybuzz_news_bot.py
#       ↓
# GNews
#       ↓
# Select NEW article
#       ↓
# Groq
#       ↓
# Chinese + Malay content
#       ↓
# TELEGRAM
#       ↓
# Telegram SUCCESS
#       ↓
# posted.json
#
# CYCLE
#
# 1 = NEWS
# 2 = NEWS
# 3 = WIKI
# 4 = NEWS
# 5 = NEWS
# 6 = WIKI
#
# ============================================================


# ============================================================
# CONFIG
# ============================================================

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "").strip()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

TELEGRAM_CHANNEL_ID = os.getenv(
    "TELEGRAM_CHANNEL_ID",
    "@mybuzzmy"
).strip()

TELEGRAM_WIKI_CHANNEL_ID = os.getenv(
    "TELEGRAM_WIKI_CHANNEL_ID",
    TELEGRAM_CHANNEL_ID
).strip()

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "llama-3.3-70b-versatile"
).strip()

POSTED_FILE = Path("posted.json")

GNEWS_URL = "https://gnews.io/api/v4/search"

WIKIPEDIA_API = (
    "https://en.wikipedia.org/w/api.php"
)

REQUEST_TIMEOUT = 20

MAX_POSTED_HISTORY = 500

GNEWS_MAX_RESULTS = 10

CYCLE_LENGTH = 3


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("MYBUZZ")


# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": (
        "MYBUZZ-News-Bot/2.0 "
        "(https://github.com/Tham333/mybuzz-news-bot)"
    ),
    "Accept": "*/*"
})


# ============================================================
# API CLIENT
# ============================================================

groq_client = None

if GROQ_API_KEY:
    groq_client = OpenAI(
        api_key=GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1"
    )


# ============================================================
# CONFIG CHECK
# ============================================================

def check_config():

    logger.info("Checking API configuration...")

    missing = []

    if not GNEWS_API_KEY:
        missing.append("GNEWS_API_KEY")

    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY")

    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")

    if not TELEGRAM_CHANNEL_ID:
        missing.append("TELEGRAM_CHANNEL_ID")

    if missing:

        logger.error(
            "Missing environment variables: %s",
            ", ".join(missing)
        )

        return False

    logger.info("API configuration OK.")

    return True


# ============================================================
# POSTED DATABASE
# ============================================================

def load_posted():

    if not POSTED_FILE.exists():

        logger.info(
            "posted.json not found. Creating new database."
        )

        return {
            "items": [],
            "cycle": 0
        }

    try:

        with open(
            POSTED_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, list):

            return {
                "items": data,
                "cycle": 0
            }

        if not isinstance(data, dict):

            return {
                "items": [],
                "cycle": 0
            }

        if "items" not in data:
            data["items"] = []

        if "cycle" not in data:
            data["cycle"] = 0

        return data

    except Exception as e:

        logger.warning(
            "Unable to read posted.json: %s",
            e
        )

        return {
            "items": [],
            "cycle": 0
        }


# ============================================================
# SAVE POSTED DATABASE
# ============================================================

def save_posted(data):

    try:

        items = data.get("items", [])

        if len(items) > MAX_POSTED_HISTORY:

            items = items[-MAX_POSTED_HISTORY:]

        data["items"] = items

        temp_file = POSTED_FILE.with_suffix(
            ".json.tmp"
        )

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

        temp_file.replace(POSTED_FILE)

        logger.info(
            "posted.json saved successfully."
        )

        return True

    except Exception as e:

        logger.error(
            "Failed to save posted.json: %s",
            e
        )

        return False


# ============================================================
# NORMALIZE TEXT
# ============================================================

def clean_text(text):

    if not text:
        return ""

    text = str(text)

    text = text.replace(
        "\xa0",
        " "
    )

    return " ".join(
        text.split()
    ).strip()


# ============================================================
# ARTICLE ID
# ============================================================

def article_id(article):

    source = (
        article.get("url")
        or article.get("title")
        or ""
    )

    return hashlib.sha256(
        source.encode(
            "utf-8",
            errors="ignore"
        )
    ).hexdigest()


# ============================================================
# GNEWS REQUEST
# ============================================================

def gnews_request(params):

    try:

        response = SESSION.get(
            GNEWS_URL,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        logger.info(
            "GNews HTTP status = %s",
            response.status_code
        )

        if response.status_code == 429:

            logger.warning(
                "GNews rate limit reached."
            )

            return None

        if not response.ok:

            logger.error(
                "GNews error: %s",
                response.text[:1000]
            )

            return None

        return response.json()

    except Exception as e:

        logger.error(
            "GNews request failed: %s",
            e
        )

        return None


# ============================================================
# FETCH MALAYSIA NEWS
# ============================================================

def fetch_news():

    logger.info(
        "Fetching Malaysia news from GNews..."
    )

    queries = [
        "Malaysia",
        "Malaysia Kuala Lumpur",
        "Malaysia government",
        "Malaysia economy",
        "Malaysia police",
        "Malaysia education"
    ]

    all_articles = {}

    for index, query in enumerate(queries):

        params = {
            "q": query,
            "lang": "en",
            "country": "my",
            "max": GNEWS_MAX_RESULTS,
            "apikey": GNEWS_API_KEY
        }

        result = gnews_request(params)

        if not result:

            if index < len(queries) - 1:

                time.sleep(1)

            continue

        articles = result.get(
            "articles",
            []
        )

        for article in articles:

            title = clean_text(
                article.get("title")
            )

            url = (
                article.get("url")
                or ""
            ).strip()

            if not title or not url:
                continue

            key = url

            if key not in all_articles:

                all_articles[key] = article

        # ----------------------------------------------------
        # Avoid GNews 429
        # ----------------------------------------------------

        if index < len(queries) - 1:

            time.sleep(0.7)

    articles = list(
        all_articles.values()
    )

    logger.info(
        "Total unique GNews articles collected: %s",
        len(articles)
    )

    return articles


# ============================================================
# FILTER MALAYSIA NEWS
# ============================================================

MALAYSIA_KEYWORDS = [
    "malaysia",
    "malaysian",
    "kuala lumpur",
    "selangor",
    "putrajaya",
    "penang",
    "johor",
    "perak",
    "kedah",
    "kelantan",
    "terengganu",
    "pahang",
    "melaka",
    "malacca",
    "negeri sembilan",
    "sabah",
    "sarawak",
    "labuan",
    "ringgit",
    "anwar ibrahim",
    "mat sabu",
    "parliament",
    "parlimen",
    "pdrm",
    "police malaysia",
    "bank negara"
]


def is_malaysia_news(article):

    text = " ".join([
        clean_text(article.get("title")),
        clean_text(article.get("description")),
        clean_text(
            article.get("content")
        )
    ]).lower()

    return any(
        keyword in text
        for keyword in MALAYSIA_KEYWORDS
    )


# ============================================================
# SELECT NEW NEWS
# ============================================================

def select_new_news(
    articles,
    posted
):

    posted_items = posted.get(
        "items",
        []
    )

    posted_ids = set()

    for item in posted_items:

        if isinstance(item, dict):

            value = item.get("id")

            if value:
                posted_ids.add(value)

        elif isinstance(item, str):

            posted_ids.add(item)

    candidates = []

    for article in articles:

        if not is_malaysia_news(article):

            continue

        aid = article_id(article)

        title = clean_text(
            article.get("title")
        )

        if aid in posted_ids:

            logger.info(
                "Duplicate news skipped: %s",
                title
            )

            continue

        candidates.append(
            article
        )

    if not candidates:

        logger.warning(
            "No new Malaysia news available."
        )

        return None

    selected = candidates[0]

    logger.info(
        "NEW NEWS FOUND: %s",
        clean_text(
            selected.get("title")
        )
    )

    return selected


# ============================================================
# GROQ CONTENT GENERATION
# ============================================================

def generate_news_content(article):

    if not groq_client:

        raise RuntimeError(
            "Groq client is not configured."
        )

    title = clean_text(
        article.get("title")
    )

    description = clean_text(
        article.get("description")
    )

    source = clean_text(
        article.get("source", {}).get("name")
        if isinstance(
            article.get("source"),
            dict
        )
        else ""
    )

    url = (
        article.get("url")
        or ""
    ).strip()

    prompt = f"""
You are the editor of MYBuzz NEWS, a bilingual Malaysia news channel.

Create a concise bilingual Telegram news post from the article below.

IMPORTANT:
- Do NOT invent facts.
- Do NOT add facts that are not supported by the article.
- Chinese should be natural Simplified Chinese.
- Malay should be natural Malaysian Malay.
- Keep both versions short and readable.
- Do not use markdown headings.
- Do not use hashtags.
- Do not include the source name in the article body.
- Do not include URLs inside the generated body.
- Chinese title should be concise.
- Malay title should be concise.
- Chinese summary: 1 short paragraph.
- Malay summary: 1 short paragraph.

OUTPUT EXACTLY IN THIS FORMAT:

CHINESE_TITLE:
...

CHINESE_BODY:
...

MALAY_TITLE:
...

MALAY_BODY:
...

ARTICLE:
{title}

DESCRIPTION:
{description}

SOURCE:
{source}

URL:
{url}
"""

    response = groq_client.responses.create(
        model=GROQ_MODEL,
        input=prompt
    )

    text = response.output_text.strip()

    return parse_generated_content(
        text,
        article
    )


# ============================================================
# PARSE GROQ CONTENT
# ============================================================

def parse_generated_content(
    text,
    article
):

    fields = {
        "chinese_title": "",
        "chinese_body": "",
        "malay_title": "",
        "malay_body": ""
    }

    current = None

    for raw_line in text.splitlines():

        line = raw_line.strip()

        if not line:
            continue

        upper = line.upper()

        if upper.startswith(
            "CHINESE_TITLE:"
        ):

            current = "chinese_title"

            value = line.split(
                ":",
                1
            )[1].strip()

            fields[current] = value

            continue

        if upper.startswith(
            "CHINESE_BODY:"
        ):

            current = "chinese_body"

            value = line.split(
                ":",
                1
            )[1].strip()

            fields[current] = value

            continue

        if upper.startswith(
            "MALAY_TITLE:"
        ):

            current = "malay_title"

            value = line.split(
                ":",
                1
            )[1].strip()

            fields[current] = value

            continue

        if upper.startswith(
            "MALAY_BODY:"
        ):

            current = "malay_body"

            value = line.split(
                ":",
                1
            )[1].strip()

            fields[current] = value

            continue

        if current:

            fields[current] += (
                " " + line
            )

    # --------------------------------------------------------
    # Fallback
    # --------------------------------------------------------

    if not fields["chinese_title"]:

        fields["chinese_title"] = clean_text(
            article.get("title")
        )

    if not fields["chinese_body"]:

        fields["chinese_body"] = clean_text(
            article.get("description")
        )

    if not fields["malay_title"]:

        fields["malay_title"] = clean_text(
            article.get("title")
        )

    if not fields["malay_body"]:

        fields["malay_body"] = clean_text(
            article.get("description")
        )

    return fields


# ============================================================
# BUILD NEWS TELEGRAM MESSAGE
# ============================================================

def build_news_message(
    content,
    article
):

    url = (
        article.get("url")
        or ""
    ).strip()

    message = (
        "🇲🇾 MYBuzz NEWS\n\n"

        "🇨🇳 "
        + content["chinese_title"]
        + "\n"

        + content["chinese_body"]
        + "\n\n"

        "🇲🇾 "
        + content["malay_title"]
        + "\n"

        + content["malay_body"]
        + "\n\n"

        "👉 点击阅读完整新闻\n"
        + url
        + "\n\n"

        "👉 Klik untuk baca berita penuh\n"
        + url
    )

    return message


# ============================================================
# WIKIPEDIA SEARCH
# ============================================================

def wikipedia_search():

    queries = [
        "Malaysia",
        "Kuala Lumpur",
        "Putrajaya",
        "Malaysian culture",
        "History of Malaysia",
        "States of Malaysia"
    ]

    for query in queries:

        try:

            params = {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "utf8": 1,
                "srlimit": 5
            }

            response = SESSION.get(
                WIKIPEDIA_API,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            if not response.ok:
                continue

            data = response.json()

            results = (
                data.get("query", {})
                .get("search", [])
            )

            if results:

                result = results[0]

                return {
                    "title": result.get(
                        "title",
                        ""
                    ),
                    "snippet": result.get(
                        "snippet",
                        ""
                    )
                }

        except Exception as e:

            logger.warning(
                "Wikipedia search error: %s",
                e
            )

    return None


# ============================================================
# WIKIPEDIA ARTICLE
# ============================================================

def wikipedia_article(title):

    try:

        params = {
            "action": "query",
            "prop": "extracts|info",
            "exintro": 1,
            "explaintext": 1,
            "inprop": "url",
            "titles": title,
            "format": "json",
            "redirects": 1
        }

        response = SESSION.get(
            WIKIPEDIA_API,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        if not response.ok:

            logger.error(
                "Wikipedia HTTP status = %s",
                response.status_code
            )

            return None

        data = response.json()

        pages = (
            data.get("query", {})
            .get("pages", {})
        )

        for page in pages.values():

            if page.get("missing"):
                continue

            return {
                "title": page.get(
                    "title",
                    title
                ),
                "extract": clean_text(
                    page.get(
                        "extract",
                        ""
                    )
                ),
                "url": page.get(
                    "fullurl",
                    "https://en.wikipedia.org/wiki/"
                    + quote(title.replace(" ", "_"))
                )
            }

    except Exception as e:

        logger.error(
            "Wikipedia article error: %s",
            e
        )

    return None


# ============================================================
# GENERATE WIKI CONTENT
# ============================================================

def generate_wiki_content():

    logger.info(
        "Fetching Wikipedia topic..."
    )

    result = wikipedia_search()

    if not result:

        logger.warning(
            "No Wikipedia topic found."
        )

        return None

    article = wikipedia_article(
        result["title"]
    )

    if not article:

        return None

    logger.info(
        "Wikipedia topic selected: %s",
        article["title"]
    )

    if not groq_client:

        return None

    prompt = f"""
You are the editor of MYBuzz NEWS.

Create a short bilingual educational MYBuzz WIKI post based ONLY on the Wikipedia information below.

The post should explain the topic in a simple way for Malaysian readers.

Do not invent information.

OUTPUT EXACTLY:

CHINESE_TITLE:
...

CHINESE_BODY:
...

MALAY_TITLE:
...

MALAY_BODY:
...

TOPIC:
{article["title"]}

INFORMATION:
{article["extract"][:5000]}
"""

    try:

        response = groq_client.responses.create(
            model=GROQ_MODEL,
            input=prompt
        )

        content = parse_generated_content(
            response.output_text,
            {
                "title": article["title"],
                "description": article["extract"]
            }
        )

        content["url"] = article["url"]

        return content

    except Exception as e:

        logger.error(
            "Wikipedia Groq generation failed: %s",
            e
        )

        return None


# ============================================================
# BUILD WIKI TELEGRAM MESSAGE
# ============================================================

def build_wiki_message(content):

    message = (
        "🇲🇾 MYBuzz WIKI\n\n"

        "🇨🇳 "
        + content["chinese_title"]
        + "\n"

        + content["chinese_body"]
        + "\n\n"

        "🇲🇾 "
        + content["malay_title"]
        + "\n"

        + content["malay_body"]
        + "\n\n"

        "👉 点击阅读完整内容\n"
        + content["url"]
        + "\n\n"

        "👉 Klik untuk baca kandungan penuh\n"
        + content["url"]
    )

    return message


# ============================================================
# TELEGRAM API
# ============================================================

def telegram_api(
    method,
    payload
):

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/"
        + method
    )

    try:

        response = SESSION.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        logger.info(
            "Telegram %s HTTP status = %s",
            method,
            response.status_code
        )

        try:

            data = response.json()

        except Exception:

            data = {
                "ok": False,
                "description": response.text
            }

        if not response.ok:

            logger.error(
                "Telegram API ERROR: %s",
                json.dumps(
                    data,
                    ensure_ascii=False
                )
            )

            return data

        if not data.get("ok"):

            logger.error(
                "Telegram API returned ok=false: %s",
                json.dumps(
                    data,
                    ensure_ascii=False
                )
            )

            return data

        return data

    except Exception as e:

        logger.error(
            "Telegram request failed: %s",
            e
        )

        return {
            "ok": False,
            "description": str(e)
        }


# ============================================================
# TEST TELEGRAM
# ============================================================

def test_telegram():

    logger.info(
        "Testing Telegram bot connection..."
    )

    result = telegram_api(
        "getMe",
        {}
    )

    if result.get("ok"):

        bot = result.get(
            "result",
            {}
        )

        logger.info(
            "Telegram bot OK: @%s",
            bot.get("username", "")
        )

        return True

    logger.error(
        "Telegram bot test FAILED."
    )

    return False


# ============================================================
# SEND TELEGRAM MESSAGE
# ============================================================

def send_telegram(
    message,
    channel_id
):

    logger.info(
        "======================================"
    )

    logger.info(
        "TELEGRAM SEND START"
    )

    logger.info(
        "Telegram target = %s",
        channel_id
    )

    logger.info(
        "Telegram message length = %s",
        len(message)
    )

    payload = {
        "chat_id": channel_id,
        "text": message,
        "disable_web_page_preview": False
    }

    result = telegram_api(
        "sendMessage",
        payload
    )

    if result.get("ok"):

        message_id = (
            result.get("result", {})
            .get("message_id")
        )

        logger.info(
            "TELEGRAM SEND SUCCESS"
        )

        logger.info(
            "Telegram message_id = %s",
            message_id
        )

        logger.info(
            "======================================"
        )

        return True

    logger.error(
        "TELEGRAM SEND FAILED"
    )

    logger.error(
        "Telegram response = %s",
        json.dumps(
            result,
            ensure_ascii=False
        )
    )

    logger.info(
        "======================================"
    )

    return False


# ============================================================
# NEWS PROCESS
# ============================================================

def process_news(posted):

    logger.info(
        "Content mode: NEWS"
    )

    articles = fetch_news()

    if not articles:

        logger.warning(
            "No GNews articles available."
        )

        return False

    article = select_new_news(
        articles,
        posted
    )

    if not article:

        return False

    logger.info(
        "Selected title: %s",
        clean_text(
            article.get("title")
        )
    )

    logger.info(
        "Selected source: %s",
        clean_text(
            article.get("source", {}).get("name")
            if isinstance(
                article.get("source"),
                dict
            )
            else ""
        )
    )

    logger.info(
        "Selected image: %s",
        article.get("image", "")
    )

    try:

        content = generate_news_content(
            article
        )

    except Exception as e:

        logger.error(
            "Groq news generation failed: %s",
            e
        )

        return False

    message = build_news_message(
        content,
        article
    )

    logger.info(
        "======================================"
    )

    logger.info(
        "MYBUZZ CONTENT READY"
    )

    logger.info(
        "======================================"
    )

    print()
    print(message)
    print()

    # --------------------------------------------------------
    # IMPORTANT
    #
    # Telegram MUST happen BEFORE posted.json.
    # --------------------------------------------------------

    sent = send_telegram(
        message,
        TELEGRAM_CHANNEL_ID
    )

    if not sent:

        logger.error(
            "Telegram failed. Article WILL NOT be added to posted.json."
        )

        return False

    # --------------------------------------------------------
    # Telegram succeeded.
    # Now save duplicate history.
    # --------------------------------------------------------

    aid = article_id(article)

    posted.setdefault(
        "items",
        []
    )

    posted["items"].append({
        "id": aid,
        "type": "NEWS",
        "title": clean_text(
            article.get("title")
        ),
        "url": article.get("url", ""),
        "posted_at": datetime.now(
            timezone.utc
        ).isoformat()
    })

    logger.info(
        "Added article to duplicate history."
    )

    return True


# ============================================================
# WIKI PROCESS
# ============================================================

def process_wiki(posted):

    logger.info(
        "Content mode: WIKI"
    )

    content = generate_wiki_content()

    if not content:

        logger.warning(
            "Unable to generate Wiki content."
        )

        return False

    message = build_wiki_message(
        content
    )

    logger.info(
        "======================================"
    )

    logger.info(
        "MYBUZZ CONTENT READY"
    )

    logger.info(
        "======================================"
    )

    print()
    print(message)
    print()

    # --------------------------------------------------------
    # Telegram first.
    # --------------------------------------------------------

    sent = send_telegram(
        message,
        TELEGRAM_WIKI_CHANNEL_ID
    )

    if not sent:

        logger.error(
            "Wiki Telegram failed."
        )

        return False

    # --------------------------------------------------------
    # Save Wiki history only after Telegram success.
    # --------------------------------------------------------

    wiki_id = hashlib.sha256(
        (
            "WIKI:"
            + content["url"]
        ).encode(
            "utf-8"
        )
    ).hexdigest()

    posted.setdefault(
        "items",
        []
    )

    posted["items"].append({
        "id": wiki_id,
        "type": "WIKI",
        "title": content[
            "chinese_title"
        ],
        "url": content["url"],
        "posted_at": datetime.now(
            timezone.utc
        ).isoformat()
    })

    logger.info(
        "Added Wiki article to duplicate history."
    )

    return True


# ============================================================
# CYCLE MODE
# ============================================================

def get_cycle_mode(cycle):

    position = (
        cycle % CYCLE_LENGTH
    ) + 1

    if position == 3:

        return (
            position,
            "WIKI"
        )

    return (
        position,
        "NEWS"
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

    if not check_config():

        raise SystemExit(
            1
        )

    posted = load_posted()

    logger.info(
        "Posted database: %s items",
        len(
            posted.get(
                "items",
                []
            )
        )
    )

    cycle = int(
        posted.get(
            "cycle",
            0
        )
    )

    logger.info(
        "Cycle counter: %s",
        cycle
    )

    position, mode = get_cycle_mode(
        cycle
    )

    logger.info(
        "Cycle position: %s/%s",
        position,
        CYCLE_LENGTH
    )

    logger.info(
        "Content mode: %s",
        mode
    )

    # --------------------------------------------------------
    # Test Telegram BEFORE doing anything.
    # --------------------------------------------------------

    if not test_telegram():

        logger.error(
            "Telegram connection test failed."
        )

        logger.error(
            "STOPPING BEFORE CONTENT GENERATION."
        )

        raise SystemExit(
            1
        )

    # --------------------------------------------------------
    # PROCESS
    # --------------------------------------------------------

    success = False

    if mode == "NEWS":

        success = process_news(
            posted
        )

    elif mode == "WIKI":

        success = process_wiki(
            posted
        )

    # --------------------------------------------------------
    # IMPORTANT
    #
    # Only advance cycle when Telegram succeeded.
    # --------------------------------------------------------

    if success:

        posted["cycle"] = cycle + 1

        logger.info(
            "Cycle advanced to counter: %s",
            posted["cycle"]
        )

        if not save_posted(
            posted
        ):

            logger.error(
                "WARNING: Telegram was successful but posted.json could not be saved."
            )

    else:

        logger.warning(
            "Content was NOT successfully published."
        )

        logger.warning(
            "Cycle will NOT advance."
        )

        logger.warning(
            "posted.json will NOT be changed."
        )

    logger.info(
        "======================================"
    )

    logger.info(
        "MYBUZZ BOT FINISHED"
    )

    logger.info(
        "======================================"

    )

    if success:

        logger.info(
            "Type processed: %s",
            mode
        )

        logger.info(
            "Telegram publication: SUCCESS"
        )

    else:

        logger.info(
            "Type processed: %s",
            mode
        )

        logger.info(
            "Telegram publication: FAILED"
        )

        raise SystemExit(
            1
        )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    main()
