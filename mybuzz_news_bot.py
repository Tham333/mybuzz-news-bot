import os
import re
import json
import html
import hashlib
import requests
from bs4 import BeautifulSoup
from openai import OpenAI


# ============================================================
# MYBUZZ NEWS BOT
# V7
# ============================================================


# ============================================================
# CONFIG
# ============================================================

GNEWS_BASE_URL = "https://gnews.io/api/v4"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

GROQ_MODEL = "openai/gpt-oss-20b"

REQUEST_TIMEOUT = 20

MAX_GNEWS_ARTICLES = 10
MAX_POSTED = 1000
MAX_GNEWS_BATCHES = 5


# ============================================================
# GROQ CONFIG
# ============================================================

# User requested: no retry
MAX_AI_ATTEMPTS = 1

AI_MAX_COMPLETION_TOKENS = 1200

AI_REASONING_EFFORT = "low"


# ============================================================
# PROMPT LIMITS
# ============================================================

MAX_TITLE_CHARS = 500
MAX_DESCRIPTION_CHARS = 1600
MAX_CONTENT_CHARS = 3500

MAX_RELEVANT_TERMS = 80

MAX_TRANSLATION_RULE_CHARS = 2200
MAX_NEWS_STRUCTURE_CHARS = 1800
MAX_MALAY_STYLE_CHARS = 1800
MAX_CHINESE_STYLE_CHARS = 1800

MAX_LOCAL_ENFORCEMENT_CHARS = 1200
MAX_PROPER_NAME_RULES_CHARS = 1600
MAX_MONEY_RULES_CHARS = 1000
MAX_NUMBER_RULES_CHARS = 1000


# ============================================================
# TELEGRAM LIMITS
# ============================================================

TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_TEXT_LIMIT = 4000


# ============================================================
# FILES
# ============================================================

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
# ENVIRONMENT VARIABLES
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


def limit_text(
    text,
    max_chars
):

    text = clean_text(
        text
    )

    if len(text) <= max_chars:

        return text

    return (
        text[:max_chars]
        + "..."
    )


def normalize_url(url):

    if not url:
        return ""

    url = str(url).strip()

    # Remove URL fragment only.
    # Query parameters are preserved.
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

            data = json.load(
                f
            )

        if isinstance(
            data,
            list
        ):

            return data

        if isinstance(
            data,
            dict
        ):

            posted = data.get(
                "posted",
                []
            )

            if isinstance(
                posted,
                list
            ):

                return posted

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

            data = json.load(
                f
            )

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

    try:

        state["run_count"] = int(
            state.get(
                "run_count",
                0
            )
        ) + 1

    except Exception:

        state["run_count"] = 1

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

    all_articles = []

    for batch in range(
        1,
        MAX_GNEWS_BATCHES + 1
    ):

        params = {
            "q": "Malaysia",
            "lang": "en",
            "country": "my",
            "max": MAX_GNEWS_ARTICLES,
            "page": batch,
            "apikey": GNEWS_API_KEY
        }

        try:

            response = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            print(
                f"GNews batch {batch} HTTP "
                f"{response.status_code}"
            )

            response.raise_for_status()

            data = response.json()

            articles = data.get(
                "articles",
                []
            )

            if not isinstance(
                articles,
                list
            ):

                print(
                    f"GNews batch {batch} returned invalid data."
                )

                continue

            print(
                f"GNews batch {batch} returned "
                f"{len(articles)} articles"
            )

            if not articles:

                break

            all_articles.extend(
                articles
            )

        except Exception as e:

            print(
                f"ERROR GNews batch {batch} failed: {e}"
            )

            break

    print(
        f"GNews total articles collected: "
        f"{len(all_articles)}"
    )

    return all_articles


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

        # og:image
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

        # twitter:image
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

    for index, article in enumerate(
        articles,
        start=1
    ):

        aid = article_id(
            article
        )

        title = clean_text(
            article.get(
                "title",
                ""
            )
        )

        url = normalize_url(
            article.get(
                "url",
                ""
            )
        )

        print(
            f"Checking article {index}: "
            f"{title}"
        )

        # ====================================================
        # ALREADY POSTED
        # ====================================================

        if aid in posted_set:

            print(
                "  SKIP: Already posted."
            )

            continue

        # ====================================================
        # NO TITLE
        # ====================================================

        if not title:

            print(
                "  SKIP: Missing title."
            )

            continue

        # ====================================================
        # NO URL
        # ====================================================

        if not url:

            print(
                "  SKIP: Missing URL."
            )

            continue

        # ====================================================
        # IMAGE
        # ====================================================

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
                "  SKIP: No image."
            )

            continue

        # ====================================================
        # SELECTED
        # ====================================================

        article["_id"] = aid

        article["_image"] = image

        source = (
            article.get(
                "source",
                {}
            )
            or {}
        )

        if not isinstance(
            source,
            dict
        ):

            source = {}

        article["_source_name"] = clean_text(
            source.get(
                "name",
                ""
            )
        )

        print(
            f"SELECTED title: {title}"
        )

        return article

    print(
        "No suitable new article found "
        "after checking all articles."
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

        print(
            f"Loaded dictionary categories: "
            f"{len(data)}"
        )

        return data

    except json.JSONDecodeError as e:

        print(
            "ERROR malaysia_terms.json contains invalid JSON:"
        )

        print(
            str(e)
        )

        return {}

    except Exception as e:

        print(
            f"ERROR failed to load malaysia_terms.json: {e}"
        )

        return {}


# ============================================================
# NON-TERM CATEGORIES
# ============================================================

NON_TERM_CATEGORIES = {
    "MALAY_STYLE",
    "CHINESE_STYLE",
    "TRANSLATION_RULES",
    "NEWS_STRUCTURE",
    "LOCAL_TERM_ENFORCEMENT",
    "proper_name_rules",
    "PROPER_NAME_RULES",
    "money_rules",
    "MONEY_RULES",
    "number_rules",
    "NUMBER_RULES"
}


# ============================================================
# KEEP ORIGINAL DETECTION
# ============================================================

def is_keep_original(value):

    if not isinstance(
        value,
        str
    ):

        return False

    return (
        value.strip().upper()
        == "KEEP ORIGINAL"
    )


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

            original_text = clean_text(
                original
            )

            if not original_text:

                continue

            # Simple mapping
            if isinstance(
                translated,
                str
            ):

                target = clean_text(
                    translated
                )

                if not target:

                    continue

                result.append({
                    "category": category,
                    "source": original_text,
                    "target": target,
                    "keep_original": is_keep_original(
                        target
                    )
                })

            # Nested mapping:
            # only flatten simple string children
            elif isinstance(
                translated,
                dict
            ):

                for child_key, child_value in translated.items():

                    if not isinstance(
                        child_value,
                        str
                    ):

                        continue

                    child_value = clean_text(
                        child_value
                    )

                    if not child_value:

                        continue

                    result.append({
                        "category": category,
                        "source": clean_text(
                            child_key
                        ),
                        "target": child_value,
                        "keep_original": is_keep_original(
                            child_value
                        )
                    })

    return result


# ============================================================
# FIND RELEVANT TERMS
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

    sorted_terms = sorted(
        terms,
        key=lambda item: len(
            item.get(
                "source",
                ""
            )
        ),
        reverse=True
    )

    for item in sorted_terms:

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

        source_lower = source.lower()

        # Normal substring match
        if source_lower in article_text_lower:

            matches.append(
                item
            )

            seen.add(
                key
            )

            if len(matches) >= MAX_RELEVANT_TERMS:

                break

    return matches


# ============================================================
# BUILD TERMS TEXT
# ============================================================

def build_terms_text(
    relevant_terms
):

    if not relevant_terms:

        return (
            "No dictionary terms detected."
        )

    lines = []

    for item in relevant_terms:

        source = item.get(
            "source",
            ""
        )

        target = item.get(
            "target",
            ""
        )

        category = item.get(
            "category",
            ""
        )

        if item.get(
            "keep_original",
            False
        ):

            lines.append(
                f"[{category}] "
                f"{source} => KEEP ORIGINAL"
            )

        else:

            lines.append(
                f"[{category}] "
                f"{source} => {target}"
            )

    return "\n".join(
        lines
    )


# ============================================================
# VERBOSE RULE KEYS
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
    "SAMPLES",

    "references",
    "REFERENCES",

    "reference",
    "REFERENCE"
}


# ============================================================
# COMPACT RULE VALUE
# ============================================================

def compact_rule_value(
    value
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
                    child
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
                        item
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
    category,
    max_chars
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

    text = json.dumps(
        compacted,
        ensure_ascii=False,
        separators=(
            ",",
            ":"
        )
    )

    if len(text) <= max_chars:

        return text

    print(
        f"WARNING {category} rules too long: "
        f"{len(text)} chars. "
        f"Reducing to {max_chars}."
    )

    return (
        text[:max_chars]
        + "..."
    )


# ============================================================
# SOURCE ARTICLE
# ============================================================

def build_source_article(
    article
):

    title = limit_text(
        article.get(
            "title",
            ""
        ),
        MAX_TITLE_CHARS
    )

    description = limit_text(
        article.get(
            "description",
            ""
        ),
        MAX_DESCRIPTION_CHARS
    )

    content = limit_text(
        article.get(
            "content",
            ""
        ),
        MAX_CONTENT_CHARS
    )

    source = limit_text(
        article.get(
            "_source_name",
            ""
        ),
        200
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
# BUILD HARD RULES
# ============================================================

def build_hard_rules(
    terms_data
):

    rules = []

    # ========================================================
    # Oriental Kopi
    # ========================================================

    rules.append(
        "Oriental Kopi / Oriental Coffee in Chinese must be "
        "translated as 华阳咖啡, never 东方咖啡."
    )

    # ========================================================
    # Mamak
    # ========================================================

    rules.append(
        "mamak in Malaysian Chinese must be 嘛嘛档. "
        "In Malaysian Malay, keep mamak or use gerai mamak/"
        "restoran mamak according to context."
    )

    # ========================================================
    # Malaysia local style
    # ========================================================

    rules.append(
        "Use Malaysian Chinese terminology, not Mainland "
        "Chinese terminology, when a Malaysian term exists."
    )

    rules.append(
        "Use Malaysian Malay, not Indonesian Malay."
    )

    # ========================================================
    # Numbers
    # ========================================================

    rules.append(
        "Never change numbers, percentages, dates, times "
        "or monetary values."
    )

    # ========================================================
    # Uncertainty
    # ========================================================

    rules.append(
        "Expected, projected, likely, may, could, alleged "
        "and suspected must remain uncertain."
    )

    # ========================================================
    # No invented names
    # ========================================================

    rules.append(
        "Never invent a Chinese name for a person if the "
        "dictionary does not provide one."
    )

    # ========================================================
    # KEEP ORIGINAL
    # ========================================================

    keep_original_terms = []

    all_terms = flatten_terms(
        terms_data
    )

    for item in all_terms:

        if item.get(
            "keep_original",
            False
        ):

            keep_original_terms.append(
                item.get(
                    "source",
                    ""
                )
            )

    if keep_original_terms:

        rules.append(
            "The following brands must remain exactly as "
            "written: "
            +
            ", ".join(
                keep_original_terms
            )
        )

    return "\n".join(
        "- " + item
        for item in rules
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
            "TRANSLATION_RULES",
            MAX_TRANSLATION_RULE_CHARS
        )
    )

    news_structure = (
        build_rule_text(
            terms_data,
            "NEWS_STRUCTURE",
            MAX_NEWS_STRUCTURE_CHARS
        )
    )

    malay_style = (
        build_rule_text(
            terms_data,
            "MALAY_STYLE",
            MAX_MALAY_STYLE_CHARS
        )
    )

    chinese_style = (
        build_rule_text(
            terms_data,
            "CHINESE_STYLE",
            MAX_CHINESE_STYLE_CHARS
        )
    )

    local_enforcement = (
        build_rule_text(
            terms_data,
            "LOCAL_TERM_ENFORCEMENT",
            MAX_LOCAL_ENFORCEMENT_CHARS
        )
    )

    proper_name_rules = (
        build_rule_text(
            terms_data,
            "proper_name_rules",
            MAX_PROPER_NAME_RULES_CHARS
        )
    )

    if proper_name_rules == "No proper_name_rules rules.":

        proper_name_rules = (
            build_rule_text(
                terms_data,
                "PROPER_NAME_RULES",
                MAX_PROPER_NAME_RULES_CHARS
            )
        )

    money_rules = (
        build_rule_text(
            terms_data,
            "money_rules",
            MAX_MONEY_RULES_CHARS
        )
    )

    if money_rules == "No money_rules rules.":

        money_rules = (
            build_rule_text(
                terms_data,
                "MONEY_RULES",
                MAX_MONEY_RULES_CHARS
            )
        )

    number_rules = (
        build_rule_text(
            terms_data,
            "number_rules",
            MAX_NUMBER_RULES_CHARS
        )
    )

    if number_rules == "No number_rules rules.":

        number_rules = (
            build_rule_text(
                terms_data,
                "NUMBER_RULES",
                MAX_NUMBER_RULES_CHARS
            )
        )

    hard_rules = (
        build_hard_rules(
            terms_data
        )
    )

    prompt = f"""
You are MYBUZZ NEWS's professional Malaysian news editor,
fact checker and bilingual translator.

Your job is to rewrite ONE Malaysian news article into:

1. Natural Malaysian Chinese
2. Natural Malaysian Malay

The result will be published on a Malaysian news Telegram channel.

============================================================
HIGHEST PRIORITY
============================================================

1. FACTUAL ACCURACY
2. PRESERVE NAMES
3. PRESERVE PLACES
4. PRESERVE NUMBERS
5. PRESERVE MONEY VALUES
6. PRESERVE DATES AND TIMES
7. PRESERVE ATTRIBUTION
8. PRESERVE UNCERTAINTY
9. USE DICTIONARY TERMS
10. NATURAL MALAYSIAN NEWS LANGUAGE

Never sacrifice factual accuracy for style.

============================================================
ABSOLUTE RULES
============================================================

- Never invent facts.
- Never invent people.
- Never invent organizations.
- Never invent places.
- Never invent dates.
- Never invent numbers.
- Never invent money amounts.
- Never invent quotes.
- Never add background information not present in the source.
- Never add opinions.
- Never speculate.
- Never change the meaning of the source.
- Do not make allegations sound like confirmed facts.
- Do not make expected/projected/likely events sound completed.
- Do not make suspected/alleged people sound guilty.
- Do not change numerical values.

============================================================
MALAYSIA LOCALIZATION
============================================================

Use Malaysian Chinese, not Mainland Chinese.

Use Malaysian Malay, not Indonesian Malay.

Examples:

Oriental Kopi
=> 华阳咖啡

mamak
=> 嘛嘛档 in Chinese
=> mamak / gerai mamak / restoran mamak in Malay

teh tarik
=> 拉茶

kopi o
=> 咖啡乌

kopitiam
=> 咖啡店

pasar malam
=> 夜市

wet market
=> 湿巴刹

hawker centre
=> 小贩中心

kampung
=> 甘榜

Hari Kebangsaan
=> 国庆日

Hari Malaysia
=> 马来西亚日

Jalur Gemilang
=> 马来西亚国旗

flood
=> 水灾

flash flood
=> 突发水灾

landslide
=> 土崩

haze
=> 烟霾

============================================================
HARD RULES
============================================================

{hard_rules}

============================================================
RELEVANT DICTIONARY TERMS
============================================================

{terms_text}

Use these mappings whenever the source contains the
corresponding term.

If a dictionary item says KEEP ORIGINAL, keep the brand name
exactly as written.

============================================================
TRANSLATION RULES
============================================================

{translation_rules}

============================================================
NEWS STRUCTURE
============================================================

{news_structure}

============================================================
MALAYSIAN MALAY STYLE
============================================================

{malay_style}

============================================================
MALAYSIAN CHINESE STYLE
============================================================

{chinese_style}

============================================================
LOCAL TERM ENFORCEMENT
============================================================

{local_enforcement}

============================================================
PROPER NAME RULES
============================================================

{proper_name_rules}

============================================================
MONEY RULES
============================================================

{money_rules}

============================================================
NUMBER RULES
============================================================

{number_rules}

============================================================
CHINESE NEWS REQUIREMENTS
============================================================

Write like a Malaysian Chinese news portal.

Headline:
- Short.
- Direct.
- Natural.
- Factual.
- Do not translate the English headline word-for-word.
- Do not use clickbait.
- Do not add facts.

Body:
- 1 to 2 concise sentences.
- Put the main fact first.
- Preserve important context.
- Natural Malaysian Chinese.
- Avoid Mainland Chinese news style.
- Avoid machine translation.
- Avoid unnecessary formal phrases.
- Do not repeat the headline.

Use established Malaysian Chinese names from the dictionary.

Do NOT automatically translate "bridge" as "桥梁".
Choose a natural expression such as:
- 媒介
- 纽带
- 拉近……与……的距离

according to context.

============================================================
MALAY NEWS REQUIREMENTS
============================================================

Write like a modern Malaysian Malay news portal.

Headline:
- Short.
- Direct.
- Natural.
- Factual.
- Do not translate English headline word-for-word.
- Avoid Indonesian vocabulary.
- Do not use clickbait.
- Do not add facts.

Body:
- 1 to 2 concise sentences.
- Main fact first.
- Natural Malaysian Malay.
- Avoid machine translation.
- Avoid unnecessarily formal bureaucratic language.
- Do not repeat the headline.

Use:
- dijangka
- diunjurkan
- diramalkan
- menurut
- berkata
- mengumumkan
- mengesahkan
- mendedahkan
- mencatatkan
- meningkat
- menurun
- susulan
- turut
- sekali gus

when appropriate.

Do not automatically translate "bridge" as "jambatan".
Use natural Malaysian Malay such as:
- menjadi medium
- menjadi wadah
- menjadi penghubung
- mendekatkan

according to context.

============================================================
DATELINE
============================================================

Do not force a dateline into the body.

If location/date is clearly provided, it may be naturally included.

Chinese examples:
（吉隆坡2日讯）
（芙蓉2日）

Malay examples:
KUALA LUMPUR, 2 Sept —
SEREMBAN, 2 Sept —

But do not invent a location or date.

============================================================
NUMBERS AND MONEY
============================================================

This is extremely important.

Do NOT change numerical values.

Examples:

85亿
=> 8.5 billion

8.5 billion
=> 85亿

85 billion
=> 850亿

RM85亿
=> RM8.5 bilion

RM8.5 bilion
=> RM85亿

RM85 bilion
=> RM850亿

Never translate:
85亿
as
85 billion

Never round numbers unless the source already rounded them.

============================================================
UNCERTAINTY
============================================================

Preserve uncertainty exactly.

expected
=> 预计 / dijangka

projected
=> 预计 / diunjurkan

likely
=> 可能 / berkemungkinan

may
=> 可能 / mungkin

could
=> 可能 / boleh

alleged
=> 被指 / didakwa

suspected
=> 涉嫌 / disyaki

Do not turn an allegation into a confirmed fact.

============================================================
OUTPUT
============================================================

Return ONLY valid JSON.

No Markdown.
No code fence.
No explanation.
No emojis.
No source.
No URL.
No "Source".
No "Read more".

Exactly these four fields:

{{
  "chinese_title": "...",
  "chinese_body": "...",
  "malay_title": "...",
  "malay_body": "..."
}}

============================================================
SOURCE ARTICLE
============================================================

{source_article}
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

    # Remove code fence
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

    # Find JSON object
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
# FIND KEEP ORIGINAL TERMS
# ============================================================

def get_keep_original_terms(
    terms_data
):

    terms = []

    for item in flatten_terms(
        terms_data
    ):

        if item.get(
            "keep_original",
            False
        ):

            source = clean_text(
                item.get(
                    "source",
                    ""
                )
            )

            if source:

                terms.append(
                    source
                )

    return terms


# ============================================================
# PROPER NOUN VALIDATION
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

        # ====================================================
        # KEEP ORIGINAL
        # ====================================================

        if item.get(
            "keep_original",
            False
        ):

            source_lower = (
                source.lower()
            )

            if (
                source_lower
                not in chinese_text_lower
                and
                source_lower
                not in malay_text_lower
            ):

                print(
                    "KEEP ORIGINAL term missing: "
                    f"{source}"
                )

                return False

            continue

        # ====================================================
        # CHINESE TARGET
        # ====================================================

        if re.search(
            r"[\u4e00-\u9fff]",
            target
        ):

            source_lower = (
                source.lower()
            )

            target_lower = (
                target.lower()
            )

            # =================================================
            # IMPORTANT:
            # Correct Chinese translation already exists.
            # Do NOT reject just because the English source
            # also appears somewhere in the Chinese output.
            # =================================================

            if target_lower in chinese_text_lower:

                continue

            # =================================================
            # If English source remains and the correct
            # Chinese translation is completely missing,
            # reject it.
            # =================================================

            if source_lower in chinese_text_lower:

                print(
                    "Chinese proper noun not translated: "
                    f"{source} -> {target}"
                )

                return False

            continue

        # ====================================================
        # MALAY TARGET
        # ====================================================

        if (
            target.lower()
            == source.lower()
        ):

            continue

        if (
            source.lower()
            in malay_text_lower
        ):

            print(
                "Malay term may not follow dictionary: "
                f"{source} -> {target}"
            )

            return False

    return True


# ============================================================
# HARD LOCAL TERM VALIDATION
# ============================================================

def validate_hard_local_terms(
    article_text,
    ai_data
):

    chinese = (
        clean_text(
            ai_data.get(
                "chinese_title",
                ""
            )
        )
        +
        " "
        +
        clean_text(
            ai_data.get(
                "chinese_body",
                ""
            )
        )
    )

    # ========================================================
    # Oriental Kopi
    # ========================================================

    oriental_present = (
        "oriental kopi"
        in article_text.lower()
        or
        "oriental coffee"
        in article_text.lower()
    )

    if oriental_present:

        if (
            "oriental kopi"
            in chinese.lower()
            or
            "oriental coffee"
            in chinese.lower()
            or
            "东方咖啡"
            in chinese
        ):

            print(
                "Hard validation failed: "
                "Oriental Kopi should be 华阳咖啡."
            )

            return False

        if "华阳咖啡" not in chinese:

            print(
                "Hard validation failed: "
                "华阳咖啡 missing."
            )

            return False

    # ========================================================
    # Mamak
    # ========================================================

    if re.search(
        r"\bmamak\b",
        article_text,
        flags=re.IGNORECASE
    ):

        # If Chinese version refers to mamak,
        # it should use 嘛嘛档.
        chinese_has_mamak = (
            "mamak"
            in chinese.lower()
        )

        if (
            chinese_has_mamak
            and
            "嘛嘛档"
            not in chinese
        ):

            print(
                "Hard validation failed: "
                "mamak should be 嘛嘛档 in Chinese."
            )

            return False

    return True


# ============================================================
# RATE LIMIT
# ============================================================

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


# ============================================================
# PROMPT TOO LARGE
# ============================================================

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
        or
        "maximum context" in text
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

    # ========================================================
    # FIND TERMS
    # ========================================================

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
        f"Relevant dictionary terms: "
        f"{len(relevant_terms)}"
    )

    if relevant_terms:

        for item in relevant_terms:

            if item.get(
                "keep_original",
                False
            ):

                print(
                    f'  [{item["category"]}] '
                    f'{item["source"]} '
                    f'=> KEEP ORIGINAL'
                )

            else:

                print(
                    f'  [{item["category"]}] '
                    f'{item["source"]} '
                    f'=> {item["target"]}'
                )

    # ========================================================
    # BUILD PROMPT
    # ========================================================

    prompt = build_groq_prompt(
        article,
        relevant_terms,
        terms_data
    )

    print(
        f"Groq prompt size: "
        f"{len(prompt)} characters"
    )

    # ========================================================
    # GROQ
    # ========================================================

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

                    max_completion_tokens=(
                        AI_MAX_COMPLETION_TOKENS
                    ),

                    reasoning_effort=(
                        AI_REASONING_EFFORT
                    ),

                    response_format={
                        "type": "json_object"
                    }
                )
            )

            if not response.choices:

                print(
                    "ERROR Groq returned no choices."
                )

                return None

            choice = (
                response.choices[0]
            )

            finish_reason = getattr(
                choice,
                "finish_reason",
                None
            )

            print(
                f"Groq finish reason: "
                f"{finish_reason}"
            )

            raw_content = ""

            if choice.message:

                raw_content = (
                    choice.message.content
                    or ""
                )

            # =================================================
            # EMPTY
            # =================================================

            if not raw_content:

                print(
                    "ERROR Groq returned empty content."
                )

                return None

            # =================================================
            # MAX TOKENS
            # =================================================

            if finish_reason in (
                "length",
                "max_tokens"
            ):

                print(
                    "WARNING Groq response "
                    "reached completion token limit."
                )

                print(
                    "AI output incomplete. "
                    "No retry."
                )

                return None

            # =================================================
            # JSON
            # =================================================

            data = extract_json(
                raw_content
            )

            if data is None:

                print(
                    "ERROR AI returned invalid JSON."
                )

                print(
                    f"AI raw response: "
                    f"{raw_content[:1000]}"
                )

                return None

            # =================================================
            # FIELD VALIDATION
            # =================================================

            if not validate_ai_fields(
                data
            ):

                print(
                    "ERROR AI JSON fields invalid."
                )

                return None

            # =================================================
            # PROPER NOUN VALIDATION
            # =================================================

            if not validate_proper_nouns(
                article_text,
                data,
                relevant_terms
            ):

                print(
                    "ERROR AI proper noun "
                    "validation failed."
                )

                return None

            # =================================================
            # HARD LOCAL VALIDATION
            # =================================================

            if not validate_hard_local_terms(
                article_text,
                data
            ):

                print(
                    "ERROR AI local terminology "
                    "validation failed."
                )

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

            # =================================================
            # RATE LIMIT
            # =================================================

            if is_rate_limit_error(
                error_text
            ):

                print(
                    "ERROR Groq rate limit reached."
                )

                print(
                    "No retry."
                )

                return None

            # =================================================
            # PROMPT TOO LARGE
            # =================================================

            if is_prompt_too_large(
                error_text
            ):

                print(
                    "ERROR Groq prompt too large."
                )

                return None

            # =================================================
            # OTHER ERROR
            # =================================================

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
# TELEGRAM NEWS FORMAT
# ============================================================

def build_telegram_news(
    ai_data,
    source_url
):

    chinese_title = clean_text(
        ai_data.get(
            "chinese_title",
            ""
        )
    )

    chinese_body = clean_text(
        ai_data.get(
            "chinese_body",
            ""
        )
    )

    malay_title = clean_text(
        ai_data.get(
            "malay_title",
            ""
        )
    )

    malay_body = clean_text(
        ai_data.get(
            "malay_body",
            ""
        )
    )

    safe_chinese_title = html.escape(
        chinese_title
    )

    safe_chinese_body = html.escape(
        chinese_body
    )

    safe_malay_title = html.escape(
        malay_title
    )

    safe_malay_body = html.escape(
        malay_body
    )

    safe_url = html.escape(
        source_url,
        quote=True
    )

    return (
        "🇲🇾 <b>MYBuzz NEWS</b>\n\n"

        "🇨🇳 <b>"
        + safe_chinese_title
        + "</b>\n"
        + safe_chinese_body
        + "\n\n"

        "🇲🇾 <b>"
        + safe_malay_title
        + "</b>\n"
        + safe_malay_body
        + "\n\n"

        "👉 <b>点击阅读完整新闻</b>\n"
        + safe_url
        + "\n\n"

        "👉 <b>Klik untuk baca berita penuh</b>\n"
        + safe_url
    )


# ============================================================
# TELEGRAM PLAIN NEWS FORMAT
# ============================================================

def build_telegram_plain_text(
    ai_data,
    source_url
):

    chinese_title = clean_text(
        ai_data.get(
            "chinese_title",
            ""
        )
    )

    chinese_body = clean_text(
        ai_data.get(
            "chinese_body",
            ""
        )
    )

    malay_title = clean_text(
        ai_data.get(
            "malay_title",
            ""
        )
    )

    malay_body = clean_text(
        ai_data.get(
            "malay_body",
            ""
        )
    )

    return (
        "🇲🇾 MYBuzz NEWS\n\n"

        "🇨🇳 "
        + chinese_title
        + "\n"
        + chinese_body
        + "\n\n"

        "🇲🇾 "
        + malay_title
        + "\n"
        + malay_body
        + "\n\n"

        "👉 点击阅读完整新闻\n"
        + source_url
        + "\n\n"

        "👉 Klik untuk baca berita penuh\n"
        + source_url
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
                f"{response.text[:1000]}"
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
                f"{response.text[:1000]}"
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
            f"ERROR Telegram send failed: "
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
        "MYBUZZ NEWS BOT V7"
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

    # ========================================================
    # CONFIG
    # ========================================================

    if not check_config():

        return

    # ========================================================
    # LOAD DATA
    # ========================================================

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

    # ========================================================
    # DICTIONARY SUMMARY
    # ========================================================

    all_terms = flatten_terms(
        terms_data
    )

    print(
        f"Dictionary terms loaded: "
        f"{len(all_terms)}"
    )

    # ========================================================
    # GNEWS
    # ========================================================

    articles = fetch_gnews()

    if not articles:

        print(
            "No articles from GNews."
        )

        return

    # ========================================================
    # SELECT NEWS
    # ========================================================

    article = select_news(
        articles,
        posted
    )

    if not article:

        return

    # ========================================================
    # AI
    # ========================================================

    ai_data = generate_ai_content(
        article,
        terms_data
    )

    if not ai_data:

        print(
            "AI failed. Nothing sent."
        )

        return

    # ========================================================
    # TELEGRAM DATA
    # ========================================================

    image_url = article.get(
        "_image",
        ""
    )

    source_url = normalize_url(
        article.get(
            "url",
            ""
        )
    )

    telegram_news = (
        build_telegram_news(
            ai_data,
            source_url
        )
    )

    telegram_plain_text = (
        build_telegram_plain_text(
            ai_data,
            source_url
        )
    )

    print(
        f"Telegram caption length: "
        f"{len(telegram_news)}"
    )

    print(
        f"Telegram text length: "
        f"{len(telegram_plain_text)}"
    )

    # ========================================================
    # SEND PHOTO
    # ========================================================

    sent = False

    if (
        image_url
        and
        len(telegram_news)
        <= TELEGRAM_CAPTION_LIMIT
    ):

        sent = send_telegram_photo(
            image_url,
            telegram_news
        )

    elif image_url:

        print(
            "Telegram caption too long. "
            "Using text message instead."
        )

    # ========================================================
    # PHOTO FAILED -> TEXT
    # ========================================================

    if not sent:

        print(
            "Sending Telegram text message..."
        )

        if len(
            telegram_plain_text
        ) > TELEGRAM_TEXT_LIMIT:

            print(
                "ERROR Telegram text exceeds "
                "Telegram limit."
            )

            return

        sent = send_telegram_text(
            telegram_plain_text
        )

    # ========================================================
    # SAVE POSTED ONLY AFTER SUCCESS
    # ========================================================

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
