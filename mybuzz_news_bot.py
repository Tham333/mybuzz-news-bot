import os
import json
import logging
import hashlib
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import requests
from openai import OpenAI


# ============================================================
# MYBUZZ NEWS BOT V7
# ============================================================
#
# GNews
#    ↓
# Topic Rotation
#    ↓
# Duplicate Check
#    ↓
# Groq AI
#    ↓
# Image
#    ↓
# Telegram
#
# 每次运行最多发送 1 条
#
# TOPICS:
# Malaysia
# Travel
# Food
# Technology
# Business
# Sports
# Entertainment
#
# ============================================================


BOT_NAME = "MYBUZZ V7"


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# ============================================================
# GROQ
# ============================================================

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-20b"


# ============================================================
# FILES
# ============================================================

POSTER_FILE = "poster.json"
STATE_FILE = "mybuzz_state.json"
LOCK_DIR = "mybuzz_bot.lock"


# ============================================================
# SETTINGS
# ============================================================

MAX_ARTICLES = 1
GNEWS_MAX_RESULTS = 10

REQUEST_TIMEOUT = 20

# 已发布记录最多保留多少条
MAX_POSTED_RECORDS = 1000

# 旧新闻多少小时后仍然允许抓取
MAX_ARTICLE_AGE_HOURS = 48

# Lock 最长有效时间
LOCK_TIMEOUT_MINUTES = 15


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
# OPENAI CLIENT -> GROQ
# ============================================================

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url=GROQ_BASE_URL,
)


# ============================================================
# TOPICS
# ============================================================
#
# 每次运行优先使用一个 topic。
#
# 如果该 topic 没有新的新闻，
# 自动尝试下一个 topic。
#
# 最终每次最多发送 1 条。
#
# ============================================================

TOPICS = [

    {
        "name": "Malaysia",
        "query": (
            "Malaysia OR "
            "\"Kuala Lumpur\" OR "
            "Selangor OR "
            "Penang OR "
            "Johor OR "
            "Sabah OR "
            "Sarawak"
        )
    },

    {
        "name": "Travel",
        "query": (
            "Malaysia AND "
            "(travel OR tourism OR holiday OR "
            "destination OR hotel OR resort OR "
            "airport OR flight)"
        )
    },

    {
        "name": "Food",
        "query": (
            "Malaysia AND "
            "(food OR restaurant OR cafe OR "
            "cuisine OR dining OR "
            "foodie OR chef)"
        )
    },

    {
        "name": "Technology",
        "query": (
            "Malaysia AND "
            "(technology OR tech OR AI OR "
            "artificial intelligence OR startup OR "
            "smartphone OR software)"
        )
    },

    {
        "name": "Business",
        "query": (
            "Malaysia AND "
            "(business OR economy OR company OR "
            "investment OR finance OR market OR "
            "ringgit)"
        )
    },

    {
        "name": "Sports",
        "query": (
            "Malaysia AND "
            "(sports OR football OR badminton OR "
            "tennis OR motorsport OR athlete)"
        )
    },

    {
        "name": "Entertainment",
        "query": (
            "Malaysia AND "
            "(entertainment OR celebrity OR "
            "actor OR actress OR singer OR "
            "concert OR movie)"
        )
    },

]


# ============================================================
# LOAD STATE
# ============================================================

def load_state():

    default_state = {
        "topic_index": 0,
        "last_run": "",
        "last_topic": "",
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

        return {
            "topic_index": int(
                data.get(
                    "topic_index",
                    0
                )
            ),
            "last_run": str(
                data.get(
                    "last_run",
                    ""
                )
            ),
            "last_topic": str(
                data.get(
                    "last_topic",
                    ""
                )
            ),
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

        temp_file = (
            STATE_FILE +
            ".tmp"
        )

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                state,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(
            temp_file,
            STATE_FILE
        )

    except Exception as e:

        logger.error(
            "Could not save state: %s",
            e
        )


# ============================================================
# LOCK
# ============================================================

def acquire_lock():

    try:

        os.mkdir(
            LOCK_DIR
        )

        with open(
            os.path.join(
                LOCK_DIR,
                "lock.json"
            ),
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                {
                    "created_at":
                        datetime.now(
                            timezone.utc
                        ).isoformat()
                },
                f
            )

        logger.info(
            "Lock acquired."
        )

        return True

    except FileExistsError:

        lock_file = os.path.join(
            LOCK_DIR,
            "lock.json"
        )

        try:

            mtime = os.path.getmtime(
                lock_file
            )

            age_minutes = (
                time.time() -
                mtime
            ) / 60

            if (
                age_minutes >
                LOCK_TIMEOUT_MINUTES
            ):

                logger.warning(
                    "Stale lock detected. Removing."
                )

                release_lock()

                return acquire_lock()

        except Exception:
            pass

        logger.warning(
            "Another MYBUZZ process is already running."
        )

        return False

    except Exception as e:

        logger.error(
            "Could not acquire lock: %s",
            e
        )

        return False


# ============================================================
# RELEASE LOCK
# ============================================================

def release_lock():

    try:

        if os.path.exists(
            LOCK_DIR
        ):

            lock_file = os.path.join(
                LOCK_DIR,
                "lock.json"
            )

            if os.path.exists(
                lock_file
            ):
                os.remove(
                    lock_file
                )

            os.rmdir(
                LOCK_DIR
            )

        logger.info(
            "Lock released."
        )

    except Exception as e:

        logger.warning(
            "Could not release lock: %s",
            e
        )


# ============================================================
# LOAD POSTED
# ============================================================

def load_posted():

    if not os.path.exists(
        POSTER_FILE
    ):
        return {}


    try:

        with open(
            POSTER_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)


        # ----------------------------------------------------
        # NEW FORMAT
        # ----------------------------------------------------

        if isinstance(
            data,
            dict
        ):

            posted = data.get(
                "posted",
                {}
            )

            if isinstance(
                posted,
                dict
            ):

                return posted


        # ----------------------------------------------------
        # OLD FORMAT
        # ----------------------------------------------------
        #
        # 兼容你以前：
        #
        # [
        #   "hash1",
        #   "hash2"
        # ]
        #
        # ----------------------------------------------------

        if isinstance(
            data,
            list
        ):

            converted = {}

            for item in data:

                key = str(
                    item
                ).strip()

                if key:

                    converted[key] = {
                        "title": "",
                        "source": "",
                        "topic": "",
                        "posted_at": ""
                    }

            return converted


    except Exception as e:

        logger.warning(
            "Could not read poster.json: %s",
            e
        )


    return {}


# ============================================================
# SAVE POSTED
# ============================================================

def save_posted(posted):

    try:

        # ----------------------------------------------------
        # Keep newest records only
        # ----------------------------------------------------

        if len(posted) > MAX_POSTED_RECORDS:

            items = list(
                posted.items()
            )

            items = items[
                -MAX_POSTED_RECORDS:
            ]

            posted = dict(
                items
            )


        temp_file = (
            POSTER_FILE +
            ".tmp"
        )


        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                {
                    "posted": posted
                },
                f,
                ensure_ascii=False,
                indent=2
            )


        os.replace(
            temp_file,
            POSTER_FILE
        )


    except Exception as e:

        logger.error(
            "Could not save poster.json: %s",
            e
        )


# ============================================================
# NORMALIZE URL
# ============================================================

def normalize_url(url):

    if not url:
        return ""

    try:

        url = url.strip()

        parts = urlsplit(
            url
        )

        query = parts.query

        # ----------------------------------------------------
        # Remove tracking parameters
        # ----------------------------------------------------

        if query:

            filtered = []

            for parameter in query.split("&"):

                if "=" in parameter:

                    key, value = (
                        parameter.split(
                            "=",
                            1
                        )
                    )

                    key_lower = (
                        key.lower()
                    )

                    if (
                        key_lower.startswith(
                            "utm_"
                        )
                        or
                        key_lower in {
                            "fbclid",
                            "gclid",
                            "mc_cid",
                            "mc_eid",
                            "ref",
                            "source"
                        }
                    ):
                        continue

                    filtered.append(
                        parameter
                    )

                else:

                    filtered.append(
                        parameter
                    )

            query = "&".join(
                filtered
            )


        normalized = urlunsplit(
            (
                parts.scheme.lower(),
                parts.netloc.lower(),
                parts.path.rstrip("/"),
                query,
                ""
            )
        )

        return normalized


    except Exception:

        return url.strip().lower()


# ============================================================
# NORMALIZE TITLE
# ============================================================

def normalize_title(title):

    if not title:
        return ""

    title = clean_text(
        title
    ).lower()

    title = re.sub(
        r"[^\w\s]",
        " ",
        title,
        flags=re.UNICODE
    )

    title = re.sub(
        r"\s+",
        " ",
        title
    )

    return title.strip()


# ============================================================
# ARTICLE ID
# ============================================================

def article_id(article):

    # --------------------------------------------------------
    # GNews unique ID
    # --------------------------------------------------------

    gnews_id = str(
        article.get(
            "id",
            ""
        )
    ).strip()

    if gnews_id:

        return (
            "gnews:" +
            gnews_id
        )


    # --------------------------------------------------------
    # Normalized URL
    # --------------------------------------------------------

    url = normalize_url(
        article.get(
            "link",
            ""
        )
    )

    if url:

        return (
            "url:" +
            hashlib.sha256(
                url.encode(
                    "utf-8"
                )
            ).hexdigest()
        )


    # --------------------------------------------------------
    # Normalized title
    # --------------------------------------------------------

    title = normalize_title(
        article.get(
            "title",
            ""
        )
    )

    return (
        "title:" +
        hashlib.sha256(
            title.encode(
                "utf-8"
            )
        ).hexdigest()
    )


# ============================================================
# TITLE HASH
# ============================================================

def title_hash(article):

    title = normalize_title(
        article.get(
            "title",
            ""
        )
    )

    return hashlib.sha256(
        title.encode(
            "utf-8"
        )
    ).hexdigest()


# ============================================================
# CHECK DUPLICATE
# ============================================================

def is_duplicate(
    article,
    posted
):

    aid = article_id(
        article
    )

    if aid in posted:

        return True


    normalized_url = normalize_url(
        article.get(
            "link",
            ""
        )
    )


    current_title_hash = title_hash(
        article
    )


    for key, record in posted.items():

        if not isinstance(
            record,
            dict
        ):
            continue


        # ----------------------------------------------------
        # URL duplicate
        # ----------------------------------------------------

        old_url = normalize_url(
            record.get(
                "url",
                ""
            )
        )

        if (
            normalized_url
            and
            old_url
            and
            normalized_url == old_url
        ):

            return True


        # ----------------------------------------------------
        # Title duplicate
        # ----------------------------------------------------

        old_title_hash = str(
            record.get(
                "title_hash",
                ""
            )
        ).strip()

        if (
            current_title_hash
            and
            old_title_hash
            and
            current_title_hash ==
            old_title_hash
        ):

            return True


    return False


# ============================================================
# CLEAN HTML
# ============================================================

def clean_text(text):

    if not text:
        return ""

    from html import unescape

    text = unescape(
        str(text)
    )

    text = re.sub(
        r"<script[\s\S]*?</script>",
        " ",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"<style[\s\S]*?</style>",
        " ",
        text,
        flags=re.IGNORECASE
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
# PARSE GNEWS DATE
# ============================================================

def parse_gnews_date(
    value
):

    if not value:
        return None

    try:

        value = value.replace(
            "Z",
            "+00:00"
        )

        return datetime.fromisoformat(
            value
        )

    except Exception:

        return None


# ============================================================
# GNEWS API
# ============================================================

def fetch_gnews(
    topic
):

    topic_name = topic[
        "name"
    ]

    query = topic[
        "query"
    ]


    logger.info(
        "Fetching GNews: %s",
        topic_name
    )

    logger.info(
        "Query: %s",
        query
    )


    url = (
        "https://gnews.io/api/v4/search"
    )


    params = {

        "q":
            query,

        "lang":
            "en",

        "country":
            "my",

        "max":
            GNEWS_MAX_RESULTS,

        "sortby":
            "publishedAt",

        "apikey":
            GNEWS_API_KEY

    }


    try:

        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )


        logger.info(
            "GNews HTTP = %s",
            response.status_code
        )


        if not response.ok:

            logger.error(
                "GNews error: %s",
                response.text
            )

            return []


        data = response.json()


        raw_articles = data.get(
            "articles",
            []
        )


        articles = []


        for item in raw_articles:

            if not isinstance(
                item,
                dict
            ):
                continue


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

            content = clean_text(
                item.get(
                    "content",
                    ""
                )
            )

            link = str(
                item.get(
                    "url",
                    ""
                )
            ).strip()

            image = str(
                item.get(
                    "image",
                    ""
                )
            ).strip()

            published_at = str(
                item.get(
                    "publishedAt",
                    ""
                )
            ).strip()

            gnews_id = str(
                item.get(
                    "id",
                    ""
                )
            ).strip()


            source_data = item.get(
                "source",
                {}
            )

            if not isinstance(
                source_data,
                dict
            ):
                source_data = {}


            source_name = str(
                source_data.get(
                    "name",
                    ""
                )
            ).strip()


            if not title or not link:
                continue


            article = {

                "id":
                    gnews_id,

                "source":
                    source_name
                    or "GNews",

                "title":
                    title,

                "link":
                    link,

                "summary":
                    description,

                "content":
                    content,

                "image":
                    image,

                "publishedAt":
                    published_at,

                "topic":
                    topic_name

            }


            # ------------------------------------------------
            # Age filter
            # ------------------------------------------------

            published_date = (
                parse_gnews_date(
                    published_at
                )
            )


            if published_date:

                now = datetime.now(
                    timezone.utc
                )

                age_hours = (
                    now -
                    published_date
                ).total_seconds() / 3600


                if (
                    age_hours >
                    MAX_ARTICLE_AGE_HOURS
                ):

                    logger.info(
                        "Skipping old article: %s",
                        title
                    )

                    continue


            articles.append(
                article
            )


        logger.info(
            "%s: %s usable articles",
            topic_name,
            len(articles)
        )


        return articles


    except Exception as e:

        logger.error(
            "GNews failed [%s]: %s",
            topic_name,
            e
        )

        return []


# ============================================================
# FIND IMAGE FROM NEWS PAGE
# ============================================================

def find_image_from_page(
    url
):

    if not url:
        return None


    try:

        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent":
                    (
                        "Mozilla/5.0 "
                        "(Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 "
                        "Chrome/139.0 Safari/537.36"
                    )
            }
        )


        if not response.ok:
            return None


        html = response.text


        # ----------------------------------------------------
        # og:image
        # ----------------------------------------------------

        patterns = [

            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',

            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',

            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',

            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',

        ]


        for pattern in patterns:

            match = re.search(
                pattern,
                html,
                re.IGNORECASE
            )

            if match:

                image = (
                    match.group(1)
                    .strip()
                )


                if image.startswith(
                    "//"
                ):

                    image = (
                        "https:" +
                        image
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


    return None


# ============================================================
# GROQ AI
# ============================================================

def generate_translation(
    article
):

    title = clean_text(
        article.get(
            "title",
            ""
        )
    )

    summary = clean_text(
        article.get(
            "summary",
            ""
        )
    )

    content = clean_text(
        article.get(
            "content",
            ""
        )
    )


    # --------------------------------------------------------
    # Use summary first, then content
    # --------------------------------------------------------

    source_text = summary

    if not source_text:
        source_text = content


    prompt = f"""
You are MYBUZZ Malaysia content editor.

Rewrite the following article into a short Telegram post.

IMPORTANT RULES:

1. Do NOT invent facts.
2. Do NOT add information that is not provided.
3. Keep names, places, numbers and facts accurate.
4. Chinese must be Simplified Chinese.
5. Malay must be natural Malaysian Malay.
6. Chinese title must be concise.
7. Malay title must be concise.
8. Chinese body should be short and easy to read.
9. Malay body should be short and easy to read.
10. Do not include URLs.
11. Do not use Markdown.
12. Do not use emojis inside the generated fields.
13. Do not write "Chinese", "Malay", "中文", "Bahasa Melayu".
14. Do not mention that AI was used.
15. Do not create clickbait.
16. If the source information is incomplete, stay conservative.
17. Keep the article suitable for MYBUZZ Malaysia audience.

Return ONLY valid JSON.

Required format:

{{
  "zh_title": "...",
  "zh_body": "...",
  "ms_title": "...",
  "ms_body": "..."
}}

TOPIC:
{article.get("topic", "")}

SOURCE:
{article.get("source", "")}

TITLE:
{title}

SUMMARY:
{source_text}
"""


    try:

        response = client.responses.create(
            model=GROQ_MODEL,
            input=prompt,
        )


        output = (
            response.output_text
            .strip()
        )


        logger.info(
            "AI response received."
        )


        # ----------------------------------------------------
        # Remove markdown fences
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
            )

            output = output.strip()


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

            if not data.get(
                key
            ):

                raise ValueError(
                    "Missing AI field: " +
                    key
                )


        return data


    except Exception as e:

        logger.error(
            "Groq API failed: %s",
            e
        )

        return None


# ============================================================
# ESCAPE HTML
# ============================================================

def escape_html(
    text
):

    if not text:
        return ""

    return (
        str(text)
        .replace(
            "&",
            "&amp;"
        )
        .replace(
            "<",
            "&lt;"
        )
        .replace(
            ">",
            "&gt;"
        )
    )


# ============================================================
# TELEGRAM FORMAT
# ============================================================

def build_caption(
    article,
    ai
):

    source = escape_html(
        article.get(
            "source",
            "GNews"
        )
    )

    link = article.get(
        "link",
        ""
    )


    topic = article.get(
        "topic",
        ""
    )


    zh_title = escape_html(
        ai[
            "zh_title"
        ].strip()
    )

    zh_body = escape_html(
        ai[
            "zh_body"
        ].strip()
    )

    ms_title = escape_html(
        ai[
            "ms_title"
        ].strip()
    )

    ms_body = escape_html(
        ai[
            "ms_body"
        ].strip()
    )


    topic_hashtag = re.sub(
        r"[^A-Za-z0-9]",
        "",
        topic
    )


    caption = (

        f"🇨🇳 {zh_title}\n\n"

        f"{zh_body}\n\n"

        f"🇲🇾 {ms_title}\n\n"

        f"{ms_body}\n\n"

        f'👉 <a href="{link}">'
        f'点击阅读完整内容'
        f'</a>\n\n'

        f'👉 <a href="{link}">'
        f'Klik untuk baca penuh'
        f'</a>\n\n'

        f"📰 Source / Sumber: "
        f"{source}\n\n"

        f"#MYBUZZ"
    )


    if topic_hashtag:

        caption += (
            " #" +
            topic_hashtag
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


    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/"
        "sendPhoto"
    )


    try:

        response = requests.post(

            url,

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


        if response.ok:

            data = response.json()

            if data.get(
                "ok"
            ):

                logger.info(
                    "Telegram photo sent successfully."
                )

                return True


        logger.error(
            "Telegram photo failed: %s",
            response.text
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

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/"
        "sendMessage"
    )


    try:

        response = requests.post(

            url,

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


        if response.ok:

            data = response.json()

            if data.get(
                "ok"
            ):

                logger.info(
                    "Telegram message sent successfully."
                )

                return True


        logger.error(
            "Telegram message failed: %s",
            response.text
        )

        return False


    except Exception as e:

        logger.error(
            "Telegram message exception: %s",
            e
        )

        return False


# ============================================================
# SELECT NEXT ARTICLE
# ============================================================

def select_article(
    posted,
    state
):

    total_topics = len(
        TOPICS
    )


    start_index = (
        state.get(
            "topic_index",
            0
        )
        %
        total_topics
    )


    logger.info(
        "Starting topic index: %s",
        start_index
    )


    # --------------------------------------------------------
    # Try every topic once
    # --------------------------------------------------------

    for offset in range(
        total_topics
    ):

        topic_index = (
            start_index +
            offset
        ) % total_topics


        topic = TOPICS[
            topic_index
        ]


        logger.info(
            "Trying topic: %s",
            topic["name"]
        )


        articles = fetch_gnews(
            topic
        )


        if not articles:

            continue


        # ----------------------------------------------------
        # Check duplicates
        # ----------------------------------------------------

        for article in articles:

            if is_duplicate(
                article,
                posted
            ):

                logger.info(
                    "Duplicate skipped: %s",
                    article["title"]
                )

                continue


            # ------------------------------------------------
            # Found new article
            # ------------------------------------------------

            logger.info(
                "NEW ARTICLE FOUND"
            )

            logger.info(
                "Topic = %s",
                topic["name"]
            )

            logger.info(
                "Title = %s",
                article["title"]
            )

            logger.info(
                "Source = %s",
                article["source"]
            )


            return (
                article,
                topic_index
            )


    return (
        None,
        start_index
    )


# ============================================================
# MARK POSTED
# ============================================================

def mark_posted(
    posted,
    article
):

    aid = article_id(
        article
    )


    posted[aid] = {

        "gnews_id":
            article.get(
                "id",
                ""
            ),

        "title":
            article.get(
                "title",
                ""
            ),

        "title_hash":
            title_hash(
                article
            ),

        "url":
            normalize_url(
                article.get(
                    "link",
                    ""
                )
            ),

        "source":
            article.get(
                "source",
                ""
            ),

        "topic":
            article.get(
                "topic",
                ""
            ),

        "published_at":
            article.get(
                "publishedAt",
                ""
            ),

        "posted_at":
            datetime.now(
                timezone.utc
            ).isoformat()

    }


    save_posted(
        posted
    )


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
        "Groq model: %s",
        GROQ_MODEL
    )

    logger.info(
        "Max articles per run: %s",
        MAX_ARTICLES
    )

    logger.info(
        "Topics: %s",
        len(TOPICS)
    )

    logger.info(
        "======================================"
    )


    # --------------------------------------------------------
    # LOCK
    # --------------------------------------------------------

    if not acquire_lock():

        logger.warning(
            "MYBUZZ V7 stopped because another "
            "instance is already running."
        )

        return


    try:

        # ----------------------------------------------------
        # Load
        # ----------------------------------------------------

        posted = load_posted()

        state = load_state()


        logger.info(
            "Posted records: %s",
            len(posted)
        )


        # ----------------------------------------------------
        # Select ONE new article
        # ----------------------------------------------------

        article, topic_index = (
            select_article(
                posted,
                state
            )
        )


        if not article:

            logger.info(
                "No new articles found "
                "in any topic."
            )

            logger.info(
                "MYBUZZ V7 FINISHED | Sent: 0"
            )

            return


        # ----------------------------------------------------
        # Update next topic
        # ----------------------------------------------------

        next_topic_index = (
            topic_index + 1
        ) % len(TOPICS)


        # ----------------------------------------------------
        # IMAGE
        # ----------------------------------------------------

        image_url = article.get(
            "image"
        )


        if not image_url:

            logger.info(
                "GNews has no image. "
                "Trying news page..."
            )


            image_url = (
                find_image_from_page(
                    article["link"]
                )
            )


        article["image"] = (
            image_url
        )


        if image_url:

            logger.info(
                "Image found: %s",
                image_url
            )

        else:

            logger.warning(
                "No image found."
            )


        # ----------------------------------------------------
        # AI
        # ----------------------------------------------------

        ai = generate_translation(
            article
        )


        if not ai:

            logger.warning(
                "AI failed."
            )

            # ----------------------------------------------
            # Do NOT mark as posted
            # ----------------------------------------------

            state[
                "topic_index"
            ] = topic_index

            state[
                "last_run"
            ] = datetime.now(
                timezone.utc
            ).isoformat()

            state[
                "last_topic"
            ] = article.get(
                "topic",
                ""
            )

            save_state(
                state
            )

            return


        # ----------------------------------------------------
        # BUILD CAPTION
        # ----------------------------------------------------

        caption = build_caption(
            article,
            ai
        )


        # ----------------------------------------------------
        # TELEGRAM
        # ----------------------------------------------------

        success = False


        if image_url:

            logger.info(
                "Trying Telegram photo..."
            )


            success = send_photo(
                image_url,
                caption
            )


            # ----------------------------------------------
            # Fallback
            # ----------------------------------------------

            if not success:

                logger.warning(
                    "Photo failed. "
                    "Trying text message..."
                )


                success = send_message(
                    caption
                )

        else:

            success = send_message(
                caption
            )


        # ----------------------------------------------------
        # ONLY SAVE AFTER SUCCESS
        # ----------------------------------------------------

        if success:

            mark_posted(
                posted,
                article
            )


            # ----------------------------------------------
            # Move to next topic
            # ----------------------------------------------

            state[
                "topic_index"
            ] = next_topic_index


            state[
                "last_run"
            ] = datetime.now(
                timezone.utc
            ).isoformat()


            state[
                "last_topic"
            ] = article.get(
                "topic",
                ""
            )


            save_state(
                state
            )


            logger.info(
                "======================================"
            )

            logger.info(
                "ARTICLE SENT SUCCESSFULLY"
            )

            logger.info(
                "Topic = %s",
                article.get(
                    "topic",
                    ""
                )
            )

            logger.info(
                "Source = %s",
                article.get(
                    "source",
                    ""
                )
            )

            logger.info(
                "Title = %s",
                article.get(
                    "title",
                    ""
                )
            )

            logger.info(
                "Next topic index = %s",
                next_topic_index
            )

            logger.info(
                "MYBUZZ V7 FINISHED | Sent: 1"
            )

            logger.info(
                "======================================"
            )


        else:

            logger.error(
                "Telegram send failed."
            )

            logger.error(
                "Article will NOT be marked as posted."
            )

            logger.info(
                "MYBUZZ V7 FINISHED | Sent: 0"
            )


    finally:

        release_lock()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
