import os
import json
import logging
import hashlib
import re
from datetime import datetime, timezone

import requests
from openai import OpenAI


# ============================================================
# MYBUZZ NEWS BOT V7
# GNEWS + WIKIVOYAGE
# ============================================================

BOT_NAME = "MYBUZZ V7"

GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Apps Script Web App
APPS_SCRIPT_URL = os.environ.get("APPS_SCRIPT_URL")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-20b"

POSTER_FILE = "poster.json"

MAX_ARTICLES = 1
REQUEST_TIMEOUT = 20

WIKIVOYAGE_API_URL = (
    "https://en.wikivoyage.org/w/api.php"
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
# VALIDATE ENVIRONMENT
# ============================================================

if not GNEWS_API_KEY:
    logger.warning(
        "GNEWS_API_KEY is missing. "
        "GNews will be skipped."
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
# POSTED STORAGE
# ============================================================

def load_posted():

    if not os.path.exists(POSTER_FILE):
        return []

    try:

        with open(
            POSTER_FILE,
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
            "Could not read poster.json: %s",
            e
        )

    return []


def save_posted(posted):

    try:

        with open(
            POSTER_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                posted[-1000:],
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        logger.error(
            "Could not save poster.json: %s",
            e
        )


# ============================================================
# ARTICLE ID
# ============================================================

def article_id(article):

    url = (
        article.get("link")
        or article.get("url")
        or ""
    ).strip()

    title = (
        article.get("title")
        or ""
    ).strip()

    source = (
        article.get("source")
        or ""
    ).strip()

    raw = (
        url
        if url
        else source + "|" + title
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


# ============================================================
# CLEAN TEXT
# ============================================================

def clean_text(text):

    from html import unescape

    if not text:
        return ""

    text = unescape(str(text))

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
# GNEWS
# ============================================================

def fetch_gnews():

    if not GNEWS_API_KEY:
        return []

    logger.info(
        "Fetching GNews Malaysia..."
    )

    url = (
        "https://gnews.io/api/v4/search"
    )

    params = {

        "q": (
            "Malaysia OR Malaysian"
        ),

        "lang": "en",

        "country": "my",

        "max": 10,

        "sortby": "publishedAt",

        "apikey": GNEWS_API_KEY

    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        articles = []

        for item in data.get(
            "articles",
            []
        ):

            title = clean_text(
                item.get("title")
            )

            description = clean_text(
                item.get("description")
            )

            article_url = (
                item.get("url")
                or ""
            ).strip()

            image = (
                item.get("image")
                or ""
            ).strip()

            source_name = (
                item.get("source", {})
                .get("name")
                or "GNews"
            )

            published_at = (
                item.get("publishedAt")
                or ""
            )

            if not title or not article_url:
                continue

            articles.append({

                "type": "news",

                "source": source_name,

                "title": title,

                "summary": description,

                "link": article_url,

                "image": image,

                "publishedAt": published_at

            })

        logger.info(
            "GNews returned %s articles.",
            len(articles)
        )

        return articles

    except Exception as e:

        logger.error(
            "GNews failed: %s",
            e
        )

        return []


# ============================================================
# WIKIVOYAGE SEARCH
# ============================================================

def wikivoyage_search(query):

    logger.info(
        "Wikivoyage search: %s",
        query
    )

    params = {

        "action": "query",

        "list": "search",

        "srsearch": query,

        "srnamespace": 0,

        "srlimit": 10,

        "format": "json"

    }

    headers = {

        "User-Agent":
            "MYBUZZ-News-Bot/7.0 "
            "(contact: mybuzz)"

    }

    try:

        response = requests.get(
            WIKIVOYAGE_API_URL,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        results = data.get(
            "query",
            {}
        ).get(
            "search",
            []
        )

        return results

    except Exception as e:

        logger.error(
            "Wikivoyage search failed: %s",
            e
        )

        return []


# ============================================================
# GET WIKIVOYAGE PAGE
# ============================================================

def get_wikivoyage_page(title):

    params = {

        "action": "query",

        "prop": (
            "extracts|info"
        ),

        "explaintext": 1,

        "exsectionformat": "plain",

        "inprop": "url",

        "titles": title,

        "format": "json"

    }

    headers = {

        "User-Agent":
            "MYBUZZ-News-Bot/7.0 "
            "(contact: mybuzz)"

    }

    try:

        response = requests.get(
            WIKIVOYAGE_API_URL,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        pages = (
            data.get("query", {})
            .get("pages", {})
        )

        for page in pages.values():

            extract = clean_text(
                page.get("extract")
            )

            full_url = (
                page.get("fullurl")
                or ""
            )

            return {

                "title":
                    page.get("title")
                    or title,

                "extract":
                    extract,

                "url":
                    full_url

            }

    except Exception as e:

        logger.error(
            "Wikivoyage page failed: %s",
            e
        )

    return None


# ============================================================
# WIKIVOYAGE FOOD
# ============================================================

def fetch_wikivoyage_food():

    queries = [

        "Malaysian cuisine",

        "Malaysia food",

        "Kuala Lumpur food",

        "Penang food",

        "Malacca food",

        "Johor food",

        "Sabah food",

        "Sarawak food"

    ]

    articles = []

    for query in queries:

        results = wikivoyage_search(
            query
        )

        for result in results:

            title = (
                result.get("title")
                or ""
            ).strip()

            if not title:
                continue

            page = get_wikivoyage_page(
                title
            )

            if not page:
                continue

            extract = page.get(
                "extract",
                ""
            )

            if not extract:
                continue

            articles.append({

                "type": "food",

                "source":
                    "Wikivoyage",

                "title":
                    page.get(
                        "title",
                        title
                    ),

                "summary":
                    extract[:6000],

                "link":
                    page.get(
                        "url",
                        ""
                    ),

                "image":
                    "",

                "publishedAt":
                    ""

            })

            # Only collect a few candidates
            if len(articles) >= 10:
                return articles

    return articles


# ============================================================
# REMOVE DUPLICATES
# ============================================================

def remove_duplicates(
    articles,
    posted_set
):

    result = []

    local_ids = set()

    for article in articles:

        aid = article_id(
            article
        )

        if aid in posted_set:
            continue

        if aid in local_ids:
            continue

        local_ids.add(aid)

        result.append(
            article
        )

    return result


# ============================================================
# GROQ AI
# ============================================================

def generate_translation(article):

    title = clean_text(
        article.get("title")
    )

    summary = clean_text(
        article.get("summary")
    )

    source = clean_text(
        article.get("source")
    )

    content_type = (
        article.get("type")
        or "news"
    )

    if content_type == "food":

        instruction = """
This is Malaysian food/travel content.

Rewrite it into an interesting,
short MYBUZZ food/travel post.

Focus on:
- food
- location
- local culture
- useful travel information

Do not invent prices, opening hours,
ratings or facts.
"""

    else:

        instruction = """
This is Malaysian news.

Rewrite it into a short,
factual MYBUZZ news post.

Do not invent facts.
"""

    prompt = f"""
You are the editor of MYBUZZ Malaysia.

{instruction}

Create BOTH:
1. Simplified Chinese
2. Natural Malaysian Malay

Chinese should be concise and natural.

Malay should sound natural for Malaysian readers.

Do not use Markdown.

Do not use emojis.

Do not include URLs.

Do not add "Chinese", "Malay",
"Title", "Body" headings.

Return ONLY valid JSON.

Required JSON:

{{
  "zh_title": "...",
  "zh_body": "...",
  "ms_title": "...",
  "ms_body": "..."
}}

SOURCE:
{source}

TITLE:
{title}

CONTENT:
{summary}
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

        if output.startswith(
            "```"
        ):

            output = re.sub(
                r"^```(?:json)?",
                "",
                output,
                flags=re.I
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
            "Groq failed: %s",
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

        "action": "collect",

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
            json.dumps(
                {
                    "zh_title":
                        ai["zh_title"],

                    "zh_body":
                        ai["zh_body"],

                    "ms_title":
                        ai["ms_title"],

                    "ms_body":
                        ai["ms_body"]
                },
                ensure_ascii=False
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

        "category":
            (
                "Food"
                if article.get(
                    "type"
                ) == "food"
                else "News"
            )

    }

    try:

        response = requests.post(
            APPS_SCRIPT_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        result = response.json()

        logger.info(
            "Apps Script response: %s",
            result
        )

        return (
            result.get("ok")
            is True
        )

    except Exception as e:

        logger.error(
            "Apps Script failed: %s",
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
        "MYBUZZ V7 START"
    )

    logger.info(
        "======================================"
    )

    posted = load_posted()

    posted_set = set(
        posted
    )

    # ========================================================
    # STEP 1
    # GNEWS
    # ========================================================

    logger.info(
        "STEP 1: GNews"
    )

    gnews_articles = fetch_gnews()

    gnews_new = remove_duplicates(
        gnews_articles,
        posted_set
    )

    logger.info(
        "New GNews articles: %s",
        len(gnews_new)
    )

    selected = None

    # ========================================================
    # PRIORITY 1: NEWS
    # ========================================================

    if gnews_new:

        selected = gnews_new[0]

        logger.info(
            "Selected GNews article: %s",
            selected["title"]
        )

    # ========================================================
    # PRIORITY 2: WIKIVOYAGE FOOD
    # ========================================================

    if not selected:

        logger.info(
            "No new GNews."
        )

        logger.info(
            "STEP 2: Wikivoyage Food"
        )

        food_articles = (
            fetch_wikivoyage_food()
        )

        food_new = remove_duplicates(
            food_articles,
            posted_set
        )

        logger.info(
            "New Wikivoyage articles: %s",
            len(food_new)
        )

        if food_new:

            selected = food_new[0]

            logger.info(
                "Selected food article: %s",
                selected["title"]
            )

    # ========================================================
    # NOTHING FOUND
    # ========================================================

    if not selected:

        logger.info(
            "No new content found."
        )

        logger.info(
            "MYBUZZ V7 FINISHED | Sent: 0"
        )

        return

    # ========================================================
    # AI
    # ========================================================

    ai = generate_translation(
        selected
    )

    if not ai:

        logger.error(
            "AI generation failed."
        )

        return

    # ========================================================
    # SEND TO APPS SCRIPT
    # ========================================================

    success = send_to_apps_script(
        selected,
        ai
    )

    # ========================================================
    # SAVE DUPLICATE ID
    # ========================================================

    if success:

        aid = article_id(
            selected
        )

        posted.append(
            aid
        )

        save_posted(
            posted
        )

        logger.info(
            "Content successfully sent "
            "to Apps Script."
        )

        logger.info(
            "Content marked as processed."
        )

    else:

        logger.error(
            "Apps Script failed."
        )

        logger.error(
            "Content will NOT be marked "
            "as processed."
        )

    logger.info(
        "======================================"
    )

    logger.info(
        "MYBUZZ V7 FINISHED"
    )

    logger.info(
        "======================================"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
