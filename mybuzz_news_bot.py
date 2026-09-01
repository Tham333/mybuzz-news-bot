import os
import json
import logging
import hashlib
import re
import html
import time
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
# GitHub Actions
#       ↓
# mybuzz_news_bot.py
#       ↓
# GNews / Wikimedia
#       ↓
# Duplicate Check
#       ↓
# Groq AI
#       ↓
# Apps Script
#       ↓
# Google Sheet NEWS
#       ↓
# PENDING
#       ↓
# Telegram Review
#
# ============================================================


BOT_NAME = "MYBUZZ BOT"


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

APPS_SCRIPT_URL = os.environ.get("APPS_SCRIPT_URL")


# ============================================================
# API CONFIG
# ============================================================

GNEWS_BASE_URL = "https://gnews.io/api/v4"

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

GROQ_MODEL = "openai/gpt-oss-20b"


# ============================================================
# FILE STORAGE
# ============================================================

POSTED_FILE = "posted.json"

STATE_FILE = "bot_state.json"


# ============================================================
# LIMITS
# ============================================================

REQUEST_TIMEOUT = 20

MAX_GNEWS_ARTICLES = 10

MAX_WIKI_RESULTS = 10

MAX_POSTED = 1000


# ============================================================
# MALAYSIA
# ============================================================

COUNTRY = "Malaysia"


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(BOT_NAME)


# ============================================================
# VALIDATE API KEYS
# ============================================================

if not GNEWS_API_KEY:
    raise RuntimeError(
        "GNEWS_API_KEY is missing."
    )


if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY is missing."
    )


if not APPS_SCRIPT_URL:
    raise RuntimeError(
        "APPS_SCRIPT_URL is missing."
    )


# ============================================================
# GROQ CLIENT
# ============================================================

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url=GROQ_BASE_URL,
)


# ============================================================
# COMMON REQUEST HEADERS
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "MYBUZZ-News-Bot/1.0"
    )
}


# ============================================================
# LOAD POSTED
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
            "Could not read %s: %s",
            POSTED_FILE,
            e
        )

    return []


# ============================================================
# SAVE POSTED
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
            "Could not save posted file: %s",
            e
        )


# ============================================================
# LOAD BOT STATE
# ============================================================

def load_state():

    default_state = {
        "counter": 0
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

        if isinstance(data, dict):

            counter = data.get(
                "counter",
                0
            )

            try:
                counter = int(counter)
            except Exception:
                counter = 0

            return {
                "counter": counter
            }

    except Exception as e:

        logger.warning(
            "Could not read state: %s",
            e
        )

    return default_state


# ============================================================
# SAVE BOT STATE
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

def get_next_mode():

    state = load_state()

    counter = state.get(
        "counter",
        0
    )

    # --------------------------------------------------------
    # Pattern:
    #
    # 1 NEWS
    # 2 NEWS
    # 3 TRAVEL
    #
    # 4 NEWS
    # 5 NEWS
    # 6 TRAVEL
    # --------------------------------------------------------

    position = (
        counter % 3
    ) + 1

    if position == 3:

        mode = "TRAVEL"

    else:

        mode = "NEWS"

    logger.info(
        "Current cycle position = %s/3",
        position
    )

    logger.info(
        "Content mode = %s",
        mode
    )

    return mode, state


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

    raw = (
        source +
        "|" +
        title
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

            "type": "NEWS",

            "source": (
                source
                or "GNews"
            ),

            "title": title,

            "description": description,

            "link": url,

            "image": image,

            "publishedAt":
                published_at,

        })

    logger.info(
        "GNews returned %s usable articles.",
        len(results)
    )

    return results


# ============================================================
# WIKIMEDIA API
# ============================================================

WIKIMEDIA_API = (
    "https://commons.wikimedia.org/w/api.php"
)


# ============================================================
# SEARCH WIKIMEDIA IMAGES
# ============================================================

def search_wikimedia_images(
    search_term,
    limit=10
):

    logger.info(
        "Searching Wikimedia Commons: %s",
        search_term
    )

    params = {

        "action": "query",

        "generator": "search",

        "gsrsearch":
            search_term,

        "gsrnamespace": "6",

        "gsrlimit": limit,

        "prop":
            "imageinfo",

        "iiprop":
            "url|mime|size",

        "format": "json",

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
                "Wikimedia HTTP error: %s",
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

            if not image_url:
                continue

            if not mime.startswith(
                "image/"
            ):
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
                    info.get(
                        "width",
                        0
                    ),

                "height":
                    info.get(
                        "height",
                        0
                    ),

            })

        logger.info(
            "Wikimedia found %s images.",
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

def choose_wikimedia_image(
    images
):

    if not images:
        return None

    # Prefer landscape images
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
            isinstance(width, int)
            and isinstance(height, int)
            and width >= 800
            and height >= 400
            and width >= height
        ):

            landscape.append(
                image
            )

    if landscape:

        return landscape[0]

    # Otherwise return first valid image
    return images[0]


# ============================================================
# TRAVEL / FOOD TOPICS
# ============================================================

TRAVEL_TOPICS = [

    {
        "category": "Travel",
        "topic": "Kuala Lumpur Malaysia travel",
        "search": "Kuala Lumpur Malaysia",
        "wiki": "Kuala Lumpur",
    },

    {
        "category": "Travel",
        "topic": "Penang Malaysia travel",
        "search": "Penang Malaysia",
        "wiki": "Penang",
    },

    {
        "category": "Travel",
        "topic": "Langkawi Malaysia travel",
        "search": "Langkawi Malaysia",
        "wiki": "Langkawi",
    },

    {
        "category": "Travel",
        "topic": "Melaka Malaysia travel",
        "search": "Malacca Malaysia",
        "wiki": "Malacca",
    },

    {
        "category": "Travel",
        "topic": "Sabah Malaysia travel",
        "search": "Sabah Malaysia",
        "wiki": "Sabah",
    },

    {
        "category": "Travel",
        "topic": "Sarawak Malaysia travel",
        "search": "Sarawak Malaysia",
        "wiki": "Sarawak",
    },

    {
        "category": "Food",
        "topic": "Malaysian food",
        "search": "Malaysia food",
        "wiki": "Malaysian cuisine",
    },

    {
        "category": "Food",
        "topic": "Nasi Lemak Malaysia",
        "search": "Nasi Lemak Malaysia",
        "wiki": "Nasi lemak",
    },

    {
        "category": "Food",
        "topic": "Penang food",
        "search": "Penang food Malaysia",
        "wiki": "Penang cuisine",
    },

    {
        "category": "Food",
        "topic": "Malacca food",
        "search": "Malacca food Malaysia",
        "wiki": "Malaysian cuisine",
    },

]


# ============================================================
# FETCH WIKIPEDIA / WIKIVOYAGE CONTENT
# ============================================================

def fetch_wiki_content(
    topic
):

    logger.info(
        "Fetching Wiki content: %s",
        topic
    )

    # --------------------------------------------------------
    # Try Wikivoyage first
    # --------------------------------------------------------

    wiki_projects = [

        (
            "https://en.wikivoyage.org/w/api.php",
            "Wikivoyage"
        ),

        (
            "https://en.wikipedia.org/w/api.php",
            "Wikipedia"
        ),

    ]

    for api_url, project_name in wiki_projects:

        params = {

            "action": "query",

            "prop": "extracts",

            "exintro": "1",

            "explaintext": "1",

            "redirects": "1",

            "titles": topic,

            "format": "json",

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
                        topic
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
# FIND TRAVEL / FOOD IMAGE
# ============================================================

def find_topic_image(
    topic
):

    searches = [

        topic["search"],

        topic["wiki"],

        topic["search"] + " Malaysia",

    ]

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
                "Selected Wikimedia image: %s",
                selected["url"]
            )

            return selected["url"]

    return ""


# ============================================================
# FETCH TRAVEL / FOOD
# ============================================================

def fetch_travel_or_food(
    posted_set
):

    logger.info(
        "Searching travel / food content..."
    )

    # --------------------------------------------------------
    # Rotate topics using current time
    # --------------------------------------------------------

    day_number = int(
        datetime.now(
            timezone.utc
        ).strftime("%j")
    )

    start_index = (
        day_number %
        len(TRAVEL_TOPICS)
    )

    ordered_topics = (

        TRAVEL_TOPICS[
            start_index:
        ]
        +
        TRAVEL_TOPICS[
            :start_index
        ]

    )

    for topic in ordered_topics:

        content = fetch_wiki_content(
            topic["wiki"]
        )

        if not content:
            continue

        # ----------------------------------------------------
        # Find image
        # ----------------------------------------------------

        image_url = find_topic_image(
            topic
        )

        if not image_url:

            logger.warning(
                "No image found for %s. Trying next topic.",
                topic["wiki"]
            )

            continue

        # ----------------------------------------------------
        # Build pseudo article
        # ----------------------------------------------------

        link = (
            "https://en.wikivoyage.org/wiki/"
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
                content["source"],

            "title":
                topic["wiki"],

            "description":
                content["content"],

            "link":
                link,

            "image":
                image_url,

            "publishedAt":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "topic":
                topic["topic"],

        }

        aid = article_id(
            article
        )

        if aid in posted_set:

            logger.info(
                "Travel/food article already posted."
            )

            continue

        return article

    return None


# ============================================================
# FIND NEWS IMAGE FROM ARTICLE PAGE
# ============================================================

def find_image_from_page(
    url
):

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
            "Could not find page image: %s",
            e
        )

    return ""


# ============================================================
# SELECT NEWS
# ============================================================

def select_news(
    posted_set
):

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

        # ----------------------------------------------------
        # GNews image
        # ----------------------------------------------------

        image = article.get(
            "image",
            ""
        )

        # ----------------------------------------------------
        # If no image, visit page
        # ----------------------------------------------------

        if not image:

            image = find_image_from_page(
                article["link"]
            )

        article["image"] = image

        return article

    return None


# ============================================================
# GENERATE AI CONTENT
# ============================================================

def generate_ai_content(
    article
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

    prompt = f"""
You are the MYBUZZ Malaysia content editor.

Create a short bilingual Malaysian content post.

CONTENT TYPE:
{content_type}

SOURCE:
{source}

TITLE:
{title}

CONTENT:
{description}

IMPORTANT RULES:

1. Do NOT invent facts.
2. Do NOT create fake prices, addresses, opening hours, ratings or claims.
3. Keep factual information accurate.
4. Chinese must be Simplified Chinese.
5. Malay must be natural Malaysian Malay.
6. The Chinese version should be concise.
7. The Malay version should be concise.
8. Do not include URLs.
9. Do not use Markdown.
10. Do not use HTML.
11. Do not add hashtags.
12. Do not mention AI.
13. Do not write "according to Wikipedia" unless necessary.
14. For travel content, make it useful for Malaysian readers.
15. For food content, describe the food naturally and factually.
16. For news, do not change the meaning of the original report.
17. Return ONLY valid JSON.

Required JSON:

{{
  "zh_title": "...",
  "zh_body": "...",
  "ms_title": "...",
  "ms_body": "...",
  "category": "..."
}}
"""

    try:

        response = client.responses.create(

            model=GROQ_MODEL,

            input=prompt,

        )

        output = (
            response
            .output_text
            .strip()
        )

        # ----------------------------------------------------
        # Remove code fences
        # ----------------------------------------------------

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

            "category",

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
# SEND TO APPS SCRIPT
# ============================================================

def send_to_apps_script(
    article,
    ai
):

    payload = {

        "action":
            "collect",

        "source":
            article.get(
                "source",
                ""
            ),

        "originalTitle":
            article.get(
                "title",
                ""
            ),

        "description":
            article.get(
                "description",
                ""
            ),

        "url":
            article.get(
                "link",
                ""
            ),

        "guid":
            article_id(
                article
            ),

        "publishedAt":
            article.get(
                "publishedAt",
                ""
            ),

        "image":
            article.get(
                "image",
                ""
            ),

        "type":
            article.get(
                "type",
                "NEWS"
            ),

        "category":
            ai.get(
                "category",
                article.get(
                    "type",
                    "NEWS"
                )
            ),

        "zhTitle":
            ai.get(
                "zh_title",
                ""
            ),

        "zhBody":
            ai.get(
                "zh_body",
                ""
            ),

        "msTitle":
            ai.get(
                "ms_title",
                ""
            ),

        "msBody":
            ai.get(
                "ms_body",
                ""
            ),

    }

    logger.info(
        "Sending content to Apps Script..."
    )

    try:

        response = requests.post(

            APPS_SCRIPT_URL,

            json=payload,

            headers={
                "Content-Type":
                    "application/json",
                "User-Agent":
                    "MYBUZZ-News-Bot/1.0"
            },

            timeout=REQUEST_TIMEOUT

        )

        logger.info(
            "Apps Script HTTP status = %s",
            response.status_code
        )

        logger.info(
            "Apps Script response = %s",
            response.text[:2000]
        )

        if not response.ok:

            return False

        try:

            result = response.json()

        except Exception:

            result = {}

        if result.get(
            "ok"
        ):

            if result.get(
                "duplicate"
            ):

                logger.warning(
                    "Apps Script reported duplicate."
                )

                return False

            return True

        logger.error(
            "Apps Script returned failure: %s",
            result
        )

        return False

    except Exception as e:

        logger.error(
            "Apps Script request failed: %s",
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
    # Load posted
    # --------------------------------------------------------

    posted = load_posted()

    posted_set = set(
        posted
    )

    logger.info(
        "Posted database contains %s items.",
        len(posted)
    )

    # --------------------------------------------------------
    # Determine mode
    # --------------------------------------------------------

    mode, state = get_next_mode()

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

        article = fetch_travel_or_food(
            posted_set
        )

        if not article:

            logger.warning(
                "No new travel/food content available."
            )

            return

    # --------------------------------------------------------
    # Log selected
    # --------------------------------------------------------

    logger.info(
        "Selected type = %s",
        article.get(
            "type"
        )
    )

    logger.info(
        "Selected title = %s",
        article.get(
            "title"
        )
    )

    logger.info(
        "Selected source = %s",
        article.get(
            "source"
        )
    )

    logger.info(
        "Selected image = %s",
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
            "AI failed. Nothing will be sent."
        )

        return

    logger.info(
        "AI content generated successfully."
    )

    logger.info(
        "ZH TITLE: %s",
        ai["zh_title"]
    )

    logger.info(
        "MS TITLE: %s",
        ai["ms_title"]
    )

    # --------------------------------------------------------
    # Send to Apps Script
    # --------------------------------------------------------

    success = send_to_apps_script(
        article,
        ai
    )

    if not success:

        logger.error(
            "Content was NOT accepted by Apps Script."
        )

        return

    # --------------------------------------------------------
    # Only mark as posted after Apps Script success
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
    # Advance cycle ONLY after success
    # --------------------------------------------------------

    advance_counter(
        state
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
        "Type sent: %s",
        article.get(
            "type"
        )
    )

    logger.info(
        "Next cycle position will continue automatically."
    )

    logger.info(
        "======================================"
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    main()
