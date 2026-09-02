import os
import re
import json
import time
import hashlib
import logging
from typing import Any, Dict, List, Optional

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
# JSON = Knowledge / Rules
# Python = Logic / Validation
#
# ============================================================


# ============================================================
# CONFIG
# ============================================================

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

GNEWS_BASE_URL = "https://gnews.io/api/v4"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

GROQ_MODEL = "openai/gpt-oss-20b"

REQUEST_TIMEOUT = 20

MAX_GNEWS_ARTICLES = 10
MAX_POSTED = 1000
MAX_AI_ATTEMPTS = 3
AI_MAX_TOKENS = 1200

POSTED_FILE = "posted.json"
STATE_FILE = "bot_state.json"
TERMS_FILE = "malaysia_terms.json"


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("MYBUZZ")


# ============================================================
# API CLIENT
# ============================================================

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url=GROQ_BASE_URL,
    max_retries=0
)


# ============================================================
# NON TERM CATEGORIES
# ============================================================

NON_TERM_CATEGORIES = {
    "MALAY_STYLE",
    "CHINESE_STYLE",
    "TRANSLATION_RULES",
    "NEWS_STRUCTURE"
}


# ============================================================
# BASIC HELPERS
# ============================================================

def clean_text(value: Any) -> str:
    if value is None:
        return ""

    value = str(value)

    value = value.replace("\x00", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_url(url: str) -> str:
    url = clean_text(url)

    if not url:
        return ""

    url = url.split("#")[0]

    return url.rstrip("/")


def article_id(article: Dict[str, Any]) -> str:
    url = normalize_url(article.get("url", ""))

    if url:
        return hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()

    raw = (
        clean_text(article.get("title", "")) +
        "|" +
        clean_text(article.get("publishedAt", ""))
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


# ============================================================
# FILE STORAGE
# ============================================================

def load_posted() -> List[str]:
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
            items = data.get("posted", [])

            if isinstance(items, list):
                return items

    except Exception as e:
        logger.warning(
            "Failed to load posted database: %s",
            e
        )

    return []


def save_posted(posted: List[str]) -> None:
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


def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

    except Exception as e:
        logger.warning(
            "Failed to load state: %s",
            e
        )

    return {}


def save_state(state: Dict[str, Any]) -> None:
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


def advance_counter() -> int:
    state = load_state()

    counter = int(
        state.get("counter", 0)
    )

    counter += 1

    state["counter"] = counter

    save_state(state)

    return counter


# ============================================================
# API CONFIG CHECK
# ============================================================

def check_api_configuration() -> bool:

    logger.info(
        "Checking API configuration..."
    )

    missing = []

    if not GNEWS_API_KEY:
        missing.append("GNEWS_API_KEY")

    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY")

    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")

    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:

        logger.error(
            "Missing API configuration: %s",
            ", ".join(missing)
        )

        return False

    logger.info(
        "API configuration OK."
    )

    return True


# ============================================================
# GNEWS REQUEST
# ============================================================

def gnews_request(
    params: Dict[str, Any]
) -> Optional[Dict[str, Any]]:

    url = f"{GNEWS_BASE_URL}/search"

    params = dict(params)

    params["apikey"] = GNEWS_API_KEY

    try:

        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        logger.info(
            "GNews HTTP status: %s",
            response.status_code
        )

        response.raise_for_status()

        return response.json()

    except Exception as e:

        logger.error(
            "GNews request failed: %s",
            e
        )

        return None


# ============================================================
# FETCH NEWS
# ============================================================

def fetch_news() -> List[Dict[str, Any]]:

    logger.info(
        "Fetching Malaysia news..."
    )

    params = {
        "q": "Malaysia OR Malaysian",
        "lang": "en",
        "country": "my",
        "max": MAX_GNEWS_ARTICLES,
        "sortby": "publishedAt"
    }

    data = gnews_request(params)

    if not data:
        return []

    articles = data.get(
        "articles",
        []
    )

    usable = []

    for article in articles:

        if not isinstance(article, dict):
            continue

        title = clean_text(
            article.get("title")
        )

        description = clean_text(
            article.get("description")
        )

        content = clean_text(
            article.get("content")
        )

        url = normalize_url(
            article.get("url")
        )

        source = article.get(
            "source",
            {}
        )

        source_name = clean_text(
            source.get("name")
            if isinstance(source, dict)
            else source
        )

        if not title:
            continue

        if not url:
            continue

        if not description and not content:
            continue

        article["title"] = title

        article["description"] = description[:1500]

        article["content"] = content[:3000]

        article["url"] = url

        article["_source_name"] = source_name

        usable.append(article)

    logger.info(
        "GNews usable articles: %s",
        len(usable)
    )

    return usable


# ============================================================
# IMAGE
# ============================================================

def find_image_from_page(
    url: str
) -> Optional[str]:

    if not url:
        return None

    try:

        headers = {
            "User-Agent":
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/151.0 Safari/537.36"
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            return None

        html = response.text

        patterns = [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']'
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                html,
                re.IGNORECASE
            )

            if match:

                image_url = clean_text(
                    match.group(1)
                )

                if image_url.startswith("//"):
                    image_url = "https:" + image_url

                if image_url.startswith("http"):
                    return image_url

    except Exception as e:

        logger.warning(
            "Failed to find page image: %s",
            e
        )

    return None


# ============================================================
# SELECT NEWS
# ============================================================

def select_news(
    articles: List[Dict[str, Any]],
    posted: List[str]
) -> Optional[Dict[str, Any]]:

    posted_set = set(posted)

    for article in articles:

        aid = article_id(article)

        title = article.get(
            "title",
            ""
        )

        if aid in posted_set:

            logger.info(
                "Duplicate news skipped: %s",
                title
            )

            continue

        image = (
            article.get("image") or
            article.get("image_url")
        )

        if not image:

            image = find_image_from_page(
                article.get("url", "")
            )

        if not image:

            logger.info(
                "News skipped because no image: %s",
                title
            )

            continue

        article["_id"] = aid
        article["_image"] = image

        logger.info(
            "Selected type: NEWS"
        )

        logger.info(
            "Selected title: %s",
            title
        )

        logger.info(
            "Selected source: %s",
            article.get("_source_name", "")
        )

        logger.info(
            "Selected image: %s",
            image
        )

        return article

    return None


# ============================================================
# LOAD MALAYSIA TERMS JSON
# ============================================================

def load_terms() -> Dict[str, Any]:

    if not os.path.exists(TERMS_FILE):

        raise FileNotFoundError(
            f"{TERMS_FILE} not found"
        )

    with open(
        TERMS_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        data = json.load(f)

    if not isinstance(data, dict):

        raise ValueError(
            "malaysia_terms.json must contain a JSON object."
        )

    logger.info(
        "Malaysia terms loaded successfully."
    )

    return data


# ============================================================
# FLATTEN PROPER NOUNS
# ============================================================

def flatten_terms(
    data: Dict[str, Any]
) -> Dict[str, str]:

    result = {}

    for category, values in data.items():

        if category in NON_TERM_CATEGORIES:
            continue

        if not isinstance(values, dict):
            continue

        for source, target in values.items():

            source = clean_text(source)
            target = clean_text(target)

            if not source:
                continue

            if isinstance(target, str):

                result[source] = target

    return result


# ============================================================
# BUILD TERMS TEXT
# ============================================================

def build_terms_text(
    data: Dict[str, Any],
    selected_terms: Optional[List[str]] = None
) -> str:

    all_terms = flatten_terms(data)

    if selected_terms is not None:

        selected_set = set(
            selected_terms
        )

        all_terms = {
            k: v
            for k, v in all_terms.items()
            if k in selected_set
        }

    if not all_terms:

        return "No relevant proper noun mapping found."

    grouped = {}

    for source, target in all_terms.items():

        for category, values in data.items():

            if category in NON_TERM_CATEGORIES:
                continue

            if not isinstance(values, dict):
                continue

            if source in values:

                grouped.setdefault(
                    category,
                    []
                ).append(
                    f"{source} → {target}"
                )

                break

    output = []

    for category, items in grouped.items():

        output.append(
            f"[{category}]"
        )

        output.extend(
            sorted(items)
        )

        output.append("")

    return "\n".join(output).strip()


# ============================================================
# BUILD RULE TEXT
# ============================================================

def build_rule_text(
    data: Dict[str, Any],
    category: str
) -> str:

    value = data.get(category)

    if value is None:

        return (
            f"No {category} rules found "
            "in malaysia_terms.json."
        )

    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2
    )


# ============================================================
# FIND PROPER NOUNS ACTUALLY USED IN ARTICLE
# ============================================================

def find_relevant_terms(
    source_text: str,
    data: Dict[str, Any]
) -> List[str]:

    source_text = clean_text(
        source_text
    )

    if not source_text:
        return []

    all_terms = flatten_terms(data)

    matches = []

    # Longer names first
    candidates = sorted(
        all_terms.keys(),
        key=len,
        reverse=True
    )

    for term in candidates:

        if not term:
            continue

        # Case insensitive for Latin text
        pattern = re.escape(term)

        try:

            if re.search(
                pattern,
                source_text,
                re.IGNORECASE
            ):

                matches.append(term)

        except Exception:
            continue

    # Remove duplicates while preserving order
    unique = []

    seen = set()

    for term in matches:

        if term not in seen:

            seen.add(term)
            unique.append(term)

    return unique


# ============================================================
# PROPER NOUN VALIDATION
# ============================================================

def validate_proper_nouns(
    source_text: str,
    zh_text: str,
    ms_text: str,
    data: Dict[str, Any]
) -> List[str]:

    errors = []

    all_terms = flatten_terms(data)

    relevant_terms = find_relevant_terms(
        source_text,
        data
    )

    for source_term in relevant_terms:

        expected = all_terms.get(
            source_term,
            ""
        )

        if not expected:
            continue

        # Malay
        #
        # Malay can normally retain original
        # English / Malay proper noun.
        #
        # We only reject if AI invents a clearly
        # wrong dictionary translation.
        #
        if expected != "KEEP ORIGINAL":

            # If dictionary has a Chinese mapping,
            # Chinese output should normally contain it
            # if the source term is translated.
            if source_term.lower() in zh_text.lower():

                if expected not in zh_text:

                    errors.append(
                        f"Chinese proper noun mismatch: "
                        f"{source_term} → {expected}"
                    )

    return errors


# ============================================================
# EXTRACT JSON FROM AI RESPONSE
# ============================================================

def extract_json(
    text: str
) -> Optional[Dict[str, Any]]:

    if not text:
        return None

    text = text.strip()

    # Remove markdown code fence
    text = re.sub(
        r"^```(?:json)?",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"```$",
        "",
        text
    )

    text = text.strip()

    first = text.find("{")
    last = text.rfind("}")

    if first == -1 or last == -1:
        return None

    candidate = text[first:last + 1]

    try:

        data = json.loads(
            candidate
        )

        if isinstance(data, dict):
            return data

    except Exception as e:

        logger.warning(
            "Failed to parse AI JSON: %s",
            e
        )

    return None


# ============================================================
# VALIDATE AI FIELDS
# ============================================================

def validate_ai_fields(
    data: Dict[str, Any]
) -> List[str]:

    required = [
        "zh_title",
        "zh_body",
        "ms_title",
        "ms_body"
    ]

    errors = []

    for field in required:

        value = data.get(field)

        if not isinstance(value, str):
            errors.append(
                f"Missing or invalid field: {field}"
            )
            continue

        if not value.strip():
            errors.append(
                f"Empty field: {field}"
            )

    return errors


# ============================================================
# BUILD SOURCE ARTICLE
# ============================================================

def build_source_article(
    article: Dict[str, Any]
) -> str:

    title = clean_text(
        article.get("title")
    )

    description = clean_text(
        article.get("description")
    )

    content = clean_text(
        article.get("content")
    )

    source = clean_text(
        article.get("_source_name")
    )

    published = clean_text(
        article.get("publishedAt")
    )

    url = clean_text(
        article.get("url")
    )

    parts = [
        f"TITLE: {title}",
        f"SOURCE: {source}",
        f"PUBLISHED: {published}",
        f"DESCRIPTION: {description}",
        f"CONTENT: {content}",
        f"URL: {url}"
    ]

    return "\n".join(parts)


# ============================================================
# BUILD GROQ PROMPT
# ============================================================

def build_groq_prompt(
    article: Dict[str, Any],
    data: Dict[str, Any]
) -> str:

    source_article = build_source_article(
        article
    )

    # Only send terms that actually occur
    # in this article.
    relevant_terms = find_relevant_terms(
        source_article,
        data
    )

    terms_text = build_terms_text(
        data,
        relevant_terms
    )

    malay_style_text = build_rule_text(
        data,
        "MALAY_STYLE"
    )

    chinese_style_text = build_rule_text(
        data,
        "CHINESE_STYLE"
    )

    translation_rules_text = build_rule_text(
        data,
        "TRANSLATION_RULES"
    )

    news_structure_text = build_rule_text(
        data,
        "NEWS_STRUCTURE"
    )

    prompt = f"""
You are the senior bilingual editor for a Malaysian news portal.

Your task is to rewrite the SOURCE ARTICLE into:

1. Natural Malaysian Chinese news
2. Natural Malaysian Malay news

This is NOT sentence-by-sentence machine translation.

The final writing must sound like it was originally written by a Malaysian journalist.

============================================================
SOURCE ARTICLE
============================================================

{source_article}

============================================================
RELEVANT PROPER NOUN DICTIONARY
============================================================

Only the proper nouns relevant to this article are included below.

{terms_text}

============================================================
TRANSLATION RULES
============================================================

The following rules come directly from malaysia_terms.json.

{translation_rules_text}

============================================================
NEWS STRUCTURE
============================================================

The following rules come directly from malaysia_terms.json.

{news_structure_text}

============================================================
MALAY STYLE
============================================================

The following rules come directly from malaysia_terms.json.

{malay_style_text}

============================================================
CHINESE STYLE
============================================================

The following rules come directly from malaysia_terms.json.

{chinese_style_text}

============================================================
RULE PRIORITY
============================================================

Follow this priority:

1. Factual accuracy
2. Translation rules
3. Proper noun dictionary
4. News structure
5. Language style
6. Natural expression

Never sacrifice factual accuracy for natural wording.

============================================================
FACTUAL ACCURACY
============================================================

You MUST preserve:

- Names
- Locations
- Dates
- Times
- Numbers
- Percentages
- Currency
- Quantities
- Causality
- Attribution
- Uncertainty
- Allegations
- Predictions
- Expected outcomes

Do NOT invent facts.

Do NOT add background information that is not in the source.

Do NOT remove important facts.

Do NOT turn an expected / projected / possible event into a confirmed fact.

Do NOT turn an allegation into a confirmed fact.

============================================================
PROPER NOUNS
============================================================

Use the dictionary when a proper noun appears in the source.

Do not invent Chinese names.

If the dictionary says KEEP ORIGINAL, keep the original name.

People and companies may remain in their original English/Malay form when appropriate.

============================================================
MONEY
============================================================

Pay special attention to Malaysian money conversion.

Examples:

RM85亿 = RM8.5 billion = RM8.5 bilion

RM8.5 billion = RM85亿令吉

RM85 billion = RM850亿令吉

NEVER translate:

RM85亿 → RM85 billion

That would change the actual amount by 10 times.

Never change or round numbers.

============================================================
WRITING QUALITY
============================================================

Rewrite naturally.

Do not preserve unnatural English sentence structure.

Do not translate word-for-word when that produces unnatural Malaysian Chinese or Malay.

For Chinese:

Use Malaysian Chinese news vocabulary and natural Malaysian news structure.

For Malay:

Use modern Malaysian Malay used by Malaysian news portals.

Avoid Indonesian-style wording.

Avoid Mainland China-style stiff news wording in Chinese.

Avoid slang.

Avoid clickbait.

============================================================
OUTPUT
============================================================

Return ONLY valid JSON.

Do not use Markdown.

Do not add explanations.

Do not add comments.

The JSON MUST end with }}.

Required format:

{{
  "zh_title": "...",
  "zh_body": "...",
  "ms_title": "...",
  "ms_body": "..."
}}

Make sure the final character is }}.
"""

    return prompt


# ============================================================
# GROQ ERROR CLASSIFICATION
# ============================================================

def is_prompt_too_large(
    error: Exception
) -> bool:

    text = str(error).lower()

    return (
        "413" in text
        or
        "request too large" in text
        or
        "tokens per minute" in text
        or
        "rate_limit_exceeded" in text
    )


# ============================================================
# GENERATE AI CONTENT
# ============================================================

def generate_ai_content(
    article: Dict[str, Any],
    data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:

    prompt = build_groq_prompt(
        article,
        data
    )

    for attempt in range(
        1,
        MAX_AI_ATTEMPTS + 1
    ):

        try:

            logger.info(
                "Sending Groq request attempt %s/%s",
                attempt,
                MAX_AI_ATTEMPTS
            )

            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.2,
                max_tokens=AI_MAX_TOKENS
            )

            choice = response.choices[0]

            finish_reason = getattr(
                choice,
                "finish_reason",
                None
            )

            if finish_reason in (
                "length",
                "max_tokens"
            ):

                logger.warning(
                    "Groq response reached max tokens."
                )

            content = choice.message.content

            result = extract_json(
                content
            )

            if not result:

                logger.error(
                    "AI returned invalid JSON."
                )

                if attempt < MAX_AI_ATTEMPTS:

                    wait = 5 * attempt

                    logger.info(
                        "Retrying Groq in %s seconds...",
                        wait
                    )

                    time.sleep(wait)

                    continue

                return None

            field_errors = validate_ai_fields(
                result
            )

            if field_errors:

                logger.error(
                    "AI field validation failed: %s",
                    " | ".join(field_errors)
                )

                if attempt < MAX_AI_ATTEMPTS:

                    wait = 5 * attempt

                    logger.info(
                        "Retrying Groq in %s seconds...",
                        wait
                    )

                    time.sleep(wait)

                    continue

                return None

            source_text = build_source_article(
                article
            )

            noun_errors = validate_proper_nouns(
                source_text,
                result["zh_title"] + "\n" + result["zh_body"],
                result["ms_title"] + "\n" + result["ms_body"],
                data
            )

            if noun_errors:

                logger.error(
                    "Proper noun validation failed: %s",
                    " | ".join(noun_errors)
                )

                if attempt < MAX_AI_ATTEMPTS:

                    wait = 3 * attempt

                    logger.info(
                        "Retrying Groq due to validation failure "
                        "in %s seconds...",
                        wait
                    )

                    time.sleep(wait)

                    continue

                return None

            logger.info(
                "Groq AI content generated successfully."
            )

            return result

        except Exception as e:

            logger.error(
                "Groq AI attempt %s failed: %s",
                attempt,
                e
            )

            # Important:
            # If request itself is too large,
            # retrying the exact same prompt will
            # never solve the problem.
            if is_prompt_too_large(e):

                logger.error(
                    "Groq request exceeds the current TPM "
                    "limit. The request should be reduced, "
                    "not repeatedly retried."
                )

                return None

            if attempt < MAX_AI_ATTEMPTS:

                wait = 5 * attempt

                logger.info(
                    "Retrying Groq in %s seconds...",
                    wait
                )

                time.sleep(wait)

    logger.error(
        "AI failed after %s attempts.",
        MAX_AI_ATTEMPTS
    )

    return None


# ============================================================
# TELEGRAM
# ============================================================

def telegram_api_url(
    method: str
) -> str:

    return (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/"
        f"{method}"
    )


# ============================================================
# TELEGRAM SEND PHOTO
# ============================================================

def send_telegram_photo(
    image_url: str,
    caption: str
) -> bool:

    url = telegram_api_url(
        "sendPhoto"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "photo": image_url,
        "caption": caption,
        "parse_mode": "HTML"
    }

    try:

        response = requests.post(
            url,
            data=payload,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:

            logger.error(
                "Telegram sendPhoto HTTP %s: %s",
                response.status_code,
                response.text[:1000]
            )

            return False

        data = response.json()

        if not data.get("ok"):

            logger.error(
                "Telegram sendPhoto failed: %s",
                data
            )

            return False

        logger.info(
            "Telegram photo sent successfully."
        )

        return True

    except Exception as e:

        logger.error(
            "Telegram photo request failed: %s",
            e
        )

        return False


# ============================================================
# TELEGRAM SEND TEXT
# ============================================================

def send_telegram_text(
    text: str
) -> bool:

    url = telegram_api_url(
        "sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }

    try:

        response = requests.post(
            url,
            data=payload,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:

            logger.error(
                "Telegram sendMessage HTTP %s: %s",
                response.status_code,
                response.text[:1000]
            )

            return False

        data = response.json()

        if not data.get("ok"):

            logger.error(
                "Telegram sendMessage failed: %s",
                data
            )

            return False

        logger.info(
            "Telegram text sent successfully."
        )

        return True

    except Exception as e:

        logger.error(
            "Telegram text request failed: %s",
            e
        )

        return False


# ============================================================
# ESCAPE TELEGRAM HTML
# ============================================================

def telegram_escape(
    text: str
) -> str:

    if not text:
        return ""

    text = str(text)

    text = text.replace(
        "&",
        "&amp;"
    )

    text = text.replace(
        "<",
        "&lt;"
    )

    text = text.replace(
        ">",
        "&gt;"
    )

    return text


# ============================================================
# BUILD TELEGRAM MESSAGE
# ============================================================

def build_telegram_caption(
    article: Dict[str, Any],
    ai: Dict[str, Any]
) -> str:

    zh_title = telegram_escape(
        ai.get("zh_title", "")
    )

    zh_body = telegram_escape(
        ai.get("zh_body", "")
    )

    ms_title = telegram_escape(
        ai.get("ms_title", "")
    )

    ms_body = telegram_escape(
        ai.get("ms_body", "")
    )

    url = clean_text(
        article.get("url", "")
    )

    source = telegram_escape(
        article.get("_source_name", "")
    )

    caption = (
        "🇲🇾 <b>MYBuzz NEWS</b>\n\n"
        f"<b>{zh_title}</b>\n\n"
        f"{zh_body}\n\n"
        f"<b>{ms_title}</b>\n\n"
        f"{ms_body}\n\n"
        f"Source: {source}\n"
        f'<a href="{url}">Read Full Article</a>'
    )

    return caption


# ============================================================
# SEND NEWS
# ============================================================

def send_news_to_telegram(
    article: Dict[str, Any],
    ai: Dict[str, Any]
) -> bool:

    caption = build_telegram_caption(
        article,
        ai
    )

    image = article.get(
        "_image"
    )

    if image:

        # Telegram caption has a 1024 character limit.
        # If too long, use text fallback.
        if len(caption) <= 1024:

            success = send_telegram_photo(
                image,
                caption
            )

            if success:
                return True

            logger.warning(
                "Photo sending failed. Trying text fallback."
            )

        else:

            logger.warning(
                "Telegram caption exceeds 1024 characters. "
                "Using text fallback."
            )

    return send_telegram_text(
        caption
    )


# ============================================================
# MAIN
# ============================================================

def main() -> int:

    print(
        "======================================"
    )

    print(
        "MYBUZZ NEWS BOT START"
    )

    print(
        "======================================"
    )

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
    # API CHECK
    # --------------------------------------------------------

    if not check_api_configuration():

        logger.error(
            "API configuration invalid."
        )

        return 1

    # --------------------------------------------------------
    # POSTED DATABASE
    # --------------------------------------------------------

    posted = load_posted()

    logger.info(
        "Posted database: %s items",
        len(posted)
    )

    logger.info(
        "Selected mode: NEWS"
    )

    # --------------------------------------------------------
    # LOAD TERMS
    # --------------------------------------------------------

    try:

        terms_data = load_terms()

    except Exception as e:

        logger.error(
            "Failed to load malaysia_terms.json: %s",
            e
        )

        return 1

    # --------------------------------------------------------
    # FETCH NEWS
    # --------------------------------------------------------

    articles = fetch_news()

    if not articles:

        logger.info(
            "No usable news found."
        )

        return 0

    # --------------------------------------------------------
    # SELECT NEWS
    # --------------------------------------------------------

    article = select_news(
        articles,
        posted
    )

    if not article:

        logger.info(
            "No new news available."
        )

        return 0

    # --------------------------------------------------------
    # GENERATE AI
    # --------------------------------------------------------

    ai = generate_ai_content(
        article,
        terms_data
    )

    if not ai:

        logger.error(
            "AI failed. Nothing sent."
        )

        return 1

    # --------------------------------------------------------
    # LOG AI RESULT
    # --------------------------------------------------------

    logger.info(
        "AI Chinese title: %s",
        ai.get("zh_title", "")
    )

    logger.info(
        "AI Malay title: %s",
        ai.get("ms_title", "")
    )

    # --------------------------------------------------------
    # SEND TELEGRAM
    # --------------------------------------------------------

    success = send_news_to_telegram(
        article,
        ai
    )

    if not success:

        logger.error(
            "Telegram failed. "
            "News will NOT be marked as posted."
        )

        return 1

    # --------------------------------------------------------
    # ONLY MARK POSTED AFTER SUCCESS
    # --------------------------------------------------------

    aid = article.get(
        "_id"
    )

    if aid:

        posted.append(aid)

        save_posted(
            posted
        )

        logger.info(
            "News marked as posted."
        )

    # --------------------------------------------------------
    # COUNTER
    # --------------------------------------------------------

    counter = advance_counter()

    logger.info(
        "Bot counter: %s",
        counter
    )

    logger.info(
        "======================================"
    )

    logger.info(
        "MYBUZZ BOT FINISHED SUCCESSFULLY"
    )

    logger.info(
        "======================================"
    )

    return 0


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        exit_code = main()

        raise SystemExit(
            exit_code
        )

    except KeyboardInterrupt:

        logger.warning(
            "Bot interrupted."
        )

        raise SystemExit(130)

    except Exception as e:

        logger.exception(
            "Unexpected fatal error: %s",
            e
        )

        raise SystemExit(1)
