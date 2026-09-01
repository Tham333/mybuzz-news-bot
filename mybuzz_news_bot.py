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
# CYCLE:
#
# 1 = NEWS
# 2 = NEWS
# 3 = TRAVEL / FOOD
#
# 4 = NEWS
# 5 = NEWS
# 6 = TRAVEL / FOOD
#
# Then repeat.
#
# NEWS:
# GNews
#
# TRAVEL / FOOD:
# Wikivoyage / Wikipedia
# +
# Wikimedia Commons image
#
# AI:
# Groq
#
# OUTPUT:
# One content per run
#
# ============================================================


BOT_NAME = "MYBUZZ BOT"


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")


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

MAX_GNEWS_ARTICLES = 10

MAX_WIKIMEDIA_RESULTS = 20

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
# API VALIDATION
# ============================================================

logger.info("Checking API configuration...")

if not GNEWS_API_KEY:
    raise RuntimeError("GNEWS_API_KEY is missing.")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is missing.")

logger.info("API configuration OK.")


# ============================================================
# GROQ CLIENT
# ============================================================

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url=GROQ_BASE_URL
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
            return data.get("posted", [])

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

            try:
                counter = int(
                    data.get(
                        "counter",
                        0
                    )
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
# GET CONTENT MODE
# ============================================================

def get_next_mode():

    state = load_state()

    counter = int(
        state.get(
            "counter",
            0
        )
    )

    position = (
        counter % 3
    ) + 1

    if position == 3:
        mode = "TRAVEL"
    else:
        mode = "NEWS"

    logger.info(
        "Cycle counter: %s",
        counter
    )

    logger.info(
        "Cycle position: %s/3",
        position
    )

    logger.info(
        "Content mode: %s",
        mode
    )

    return mode, state


# ============================================================
# ADVANCE CYCLE
# ============================================================

def advance_counter(state):

    current = int(
        state.get(
            "counter",
            0
        )
    )

    state["counter"] = (
        current + 1
    )

    save_state(state)

    logger.info(
        "Cycle advanced to counter: %s",
        state["counter"]
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
# HASH ID
# ============================================================

def make_hash(value):

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


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
        return make_hash(link)

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

    return make_hash(
        source + "|" + title
    )


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
# FETCH NEWS
# ============================================================

def fetch_news():

    logger.info(
        "Fetching Malaysia news from GNews..."
    )

    queries = [

        "Malaysia",

        "Malaysia politics",

        "Malaysia economy",

        "Malaysia business",

        "Malaysia technology",

        "Malaysia lifestyle",

        "Malaysia tourism",

        "Malaysia society",

    ]

    all_articles = []

    seen_urls = set()

    for query in queries:

        params = {

            "q": query,

            "lang": "en",

            "country": "my",

            "max": MAX_GNEWS_ARTICLES,

        }

        articles = gnews_request(
            params
        )

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

            if url in seen_urls:
                continue

            seen_urls.add(url)

            all_articles.append({

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
        "Total unique GNews articles collected: %s",
        len(all_articles)
    )

    return all_articles


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
            "News image extraction failed: %s",
            e
        )

    return ""


# ============================================================
# SELECT NEWS
# ============================================================

def select_news(posted_set):

    articles = fetch_news()

    if not articles:

        logger.warning(
            "No GNews articles returned."
        )

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

            image = find_image_from_page(
                article["link"]
            )

        article["image"] = image

        logger.info(
            "NEW NEWS FOUND: %s",
            article["title"]
        )

        return article

    logger.info(
        "All current GNews results were already posted."
    )

    return None


# ============================================================
# TRAVEL / FOOD TOPICS
# ============================================================

TRAVEL_TOPICS = [

    {
        "category": "Travel",
        "title": "Kuala Lumpur",
        "wiki": "Kuala Lumpur",
        "search": "Kuala Lumpur Malaysia"
    },

    {
        "category": "Travel",
        "title": "Penang",
        "wiki": "Penang",
        "search": "Penang Malaysia"
    },

    {
        "category": "Travel",
        "title": "Langkawi",
        "wiki": "Langkawi",
        "search": "Langkawi Malaysia"
    },

    {
        "category": "Travel",
        "title": "Malacca",
        "wiki": "Malacca",
        "search": "Malacca Malaysia"
    },

    {
        "category": "Travel",
        "title": "Sabah",
        "wiki": "Sabah",
        "search": "Sabah Malaysia"
    },

    {
        "category": "Travel",
        "title": "Sarawak",
        "wiki": "Sarawak",
        "search": "Sarawak Malaysia"
    },

    {
        "category": "Travel",
        "title": "Ipoh",
        "wiki": "Ipoh",
        "search": "Ipoh Malaysia"
    },

    {
        "category": "Travel",
        "title": "Johor Bahru",
        "wiki": "Johor Bahru",
        "search": "Johor Bahru Malaysia"
    },

    {
        "category": "Food",
        "title": "Malaysian Cuisine",
        "wiki": "Malaysian cuisine",
        "search": "Malaysian cuisine food"
    },

    {
        "category": "Food",
        "title": "Nasi Lemak",
        "wiki": "Nasi lemak",
        "search": "Nasi Lemak Malaysia"
    },

    {
        "category": "Food",
        "title": "Penang Cuisine",
        "wiki": "Penang cuisine",
        "search": "Penang food Malaysia"
    },

    {
        "category": "Food",
        "title": "Satay",
        "wiki": "Satay",
        "search": "Satay Malaysia"
    },

    {
        "category": "Food",
        "title": "Laksa",
        "wiki": "Laksa",
        "search": "Laksa Malaysia"
    },

    {
        "category": "Food",
        "title": "Roti Canai",
        "wiki": "Roti canai",
        "search": "Roti Canai Malaysia"
    },

    {
        "category": "Food",
        "title": "Char Kway Teow",
        "wiki": "Char kway teow",
        "search": "Char Kway Teow Malaysia"
    },

]


# ============================================================
# FETCH WIKI CONTENT
# ============================================================

def fetch_wiki_content(topic):

    logger.info(
        "Searching Wikivoyage/Wikipedia: %s",
        topic
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

                logger.warning(
                    "%s HTTP status: %s",
                    project_name,
                    response.status_code
                )

                continue

            data = response.json()

            pages = (
                data
                .get(
                    "query",
                    {}
                )
                .get(
                    "pages",
                    {}
                )
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

                logger.info(
                    "Wiki content found from %s",
                    project_name
                )

                return {

                    "source":
                        project_name,

                    "title":
                        page_title,

                    "content":
                        extract[:6000],

                }

        except Exception as e:

            logger.warning(
                "%s request failed: %s",
                project_name,
                e
            )

    return None


# ============================================================
# SEARCH WIKIMEDIA IMAGES
# ============================================================

def search_wikimedia_images(
    search_term,
    limit=20
):

    logger.info(
        "Searching Wikimedia Commons image: %s",
        search_term
    )

    params = {

        "action": "query",

        "generator": "search",

        "gsrsearch":
            search_term,

        "gsrnamespace": "6",

        "gsrlimit": limit,

        "prop": "imageinfo",

        "iiprop": "url|mime|size",

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
                "Wikimedia HTTP status: %s",
                response.status_code
            )

            return []

        data = response.json()

        pages = (
            data
            .get(
                "query",
                {}
            )
            .get(
                "pages",
                {}
            )
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

            image_url = normalize_url(
                info.get(
                    "url",
                    ""
                )
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

            try:
                width = int(width)
                height = int(height)
            except Exception:
                continue

            if width < 600 or height < 300:
                continue

            if width < height:
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
            "Wikimedia usable images: %s",
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
# FIND TOPIC IMAGE
# ============================================================

def find_topic_image(topic):

    searches = [

        topic["search"],

        topic["title"],

        topic["wiki"],

    ]

    for search_term in searches:

        images = search_wikimedia_images(
            search_term,
            limit=MAX_WIKIMEDIA_RESULTS
        )

        if images:

            selected = images[0]

            logger.info(
                "Selected Wikimedia image: %s",
                selected["url"]
            )

            return selected["url"]

    return ""


# ============================================================
# TRAVEL / FOOD ARTICLE
# ============================================================

def fetch_travel_or_food(
    posted_set
):

    logger.info(
        "Searching Travel / Food content..."
    )

    state = load_state()

    counter = int(
        state.get(
            "counter",
            0
        )
    )

    start_index = (
        counter //
        3
    ) % len(TRAVEL_TOPICS)

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

        logger.info(
            "Trying topic: %s",
            topic["title"]
        )

        content = fetch_wiki_content(
            topic["wiki"]
        )

        if not content:

            logger.warning(
                "No Wiki content for %s",
                topic["title"]
            )

            continue

        image_url = find_topic_image(
            topic
        )

        if not image_url:

            logger.warning(
                "No image for %s. Trying next topic.",
                topic["title"]
            )

            continue

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
                content["title"],

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
                topic["title"],

        }

        aid = article_id(
            article
        )

        if aid in posted_set:

            logger.info(
                "Duplicate Travel/Food topic skipped: %s",
                topic["title"]
            )

            continue

        logger.info(
            "NEW TRAVEL/FOOD FOUND: %s",
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

    link = article.get(
        "link",
        ""
    )

    prompt = f"""
You are the MYBUZZ Malaysia content editor.

Create ONE short bilingual Malaysian content post.

CONTENT TYPE:
{content_type}

SOURCE:
{source}

TITLE:
{title}

CONTENT:
{description}

SOURCE LINK:
{link}

IMPORTANT RULES:

1. Do NOT invent facts.
2. Do NOT invent prices.
3. Do NOT invent addresses.
4. Do NOT invent opening hours.
5. Do NOT invent ratings.
6. Do NOT invent statistics.
7. Do NOT create fake information.
8. Chinese must be Simplified Chinese.
9. Malay must be natural Malaysian Malay.
10. Keep both versions concise.
11. Do not include URLs inside the title or body.
12. Do not use Markdown.
13. Do not use HTML.
14. Do not use hashtags.
15. Do not mention AI.
16. Do not mention Wikipedia unless necessary.
17. News must keep the original meaning.
18. Travel content should be useful to Malaysian readers.
19. Food content should naturally describe the food.
20. Return ONLY valid JSON.

JSON FORMAT:

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
# BUILD FINAL TELEGRAM MESSAGE
# ============================================================

def build_message(
    article,
    ai
):

    link = article.get(
        "link",
        ""
    )

    message = (

        "🇲🇾 MYBuzz NEWS\n\n"

        "🇨🇳 "
        + ai["zh_title"]
        + "\n"

        + ai["zh_body"]
        + "\n\n"

        "🇲🇾 "
        + ai["ms_title"]
        + "\n"

        + ai["ms_body"]
        + "\n\n"

        "👉 点击阅读完整新闻\n"
        + link
        + "\n\n"

        "👉 Klik untuk baca berita penuh\n"
        + link

    )

    return message


# ============================================================
# OUTPUT
# ============================================================

def output_content(
    article,
    ai
):

    message = build_message(
        article,
        ai
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

    logger.info(
        "======================================"
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

    posted = load_posted()

    posted_set = set(
        posted
    )

    logger.info(
        "Posted database: %s items",
        len(posted)
    )

    mode, state = get_next_mode()

    article = None

    # ========================================================
    # NEWS
    # ========================================================

    if mode == "NEWS":

        article = select_news(
            posted_set
        )

        if not article:

            logger.warning(
                "No new NEWS available."
            )

            # IMPORTANT:
            # Even if current NEWS source has
            # no new article, advance cycle.
            advance_counter(
                state
            )

            logger.info(
                "No content sent, but cycle advanced."
            )

            return

    # ========================================================
    # TRAVEL / FOOD
    # ========================================================

    else:

        article = fetch_travel_or_food(
            posted_set
        )

        if not article:

            logger.warning(
                "No new Travel/Food content available."
            )

            advance_counter(
                state
            )

            logger.info(
                "No content sent, but cycle advanced."
            )

            return

    # ========================================================
    # LOG ARTICLE
    # ========================================================

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

    # ========================================================
    # AI
    # ========================================================

    ai = generate_ai_content(
        article
    )

    if not ai:

        logger.error(
            "AI generation failed."
        )

        # Advance cycle so it does not
        # get stuck forever on same mode.
        advance_counter(
            state
        )

        return

    # ========================================================
    # OUTPUT
    # ========================================================

    output_content(
        article,
        ai
    )

    # ========================================================
    # SAVE DUPLICATE
    # ========================================================

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

        logger.info(
            "Added article to duplicate history."
        )

    # ========================================================
    # ADVANCE CYCLE
    # ========================================================

    advance_counter(
        state
    )

    # ========================================================
    # FINISH
    # ========================================================

    logger.info(
        "MYBUZZ BOT FINISHED"
    )

    logger.info(
        "Type processed: %s",
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
