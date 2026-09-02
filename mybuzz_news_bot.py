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
# malaysia_terms.json
#       ↓
# Groq AI
#       ↓
# Proper Noun Protection
#       ↓
# Translation Validation
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

MAX_AI_RETRIES = 2


# ============================================================
# HEADERS
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "MYBUZZ-News-Bot/2.0"
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
# LOAD MALAYSIA TERMS
# ============================================================

def load_malaysia_terms():

    if not os.path.exists(
        TERMS_FILE
    ):

        logger.warning(
            "Malaysia terms file not found: %s",
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

            logger.error(
                "Malaysia terms must be a JSON object."
            )

            return {}


        total = 0

        for category, terms in data.items():

            if isinstance(
                terms,
                dict
            ):

                total += len(
                    terms
                )


        logger.info(
            "Malaysia terms loaded: %s terms",
            total
        )

        return data


    except json.JSONDecodeError as e:

        logger.error(
            "Malaysia terms JSON error: %s",
            e
        )

        return {}


    except Exception as e:

        logger.error(
            "Could not read Malaysia terms: %s",
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

            flattened[
                original
            ] = translation


    return flattened


# ============================================================
# BUILD TERMS TEXT
# ============================================================

def build_terms_text(terms):

    if not terms:

        return (
            "No Malaysia proper noun dictionary "
            "is currently available."
        )


    sections = []


    for category, values in terms.items():

        if not isinstance(
            values,
            dict
        ):
            continue


        lines = []


        for original, translation in values.items():

            original = clean_text(
                original
            )

            translation = clean_text(
                translation
            )


            if translation:

                lines.append(
                    f"{original} = {translation}"
                )

            else:

                lines.append(
                    f"{original} = KEEP ORIGINAL"
                )


        if lines:

            section = (
                f"[{category.upper()}]\n"
                + "\n".join(lines)
            )

            sections.append(
                section
            )


    return "\n\n".join(
        sections
    )


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
# EXTRACT JSON FROM AI
# ============================================================

def extract_json(output):

    if not output:
        return None


    output = output.strip()


    # Remove markdown code fence

    output = re.sub(
        r"^```json\s*",
        "",
        output,
        flags=re.IGNORECASE
    )

    output = re.sub(
        r"^```\s*",
        "",
        output
    )

    output = re.sub(
        r"\s*```$",
        "",
        output
    )


    # First try entire output

    try:

        return json.loads(
            output
        )

    except Exception:

        pass


    # Find JSON object

    start = output.find(
        "{"
    )

    end = output.rfind(
        "}"
    )


    if start == -1 or end <= start:

        return None


    candidate = output[
        start:end + 1
    ]


    try:

        return json.loads(
            candidate
        )

    except Exception:

        return None


# ============================================================
# VALIDATE AI FIELDS
# ============================================================

def validate_ai_fields(data):

    required = [

        "zh_title",
        "zh_body",

        "ms_title",
        "ms_body",

    ]


    if not isinstance(
        data,
        dict
    ):

        return False


    for key in required:

        value = data.get(
            key
        )


        if not value:

            logger.error(
                "Missing AI field: %s",
                key
            )

            return False


        if not isinstance(
            value,
            str
        ):

            return False


    return True


# ============================================================
# PROPER NOUN VALIDATION
# ============================================================

def validate_proper_nouns(
    original_text,
    ai_data,
    terms
):

    if not terms:
        return True


    zh_text = (
        ai_data.get(
            "zh_title",
            ""
        )
        + " "
        + ai_data.get(
            "zh_body",
            ""
        )
    )


    ms_text = (
        ai_data.get(
            "ms_title",
            ""
        )
        + " "
        + ai_data.get(
            "ms_body",
            ""
        )
    )


    original_lower = (
        original_text.lower()
    )


    problems = []


    for original, translation in terms.items():

        original_clean = clean_text(
            original
        )


        translation_clean = clean_text(
            translation
        )


        if not original_clean:
            continue


        # Only check terms actually appearing
        # in the source article.

        if original_clean.lower() not in original_lower:

            continue


        # KEEP ORIGINAL terms

        if not translation_clean:

            if (
                original_clean.lower()
                not in ms_text.lower()
            ):

                problems.append(
                    f"{original_clean} should remain unchanged in Malay"
                )

            continue


        # Chinese dictionary translation

        if translation_clean not in zh_text:

            problems.append(
                f"{original_clean} -> {translation_clean} missing from Chinese output"
            )


    if problems:

        logger.warning(
            "Proper noun validation failed:"
        )


        for problem in problems[:20]:

            logger.warning(
                "  %s",
                problem
            )


        return False


    return True


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


    # --------------------------------------------------------
    # LOAD DICTIONARY
    # --------------------------------------------------------

    malaysia_terms = (
        load_malaysia_terms()
    )


    flattened_terms = (
        flatten_terms(
            malaysia_terms
        )
    )


    terms_text = (
        build_terms_text(
            malaysia_terms
        )
    )


    # --------------------------------------------------------
    # SOURCE TEXT
    # --------------------------------------------------------

    original_text = (
        f"SOURCE: {source}\n\n"
        f"TITLE: {title}\n\n"
        f"CONTENT: {description}"
    )


    # --------------------------------------------------------
    # PROMPT
    # --------------------------------------------------------

    prompt = f"""
You are the MYBUZZ Malaysia news editor.

Create ONE short bilingual Malaysian Telegram news post.

SOURCE:
{source}

TITLE:
{title}

CONTENT:
{description}


============================================================
MALAYSIA PROPER NOUN DICTIONARY
============================================================

{terms_text}


============================================================
VERY IMPORTANT PROPER NOUN RULES
============================================================

1. The Malaysia proper noun dictionary is authoritative.

2. If a person, place, state, government agency,
   organization, company, brand, university, hospital,
   shopping mall or other proper noun exists in the dictionary,
   follow the exact instruction in the dictionary.

3. NEVER invent a different Chinese translation for a
   dictionary entry.

4. NEVER translate a Malaysian person's name based only
   on pronunciation.

5. NEVER translate a Malaysian place name based only
   on pronunciation.

6. If a person's Chinese name is NOT in the dictionary,
   KEEP THE ORIGINAL NAME in the Chinese version.

7. If a Malaysian place name is NOT in the dictionary,
   KEEP THE ORIGINAL NAME in the Chinese version.

8. Company names and brand names should normally remain
   in their official form unless the dictionary provides
   an established Chinese name.

9. Shopping mall names should normally remain in their
   official form unless the dictionary provides an
   established Chinese name.

10. Restaurant names should normally remain in their
    official form unless the dictionary provides an
    established Chinese name.

11. Road names such as Jalan Tun Razak should not be
    randomly converted into Chinese.

12. Taman, Kampung, Bandar, Jalan, Lorong and similar
    Malaysian geographical names must NOT be randomly
    translated.

13. Do NOT create Chinese names for unknown Malaysian
    people or places.

14. Accuracy is more important than making every word
    Chinese.

15. Preserve the original spelling of Malaysian proper nouns.

16. Do not confuse different people with similar names.

17. Do not change a person's name into another person's name.

18. Do not invent titles, positions, locations, dates,
    numbers or other facts.


============================================================
CHINESE VERSION
============================================================

- Use Simplified Chinese.
- Natural Malaysian Chinese news style.
- Keep unknown Malaysian proper nouns in original form.
- Use dictionary translations when available.
- Do not use Taiwan-specific wording.
- Do not use Hong Kong-specific wording.
- Do not over-translate.


============================================================
MALAY VERSION
============================================================

- Use natural Malaysian Malay.
- Keep Malaysian proper nouns accurate.
- Do not translate people's names.
- Do not randomly translate place names.
- Do not change official organization names unnecessarily.


============================================================
GENERAL RULES
============================================================

1. Do NOT invent facts.
2. Only use information contained in the source.
3. Keep both Chinese and Malay versions short.
4. Each body should be approximately 1-2 sentences.
5. Do not include URLs.
6. Do not use Markdown.
7. Do not add hashtags.
8. Do not mention AI.
9. Do not add commentary.
10. Do not add information that is not in the source.
11. Return ONLY valid JSON.


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


    # --------------------------------------------------------
    # AI RETRY
    # --------------------------------------------------------

    for attempt in range(
        1,
        MAX_AI_RETRIES + 2
    ):

        try:

            logger.info(
                "Groq generation attempt %s",
                attempt
            )


            response = (
                client.chat.completions.create(

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
                            "content": prompt
                        }

                    ],

                    temperature=0.1,

                )
            )


            output = (
                response
                .choices[0]
                .message
                .content
                .strip()
            )


            data = extract_json(
                output
            )


            if not validate_ai_fields(
                data
            ):

                logger.warning(
                    "AI output validation failed."
                )

                continue


            # ------------------------------------------------
            # PROPER NOUN CHECK
            # ------------------------------------------------

            if not validate_proper_nouns(
                original_text,
                data,
                flattened_terms
            ):

                logger.warning(
                    "Proper noun validation failed."
                )

                # Tell next attempt exactly what happened.

                prompt += """

IMPORTANT:
The previous output failed proper noun validation.

Before returning the next answer, carefully check every
person name, Malaysian place name, organization name,
company name and other proper noun against the dictionary.

Do not invent Chinese names for unknown Malaysian proper nouns.

If a proper noun is not in the dictionary, keep the original
name.
"""

                continue


            logger.info(
                "AI content generated and validated successfully."
            )


            return data


        except json.JSONDecodeError as e:

            logger.warning(
                "JSON decode error: %s",
                e
            )


        except Exception as e:

            logger.error(
                "Groq AI failed: %s",
                e
            )


    logger.error(
        "AI failed after all attempts."
    )


    return None


# ============================================================
# TELEGRAM HTML ESCAPE
# ============================================================

def escape_html(text):

    return html.escape(
        str(text),
        quote=False
    )


# ============================================================
# TELEGRAM CAPTION
# ============================================================

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


    logger.info(
        "Chinese title: %s",
        ai.get(
            "zh_title"
        )
    )


    logger.info(
        "Malay title: %s",
        ai.get(
            "ms_title"
        )
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
