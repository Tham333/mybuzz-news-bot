import os
import re
import json
import time
import html
import hashlib
import requests
from bs4 import BeautifulSoup
from openai import OpenAI


# ============================================================
# CONFIG
# ============================================================

GNEWS_BASE_URL = "https://gnews.io/api/v4"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

GROQ_MODEL = "openai/gpt-oss-20b"

REQUEST_TIMEOUT = 20

MAX_GNEWS_ARTICLES = 10
MAX_POSTED = 1000

MAX_AI_ATTEMPTS = 2
AI_MAX_TOKENS = 1200

DATA_DIR = "."

TERMS_FILE = os.path.join(
    DATA_DIR,
    "malaysia_terms.json"
)

POSTED_FILE = os.path.join(
    DATA_DIR,
    "posted.json"
)

STATE_FILE = os.path.join(
    DATA_DIR,
    "bot_state.json"
)


# ============================================================
# ENV
# ============================================================

GNEWS_API_KEY = os.getenv(
    "GNEWS_API_KEY",
    ""
).strip()

GROQ_API_KEY = os.getenv(
    "GROQ_API_KEY",
    ""
).strip()

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# ============================================================
# GROQ CLIENT
# ============================================================

groq_client = None

if GROQ_API_KEY:

    groq_client = OpenAI(
        api_key=GROQ_API_KEY,
        base_url=GROQ_BASE_URL,
        max_retries=0
    )


# ============================================================
# BASIC HELPERS
# ============================================================

def clean_text(text):

    if not text:
        return ""

    text = str(text)

    text = text.replace(
        "\r",
        " "
    )

    text = text.replace(
        "\n",
        " "
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def normalize_url(url):

    if not url:
        return ""

    url = url.strip()

    return url.split("#")[0]


def article_id(article):

    url = normalize_url(
        article.get(
            "url",
            ""
        )
    )

    if url:

        return hashlib.sha256(
            url.encode(
                "utf-8"
            )
        ).hexdigest()

    raw = (
        clean_text(
            article.get(
                "title",
                ""
            )
        )
        +
        clean_text(
            article.get(
                "description",
                ""
            )
        )
    )

    return hashlib.sha256(
        raw.encode(
            "utf-8"
        )
    ).hexdigest()


# ============================================================
# POSTED DATABASE
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

        print(
            f"WARNING failed to load posted.json: {e}"
        )

    return []


def save_posted(posted):

    posted = posted[
        -MAX_POSTED:
    ]

    try:

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

        print(
            f"ERROR saving posted.json: {e}"
        )


# ============================================================
# STATE
# ============================================================

def load_state():

    if not os.path.exists(
        STATE_FILE
    ):

        return {
            "run_count": 0
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

            return data

    except Exception as e:

        print(
            f"WARNING failed to load bot_state.json: {e}"
        )

    return {
        "run_count": 0
    }


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

        print(
            f"WARNING failed to save bot_state.json: {e}"
        )


def increase_run_counter():

    state = load_state()

    state["run_count"] = int(
        state.get(
            "run_count",
            0
        )
    ) + 1

    save_state(
        state
    )

    return state[
        "run_count"
    ]


# ============================================================
# CONFIG CHECK
# ============================================================

def check_config():

    missing = []

    if not GNEWS_API_KEY:

        missing.append(
            "GNEWS_API_KEY"
        )

    if not GROQ_API_KEY:

        missing.append(
            "GROQ_API_KEY"
        )

    if not TELEGRAM_BOT_TOKEN:

        missing.append(
            "TELEGRAM_BOT_TOKEN"
        )

    if not TELEGRAM_CHAT_ID:

        missing.append(
            "TELEGRAM_CHAT_ID"
        )

    if missing:

        print(
            "ERROR Missing environment variables: "
            + ", ".join(missing)
        )

        return False

    if not os.path.exists(
        TERMS_FILE
    ):

        print(
            f"ERROR Missing {TERMS_FILE}"
        )

        return False

    return True


# ============================================================
# GNEWS
# ============================================================

def fetch_gnews():

    url = (
        f"{GNEWS_BASE_URL}/search"
    )

    params = {
        "q": "Malaysia",
        "lang": "en",
        "country": "my",
        "max": MAX_GNEWS_ARTICLES,
        "apikey": GNEWS_API_KEY
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        print(
            f"GNews HTTP "
            f"{response.status_code}"
        )

        response.raise_for_status()

        data = response.json()

        articles = data.get(
            "articles",
            []
        )

        print(
            f"GNews returned "
            f"{len(articles)} articles"
        )

        return articles

    except Exception as e:

        print(
            f"ERROR GNews request failed: {e}"
        )

        return []


# ============================================================
# ARTICLE IMAGE
# ============================================================

def get_article_image(url):

    if not url:

        return ""

    try:

        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent":
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "Chrome/151 Safari/537.36"
            }
        )

        if response.status_code != 200:

            return ""

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        og_image = soup.find(
            "meta",
            property="og:image"
        )

        if og_image:

            content = (
                og_image
                .get(
                    "content",
                    ""
                )
                .strip()
            )

            if content:

                return content

        twitter_image = soup.find(
            "meta",
            attrs={
                "name": "twitter:image"
            }
        )

        if twitter_image:

            content = (
                twitter_image
                .get(
                    "content",
                    ""
                )
                .strip()
            )

            if content:

                return content

    except Exception as e:

        print(
            f"WARNING image extraction failed: {e}"
        )

    return ""


# ============================================================
# SELECT NEWS
# ============================================================

def select_news(
    articles,
    posted
):

    posted_set = set(
        posted
    )

    for article in articles:

        aid = article_id(
            article
        )

        if aid in posted_set:

            continue

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

        content = clean_text(
            article.get(
                "content",
                ""
            )
        )

        url = normalize_url(
            article.get(
                "url",
                ""
            )
        )

        source = (
            article.get(
                "source",
                {}
            )
            or {}
        )

        source_name = clean_text(
            source.get(
                "name",
                ""
            )
        )

        if not title:

            continue

        if not url:

            continue

        image = (
            article.get(
                "image",
                ""
            )
            or
            get_article_image(
                url
            )
        )

        if not image:

            print(
                f"Skipping without image: "
                f"{title}"
            )

            continue

        article["_id"] = aid

        article["_image"] = image

        article["_source_name"] = (
            source_name
        )

        print(
            f"Selected title: {title}"
        )

        return article

    print(
        "No suitable new article found."
    )

    return None


# ============================================================
# LOAD TERMS
# ============================================================

def load_terms():

    try:

        with open(
            TERMS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(
                f
            )

        if not isinstance(
            data,
            dict
        ):

            raise ValueError(
                "malaysia_terms.json root must be object"
            )

        return data

    except Exception as e:

        print(
            f"ERROR failed to load malaysia_terms.json: {e}"
        )

        return {}


# ============================================================
# TERM CATEGORIES
# ============================================================

NON_TERM_CATEGORIES = {
    "MALAY_STYLE",
    "CHINESE_STYLE",
    "TRANSLATION_RULES",
    "NEWS_STRUCTURE"
}


# ============================================================
# FLATTEN TERMS
# ============================================================

def flatten_terms(data):

    result = []

    for category, values in data.items():

        if category in NON_TERM_CATEGORIES:

            continue

        if not isinstance(
            values,
            dict
        ):

            continue

        for original, translated in values.items():

            if isinstance(
                translated,
                str
            ):

                result.append({
                    "category": category,
                    "source": original,
                    "target": translated
                })

    return result


# ============================================================
# FIND RELEVANT TERMS
#
# Remove duplicate source -> target mappings.
# ============================================================

def find_relevant_terms(
    article_text,
    terms
):

    article_text_lower = (
        article_text.lower()
    )

    matches = []

    seen = set()

    for item in terms:

        source = clean_text(
            item.get(
                "source",
                ""
            )
        )

        target = clean_text(
            item.get(
                "target",
                ""
            )
        )

        if not source:

            continue

        key = (
            source.lower(),
            target.lower()
        )

        if key in seen:

            continue

        if (
            source.lower()
            in article_text_lower
        ):

            matches.append(
                item
            )

            seen.add(
                key
            )

    return matches


# ============================================================
# BUILD TERMS TEXT
# ============================================================

def build_terms_text(
    relevant_terms
):

    if not relevant_terms:

        return (
            "No dictionary terms detected "
            "in this article."
        )

    lines = []

    for item in relevant_terms:

        lines.append(
            f'{item["source"]} => '
            f'{item["target"]}'
        )

    return "\n".join(
        lines
    )


# ============================================================
# VERBOSE RULE KEYS
#
# These are examples/reference material.
# Actual rules remain in malaysia_terms.json.
# ============================================================

VERBOSE_RULE_KEYS = {
    "examples",
    "example",
    "EXAMPLES",
    "Examples",

    "preferred_patterns",
    "PREFERRED_PATTERNS",

    "NEWS_RESTRUCTURING",
    "news_restructuring",

    "context_rules",
    "CONTEXT_RULES",

    "translation_examples",
    "TRANSLATION_EXAMPLES",

    "bad_examples",
    "BAD_EXAMPLES",

    "good_examples",
    "GOOD_EXAMPLES",

    "sample",
    "samples",
    "SAMPLE",
    "SAMPLES"
}


# ============================================================
# COMPACT RULE VALUE
# ============================================================

def compact_rule_value(
    value,
    depth=0
):

    if isinstance(
        value,
        dict
    ):

        result = {}

        for key, child in value.items():

            key_text = str(
                key
            )

            if key_text in VERBOSE_RULE_KEYS:

                continue

            compact_child = (
                compact_rule_value(
                    child,
                    depth + 1
                )
            )

            if compact_child in (
                None,
                "",
                {},
                []
            ):

                continue

            result[key] = (
                compact_child
            )

        return result

    if isinstance(
        value,
        list
    ):

        result = []

        for item in value:

            if isinstance(
                item,
                str
            ):

                text = clean_text(
                    item
                )

                if text:

                    result.append(
                        text
                    )

            elif isinstance(
                item,
                dict
            ):

                compact_child = (
                    compact_rule_value(
                        item,
                        depth + 1
                    )
                )

                if compact_child not in (
                    None,
                    "",
                    {},
                    []
                ):

                    result.append(
                        compact_child
                    )

        return result

    if isinstance(
        value,
        str
    ):

        return clean_text(
            value
        )

    return value


# ============================================================
# BUILD RULE TEXT
# ============================================================

def build_rule_text(
    data,
    category
):

    value = data.get(
        category
    )

    if value is None:

        return (
            f"No {category} rules."
        )

    compacted = (
        compact_rule_value(
            value
        )
    )

    return json.dumps(
        compacted,
        ensure_ascii=False,
        separators=(
            ",",
            ":"
        )
    )


# ============================================================
# SOURCE ARTICLE
# ============================================================

def build_source_article(
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

    content = clean_text(
        article.get(
            "content",
            ""
        )
    )

    source = clean_text(
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
        f"SOURCE: {source}\n"
        f"TITLE: {title}\n"
        f"DESCRIPTION: {description}\n"
        f"CONTENT: {content}\n"
        f"URL: {url}"
    )


# ============================================================
# GROQ PROMPT
# ============================================================

def build_groq_prompt(
    article,
    relevant_terms,
    terms_data
):

    source_article = (
        build_source_article(
            article
        )
    )

    terms_text = (
        build_terms_text(
            relevant_terms
        )
    )

    translation_rules = (
        build_rule_text(
            terms_data,
            "TRANSLATION_RULES"
        )
    )

    news_structure = (
        build_rule_text(
            terms_data,
            "NEWS_STRUCTURE"
        )
    )

    malay_style = (
        build_rule_text(
            terms_data,
            "MALAY_STYLE"
        )
    )

    chinese_style = (
        build_rule_text(
            terms_data,
            "CHINESE_STYLE"
        )
    )

    prompt = f"""
You are a professional Malaysian news editor and bilingual translator.

TASK:
Rewrite the source article into:
1. Natural Malaysian Chinese news.
2. Natural Malaysian Malay news.

FACTUAL ACCURACY:
- Preserve facts from the source.
- Never invent facts.
- Never invent names, places, organizations or numbers.
- Preserve uncertainty such as expected, may, could, according to, etc.
- Do not change the meaning.
- Use dictionary mappings when applicable.
- Chinese must sound natural in Malaysian Chinese news.
- Malay must sound natural in Malaysian Malay news.
- Avoid literal machine translation.
- Avoid Indonesian Malay.

DICTIONARY:
{terms_text}

TRANSLATION RULES:
{translation_rules}

NEWS STRUCTURE:
{news_structure}

MALAY STYLE:
{malay_style}

CHINESE STYLE:
{chinese_style}

SOURCE ARTICLE:
{source_article}

RETURN ONLY THIS JSON:
{{
  "chinese_title": "Chinese news headline",
  "chinese_body": "Chinese news body",
  "malay_title": "Malay news headline",
  "malay_body": "Malay news body"
}}

OUTPUT RULES:
- Valid JSON only.
- No Markdown.
- No code fence.
- No explanation.
- Chinese title: concise news headline.
- Malay title: concise news headline.
- Chinese body: normally 2-4 sentences.
- Malay body: normally 2-4 sentences.
- Do not add unsupported information.
"""

    return prompt.strip()


# ============================================================
# JSON EXTRACTION
# ============================================================

def extract_json(
    text
):

    if not text:

        return None

    text = text.strip()

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

    text = text.strip()

    try:

        return json.loads(
            text
        )

    except Exception:

        pass

    start = text.find(
        "{"
    )

    end = text.rfind(
        "}"
    )

    if (
        start == -1
        or end == -1
        or end <= start
    ):

        return None

    candidate = text[
        start:end + 1
    ]

    try:

        return json.loads(
            candidate
        )

    except Exception as e:

        print(
            f"JSON extraction failed: {e}"
        )

        return None


# ============================================================
# VALIDATE AI FIELDS
# ============================================================

def validate_ai_fields(
    data
):

    if not isinstance(
        data,
        dict
    ):

        return False

    required = [
        "chinese_title",
        "chinese_body",
        "malay_title",
        "malay_body"
    ]

    for key in required:

        value = data.get(
            key
        )

        if not isinstance(
            value,
            str
        ):

            print(
                f"Missing or invalid field: {key}"
            )

            return False

        value = clean_text(
            value
        )

        if not value:

            print(
                f"Empty AI field: {key}"
            )

            return False

        if len(value) > 5000:

            print(
                f"AI field too long: {key}"
            )

            return False

    return True


# ============================================================
# PROPER NOUN VALIDATION
#
# Do NOT require every dictionary term to appear.
#
# Example:
#
# Malaysia -> 马来西亚
#
# Correct:
# 马来西亚股市...
#
# Wrong:
# Malaysia股市...
#
# If the AI shortens the article and does not mention
# Malaysia again, that is acceptable.
# ============================================================

def validate_proper_nouns(
    article_text,
    ai_data,
    relevant_terms
):

    chinese_text = (
        ai_data.get(
            "chinese_title",
            ""
        )
        +
        " "
        +
        ai_data.get(
            "chinese_body",
            ""
        )
    )

    malay_text = (
        ai_data.get(
            "malay_title",
            ""
        )
        +
        " "
        +
        ai_data.get(
            "malay_body",
            ""
        )
    )

    chinese_text_lower = (
        chinese_text.lower()
    )

    malay_text_lower = (
        malay_text.lower()
    )

    article_text_lower = (
        article_text.lower()
    )

    for item in relevant_terms:

        source = clean_text(
            item.get(
                "source",
                ""
            )
        )

        target = clean_text(
            item.get(
                "target",
                ""
            )
        )

        if not source:

            continue

        if (
            source.lower()
            not in article_text_lower
        ):

            continue

        if not target:

            continue

        # ----------------------------------------------------
        # KEEP ORIGINAL
        # ----------------------------------------------------

        if (
            target.lower()
            == source.lower()
        ):

            continue

        # ----------------------------------------------------
        # Chinese translation
        #
        # Only reject if the original source term remains.
        # Do not require target to appear.
        # ----------------------------------------------------

        if re.search(
            r"[\u4e00-\u9fff]",
            target
        ):

            if (
                source.lower()
                in chinese_text_lower
            ):

                print(
                    f"Chinese proper noun not translated: "
                    f"{source} -> {target}"
                )

                return False

            continue

        # ----------------------------------------------------
        # Latin target
        # ----------------------------------------------------

        if (
            source.lower()
            in malay_text_lower
        ):

            if (
                target.lower()
                != source.lower()
            ):

                print(
                    f"Malay proper noun not translated: "
                    f"{source} -> {target}"
                )

                return False

    return True


# ============================================================
# RATE LIMIT HELPERS
# ============================================================

def extract_retry_seconds(
    error_text
):

    if not error_text:

        return 30

    patterns = [

        r"try again in\s*"
        r"([0-9]+(?:\.[0-9]+)?)s",

        r"retry after\s*"
        r"([0-9]+(?:\.[0-9]+)?)s",

        r"in\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*seconds"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            error_text,
            re.IGNORECASE
        )

        if match:

            try:

                seconds = float(
                    match.group(1)
                )

                return max(
                    1,
                    min(
                        int(seconds) + 2,
                        120
                    )
                )

            except Exception:

                pass

    return 30


def is_rate_limit_error(
    error_text
):

    if not error_text:

        return False

    text = error_text.lower()

    return (
        "429" in text
        or
        "rate limit" in text
        or
        "tpm limit" in text
        or
        "too many requests" in text
    )


def is_prompt_too_large(
    error_text
):

    if not error_text:

        return False

    text = error_text.lower()

    return (
        "413" in text
        or
        "request too large" in text
        or
        "prompt is too long" in text
        or
        "context length" in text
    )


# ============================================================
# AI GENERATION
# ============================================================

def generate_ai_content(
    article,
    terms_data
):

    if groq_client is None:

        print(
            "ERROR Groq client not initialized."
        )

        return None

    article_text = (
        clean_text(
            article.get(
                "title",
                ""
            )
        )
        +
        " "
        +
        clean_text(
            article.get(
                "description",
                ""
            )
        )
        +
        " "
        +
        clean_text(
            article.get(
                "content",
                ""
            )
        )
    )

    all_terms = flatten_terms(
        terms_data
    )

    relevant_terms = (
        find_relevant_terms(
            article_text,
            all_terms
        )
    )

    print(
        f"Relevant proper nouns: "
        f"{len(relevant_terms)}"
    )

    if relevant_terms:

        print(
            "Relevant dictionary terms:"
        )

        for item in relevant_terms:

            print(
                f'  {item["source"]} '
                f'=> {item["target"]}'
            )

    prompt = build_groq_prompt(
        article,
        relevant_terms,
        terms_data
    )

    print(
        f"Groq prompt size: "
        f"{len(prompt)} characters"
    )

    for attempt in range(
        1,
        MAX_AI_ATTEMPTS + 1
    ):

        print(
            f"Sending Groq request "
            f"attempt {attempt}/"
            f"{MAX_AI_ATTEMPTS}"
        )

        try:

            response = (
                groq_client
                .chat
                .completions
                .create(
                    model=GROQ_MODEL,

                    messages=[
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],

                    temperature=0.1,

                    max_tokens=AI_MAX_TOKENS
                )
            )

            choice = (
                response.choices[0]
            )

            finish_reason = getattr(
                choice,
                "finish_reason",
                None
            )

            raw_content = ""

            if choice.message:

                raw_content = (
                    choice.message.content
                    or ""
                )

            # ------------------------------------------------
            # MAX TOKEN
            # ------------------------------------------------

            if finish_reason in (
                "length",
                "max_tokens"
            ):

                print(
                    "WARNING Groq response "
                    "reached max_tokens."
                )

                if attempt < MAX_AI_ATTEMPTS:

                    print(
                        "Retrying Groq..."
                    )

                    time.sleep(
                        3
                    )

                    continue

                return None

            # ------------------------------------------------
            # JSON
            # ------------------------------------------------

            data = extract_json(
                raw_content
            )

            if data is None:

                print(
                    "ERROR AI returned invalid JSON."
                )

                if attempt < MAX_AI_ATTEMPTS:

                    time.sleep(
                        3
                    )

                    continue

                return None

            # ------------------------------------------------
            # FIELD VALIDATION
            # ------------------------------------------------

            if not validate_ai_fields(
                data
            ):

                print(
                    "ERROR AI JSON fields invalid."
                )

                if attempt < MAX_AI_ATTEMPTS:

                    time.sleep(
                        3
                    )

                    continue

                return None

            # ------------------------------------------------
            # PROPER NOUN VALIDATION
            # ------------------------------------------------

            if not validate_proper_nouns(
                article_text,
                data,
                relevant_terms
            ):

                print(
                    "ERROR AI proper noun "
                    "validation failed."
                )

                if attempt < MAX_AI_ATTEMPTS:

                    print(
                        "Retrying Groq because "
                        "proper noun validation failed..."
                    )

                    time.sleep(
                        3
                    )

                    continue

                return None

            print(
                "AI generation successful."
            )

            return data

        except Exception as e:

            error_text = str(e)

            print(
                f"ERROR Groq request failed: "
                f"{error_text}"
            )

            # ------------------------------------------------
            # RATE LIMIT
            # ------------------------------------------------

            if is_rate_limit_error(
                error_text
            ):

                if attempt >= MAX_AI_ATTEMPTS:

                    print(
                        "ERROR Rate limit reached. "
                        "No more retries."
                    )

                    return None

                wait_seconds = (
                    extract_retry_seconds(
                        error_text
                    )
                )

                print(
                    f"Rate limited. "
                    f"Waiting {wait_seconds} seconds..."
                )

                time.sleep(
                    wait_seconds
                )

                continue

            # ------------------------------------------------
            # PROMPT TOO LARGE
            # ------------------------------------------------

            if is_prompt_too_large(
                error_text
            ):

                print(
                    "ERROR Groq prompt too large."
                )

                print(
                    "Do not retry the same prompt."
                )

                return None

            # ------------------------------------------------
            # OTHER ERROR
            # ------------------------------------------------

            if attempt < MAX_AI_ATTEMPTS:

                time.sleep(
                    5
                )

                continue

            return None

    return None


# ============================================================
# TELEGRAM API
# ============================================================

def telegram_api_url(
    method
):

    return (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/"
        f"{method}"
    )


# ============================================================
# TELEGRAM CAPTION
# ============================================================

def build_telegram_caption(
    ai_data,
    source_name,
    source_url
):

    chinese_title = clean_text(
        ai_data[
            "chinese_title"
        ]
    )

    chinese_body = clean_text(
        ai_data[
            "chinese_body"
        ]
    )

    safe_title = html.escape(
        chinese_title
    )

    safe_body = html.escape(
        chinese_body
    )

    safe_source = html.escape(
        source_name
    )

    safe_url = html.escape(
        source_url,
        quote=True
    )

    return (
        "<b>"
        + safe_title
        + "</b>\n\n"
        + safe_body
        + "\n\n"
        + "<i>Source: "
        + safe_source
        + "</i>\n"
        + '<a href="'
        + safe_url
        + '">Read more</a>'
    )


# ============================================================
# SEND TELEGRAM PHOTO
# ============================================================

def send_telegram_photo(
    image_url,
    caption
):

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

        print(
            f"Telegram photo HTTP "
            f"{response.status_code}"
        )

        if response.status_code != 200:

            print(
                f"Telegram error: "
                f"{response.text}"
            )

            return False

        data = response.json()

        if not data.get(
            "ok"
        ):

            print(
                f"Telegram API error: "
                f"{data}"
            )

            return False

        return True

    except Exception as e:

        print(
            f"ERROR Telegram photo failed: "
            f"{e}"
        )

        return False


# ============================================================
# SEND TELEGRAM TEXT
# ============================================================

def send_telegram_text(
    text
):

    url = telegram_api_url(
        "sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:

        response = requests.post(
            url,
            data=payload,
            timeout=REQUEST_TIMEOUT
        )

        print(
            f"Telegram text HTTP "
            f"{response.status_code}"
        )

        if response.status_code != 200:

            print(
                f"Telegram error: "
                f"{response.text}"
            )

            return False

        data = response.json()

        return bool(
            data.get(
                "ok"
            )
        )

    except Exception as e:

        print(
            f"ERROR Telegram text failed: "
            f"{e}"
        )

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 60
    )

    print(
        "MYBUZZ NEWS BOT"
    )

    print(
        "=" * 60
    )

    run_count = (
        increase_run_counter()
    )

    print(
        f"Run #{run_count}"
    )

    # --------------------------------------------------------
    # CONFIG
    # --------------------------------------------------------

    if not check_config():

        return

    # --------------------------------------------------------
    # LOAD DATA
    # --------------------------------------------------------

    posted = load_posted()

    print(
        f"Posted database: "
        f"{len(posted)} records"
    )

    terms_data = load_terms()

    if not terms_data:

        print(
            "ERROR malaysia_terms.json is empty."
        )

        return

    # --------------------------------------------------------
    # GNEWS
    # --------------------------------------------------------

    articles = fetch_gnews()

    if not articles:

        print(
            "No articles from GNews."
        )

        return

    # --------------------------------------------------------
    # SELECT NEWS
    # --------------------------------------------------------

    article = select_news(
        articles,
        posted
    )

    if not article:

        return

    # --------------------------------------------------------
    # AI
    # --------------------------------------------------------

    ai_data = generate_ai_content(
        article,
        terms_data
    )

    if not ai_data:

        print(
            "AI failed. Nothing sent."
        )

        return

    # --------------------------------------------------------
    # TELEGRAM DATA
    # --------------------------------------------------------

    image_url = article.get(
        "_image",
        ""
    )

    source_name = clean_text(
        article.get(
            "_source_name",
            ""
        )
    )

    source_url = normalize_url(
        article.get(
            "url",
            ""
        )
    )

    caption = (
        build_telegram_caption(
            ai_data,
            source_name,
            source_url
        )
    )

    # --------------------------------------------------------
    # SEND PHOTO
    # --------------------------------------------------------

    sent = False

    if image_url:

        sent = send_telegram_photo(
            image_url,
            caption
        )

    # --------------------------------------------------------
    # PHOTO FAILED -> SEND TEXT
    # --------------------------------------------------------

    if not sent:

        print(
            "Photo send failed. "
            "Trying text message..."
        )

        safe_title = html.escape(
            ai_data[
                "chinese_title"
            ]
        )

        safe_body = html.escape(
            ai_data[
                "chinese_body"
            ]
        )

        safe_source = html.escape(
            source_name
        )

        safe_url = html.escape(
            source_url,
            quote=True
        )

        text = (
            "<b>"
            + safe_title
            + "</b>\n\n"
            + safe_body
            + "\n\n"
            + "<i>Source: "
            + safe_source
            + "</i>\n"
            + '<a href="'
            + safe_url
            + '">Read more</a>'
        )

        sent = send_telegram_text(
            text
        )

    # --------------------------------------------------------
    # SAVE POSTED ONLY AFTER SUCCESS
    # --------------------------------------------------------

    if sent:

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

        print(
            "Telegram post successful."
        )

    else:

        print(
            "ERROR Telegram send failed."
        )

    print(
        "=" * 60
    )

    print(
        "BOT FINISHED"
    )

    print(
        "=" * 60
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    main()
