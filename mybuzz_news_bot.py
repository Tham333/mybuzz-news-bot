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
# Schedule:
#
# 1 = NEWS
# 2 = NEWS
# 3 = TRAVEL / FOOD
# 4 = NEWS
# 5 = NEWS
# 6 = TRAVEL / FOOD
#
# Cloudflare Worker
#       ↓
# GitHub Actions
#       ↓
# mybuzz_news_bot.py
#       ↓
# GNews / Wikivoyage / Wikimedia
#       ↓
# Duplicate Check
#       ↓
# Groq AI
#       ↓
# Telegram
#
# IMPORTANT:
# One execution = ONE post only.
#
# ============================================================


BOT_NAME = "MYBUZZ BOT"


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# ============================================================
# API CONFIG
# ============================================================

GNEWS_BASE_URL = "https://gnews.io/api/v4"

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

GROQ_MODEL = "openai/gpt-oss-20b"

WIKIVOYAGE_API = "https://en.wikivoyage.org/w/api.php"

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"


# ============================================================
# FILE STORAGE
# ============================================================

POSTED_FILE = "posted.json"

STATE_FILE = "bot_state.json"


# ============================================================
# LIMITS
# ============================================================

REQUEST_TIMEOUT = 20

MAX_GNEWS_ARTICLES = 20

MAX_WIKI_RESULTS = 10

MAX_POSTED = 1000


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(BOT_NAME)


# ============================================================
# VALIDATE CONFIG
# ============================================================

logger.info("Checking API configuration...")


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


logger.info("API configuration OK.")


# ============================================================
# GROQ CLIENT
# ============================================================

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url=GROQ_BASE_URL,
)


# ============================================================
# REQUEST HEADERS
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "MYBUZZ-News-Bot/1.0"
    )
}


# ============================================================
# LOAD POSTED DATABASE
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

            posted = data.get(
                "posted",
                []
            )

            if isinstance(posted, list):
                return posted

    except Exception as e:

        logger.warning(
            "Could not read %s: %s",
            POSTED_FILE,
            e
        )

    return []


# ============================================================
# SAVE POSTED DATABASE
# ============================================================

def save_posted(posted):

    try:

        posted = posted[-MAX_POSTED:]

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
            "Could not save posted database: %s",
            e
        )


# ============================================================
# LOAD STATE
# ============================================================

def load_state():

    default_state = {
        "counter": 0,
        "topic_counter": 0
    }

    if not os.path.exists(STATE_FILE):
        return default_state

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if not isinstance(data, dict):
            return default_state

        counter = data.get(
            "counter",
            0
        )

        topic_counter = data.get(
            "topic_counter",
            0
        )

        try:
            counter = int(counter)
        except Exception:
            counter = 0

        try:
            topic_counter = int(topic_counter)
        except Exception:
            topic_counter = 0

        return {
            "counter": counter,
            "topic_counter": topic_counter
        }

    except Exception as e:

        logger.warning(
            "Could not read state: %s",
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
            "Could not save state: %s",
            e
        )


# ============================================================
# CONTENT MODE
# ============================================================

def get_next_mode(state):

    counter = state.get(
        "counter",
        0
    )

    position = (
        counter % 3
    ) + 1

    if position == 3:

        mode = "TRAVEL_FOOD"

    else:

        mode = "NEWS"

    logger.info(
        "Cycle position: %s/3",
        position
    )

    logger.info(
        "Content mode: %s",
        mode
    )

    return mode


# ============================================================
# ADVANCE STATE
# ============================================================

def advance_state(state):

    state["counter"] = (
        int(
            state.get(
                "counter",
                0
            )
        ) + 1
    )

    save_state(state)


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
# CREATE ARTICLE ID
# ============================================================

def article_id(article):

    link = normalize_url(
        article.get(
            "link",
            ""
        )
    )

    if link:

        return hashlib.sha256(
            link.encode("utf-8")
        ).hexdigest()

    title = clean_text(
        article.get(
            "title",
            ""
        )
    ).lower()

    source = clean_text(
        article.get(
            "source",
            ""
        )
    ).lower()

    content_type = clean_text(
        article.get(
            "type",
            ""
        )
    ).lower()

    raw = (
        content_type
        + "|"
        + source
        + "|"
        + title
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


# ============================================================
# GNEWS REQUEST
# ============================================================

def gnews_request(params):

    params = dict(params)

    params["apikey"] = GNEWS_API_KEY

    try:

        response = requests.get(
            GNEWS_BASE_URL + "/search",
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
        )

        logger.info(
            "GNews HTTP status = %s",
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
        "Fetching Malaysia news from GNews..."
    )

    params = {

        "q": (
            "Malaysia OR Malaysian"
        ),

        "lang": "en",

        "country": "my",

        "max": MAX_GNEWS_ARTICLES,

        "in": "title,description",

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

        published_at = clean_text(
            item.get(
                "publishedAt",
                ""
            )
        )

        if not title or not url:
            continue

        results.append({

            "type":
                "NEWS",

            "source":
                source or "GNews",

            "title":
                title,

            "description":
                description,

            "link":
                url,

            "image":
                image,

            "publishedAt":
                published_at,

        })

    logger.info(
        "GNews returned %s usable articles.",
        len(results)
    )

    return results


# ============================================================
# FIND IMAGE FROM NEWS PAGE
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
            "Could not find article image: %s",
            e
        )

    return ""


# ============================================================
# SELECT NEWS
# ============================================================

def select_news(posted_set):

    articles = fetch_news()

    if not articles:

        return None

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

        article["image"] = image

        logger.info(
            "Selected new news: %s",
            article["title"]
        )

        return article

    logger.info(
        "All GNews results were already posted."
    )

    return None


# ============================================================
# TRAVEL / FOOD TOPICS
# ============================================================

TRAVEL_FOOD_TOPICS = [

    {
        "category": "TRAVEL",
        "title": "Kuala Lumpur",
        "wiki": "Kuala Lumpur",
        "searches": [
            "Kuala Lumpur Malaysia",
            "Kuala Lumpur"
        ]
    },

    {
        "category": "TRAVEL",
        "title": "Penang",
        "wiki": "Penang",
        "searches": [
            "Penang Malaysia",
            "Penang"
        ]
    },

    {
        "category": "TRAVEL",
        "title": "Langkawi",
        "wiki": "Langkawi",
        "searches": [
            "Langkawi Malaysia",
            "Langkawi"
        ]
    },

    {
        "category": "TRAVEL",
        "title": "Melaka",
        "wiki": "Malacca",
        "searches": [
            "Malacca Malaysia",
            "Melaka Malaysia"
        ]
    },

    {
        "category": "TRAVEL",
        "title": "Sabah",
        "wiki": "Sabah",
        "searches": [
            "Sabah Malaysia",
            "Sabah"
        ]
    },

    {
        "category": "TRAVEL",
        "title": "Sarawak",
        "wiki": "Sarawak",
        "searches": [
            "Sarawak Malaysia",
            "Sarawak"
        ]
    },

    {
        "category": "FOOD",
        "title": "Malaysian Cuisine",
        "wiki": "Malaysian cuisine",
        "searches": [
            "Malaysian food",
            "Malaysian cuisine"
        ]
    },

    {
        "category": "FOOD",
        "title": "Nasi Lemak",
        "wiki": "Nasi lemak",
        "searches": [
            "Nasi Lemak Malaysia",
            "Nasi lemak"
        ]
    },

    {
        "category": "FOOD",
        "title": "Penang Cuisine",
        "wiki": "Penang cuisine",
        "searches": [
            "Penang food Malaysia",
            "Penang cuisine"
        ]
    },

    {
        "category": "FOOD",
        "title": "Satay",
        "wiki": "Satay",
        "searches": [
            "Malaysian satay",
            "satay Malaysia"
        ]
    },

    {
        "category": "FOOD",
        "title": "Laksa",
        "wiki": "Laksa",
        "searches": [
            "Malaysian laksa",
            "laksa Malaysia"
        ]
    },

    {
        "category": "FOOD",
        "title": "Roti Canai",
        "wiki": "Roti canai",
        "searches": [
            "Roti canai Malaysia",
            "roti canai"
        ]
    },

]


# ============================================================
# FETCH WIKIVOYAGE / WIKIPEDIA CONTENT
# ============================================================

def fetch_wiki_content(topic_name):

    logger.info(
        "Searching travel content: %s",
        topic_name
    )

    projects = [

        (
            WIKIVOYAGE_API,
            "Wikivoyage"
        ),

        (
            WIKIPEDIA_API,
            "Wikipedia"
        ),

    ]

    for api_url, project_name in projects:

        params = {

            "action":
                "query",

            "prop":
                "extracts",

            "exintro":
                "1",

            "explaintext":
                "1",

            "redirects":
                "1",

            "titles":
                topic_name,

            "format":
                "json",

        }

        try:

            response = requests.get(
                api_url,
                params=params,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT
            )

            if not response.ok:
                continue

            data = response.json()

            pages = (
                data
                .get("query", {})
                .get("pages", {})
            )

            for page in pages.values():

                extract = clean_text(
                    page.get(
                        "extract",
                        ""
                    )
                )

                if len(extract) < 100:
                    continue

                page_title = clean_text(
                    page.get(
                        "title",
                        topic_name
                    )
                )

                return {

                    "source":
                        project_name,

                    "title":
                        page_title,

                    "content":
                        extract[:5000],

                }

        except Exception as e:

            logger.warning(
                "%s content failed: %s",
                project_name,
                e
            )

    return None


# ============================================================
# SEARCH WIKIMEDIA COMMONS IMAGES
# ============================================================

def search_wikimedia_images(
    search_term,
    limit=10
):

    logger.info(
        "Searching Wikimedia Commons image: %s",
        search_term
    )

    params = {

        "action":
            "query",

        "generator":
            "search",

        "gsrsearch":
            search_term,

        "gsrnamespace":
            "6",

        "gsrlimit":
            limit,

        "prop":
            "imageinfo",

        "iiprop":
            "url|mime|size",

        "format":
            "json",

    }

    try:

        response = requests.get(
            WIKIMEDIA_API,
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
        )

        if not response.ok:

            logger.warning(
                "Wikimedia HTTP status = %s",
                response.status_code
            )

            return []

        data = response.json()

        pages = (
            data
            .get("query", {})
            .get("pages", {})
        )

        results = []

        for page in pages.values():

            imageinfo = page.get(
                "imageinfo",
                []
            )

            if not imageinfo:
                continue

            info = imageinfo[0]

            image_url = info.get(
                "url",
                ""
            )

            mime = info.get(
                "mime",
                ""
            )

            width = info.get(
                "width",
                0
            )

            height = info.get(
                "height",
                0
            )

            if not image_url:
                continue

            if not mime.startswith(
                "image/"
            ):
                continue

            if (
                not isinstance(width, int)
                or not isinstance(height, int)
            ):
                continue

            if width < 500 or height < 300:
                continue

            results.append({

                "title":
                    page.get(
                        "title",
                        ""
                    ),

                "url":
                    image_url,

                "mime":
                    mime,

                "width":
                    width,

                "height":
                    height,

            })

        logger.info(
            "Wikimedia found %s usable images.",
            len(results)
        )

        return results

    except Exception as e:

        logger.warning(
            "Wikimedia image search failed: %s",
            e
        )

        return []


# ============================================================
# CHOOSE GOOD IMAGE
# ============================================================

def choose_wikimedia_image(images):

    if not images:
        return None

    landscape = []

    for image in images:

        width = image.get(
            "width",
            0
        )

        height = image.get(
            "height",
            0
        )

        if (
            width >= 800
            and height >= 400
            and width >= height
        ):

            landscape.append(
                image
            )

    if landscape:

        return landscape[0]

    return images[0]


# ============================================================
# FIND TOPIC IMAGE
# ============================================================

def find_topic_image(topic):

    searches = topic.get(
        "searches",
        []
    )

    for search_term in searches:

        images = search_wikimedia_images(
            search_term,
            limit=MAX_WIKI_RESULTS
        )

        selected = choose_wikimedia_image(
            images
        )

        if selected:

            logger.info(
                "Selected image: %s",
                selected["url"]
            )

            return selected["url"]

    return ""


# ============================================================
# FETCH TRAVEL / FOOD
# ============================================================

def fetch_travel_food(
    posted_set,
    state
):

    logger.info(
        "Searching travel / food content..."
    )

    total_topics = len(
        TRAVEL_FOOD_TOPICS
    )

    start_index = (
        int(
            state.get(
                "topic_counter",
                0
            )
        )
        %
        total_topics
    )

    ordered_topics = (

        TRAVEL_FOOD_TOPICS[
            start_index:
        ]

        +

        TRAVEL_FOOD_TOPICS[
            :start_index
        ]

    )

    for topic in ordered_topics:

        wiki = fetch_wiki_content(
            topic["wiki"]
        )

        if not wiki:

            logger.warning(
                "No Wiki content: %s",
                topic["wiki"]
            )

            continue

        image_url = find_topic_image(
            topic
        )

        if not image_url:

            logger.warning(
                "No image found: %s",
                topic["title"]
            )

            continue

        if topic["category"] == "TRAVEL":

            link = (
                "https://en.wikivoyage.org/wiki/"
                +
                topic["wiki"].replace(
                    " ",
                    "_"
                )
            )

        else:

            link = (
                "https://en.wikipedia.org/wiki/"
                +
                topic["wiki"].replace(
                    " ",
                    "_"
                )
            )

        article = {

            "type":
                topic["category"],

            "source":
                wiki["source"],

            "title":
                wiki["title"],

            "description":
                wiki["content"],

            "link":
                link,

            "image":
                image_url,

            "publishedAt":
                datetime.now(
                    timezone.utc
                ).isoformat(),

        }

        aid = article_id(
            article
        )

        if aid in posted_set:

            logger.info(
                "Duplicate travel/food skipped: %s",
                topic["title"]
            )

            continue

        logger.info(
            "Selected %s: %s",
            topic["category"],
            topic["title"]
        )

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

    content_type = article.get(
        "type",
        "NEWS"
    )

    if content_type == "NEWS":

        extra_instruction = """
This is a Malaysia news article.

Rewrite it as a concise news update.
Keep the facts, names, places and numbers accurate.
Do not add information that is not in the source.
"""

    elif content_type == "TRAVEL":

        extra_instruction = """
This is Malaysia travel content.

Make it useful and interesting for Malaysian readers.
Use only information supported by the source.
Do not invent attractions, prices, opening hours or ratings.
"""

    else:

        extra_instruction = """
This is Malaysia food content.

Make it useful and interesting for Malaysian readers.
Describe the food naturally.
Use only information supported by the source.
Do not invent prices, restaurants, ratings or claims.
"""

    prompt = f"""
You are the MYBUZZ Malaysia editor.

Create ONE short bilingual Telegram post.

CONTENT TYPE:
{content_type}

SOURCE:
{source}

TITLE:
{title}

CONTENT:
{description}

{extra_instruction}

IMPORTANT RULES:

1. Chinese must be Simplified Chinese.
2. Malay must be natural Malaysian Malay.
3. Keep both versions concise.
4. Do not invent facts.
5. Do not create fake prices.
6. Do not create fake addresses.
7. Do not create fake opening hours.
8. Do not create fake ratings.
9. Do not create fake statistics.
10. Do not include URLs.
11. Do not use Markdown.
12. Do not use HTML.
13. Do not use emojis.
14. Do not use hashtags.
15. Do not mention AI.
16. Do not mention Wikipedia.
17. For NEWS, preserve the original meaning.
18. For TRAVEL, make the content useful for Malaysian readers.
19. For FOOD, describe the food naturally and factually.
20. Return ONLY valid JSON.

Required JSON:

{{
  "zh_title": "...",
  "zh_body": "...",
  "ms_title": "...",
  "ms_body": "..."
}}
"""

    try:

        response = client.responses.create(
            model=GROQ_MODEL,
            input=prompt
        )

        output = (
            response
            .output_text
            .strip()
        )

        if output.startswith(
            "```"
        ):

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

            "ms_body",

        ]

        for key in required:

            if not data.get(key):

                raise ValueError(
                    f"Missing AI field: {key}"
                )

        return data

    except Exception as e:

        logger.error(
            "Groq AI failed: %s",
            e
        )

        return None


# ============================================================
# TELEGRAM CAPTION
# ============================================================

def build_caption(
    article,
    ai
):

    zh_title = clean_text(
        ai.get(
            "zh_title",
            ""
        )
    )

    zh_body = clean_text(
        ai.get(
            "zh_body",
            ""
        )
    )

    ms_title = clean_text(
        ai.get(
            "ms_title",
            ""
        )
    )

    ms_body = clean_text(
        ai.get(
            "ms_body",
            ""
        )
    )

    link = normalize_url(
        article.get(
            "link",
            ""
        )
    )

    caption = (

        "🇲🇾 MYBuzz NEWS\n\n"

        f"🇨🇳 {zh_title}\n"
        f"{zh_body}\n\n"

        f"🇲🇾 {ms_title}\n"
        f"{ms_body}\n\n"

        f'👉 <a href="{link}">点击阅读完整新闻</a>\n\n'

        f'👉 <a href="{link}">Klik untuk baca berita penuh</a>'

    )

    return caption


# ============================================================
# TELEGRAM SEND PHOTO
# ============================================================

def send_photo(
    image_url,
    caption
):

    if not image_url:

        return False

    telegram_url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    )

    try:

        response = requests.post(

            telegram_url,

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
            "Telegram photo status = %s",
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

    telegram_url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:

        response = requests.post(

            telegram_url,

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
            "Telegram message status = %s",
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
    # Load databases
    # --------------------------------------------------------

    posted = load_posted()

    posted_set = set(
        posted
    )

    state = load_state()

    logger.info(
        "Posted database: %s items",
        len(posted)
    )

    logger.info(
        "Cycle counter: %s",
        state.get(
            "counter",
            0
        )
    )

    # --------------------------------------------------------
    # Determine content mode
    # --------------------------------------------------------

    mode = get_next_mode(
        state
    )

    article = None

    # --------------------------------------------------------
    # NEWS
    # --------------------------------------------------------

    if mode == "NEWS":

        article = select_news(
            posted_set
        )

        if not article:

            logger.warning(
                "No new Malaysia news available."
            )

            return

    # --------------------------------------------------------
    # TRAVEL / FOOD
    # --------------------------------------------------------

    else:

        article = fetch_travel_food(
            posted_set,
            state
        )

        if not article:

            logger.warning(
                "No new travel/food content available."
            )

            return

    # --------------------------------------------------------
    # Selected content
    # --------------------------------------------------------

    logger.info(
        "Selected type: %s",
        article.get(
            "type"
        )
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
    # Generate AI
    # --------------------------------------------------------

    ai = generate_ai_content(
        article
    )

    if not ai:

        logger.error(
            "AI failed. Nothing will be sent."
        )

        return

    logger.info(
        "AI content generated successfully."
    )

    # --------------------------------------------------------
    # Build Telegram
    # --------------------------------------------------------

    caption = build_caption(
        article,
        ai
    )

    # --------------------------------------------------------
    # Send
    # --------------------------------------------------------

    image_url = article.get(
        "image",
        ""
    )

    success = False

    if image_url:

        success = send_photo(
            image_url,
            caption
        )

        if not success:

            logger.warning(
                "Photo failed."
            )

            # NEWS can fall back to text.
            #
            # Travel/Food requires image,
            # so do NOT send without image.

            if article.get(
                "type"
            ) == "NEWS":

                logger.info(
                    "Trying text fallback for NEWS..."
                )

                success = send_message(
                    caption
                )

            else:

                logger.error(
                    "Travel/Food requires an image."
                )

    else:

        if article.get(
            "type"
        ) == "NEWS":

            success = send_message(
                caption
            )

        else:

            logger.error(
                "Travel/Food has no image. "
                "Nothing will be sent."
            )

    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    if success:

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

        # Advance topic counter
        if article.get(
            "type"
        ) in (
            "TRAVEL",
            "FOOD"
        ):

            state["topic_counter"] = (

                int(
                    state.get(
                        "topic_counter",
                        0
                    )
                )
                + 1

            )

        # Advance cycle
        advance_state(
            state
        )

        logger.info(
            "Content successfully sent."
        )

    else:

        logger.error(
            "Content was NOT sent."
        )

        logger.error(
            "Counter will NOT advance."
        )

        logger.error(
            "Article will NOT be marked as posted."
        )

    # --------------------------------------------------------
    # Finish
    # --------------------------------------------------------

    logger.info(
        "======================================"
    )

    logger.info(
        "MYBUZZ BOT FINISHED"
    )

    logger.info(
        "Sent: %s",
        "YES" if success else "NO"
    )

    logger.info(
        "Type: %s",
        article.get(
            "type"
        )
    )

    logger.info(
        "======================================"
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    main()
