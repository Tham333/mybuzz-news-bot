import os
import json
import time
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote

import requests
import argostranslate.package
import argostranslate.translate


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
# Argos Translate
#       ↓
# English → Chinese
# English → Malay
#       ↓
# TELEGRAM
#       ↓
# Telegram SUCCESS
#       ↓
# posted.json
#
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

GNEWS_API_KEY = os.getenv(
    "GNEWS_API_KEY",
    ""
).strip()

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHANNEL_ID = os.getenv(
    "TELEGRAM_CHANNEL_ID",
    "@mybuzzmy"
).strip()

TELEGRAM_WIKI_CHANNEL_ID = os.getenv(
    "TELEGRAM_WIKI_CHANNEL_ID",
    TELEGRAM_CHANNEL_ID
).strip()


# ============================================================
# FILES
# ============================================================

POSTED_FILE = Path("posted.json")


# ============================================================
# URLS
# ============================================================

GNEWS_URL = "https://gnews.io/api/v4/search"

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"


# ============================================================
# RUNTIME
# ============================================================

REQUEST_TIMEOUT = 30

MAX_POSTED_HISTORY = 500

GNEWS_MAX_RESULTS = 10

CYCLE_LENGTH = 3


# ============================================================
# ARGOS LANGUAGES
# ============================================================

ARGOS_SOURCE_LANGUAGE = "en"

ARGOS_CHINESE_LANGUAGE = "zh"

ARGOS_MALAY_LANGUAGE = "ms"


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
        "MYBUZZ-News-Bot/3.0 "
        "(https://github.com/Tham333/mybuzz-news-bot)"
    ),
    "Accept": "*/*"
})


# ============================================================
# CONFIG CHECK
# ============================================================

def check_config():

    logger.info(
        "Checking API configuration..."
    )

    missing = []

    if not GNEWS_API_KEY:
        missing.append(
            "GNEWS_API_KEY"
        )

    if not TELEGRAM_BOT_TOKEN:
        missing.append(
            "TELEGRAM_BOT_TOKEN"
        )

    if not TELEGRAM_CHANNEL_ID:
        missing.append(
            "TELEGRAM_CHANNEL_ID"
        )

    if missing:

        logger.error(
            "Missing environment variables: %s",
            ", ".join(missing)
        )

        return False

    logger.info(
        "API configuration OK."
    )

    return True


# ============================================================
# ARGOS TRANSLATE
# ============================================================

def get_argos_translation(
    from_code,
    to_code
):

    """
    Get an installed Argos translation model.

    If the model does not exist, install it automatically.
    """

    try:

        translation = (
            argostranslate.translate
            .get_translation_from_codes(
                from_code,
                to_code
            )
        )

        if translation:

            logger.info(
                "Argos model already installed: %s -> %s",
                from_code,
                to_code
            )

            return translation

    except Exception:

        pass

    logger.info(
        "Argos model missing: %s -> %s",
        from_code,
        to_code
    )

    logger.info(
        "Updating Argos package index..."
    )

    argostranslate.package.update_package_index()

    available_packages = (
        argostranslate.package
        .get_available_packages()
    )

    package_to_install = None

    for package in available_packages:

        if (
            package.from_code == from_code
            and
            package.to_code == to_code
        ):

            package_to_install = package
            break

    if not package_to_install:

        raise RuntimeError(
            "Argos translation model not found: "
            + from_code
            + " -> "
            + to_code
        )

    logger.info(
        "Downloading Argos model: %s -> %s",
        from_code,
        to_code
    )

    package_path = (
        package_to_install.download()
    )

    logger.info(
        "Installing Argos model..."
    )

    argostranslate.package.install_from_path(
        package_path
    )

    logger.info(
        "Argos model installed: %s -> %s",
        from_code,
        to_code
    )

    translation = (
        argostranslate.translate
        .get_translation_from_codes(
            from_code,
            to_code
        )
    )

    if not translation:

        raise RuntimeError(
            "Argos model installation succeeded "
            "but translation model could not be loaded: "
            + from_code
            + " -> "
            + to_code
        )

    return translation


# ============================================================
# INITIALIZE ARGOS
# ============================================================

ARGOS_EN_ZH = None

ARGOS_EN_MS = None


def initialize_argos():

    global ARGOS_EN_ZH
    global ARGOS_EN_MS

    logger.info(
        "======================================"
    )

    logger.info(
        "INITIALIZING ARGOS TRANSLATE"
    )

    logger.info(
        "======================================"
    )

    # English → Chinese

    ARGOS_EN_ZH = get_argos_translation(
        ARGOS_SOURCE_LANGUAGE,
        ARGOS_CHINESE_LANGUAGE
    )

    # English → Malay

    ARGOS_EN_MS = get_argos_translation(
        ARGOS_SOURCE_LANGUAGE,
        ARGOS_MALAY_LANGUAGE
    )

    logger.info(
        "Argos translation models READY."
    )

    logger.info(
        "English → Chinese: READY"
    )

    logger.info(
        "English → Malay: READY"
    )

    logger.info(
        "======================================"
    )


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

    text = text.replace(
        "\r",
        " "
    )

    text = text.replace(
        "\n",
        " "
    )

    return " ".join(
        text.split()
    ).strip()


# ============================================================
# ARGOS TRANSLATE TEXT
# ============================================================

def translate_text(
    text,
    target_language
):

    text = clean_text(text)

    if not text:
        return ""

    global ARGOS_EN_ZH
    global ARGOS_EN_MS

    try:

        if target_language == "zh":

            if not ARGOS_EN_ZH:

                ARGOS_EN_ZH = get_argos_translation(
                    "en",
                    "zh"
                )

            translated = (
                ARGOS_EN_ZH.translate(text)
            )

        elif target_language == "ms":

            if not ARGOS_EN_MS:

                ARGOS_EN_MS = get_argos_translation(
                    "en",
                    "ms"
                )

            translated = (
                ARGOS_EN_MS.translate(text)
            )

        else:

            raise ValueError(
                "Unsupported target language: "
                + target_language
            )

        return clean_text(
            translated
        )

    except Exception as e:

        logger.error(
            "Argos translation failed (%s): %s",
            target_language,
            e
        )

        raise


# ============================================================
# TEXT LENGTH CONTROL
# ============================================================

def truncate_text(
    text,
    max_chars
):

    text = clean_text(text)

    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]

    boundaries = [
        "。",
        "！",
        "？",
        ".",
        "!",
        "?"
    ]

    best_position = -1

    for boundary in boundaries:

        position = truncated.rfind(
            boundary
        )

        if position > best_position:
            best_position = position

    if best_position > int(
        max_chars * 0.65
    ):

        return truncated[
            :best_position + 1
        ].strip()

    return truncated.strip()


# ============================================================
# POSTED DATABASE
# ============================================================

def load_posted():

    if not POSTED_FILE.exists():

        logger.info(
            "posted.json not found. "
            "Creating new database."
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

        items = data.get(
            "items",
            []
        )

        if len(items) > MAX_POSTED_HISTORY:

            items = items[
                -MAX_POSTED_HISTORY:
            ]

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

        temp_file.replace(
            POSTED_FILE
        )

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
        "Malaysia government",
        "Malaysia economy"
    ]

    all_articles = {}

    for index, query in enumerate(
        queries
    ):

        params = {
            "q": query,
            "lang": "en",
            "country": "my",
            "max": GNEWS_MAX_RESULTS,
            "apikey": GNEWS_API_KEY
        }

        result = gnews_request(
            params
        )

        if result:

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

                if url not in all_articles:

                    all_articles[url] = article

        if index < len(queries) - 1:
            time.sleep(2)

    articles = list(
        all_articles.values()
    )

    logger.info(
        "Total unique GNews articles collected: %s",
        len(articles)
    )

    return articles


# ============================================================
# MALAYSIA KEYWORDS
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

    "petaling jaya",
    "shah alam",
    "subang jaya",
    "klang",
    "kajang",
    "cyberjaya",
    "sepang",
    "serdang",
    "ipoh",
    "george town",
    "johor bahru",
    "malacca city",
    "kota kinabalu",
    "kuching",

    "ringgit",
    "anwar ibrahim",
    "mat sabu",
    "parliament",
    "parlimen",
    "pdrm",
    "police malaysia",
    "bank negara",
    "malaysian government"
]


# ============================================================
# CHECK MALAYSIA NEWS
# ============================================================

def is_malaysia_news(article):

    text = " ".join([
        clean_text(
            article.get("title")
        ),
        clean_text(
            article.get("description")
        ),
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

        if isinstance(
            item,
            dict
        ):

            value = item.get(
                "id"
            )

            if value:
                posted_ids.add(
                    value
                )

        elif isinstance(
            item,
            str
        ):

            posted_ids.add(
                item
            )

    candidates = []

    for article in articles:

        if not is_malaysia_news(
            article
        ):
            continue

        aid = article_id(
            article
        )

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
# GENERATE NEWS CONTENT
# ============================================================

def generate_news_content(
    article
):

    title = clean_text(
        article.get("title")
    )

    description = clean_text(
        article.get("description")
    )

    content = clean_text(
        article.get("content")
    )

    source_data = article.get(
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

    english_body = description

    if len(english_body) < 100:
        english_body = content

    if not english_body:
        english_body = title

    english_body = truncate_text(
        english_body,
        700
    )

    english_title = truncate_text(
        title,
        180
    )

    logger.info(
        "======================================"
    )

    logger.info(
        "ARGOS TRANSLATION START"
    )

    logger.info(
        "Source: %s",
        source
    )

    logger.info(
        "English title: %s",
        english_title
    )

    logger.info(
        "======================================"
    )

    chinese_title = translate_text(
        english_title,
        "zh"
    )

    chinese_body = translate_text(
        english_body,
        "zh"
    )

    malay_title = translate_text(
        english_title,
        "ms"
    )

    malay_body = translate_text(
        english_body,
        "ms"
    )

    chinese_title = clean_text(
        chinese_title
    )

    chinese_body = clean_text(
        chinese_body
    )

    malay_title = clean_text(
        malay_title
    )

    malay_body = clean_text(
        malay_body
    )

    if not chinese_title:
        chinese_title = english_title

    if not chinese_body:
        chinese_body = english_body

    if not malay_title:
        malay_title = english_title

    if not malay_body:
        malay_body = english_body

    logger.info(
        "ARGOS TRANSLATION COMPLETE"
    )

    return {
        "chinese_title": chinese_title,
        "chinese_body": chinese_body,
        "malay_title": malay_title,
        "malay_body": malay_body
    }


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
        + "\n\n"

        + content["chinese_body"]
        + "\n\n"

        "🇲🇾 "
        + content["malay_title"]
        + "\n\n"

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
                data
                .get("query", {})
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

def wikipedia_article(
    title
):

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
            data
            .get("query", {})
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
                    + quote(
                        title.replace(
                            " ",
                            "_"
                        )
                    )
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

    english_title = clean_text(
        article["title"]
    )

    english_body = truncate_text(
        article["extract"],
        900
    )

    if not english_body:
        english_body = english_title

    chinese_title = translate_text(
        english_title,
        "zh"
    )

    chinese_body = translate_text(
        english_body,
        "zh"
    )

    malay_title = translate_text(
        english_title,
        "ms"
    )

    malay_body = translate_text(
        english_body,
        "ms"
    )

    return {
        "chinese_title": clean_text(
            chinese_title
        ),
        "chinese_body": clean_text(
            chinese_body
        ),
        "malay_title": clean_text(
            malay_title
        ),
        "malay_body": clean_text(
            malay_body
        ),
        "url": article["url"]
    }


# ============================================================
# BUILD WIKI TELEGRAM MESSAGE
# ============================================================

def build_wiki_message(
    content
):

    message = (
        "🇲🇾 MYBuzz WIKI\n\n"

        "🇨🇳 "
        + content["chinese_title"]
        + "\n\n"

        + content["chinese_body"]
        + "\n\n"

        "🇲🇾 "
        + content["malay_title"]
        + "\n\n"

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
            bot.get(
                "username",
                ""
            )
        )

        return True

    logger.error(
        "Telegram bot test FAILED."
    )

    return False


# ============================================================
# SEND TELEGRAM
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
            result
            .get("result", {})
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

def process_news(
    posted
):

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

    source_data = article.get(
        "source",
        {}
    )

    if isinstance(
        source_data,
        dict
    ):

        source_name = clean_text(
            source_data.get(
                "name",
                ""
            )
        )

    else:

        source_name = ""

    logger.info(
        "Selected source: %s",
        source_name
    )

    logger.info(
        "Selected image: %s",
        article.get(
            "image",
            ""
        )
    )

    try:

        content = generate_news_content(
            article
        )

    except Exception as e:

        logger.error(
            "Argos news translation failed: %s",
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

    sent = send_telegram(
        message,
        TELEGRAM_CHANNEL_ID
    )

    if not sent:

        logger.error(
            "Telegram failed. "
            "Article WILL NOT be added to posted.json."
        )

        return False

    aid = article_id(
        article
    )

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
        "url": article.get(
            "url",
            ""
        ),
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

def process_wiki(
    posted
):

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

    sent = send_telegram(
        message,
        TELEGRAM_WIKI_CHANNEL_ID
    )

    if not sent:

        logger.error(
            "Wiki Telegram failed."
        )

        return False

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
        "url": content[
            "url"
        ],
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

def get_cycle_mode(
    cycle
):

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

    try:

        initialize_argos()

    except Exception as e:

        logger.error(
            "Argos initialization failed: %s",
            e
        )

        raise SystemExit(
            1
        )

    success = False

    if mode == "NEWS":

        success = process_news(
            posted
        )

    elif mode == "WIKI":

        success = process_wiki(
            posted
        )

    if success:

        posted["cycle"] = (
            cycle + 1
        )

        logger.info(
            "Cycle advanced to counter: %s",
            posted["cycle"]
        )

        if not save_posted(
            posted
        ):

            logger.error(
                "WARNING: Telegram was successful "
                "but posted.json could not be saved."
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
