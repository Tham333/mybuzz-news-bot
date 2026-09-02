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
# Proper Noun Validation
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
TERMS_FILE = "malaysia_terms.json"


# ============================================================
# LIMITS
# ============================================================

REQUEST_TIMEOUT = 20

MAX_GNEWS_ARTICLES = 10

MAX_POSTED = 1000

MAX_AI_ATTEMPTS = 3

AI_MAX_TOKENS = 1200


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
#
# max_retries=0
#
# 重要：
# OpenAI SDK 默认会自动 retry 429。
# 我们关闭 SDK 自动 retry，
# 由 MYBUZZ 自己控制 retry，
# 避免一次失败产生多次隐藏请求。
#
# ============================================================

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url=GROQ_BASE_URL,
    max_retries=0,
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

        # 防止过长 description 进入 AI prompt
        description = description[:1500]

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
# MALAYSIA PROPER NOUN DICTIONARY
# ============================================================

def load_terms():

    if not os.path.exists(
        TERMS_FILE
    ):

        logger.warning(
            "%s not found. Proper noun dictionary disabled.",
            TERMS_FILE
        )

        return {}

    try:

        with open(
            TERMS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if not isinstance(
            data,
            dict
        ):

            return {}

        return data

    except Exception as e:

        logger.warning(
            "Could not read %s: %s",
            TERMS_FILE,
            e
        )

        return {}


# ============================================================
# FLATTEN TERMS
# ============================================================

def flatten_terms(data):

    flattened = {}

    if not isinstance(
        data,
        dict
    ):

        return flattened

    for category, terms in data.items():

        if not isinstance(
            terms,
            dict
        ):

            continue

        for original, translation in terms.items():

            original = clean_text(
                original
            )

            translation = clean_text(
                translation
            )

            if not original:
                continue

            if translation is None:
                translation = ""

            flattened[original] = translation

    return flattened


# ============================================================
# BUILD TERMS TEXT
# ============================================================

def build_terms_text(data):

    if not isinstance(
        data,
        dict
    ):

        return (
            "No proper noun dictionary available."
        )

    blocks = []

    for category, terms in data.items():

        if not isinstance(
            terms,
            dict
        ) or not terms:

            continue

        lines = [
            f"[{str(category).upper()}]"
        ]

        for original, translation in terms.items():

            original = clean_text(
                original
            )

            translation = clean_text(
                translation
            )

            if not original:
                continue

            if (
                not translation
                or
                translation.upper()
                == "KEEP ORIGINAL"
            ):

                translation = (
                    "KEEP ORIGINAL"
                )

            lines.append(
                f"{original} = {translation}"
            )

        if len(lines) > 1:

            blocks.append(
                "\n".join(lines)
            )

    return (
        "\n\n".join(blocks)
        or
        "No proper noun dictionary available."
    )


# ============================================================
# VALIDATE PROPER NOUNS
# ============================================================

def validate_proper_nouns(
    article,
    ai,
    terms
):

    flattened = flatten_terms(
        terms
    )

    if not flattened:
        return True, ""

    article_text = clean_text(
        str(article.get("title", ""))
        + " "
        + str(article.get("description", ""))
        + " "
        + str(article.get("content", ""))
    )

    zh = (
        clean_text(
            ai.get("zh_title", "")
        )
        + " "
        + clean_text(
            ai.get("zh_body", "")
        )
    )

    ms = (
        clean_text(
            ai.get("ms_title", "")
        )
        + " "
        + clean_text(
            ai.get("ms_body", "")
        )
    )

    article_lower = article_text.lower()
    ms_lower = ms.lower()

    errors = []

    for original, translation in flattened.items():

        original = clean_text(
            original
        )

        translation = clean_text(
            translation
        )

        if len(original) < 2:
            continue

        # ==================================================
        # 只检查原新闻实际出现过的专有名词
        # ==================================================

        if original.lower() not in article_lower:
            continue

        # ==================================================
        # MALAY
        #
        # 不再强制每个专有名词都必须出现在摘要。
        #
        # 如果 AI 使用了这个专有名词，
        # 则保持原文即可。
        # ==================================================

        if original.lower() in ms_lower:
            continue

        # ==================================================
        # CHINESE
        #
        # 如果 AI 没有提到这个专有名词，
        # 不报错。
        #
        # 如果 AI 使用原文名称，
        # 但 dictionary 有正式中文翻译，
        # 则必须使用正式中文翻译。
        # ==================================================

        if original in zh:

            if (
                translation
                and
                translation.upper()
                != "KEEP ORIGINAL"
            ):

                if translation not in zh:

                    errors.append(
                        "Chinese used original "
                        "instead of translation: "
                        f"{original} -> {translation}"
                    )

        # ==================================================
        # KEEP ORIGINAL
        #
        # 不强制 AI 必须提到。
        # 如果提到了，保持原文即可。
        # ==================================================

        if (
            translation.upper()
            == "KEEP ORIGINAL"
        ):

            continue

    if errors:

        return (
            False,
            " | ".join(
                errors[:12]
            )
        )

    return True, ""


# ============================================================
# EXTRACT JSON
# ============================================================

def extract_json(text):

    if not text:
        return None

    text = text.strip()

    # Remove Markdown code fence
    if text.startswith("```"):

        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.IGNORECASE
        )

        text = re.sub(
            r"\s*```$",
            "",
            text
        )

    start = text.find(
        "{"
    )

    end = text.rfind(
        "}"
    )

    if (
        start == -1
        or
        end == -1
        or
        end <= start
    ):

        return None

    candidate = text[
        start:end + 1
    ]

    try:

        return json.loads(
            candidate
        )

    except json.JSONDecodeError:

        return None


# ============================================================
# VALIDATE AI FIELDS
# ============================================================

def validate_ai_fields(data):

    if not isinstance(
        data,
        dict
    ):

        return False, "AI result is not an object."

    required = [
        "zh_title",
        "zh_body",
        "ms_title",
        "ms_body",
    ]

    for key in required:

        value = clean_text(
            data.get(
                key,
                ""
            )
        )

        if not value:

            return False, (
                f"Missing AI field: {key}"
            )

        data[key] = value

    return True, ""


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

    description = description[
        :1500
    ]

    source = clean_text(
        article.get(
            "source",
            ""
        )
    )

    terms_data = load_terms()

    terms_text = build_terms_text(
        terms_data
    )

    prompt = f"""
You are the MYBUZZ Malaysia news editor and a professional Malaysian Chinese/Malay news translator.

Create one short bilingual Malaysian Telegram news post from the source below.

SOURCE:
{source}

ORIGINAL TITLE:
{title}

ORIGINAL CONTENT:
{description}

============================================================
MALAYSIA PROPER NOUN DICTIONARY
============================================================

{terms_text}

============================================================
PROPER NOUN RULES
============================================================

1. Follow the dictionary exactly when a proper noun is used.
2. If the dictionary provides a Chinese translation, use that exact translation.
3. If the dictionary says KEEP ORIGINAL, keep the original name.
4. Never invent Chinese names.
5. Never creatively rewrite proper nouns.
6. Malaysian people names normally remain in Roman letters unless the dictionary provides a Chinese name.
7. Malaysian place names use the dictionary translation when available.
8. In Malay, Malaysian proper nouns should remain in their original form.

IMPORTANT:

Do NOT force every proper noun from the source article into the short summary.

Only mention proper nouns that are relevant to the summary.

If you mention a proper noun, it MUST follow the dictionary.

============================================================
CHINESE
============================================================

1. Use natural Simplified Chinese used by Malaysian Chinese news media.
2. Do not translate word by word.
3. Preserve factual meaning.
4. Keep the headline concise and professional.
5. Use sentence context to determine meaning.
6. Do not invent names.
7. Do not add facts.
8. Do not remove important facts.
9. Natural Chinese is more important than literal translation.

============================================================
MALAY
============================================================

1. Use natural Malaysian Malay.
2. Do not translate mechanically.
3. Keep names, places, organisations, companies and events accurate.
4. Keep Malaysian proper nouns in original form.
5. Make the Malay headline sound like a real Malaysian news headline.

============================================================
CONTEXTUAL TRANSLATION
============================================================

Understand the complete sentence before translating.

Common Malay words can have different meanings depending on context.

For example:

"santai" does NOT always mean "轻松".

In a portrait, photo, painting, expression or appearance context, "santai" may mean:
"自然", "亲切", "随和", "非正式" or "神态轻松".

"Potret santai Tunku Abdul Rahman" should NOT automatically become:
"轻松的东姑肖像".

Choose the natural meaning according to context.

"menarik tumpuan" may mean:
"引起关注", "吸引关注", "成为焦点", "受到关注" or "成为亮点".

"menjadi tarikan utama" may mean:
"成为主要亮点", "成为主要看点" or "成为焦点".

Do not blindly copy these examples.

============================================================
FACT CHECK
============================================================

Before returning the answer, silently check:

1. Names correct?
2. Places correct?
3. Companies correct?
4. Organisations correct?
5. Dates correct?
6. Numbers correct?
7. Money amounts correct?
8. Meaning preserved?
9. No invented facts?
10. Natural Malaysian Chinese?
11. Natural Malaysian Malay?
12. Proper noun dictionary followed?

============================================================
OUTPUT RULES
============================================================

Return ONLY ONE complete JSON object.

Never return Markdown.

Never return explanations.

Never stop in the middle of a field.

Never truncate a sentence.

The JSON MUST end with }.

Keep the content short.

zh_title: maximum 35 Chinese characters.

zh_body: maximum 120 Chinese characters.

ms_title: maximum 100 characters.

ms_body: maximum 300 characters.

Use 1-2 short sentences for each body.

Do not repeat information.

Do not include URLs.

Do not include hashtags.

Do not mention AI.

============================================================
OUTPUT
============================================================

Return exactly:

{{
  "zh_title": "...",
  "zh_body": "...",
  "ms_title": "...",
  "ms_body": "..."
}}
"""

    last_error = ""

    for attempt in range(
        1,
        MAX_AI_ATTEMPTS + 1
    ):

        try:

            current_prompt = prompt

            if attempt > 1:

                current_prompt += f"""

============================================================
RETRY CORRECTION
============================================================

The previous AI response failed.

Reason:
{last_error}

IMPORTANT:

The previous response may have been incomplete or truncated.

Generate a MUCH SHORTER response.

Do not repeat the previous incomplete response.

Make sure every JSON string is complete.

Make sure the final character is }.

Keep:

zh_title <= 35 Chinese characters
zh_body <= 120 Chinese characters
ms_title <= 100 characters
ms_body <= 300 characters

Return ONLY valid JSON.
"""

            logger.info(
                "Sending Groq request attempt %s/%s",
                attempt,
                MAX_AI_ATTEMPTS
            )

            response = client.chat.completions.create(

                model=GROQ_MODEL,

                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a highly accurate "
                            "Malaysian news editor and "
                            "translation system. "
                            "Return ONLY valid JSON."
                        )
                    },
                    {
                        "role": "user",
                        "content": current_prompt
                    }
                ],

                temperature=0.1,

                max_tokens=AI_MAX_TOKENS,
            )

            output = (
                response.choices[0].message.content
                or ""
            ).strip()

            finish_reason = getattr(
                response.choices[0],
                "finish_reason",
                None
            )

            logger.info(
                "Groq finish reason: %s",
                finish_reason
            )

            logger.info(
                "Groq AI response attempt %s: %s",
                attempt,
                output[:1500]
            )

            # ==================================================
            # EMPTY RESPONSE
            # ==================================================

            if not output:

                raise ValueError(
                    "Groq returned an empty response"
                )

            # ==================================================
            # DETECT TOKEN TRUNCATION
            # ==================================================

            if (
                finish_reason
                and
                str(finish_reason).lower()
                in (
                    "length",
                    "max_tokens"
                )
            ):

                raise ValueError(
                    "AI output was truncated by token limit"
                )

            # ==================================================
            # EXTRACT JSON
            # ==================================================

            data = extract_json(
                output
            )

            if not data:

                raise ValueError(
                    "AI returned incomplete or invalid JSON"
                )

            # ==================================================
            # VALIDATE FIELDS
            # ==================================================

            valid_fields, field_error = (
                validate_ai_fields(
                    data
                )
            )

            if not valid_fields:

                raise ValueError(
                    field_error
                )

            # ==================================================
            # PROPER NOUN VALIDATION
            # ==================================================

            valid, error_message = (
                validate_proper_nouns(
                    article,
                    data,
                    terms_data
                )
            )

            if not valid:

                last_error = error_message

                logger.warning(
                    "Proper noun validation failed: %s",
                    error_message
                )

                continue

            # ==================================================
            # SUCCESS
            # ==================================================

            logger.info(
                "AI content validation passed."
            )

            return data

        except json.JSONDecodeError as e:

            last_error = (
                f"JSON decode error: {e}"
            )

            logger.error(
                last_error
            )

            logger.info(
                "Raw output: %s",
                output[:1500]
                if output
                else "(empty)"
            )

        except Exception as e:

            last_error = str(e)

            error_text = str(e).lower()

            # ==================================================
            # GROQ RATE LIMIT
            # ==================================================

            if (
                "429" in error_text
                or
                "rate limit" in error_text
                or
                "too many requests" in error_text
            ):

                if attempt < MAX_AI_ATTEMPTS:

                    wait_time = (
                        30 * attempt
                    )

                    logger.warning(
                        "Groq rate limit reached. "
                        "Waiting %s seconds before retry.",
                        wait_time
                    )

                    time.sleep(
                        wait_time
                    )

                    continue

            logger.error(
                "Groq AI attempt %s failed: %s",
                attempt,
                e
            )

            # ==================================================
            # NORMAL ERROR RETRY
            # ==================================================

            if attempt < MAX_AI_ATTEMPTS:

                wait_time = (
                    5 * attempt
                )

                logger.info(
                    "Retrying Groq in %s seconds...",
                    wait_time
                )

                time.sleep(
                    wait_time
                )

    logger.error(
        "AI failed after %s attempts: %s",
        MAX_AI_ATTEMPTS,
        last_error
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
    # MODE
    # --------------------------------------------------------

    logger.info(
        "Selected mode: NEWS"
    )

    # --------------------------------------------------------
    # SELECT NEWS
    # --------------------------------------------------------

    article = select_news(
        posted_set
    )

    if not article:

        logger.warning(
            "No new Malaysia news with image available."
        )

        return

    # --------------------------------------------------------
    # LOG ARTICLE
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

        # 不标记为 posted
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
