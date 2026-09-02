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

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url=GROQ_BASE_URL,
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
    if not os.path.exists(TERMS_FILE):
        logger.warning("%s not found. Proper noun dictionary disabled.", TERMS_FILE)
        return {}
    try:
        with open(TERMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as e:
        logger.warning("Could not read %s: %s", TERMS_FILE, e)
        return {}


def flatten_terms(data):
    flattened = {}
    if not isinstance(data, dict):
        return flattened
    for category, terms in data.items():
        if not isinstance(terms, dict):
            continue
        for original, translation in terms.items():
            original = clean_text(original)
            translation = clean_text(translation)
            if not original:
                continue
            if translation is None:
                translation = ""
            flattened[original] = translation
    return flattened


def build_terms_text(data):
    if not isinstance(data, dict):
        return "No proper noun dictionary available."

    blocks = []
    for category, terms in data.items():
        if not isinstance(terms, dict) or not terms:
            continue
        lines = [f"[{str(category).upper()}]"]
        for original, translation in terms.items():
            original = clean_text(original)
            translation = clean_text(translation)
            if not original:
                continue
            if not translation or translation.upper() == "KEEP ORIGINAL":
                translation = "KEEP ORIGINAL"
            lines.append(f"{original} = {translation}")
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    return "\n\n".join(blocks) or "No proper noun dictionary available."


def validate_proper_nouns(article, ai, terms):
    flattened = flatten_terms(terms)
    if not flattened:
        return True, ""

    zh = clean_text(ai.get("zh_title", "")) + " " + clean_text(ai.get("zh_body", ""))
    ms = clean_text(ai.get("ms_title", "")) + " " + clean_text(ai.get("ms_body", ""))

    errors = []

    for original, translation in flattened.items():
        if len(original) < 2:
            continue

        if original.lower() not in ms.lower():
            errors.append(f'Malay missing original proper noun: {original}')

        if translation and translation.upper() != "KEEP ORIGINAL":
            if translation not in zh:
                errors.append(
                    f'Chinese missing required translation: {original} -> {translation}'
                )
        else:
            if original not in zh:
                errors.append(
                    f'Chinese must keep original proper noun: {original}'
                )

    if errors:
        return False, " | ".join(errors[:12])

    return True, ""


# ============================================================
# GENERATE AI CONTENT
# ============================================================

def generate_ai_content(article):
    title = clean_text(article.get("title", ""))
    description = clean_text(article.get("description", ""))
    source = clean_text(article.get("source", ""))

    terms_data = load_terms()
    terms_text = build_terms_text(terms_data)

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
VERY IMPORTANT PROPER NOUN RULES
============================================================

1. Proper nouns are more important than literal translation.
2. People names, place names, Malaysian states, cities, districts, government agencies, political parties, companies, brands, universities, hospitals, organisations, institutions, programmes and event names must be handled carefully.
3. If the dictionary provides a Chinese translation, use that exact Chinese translation.
4. If the dictionary says KEEP ORIGINAL, keep the original proper noun in Chinese.
5. Never invent a Chinese name for a person, place, organisation, company or event.
6. Never change, shorten, transliterate or creatively rewrite a proper noun unless the dictionary explicitly provides the translation.
7. In Malay, keep Malaysian proper nouns in their original form whenever possible.
8. Do not translate a Malaysian person's name as a Chinese name unless the dictionary explicitly provides one.

============================================================
CHINESE VERSION
============================================================

1. Write in natural Simplified Chinese used by Malaysian Chinese news media.
2. Do NOT translate Malay word-by-word.
3. Preserve the exact factual meaning.
4. Headlines must be concise, natural and professional.
5. Do not use awkward machine-translation wording.
6. Use the full sentence context to determine meaning.
7. Proper nouns must follow the dictionary exactly.
8. Malaysian people's names should normally remain in Roman letters unless the dictionary provides a Chinese name.
9. Malaysian place names should use the dictionary translation when available; otherwise keep the original Roman spelling rather than inventing a translation.

============================================================
MALAY VERSION
============================================================

1. Write natural Malaysian Malay (Bahasa Melayu Malaysia).
2. Do not translate English/Malay source text mechanically.
3. Keep names, places, organisations, companies and events accurate.
4. Keep Malaysian proper nouns in their original form unless a standard Malay form is clearly required.
5. The Malay headline must sound like a real Malaysian news headline.

============================================================
CONTEXTUAL TRANSLATION RULES
============================================================

Natural translation is more important than word-for-word translation.

1. Do not translate individual Malay words first and then combine them.
2. Understand the complete sentence and surrounding context before translating.
3. Common Malay words can have different Chinese meanings depending on context.
4. Never force one fixed Chinese meaning onto a common word when the sentence requires another meaning.
5. If a literal Chinese translation sounds strange, unnatural or misleading, rewrite it naturally while preserving the original meaning.
6. Do not add information that is not present in the source.
7. Do not remove important factual information.

IMPORTANT EXAMPLES:

- "santai" does NOT always mean "轻松".
- In a portrait, photo, painting, expression or appearance context, "santai" may mean "自然", "亲切", "随和", "非正式" or "神态轻松", depending on the sentence.
- "Potret santai Tunku Abdul Rahman" should NOT be translated as "轻松的东姑肖像".
- Better Chinese choices include "东姑阿都拉曼亲切肖像", "东姑阿都拉曼一幅神态自然的肖像" or "东姑阿都拉曼非正式肖像", depending on context.
- "menarik tumpuan" may naturally mean "引起关注", "吸引关注", "成为焦点", "受到关注" or "成为亮点".
- "menjadi tarikan utama" may naturally mean "成为主要亮点", "成为主要看点" or "成为焦点".

Do not blindly copy these examples. Choose the most natural meaning according to the actual sentence.

============================================================
TRANSLATION QUALITY CONTROL
============================================================

Before returning the answer, silently check:

1. Are all people names correct?
2. Are all Malaysian place names correct?
3. Are organisations, companies, brands and events correct?
4. Did you follow the proper noun dictionary exactly?
5. Did you accidentally translate a proper noun into an invented Chinese name?
6. Did you translate common Malay words according to context?
7. Does the Chinese sound like natural Malaysian Chinese news writing?
8. Does the Malay sound like natural Malaysian Malay news writing?
9. Are dates, numbers, amounts and titles accurate?
10. Did you preserve the original factual meaning?
11. Did you add anything that was not in the source?
12. Did you remove any important fact?
13. Avoid awkward literal phrases such as "轻松的东姑肖像" when the context means a relaxed, natural or informal portrait.

============================================================
GENERAL RULES
============================================================

1. Do NOT invent facts.
2. Do NOT speculate.
3. Do NOT add opinions.
4. Do NOT add information from outside the source.
5. Chinese must be Simplified Chinese.
6. Malay must be natural Malaysian Malay.
7. Keep both versions short: 1-2 sentences each.
8. Do not include URLs.
9. Do not use Markdown.
10. Do not add hashtags.
11. Do not mention AI.
12. Return ONLY valid JSON.

============================================================
OUTPUT
============================================================

Return exactly this JSON object and nothing else:

{{
  "zh_title": "...",
  "zh_body": "...",
  "ms_title": "...",
  "ms_body": "..."
}}
"""

    max_attempts = 3
    last_error = ""

    for attempt in range(1, max_attempts + 1):
        try:
            current_prompt = prompt
            if attempt > 1:
                current_prompt += f"""

============================================================
RETRY CORRECTION
============================================================

The previous output failed validation.

Validation error:
{last_error}

Correct ONLY the identified problems.
Do not change factual information.
Pay special attention to Malaysian proper nouns and contextual Malay-to-Chinese translation.
Return ONLY the JSON object.
"""

            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a highly accurate Malaysian news editor "
                            "and translation system. Return ONLY valid JSON."
                        )
                    },
                    {
                        "role": "user",
                        "content": current_prompt
                    }
                ],
                temperature=0.1,
            )

            output = (
                response.choices[0].message.content or ""
            ).strip()

            logger.info(
                "Groq AI response attempt %s: %s",
                attempt,
                output[:1000]
            )

            json_match = re.search(
                r"\{[^{}]*\}",
                output,
                re.DOTALL
            )

            if json_match:
                output = json_match.group()
            else:
                start = output.find("{")
                end = output.rfind("}") + 1
                if start != -1 and end > start:
                    output = output[start:end]

            if not output:
                raise ValueError("No JSON found in AI response")

            data = json.loads(output)

            required = [
                "zh_title",
                "zh_body",
                "ms_title",
                "ms_body",
            ]

            for key in required:
                value = clean_text(data.get(key, ""))
                if not value:
                    raise ValueError(
                        f"Missing AI field: {key}"
                    )
                data[key] = value

            valid, error_message = validate_proper_nouns(
                article,
                data,
                terms_data
            )

            if not valid:
                last_error = error_message
                logger.warning(
                    "Proper noun validation failed: %s",
                    error_message
                )
                continue

            return data

        except json.JSONDecodeError as e:
            last_error = f"JSON decode error: {e}"
            logger.error(last_error)
            logger.info(
                "Raw output: %s",
                output[:1000] if output else "(empty)"
            )

        except Exception as e:
            last_error = str(e)
            logger.error(
                "Groq AI attempt %s failed: %s",
                attempt,
                e
            )

    logger.error(
        "AI failed after %s attempts: %s",
        max_attempts,
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
    # DETERMINE MODE
    # --------------------------------------------------------

    # 直接使用 NEWS 模式
    logger.info(
        "Selected mode: NEWS"
    )

    article = select_news(
        posted_set
    )

    if not article:

        logger.warning(
            "No new Malaysia news with image available."
        )

        return

    # --------------------------------------------------------
    # LOG
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

        # Do not mark as posted.
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
