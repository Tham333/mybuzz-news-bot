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
# malaysia_terms.json
#       ↓
# Proper nouns
# Malay style
# Chinese style
# Translation rules
# News structure
#
# Python = logic / validation
# JSON    = knowledge / writing rules
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

# Keep completion smaller because Groq TPM includes
# requested input/output token budget.
AI_MAX_TOKENS = 900

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
# GROQ CLIENT
# ============================================================

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url=GROQ_BASE_URL,
    max_retries=0
)


# ============================================================
# JSON CATEGORIES THAT ARE NOT PROPER NOUN DICTIONARIES
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

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


def normalize_url(url: str) -> str:

    url = clean_text(url)

    if not url:
        return ""

    url = url.split("#")[0]

    return url.rstrip("/")


def article_id(
    article: Dict[str, Any]
) -> str:

    url = normalize_url(
        article.get("url", "")
    )

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
# POSTED DATABASE
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

            posted = data.get(
                "posted",
                []
            )

            if isinstance(posted, list):
                return posted

    except Exception as e:

        logger.warning(
            "Failed to load posted database: %s",
            e
        )

    return []


def save_posted(
    posted: List[str]
) -> None:

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


# ============================================================
# STATE
# ============================================================

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


def save_state(
    state: Dict[str, Any]
) -> None:

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
        state.get(
            "counter",
            0
        )
    )

    counter += 1

    state["counter"] = counter

    save_state(state)

    return counter


# ============================================================
# API CONFIGURATION
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
# GNEWS
# ============================================================

def gnews_request(
    params: Dict[str, Any]
) -> Optional[Dict[str, Any]]:

    url = (
        f"{GNEWS_BASE_URL}/search"
    )

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

    data = gnews_request(
        params
    )

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

        if isinstance(source, dict):

            source_name = clean_text(
                source.get("name")
            )

        else:

            source_name = clean_text(
                source
            )

        if not title:
            continue

        if not url:
            continue

        if not description and not content:
            continue

        article["title"] = title

        article["description"] = (
            description[:1500]
        )

        article["content"] = (
            content[:3000]
        )

        article["url"] = url

        article["_source_name"] = (
            source_name
        )

        usable.append(
            article
        )

    logger.info(
        "GNews usable articles: %s",
        len(usable)
    )

    return usable


# ============================================================
# FIND IMAGE
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

                    image_url = (
                        "https:" +
                        image_url
                    )

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

    posted_set = set(
        posted
    )

    for article in articles:

        aid = article_id(
            article
        )

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
            article.get("image")
            or
            article.get("image_url")
        )

        if not image:

            image = find_image_from_page(
                article.get(
                    "url",
                    ""
                )
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
            article.get(
                "_source_name",
                ""
            )
        )

        logger.info(
            "Selected image: %s",
            image
        )

        return article

    return None


# ============================================================
# LOAD JSON
# ============================================================

def load_terms() -> Dict[str, Any]:

    if not os.path.exists(
        TERMS_FILE
    ):

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
            "malaysia_terms.json must contain "
            "a JSON object."
        )

    logger.info(
        "Malaysia terms loaded successfully."
    )

    return data


# ============================================================
# FLATTEN PROPER NOUN DICTIONARY
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

            source = clean_text(
                source
            )

            target = clean_text(
                target
            )

            if not source:
                continue

            if not target:
                continue

            result[source] = target

    return result


# ============================================================
# BUILD RELEVANT PROPER NOUN TEXT
# ============================================================

def build_terms_text(
    data: Dict[str, Any],
    selected_terms: Optional[List[str]] = None
) -> str:

    all_terms = flatten_terms(
        data
    )

    if selected_terms is not None:

        selected_set = set(
            selected_terms
        )

        all_terms = {
            key: value
            for key, value in all_terms.items()
            if key in selected_set
        }

    if not all_terms:

        return "No relevant proper noun mapping."

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

    return "\n".join(
        output
    )


# ============================================================
# BUILD JSON RULE TEXT
# ============================================================

def build_rule_text(
    data: Dict[str, Any],
    category: str
) -> str:

    value = data.get(
        category
    )

    if value is None:

        return (
            f"No {category} rules."
        )

    # Compact JSON saves tokens.
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(
            ",",
            ":"
        )
    )


# ============================================================
# FIND RELEVANT PROPER NOUNS
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

    all_terms = flatten_terms(
        data
    )

    matches = []

    # Longer terms first.
    candidates = sorted(
        all_terms.keys(),
        key=len,
        reverse=True
    )

    for term in candidates:

        if not term:
            continue

        try:

            if re.search(
                re.escape(term),
                source_text,
                re.IGNORECASE
            ):

                matches.append(
                    term
                )

        except Exception:
            continue

    unique = []

    seen = set()

    for term in matches:

        if term not in seen:

            seen.add(
                term
            )

            unique.append(
                term
            )

    return unique


# ============================================================
# PROPER NOUN VALIDATION
# ============================================================
#
# IMPORTANT:
#
# Source:
# Malaysia
#
# Dictionary:
# Malaysia → 马来西亚
#
# Chinese:
# 马来西亚
#
# We check:
# expected "马来西亚" in Chinese
#
# NOT:
# "Malaysia" in Chinese
#
# ============================================================

def validate_proper_nouns(
    source_text: str,
    zh_text: str,
    ms_text: str,
    data: Dict[str, Any]
) -> List[str]:

    errors = []

    all_terms = flatten_terms(
        data
    )

    relevant_terms = find_relevant_terms(
        source_text,
        data
    )

    zh_text = clean_text(
        zh_text
    )

    ms_text = clean_text(
        ms_text
    )

    for source_term in relevant_terms:

        expected = all_terms.get(
            source_term,
            ""
        )

        if not expected:
            continue

        # ----------------------------------------------------
        # KEEP ORIGINAL
        # ----------------------------------------------------

        if expected == "KEEP ORIGINAL":

            # Original term should normally be retained,
            # but we do not reject the article solely because
            # a term disappeared during natural restructuring.

            continue

        # ----------------------------------------------------
        # CHINESE VALIDATION
        # ----------------------------------------------------

        # If source contains:
        #
        # Malaysia
        #
        # expected:
        #
        # 马来西亚
        #
        # Chinese output must contain the expected mapping.

        if expected not in zh_text:

            errors.append(
                f"Chinese proper noun mismatch: "
                f"{source_term} → {expected}"
            )

    return errors


# ============================================================
# EXTRACT JSON
# ============================================================

def extract_json(
    text: str
) -> Optional[Dict[str, Any]]:

    if not text:
        return None

    text = text.strip()

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

    first = text.find(
        "{"
    )

    last = text.rfind(
        "}"
    )

    if first == -1 or last == -1:
        return None

    candidate = text[
        first:last + 1
    ]

    try:

        result = json.loads(
            candidate
        )

        if isinstance(
            result,
            dict
        ):

            return result

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

        value = data.get(
            field
        )

        if not isinstance(
            value,
            str
        ):

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
        article.get(
            "title"
        )
    )

    description = clean_text(
        article.get(
            "description"
        )
    )

    content = clean_text(
        article.get(
            "content"
        )
    )

    source = clean_text(
        article.get(
            "_source_name"
        )
    )

    published = clean_text(
        article.get(
            "publishedAt"
        )
    )

    return (
        f"TITLE: {title}\n"
        f"SOURCE: {source}\n"
        f"PUBLISHED: {published}\n"
        f"DESCRIPTION: {description}\n"
        f"CONTENT: {content}"
    )


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

    relevant_terms = find_relevant_terms(
        source_article,
        data
    )

    terms_text = build_terms_text(
        data,
        relevant_terms
    )

    translation_rules = build_rule_text(
        data,
        "TRANSLATION_RULES"
    )

    news_structure = build_rule_text(
        data,
        "NEWS_STRUCTURE"
    )

    malay_style = build_rule_text(
        data,
        "MALAY_STYLE"
    )

    chinese_style = build_rule_text(
        data,
        "CHINESE_STYLE"
    )

    prompt = f"""
You are a senior editor for a Malaysian news portal.

Rewrite the SOURCE ARTICLE into:
1. Natural Malaysian Chinese news
2. Natural Malaysian Malay news

Do NOT translate sentence-by-sentence.
Rewrite naturally while preserving every fact.

SOURCE ARTICLE:
{source_article}

RELEVANT PROPER NOUNS:
{terms_text}

TRANSLATION RULES:
{translation_rules}

NEWS STRUCTURE:
{news_structure}

MALAY STYLE:
{malay_style}

CHINESE STYLE:
{chinese_style}

PRIORITY:
1. factual accuracy
2. translation rules
3. proper noun dictionary
4. news structure
5. language style
6. natural expression

STRICT FACT RULES:
- Never invent facts.
- Never remove important facts.
- Never change names.
- Never change locations.
- Never change dates or times.
- Never change numbers.
- Never change percentages.
- Never change money amounts.
- Never change causality.
- Preserve attribution.
- Preserve uncertainty.
- Do not turn expected/projected/possible into confirmed facts.
- Do not turn allegations into confirmed facts.
- Do not add unsupported background.

PROPER NOUN RULES:
- Use the supplied dictionary.
- Do not invent Chinese names.
- If a mapping says KEEP ORIGINAL, keep the original.
- Do not translate company or brand names when the dictionary says KEEP ORIGINAL.

MONEY:
85亿 = 8.5 billion = 8.5 bilion
8.5 billion = 85亿令吉
85 billion = 850亿令吉

Never convert RM85亿 into RM85 billion.
Never change or round source numbers.

LANGUAGE:
Chinese must sound like Malaysian Chinese news media.
Malay must sound like modern Malaysian Malay news media.
Avoid Indonesian style.
Avoid Mainland China-style stiff wording.
Avoid machine translation.
Avoid word-for-word English structure.
Avoid clickbait.
Avoid unsupported conclusions.

OUTPUT:
Return ONLY valid JSON.

{{
"zh_title":"...",
"zh_body":"...",
"ms_title":"...",
"ms_body":"..."
}}
"""

    return prompt.strip()


# ============================================================
# PARSE RETRY SECONDS FROM GROQ ERROR
# ============================================================

def extract_retry_seconds(
    error: Exception
) -> Optional[float]:

    text = str(error)

    patterns = [
        r"try again in\s+([\d.]+)s",
        r"retry.*?([\d.]+)s"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            try:

                seconds = float(
                    match.group(1)
                )

                return seconds

            except Exception:
                pass

    return None


# ============================================================
# CHECK GROQ RATE LIMIT
# ============================================================

def is_rate_limit_error(
    error: Exception
) -> bool:

    text = str(
        error
    ).lower()

    return (
        "429" in text
        or
        "rate limit" in text
        or
        "rate_limit_exceeded" in text
        or
        "tokens per minute" in text
    )


# ============================================================
# CHECK PROMPT TOO LARGE
# ============================================================

def is_prompt_too_large(
    error: Exception
) -> bool:

    text = str(
        error
    ).lower()

    return (
        "413" in text
        or
        "request too large" in text
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

    prompt_chars = len(
        prompt
    )

    logger.info(
        "Groq prompt size: %s characters",
        prompt_chars
    )

    # --------------------------------------------------------
    # IMPORTANT
    # --------------------------------------------------------
    #
    # We deliberately keep max_tokens at 900.
    # This reduces total TPM usage.
    #
    # --------------------------------------------------------

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
                    "Groq response reached max_tokens."
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

                    logger.info(
                        "Retrying Groq in 5 seconds..."
                    )

                    time.sleep(5)

                    continue

                return None

            # ------------------------------------------------
            # FIELD VALIDATION
            # ------------------------------------------------

            field_errors = validate_ai_fields(
                result
            )

            if field_errors:

                logger.error(
                    "AI field validation failed: %s",
                    " | ".join(field_errors)
                )

                if attempt < MAX_AI_ATTEMPTS:

                    logger.info(
                        "Retrying Groq in 5 seconds..."
                    )

                    time.sleep(5)

                    continue

                return None

            # ------------------------------------------------
            # PROPER NOUN VALIDATION
            # ------------------------------------------------

            source_text = build_source_article(
                article
            )

            zh_text = (
                result["zh_title"] +
                "\n" +
                result["zh_body"]
            )

            ms_text = (
                result["ms_title"] +
                "\n" +
                result["ms_body"]
            )

            noun_errors = validate_proper_nouns(
                source_text,
                zh_text,
                ms_text,
                data
            )

            if noun_errors:

                logger.error(
                    "Proper noun validation failed: %s",
                    " | ".join(noun_errors)
                )

                # ------------------------------------------------
                # DO NOT immediately send another huge request.
                #
                # This prevents the validation bug from creating
                # another Groq 429.
                #
                # ------------------------------------------------

                if attempt < MAX_AI_ATTEMPTS:

                    logger.info(
                        "Retrying Groq due to proper noun "
                        "validation failure in 10 seconds..."
                    )

                    time.sleep(10)

                    continue

                return None

            # ------------------------------------------------
            # SUCCESS
            # ------------------------------------------------

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

            # ------------------------------------------------
            # PROMPT TOO LARGE
            # ------------------------------------------------

            if is_prompt_too_large(e):

                logger.error(
                    "Groq request is too large. "
                    "Do not retry the same request."
                )

                return None

            # ------------------------------------------------
            # RATE LIMIT
            # ------------------------------------------------

            if is_rate_limit_error(e):

                retry_seconds = extract_retry_seconds(
                    e
                )

                if retry_seconds is None:

                    retry_seconds = 60

                # Add small safety buffer.
                retry_seconds = (
                    retry_seconds + 2
                )

                logger.warning(
                    "Groq rate limit reached. "
                    "Waiting %.1f seconds before retry.",
                    retry_seconds
                )

                if attempt < MAX_AI_ATTEMPTS:

                    time.sleep(
                        retry_seconds
                    )

                    continue

                logger.error(
                    "Groq rate limit persists after "
                    "%s attempts.",
                    MAX_AI_ATTEMPTS
                )

                return None

            # ------------------------------------------------
            # OTHER ERRORS
            # ------------------------------------------------

            if attempt < MAX_AI_ATTEMPTS:

                wait = (
                    5 * attempt
                )

                logger.info(
                    "Retrying Groq in %s seconds...",
                    wait
                )

                time.sleep(
                    wait
                )

                continue

    logger.error(
        "AI failed after %s attempts.",
        MAX_AI_ATTEMPTS
    )

    return None


# ============================================================
# TELEGRAM API
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
# TELEGRAM HTML ESCAPE
# ============================================================

def telegram_escape(
    text: str
) -> str:

    if not text:
        return ""

    text = str(
        text
    )

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
# SEND TELEGRAM PHOTO
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
# SEND TELEGRAM TEXT
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
# BUILD TELEGRAM CAPTION
# ============================================================

def build_telegram_caption(
    article: Dict[str, Any],
    ai: Dict[str, Any]
) -> str:

    zh_title = telegram_escape(
        ai.get(
            "zh_title",
            ""
        )
    )

    zh_body = telegram_escape(
        ai.get(
            "zh_body",
            ""
        )
    )

    ms_title = telegram_escape(
        ai.get(
            "ms_title",
            ""
        )
    )

    ms_body = telegram_escape(
        ai.get(
            "ms_body",
            ""
        )
    )

    source = telegram_escape(
        article.get(
            "_source_name",
            ""
        )
    )

    url = normalize_url(
        article.get(
            "url",
            ""
        )
    )

    return (
        "🇲🇾 <b>MYBuzz NEWS</b>\n\n"
        f"<b>{zh_title}</b>\n\n"
        f"{zh_body}\n\n"
        f"<b>{ms_title}</b>\n\n"
        f"{ms_body}\n\n"
        f"Source: {source}\n"
        f'<a href="{url}">Read Full Article</a>'
    )


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

        # Telegram photo caption max is 1024 characters.
        if len(caption) <= 1024:

            success = send_telegram_photo(
                image,
                caption
            )

            if success:
                return True

            logger.warning(
                "Photo sending failed. "
                "Trying text fallback."
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
    # API CONFIG
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
    # LOAD JSON
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
    # AI
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
    # LOG AI TITLES
    # --------------------------------------------------------

    logger.info(
        "AI Chinese title: %s",
        ai.get(
            "zh_title",
            ""
        )
    )

    logger.info(
        "AI Malay title: %s",
        ai.get(
            "ms_title",
            ""
        )
    )

    # --------------------------------------------------------
    # TELEGRAM
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
    # MARK POSTED ONLY AFTER SUCCESS
    # --------------------------------------------------------

    aid = article.get(
        "_id"
    )

    if aid:

        posted.append(
            aid
        )

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

        raise SystemExit(
            130
        )

    except Exception as e:

        logger.exception(
            "Unexpected fatal error: %s",
            e
        )

        raise SystemExit(
            1
        )
