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
# ┌───────────────────────┐
# │ NEWS                  │
# │ NEWS                  │
# │ FOOD                  │
# │ TRAVEL                │
# │ NEWS                  │
# │ NEWS                  │
# │ FOOD                  │
# │ TRAVEL                │
# └───────────────────────┘
#       ↓
# Telegram
#
# 每次运行只发送 1 条
#
# ============================================================


BOT_NAME = "MYBUZZ NEWS BOT"

REQUEST_TIMEOUT = 20

MAX_HISTORY = 2000

STATE_FILE = "posted.json"


# ============================================================
# ROTATION
# ============================================================

ROTATION = [

    "news",
    "news",
    "food",
    "travel",

]


# ============================================================
# ENVIRONMENT
# ============================================================

GNEWS_API_KEY = os.environ.get(
    "GNEWS_API_KEY"
)

GROQ_API_KEY = os.environ.get(
    "GROQ_API_KEY"
)

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID"
)


# ============================================================
# CHECK ENVIRONMENT
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

GROQ_MODEL = (
    "openai/gpt-oss-20b"
)


client = OpenAI(

    api_key=GROQ_API_KEY,

    base_url=GROQ_BASE_URL,

)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(

    level=logging.INFO,

    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    )

)

logger = logging.getLogger(
    BOT_NAME
)


# ============================================================
# LOAD STATE
# ============================================================

def load_state():

    if not os.path.exists(
        STATE_FILE
    ):

        return {

            "counter": 0,

            "posted": []

        }


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

            posted = data.get(
                "posted",
                []
            )


            if not isinstance(
                counter,
                int
            ):

                counter = 0


            if not isinstance(
                posted,
                list
            ):

                posted = []


            return {

                "counter":
                    counter,

                "posted":
                    posted

            }


    except Exception as e:

        logger.warning(
            "Could not read state: %s",
            e
        )


    return {

        "counter": 0,

        "posted": []

    }


# ============================================================
# SAVE STATE
# ============================================================

def save_state(state):

    try:

        posted = state.get(
            "posted",
            []
        )


        unique = []

        seen = set()


        for item in posted:

            item = str(
                item
            ).strip()


            if not item:

                continue


            if item in seen:

                continue


            seen.add(
                item
            )

            unique.append(
                item
            )


        state["posted"] = (
            unique[-MAX_HISTORY:]
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


        logger.info(
            "State saved. Counter=%s | History=%s",
            state["counter"],
            len(state["posted"])
        )


        return True


    except Exception as e:

        logger.error(
            "Could not save state: %s",
            e
        )

        return False


# ============================================================
# NORMALIZE
# ============================================================

def normalize_text(text):

    text = str(
        text or ""
    )


    text = html.unescape(
        text
    )


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
# CONTENT ID
# ============================================================

def make_id(article):

    url = normalize_text(
        article.get(
            "url",
            ""
        )
    )


    title = normalize_text(
        article.get(
            "title",
            ""
        )
    )


    source = normalize_text(
        article.get(
            "source",
            ""
        )
    )


    raw = (

        url
        + "|"
        + title
        + "|"
        + source

    )


    return hashlib.sha256(
        raw.encode(
            "utf-8"
        )
    ).hexdigest()


# ============================================================
# URL ID
# ============================================================

def make_url_id(url):

    value = normalize_text(
        url
    )


    return hashlib.sha256(
        value.encode(
            "utf-8"
        )
    ).hexdigest()


# ============================================================
# TITLE ID
# ============================================================

def make_title_id(title):

    value = normalize_text(
        title
    )


    return hashlib.sha256(
        value.encode(
            "utf-8"
        )
    ).hexdigest()


# ============================================================
# GNEWS
# ============================================================

def fetch_news():

    logger.info(
        "======================================"
    )

    logger.info(
        "FETCH GNEWS - MALAYSIA"
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

            title = str(

                article.get(
                    "title",
                    ""
                )

            ).strip()


            description = str(

                article.get(
                    "description",
                    ""
                )

            ).strip()


            url_value = str(

                article.get(
                    "url",
                    ""
                )

            ).strip()


            image = str(

                article.get(
                    "image",
                    ""
                )

            ).strip()


            published = str(

                article.get(
                    "publishedAt",
                    ""
                )

            ).strip()


            source_data = (

                article.get(
                    "source",
                    {}
                )
                or {}

            )


            source = str(

                source_data.get(
                    "name",
                    "GNews"
                )

            ).strip()


            if not title:

                continue


            if not url_value:

                continue


            result.append({

                "type":
                    "news",

                "source":
                    source,

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
            "GNews articles: %s",
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
# WIKIMEDIA FOOD
# ============================================================

def fetch_food():

    logger.info(
        "======================================"
    )

    logger.info(
        "FETCH WIKIMEDIA - MALAYSIA FOOD"
    )

    logger.info(
        "======================================"
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
            (
                "Malaysian food "
                "nasi lemak "
                "char kway teow "
                "laksa "
                "roti canai"
            ),

        "gsrnamespace":
            6,

        "gsrlimit":
            20,

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

            .get(
                "query",
                {}
            )

            .get(
                "pages",
                {}
            )

        )


        result = []


        for page in pages.values():

            title = str(

                page.get(
                    "title",
                    ""
                )

            ).strip()


            image_url = ""


            image_info = (

                page.get(
                    "imageinfo",
                    []
                )
                or []

            )


            if image_info:

                image_url = str(

                    image_info[0].get(
                        "url",
                        ""
                    )

                ).strip()


            if not title:

                continue


            if not image_url:

                continue


            clean_title = title.replace(
                "File:",
                ""
            )


            page_url = (

                "https://commons.wikimedia.org/wiki/"

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
                    clean_title,

                "description":
                    (
                        "Malaysian food and "
                        "culinary content."
                    ),

                "url":
                    page_url,

                "image":
                    image_url,

                "publishedAt":
                    ""

            })


        logger.info(
            "Food results: %s",
            len(result)
        )


        return result


    except Exception as e:

        logger.error(
            "Wikimedia food failed: %s",
            e
        )


        return []


# ============================================================
# WIKIVOYAGE TRAVEL
# ============================================================

def fetch_travel():

    logger.info(
        "======================================"
    )

    logger.info(
        "FETCH WIKIVOYAGE - MALAYSIA TRAVEL"
    )

    logger.info(
        "======================================"
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
            (
                "Malaysia "
                "Kuala Lumpur "
                "Penang "
                "Langkawi "
                "Melaka "
                "Sabah "
                "Sarawak"
            ),

        "gsrnamespace":
            0,

        "gsrlimit":
            20,

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

            .get(
                "query",
                {}
            )

            .get(
                "pages",
                {}
            )

        )


        result = []


        for page in pages.values():

            title = str(

                page.get(
                    "title",
                    ""
                )

            ).strip()


            extract = str(

                page.get(
                    "extract",
                    ""
                )

            ).strip()


            page_url = str(

                page.get(
                    "fullurl",
                    ""
                )

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
            "Travel results: %s",
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
# DUPLICATE FILTER
# ============================================================

def remove_duplicates(
    articles,
    posted
):

    posted_set = set(
        posted
    )


    result = []


    seen_content = set()

    seen_urls = set()

    seen_titles = set()


    for article in articles:

        content_id = make_id(
            article
        )


        url_id = make_url_id(

            article.get(
                "url",
                ""
            )

        )


        title_id = make_title_id(

            article.get(
                "title",
                ""
            )

        )


        if content_id in posted_set:

            continue


        if url_id in posted_set:

            continue


        if title_id in posted_set:

            continue


        if content_id in seen_content:

            continue


        if url_id in seen_urls:

            continue


        if title_id in seen_titles:

            continue


        seen_content.add(
            content_id
        )

        seen_urls.add(
            url_id
        )

        seen_titles.add(
            title_id
        )


        result.append(
            article
        )


    return result


# ============================================================
# GET CONTENT FOR ROTATION
# ============================================================

def get_content(
    content_type,
    posted
):

    if content_type == "news":

        articles = fetch_news()


    elif content_type == "food":

        articles = fetch_food()


    elif content_type == "travel":

        articles = fetch_travel()


    else:

        return []


    return remove_duplicates(
        articles,
        posted
    )


# ============================================================
# AI
# ============================================================

def generate_ai(
    article
):

    article_type = article.get(
        "type",
        "news"
    )


    title = article.get(
        "title",
        ""
    )


    description = article.get(
        "description",
        ""
    )


    source = article.get(
        "source",
        ""
    )


    if article_type == "news":

        instruction = """

This is Malaysian current news.

Rewrite it into a concise
MYBUZZ Malaysia news post.

Do not invent facts.
Do not add unsupported information.
Keep names, locations and numbers accurate.

"""


    elif article_type == "food":

        instruction = """

This is Malaysian food content.

Turn it into an interesting,
informative MYBUZZ food post.

Focus on the food, culinary culture,
origin or characteristics when supported
by the source.

Do not invent facts.

"""


    else:

        instruction = """

This is Malaysian travel content.

Turn it into a useful and interesting
MYBUZZ Malaysia travel post.

Focus on the destination,
attractions and useful travel information
when supported by the source.

Do not invent facts.

"""


    prompt = f"""

You are the MYBUZZ Malaysia editor.

{instruction}

Create:

1. Simplified Chinese title
2. Simplified Chinese body
3. Malaysian Malay title
4. Malaysian Malay body

Return ONLY valid JSON.

Format:

{{
  "zh_title": "...",
  "zh_body": "...",
  "ms_title": "...",
  "ms_body": "..."
}}

Rules:

- Natural Simplified Chinese.
- Natural Malaysian Malay.
- Concise.
- No Markdown.
- No emojis.
- No URLs.
- No fake quotes.
- No exaggerated claims.
- Do not mention that the content was generated by AI.
- Do not add facts that are not supported.

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
            "ms_body"

        ]


        for key in required:

            if not data.get(
                key
            ):

                raise ValueError(

                    f"Missing AI field: {key}"

                )


        return data


    except Exception as e:

        logger.error(
            "AI failed: %s",
            e
        )


        return None


# ============================================================
# HTML ESCAPE
# ============================================================

def escape_html(
    text
):

    return html.escape(

        str(
            text or ""
        ),

        quote=True

    )


# ============================================================
# BUILD MESSAGE
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

        header = (
            "MYBUZZ NEWS"
        )


    elif article_type == "food":

        header = (
            "MYBUZZ FOOD"
        )


    else:

        header = (
            "MYBUZZ TRAVEL"
        )


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

        ai.get(
            "zh_title",
            ""
        ).strip()

    )


    zh_body = escape_html(

        ai.get(
            "zh_body",
            ""
        ).strip()

    )


    ms_title = escape_html(

        ai.get(
            "ms_title",
            ""
        ).strip()

    )


    ms_body = escape_html(

        ai.get(
            "ms_body",
            ""
        ).strip()

    )


    message = (

        f"<b>{header}</b>\n\n"

        f"<b>🇨🇳 {zh_title}</b>\n"
        f"{zh_body}\n\n"

        f"<b>🇲🇾 {ms_title}</b>\n"
        f"{ms_body}\n\n"

        f"📰 Source / Sumber: {source}\n\n"

        f'<a href="{url}">'
        f"查看完整内容 / "
        f"Baca selanjutnya"
        f"</a>"

    )


    return message


# ============================================================
# SEND TELEGRAM MESSAGE
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
# SEND TELEGRAM PHOTO
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

            "Telegram photo status: %s",

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


    # ========================================================
    # LOAD STATE
    # ========================================================

    state = load_state()


    counter = int(

        state.get(
            "counter",
            0
        )

    )


    posted = state.get(
        "posted",
        []
    )


    # ========================================================
    # DETERMINE CURRENT ROTATION
    # ========================================================

    rotation_index = (

        counter
        % len(ROTATION)

    )


    content_type = ROTATION[
        rotation_index
    ]


    logger.info(
        "Rotation counter: %s",
        counter
    )


    logger.info(
        "Rotation index: %s",
        rotation_index
    )


    logger.info(
        "Current type: %s",
        content_type.upper()
    )


    # ========================================================
    # FETCH CURRENT TYPE
    # ========================================================

    articles = get_content(

        content_type,

        posted

    )


    # ========================================================
    # IF CURRENT TYPE HAS NO NEW CONTENT
    # ========================================================

    if not articles:

        logger.warning(

            "No new %s content.",

            content_type

        )


        # ----------------------------------------------------
        # IMPORTANT
        # ----------------------------------------------------
        #
        # 如果这一轮没有新的内容：
        #
        # 不发送
        #
        # 但轮次继续。
        #
        # 下一次运行进入下一个类别。
        #
        # ----------------------------------------------------

        state["counter"] = (
            counter + 1
        )


        save_state(
            state
        )


        logger.info(
            "Rotation advanced."
        )


        logger.info(
            "Nothing sent this run."
        )


        return


    # ========================================================
    # SELECT ONE ONLY
    # ========================================================

    selected = articles[0]


    logger.info(
        "Selected content:"
    )


    logger.info(
        "TYPE = %s",
        selected.get(
            "type"
        )
    )


    logger.info(
        "SOURCE = %s",
        selected.get(
            "source"
        )
    )


    logger.info(
        "TITLE = %s",
        selected.get(
            "title"
        )
    )


    # ========================================================
    # AI
    # ========================================================

    ai = generate_ai(
        selected
    )


    if not ai:

        logger.error(
            "AI generation failed."
        )


        # 不保存为 posted
        # 但不要跳过轮次

        state["counter"] = (
            counter + 1
        )


        save_state(
            state
        )


        return


    # ========================================================
    # MESSAGE
    # ========================================================

    message = build_message(

        selected,

        ai

    )


    # ========================================================
    # SEND
    # ========================================================

    image_url = selected.get(
        "image",
        ""
    )


    success = False


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
    # SUCCESS
    # ========================================================

    if success:

        content_id = make_id(
            selected
        )


        url_id = make_url_id(

            selected.get(
                "url",
                ""
            )

        )


        title_id = make_title_id(

            selected.get(
                "title",
                ""
            )

        )


        # ----------------------------------------------------
        # SAVE ALL DUPLICATE IDs
        # ----------------------------------------------------

        state["posted"].append(
            content_id
        )


        state["posted"].append(
            url_id
        )


        state["posted"].append(
            title_id
        )


        # ----------------------------------------------------
        # ADVANCE ROTATION
        # ----------------------------------------------------

        state["counter"] = (
            counter + 1
        )


        save_state(
            state
        )


        logger.info(
            "======================================"
        )

        logger.info(
            "SUCCESS"
        )

        logger.info(
            "TYPE = %s",
            content_type.upper()
        )

        logger.info(
            "SENT = 1"
        )

        logger.info(
            "NEXT TYPE = %s",
            ROTATION[
                state["counter"]
                % len(ROTATION)
            ].upper()
        )

        logger.info(
            "======================================"
        )


    else:

        logger.error(
            "Telegram send failed."
        )


        # ----------------------------------------------------
        # DO NOT MARK CONTENT AS POSTED
        # ----------------------------------------------------
        #
        # 但是轮次继续
        #
        # ----------------------------------------------------

        state["counter"] = (
            counter + 1
        )


        save_state(
            state
        )


        logger.error(
            "Content was NOT marked as posted."
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
