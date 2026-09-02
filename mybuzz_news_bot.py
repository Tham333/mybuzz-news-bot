import os
import re
import json
import html
import hashlib
import requests
from bs4 import BeautifulSoup
from openai import OpenAI


# ============================================================
# MYBUZZ NEWS BOT V7
# ============================================================


# ============================================================
# CONFIG
# ============================================================

GNEWS_BASE_URL = "https://gnews.io/api/v4"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

GROQ_MODEL = "openai/gpt-oss-20b"

REQUEST_TIMEOUT = 20

MAX_GNEWS_ARTICLES = 10
MAX_GNEWS_BATCHES = 5

MAX_POSTED = 1000

# 不重试 Groq
MAX_AI_ATTEMPTS = 1

AI_MAX_COMPLETION_TOKENS = 1200
AI_REASONING_EFFORT = "low"

TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_TEXT_LIMIT = 4000


# ============================================================
# FILES
# ============================================================

TERMS_FILE = "malaysia_terms.json"
POSTED_FILE = "posted.json"
STATE_FILE = "bot_state.json"


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

    if text is None:
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

    # 只删除 #fragment
    # 不删除 query parameters
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
# CONFIG CHECK
# ============================================================

def check_config():

    print(
        "Checking API configuration..."
    )

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
            "ERROR Missing environment variables:"
        )

        for item in missing:
            print(
                f"  - {item}"
            )

        return False

    if not os.path.exists(
        TERMS_FILE
    ):

        print(
            f"ERROR Missing {TERMS_FILE}"
        )

        return False

    print(
        "API configuration OK."
    )

    return True


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
            f"WARNING state load failed: {e}"
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
            f"WARNING state save failed: {e}"
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

            # =================================================
            # 429
            # =================================================

            if response.status_code == 429:

                print(
                    "WARNING GNews rate limit "
                    "reached (429)."
                )

                print(
                    "Stopping further GNews requests."
                )

                break

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
                    f"GNews batch {batch} returned "
                    f"invalid articles data."
                )

                break

            print(
                f"GNews batch {batch} returned "
                f"{len(articles)} articles"
            )

            if not articles:

                print(
                    "No more GNews articles."
                )

                break

            all_articles.extend(
                articles
            )

        except requests.HTTPError as e:

            print(
                f"ERROR GNews batch {batch} failed: "
                f"{e}"
            )

            break

        except Exception as e:

            print(
                f"ERROR GNews batch {batch} failed: "
                f"{e}"
            )

            break

    # ========================================================
    # Remove duplicate URLs
    # ========================================================

    unique_articles = []

    seen_urls = set()

    for article in all_articles:

        url = normalize_url(
            article.get(
                "url",
                ""
            )
        )

        if not url:

            continue

        if url in seen_urls:

            continue

        seen_urls.add(
            url
        )

        unique_articles.append(
            article
        )

    print(
        f"GNews total articles collected: "
        f"{len(unique_articles)}"
    )

    return unique_articles


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

            image = og_image.get(
                "content",
                ""
            ).strip()

            if image:

                return image

        # twitter:image
        twitter_image = soup.find(
            "meta",
            attrs={
                "name": "twitter:image"
            }
        )

        if twitter_image:

            image = twitter_image.get(
                "content",
                ""
            ).strip()

            if image:

                return image

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
            f"Checking article {index}: {title}"
        )

        if aid in posted_set:

            print(
                "  SKIP: Already posted."
            )

            continue

        if not title:

            print(
                "  SKIP: Missing title."
            )

            continue

        if not url:

            print(
                "  SKIP: Missing URL."
            )

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
                "  SKIP: No image."
            )

            continue

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
        "No suitable new article found."
    )

    return None


# ============================================================
# LOAD DICTIONARY
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
                "Root must be a JSON object."
            )

        print(
            f"Loaded dictionary categories: "
            f"{len(data)}"
        )

        return data

    except json.JSONDecodeError as e:

        print(
            "ERROR malaysia_terms.json invalid JSON:"
        )

        print(
            str(e)
        )

        return {}

    except Exception as e:

        print(
            f"ERROR dictionary loading failed: {e}"
        )

        return {}


# ============================================================
# NON TERM CATEGORIES
# ============================================================

NON_TERM_CATEGORIES = {

    "MALAY_STYLE",
    "CHINESE_STYLE",

    "TRANSLATION_RULES",
    "NEWS_STRUCTURE",

    "LOCAL_TERM_ENFORCEMENT",

    "ANTI_MACHINE_TRANSLATION",

    "ANTI_MACHINE_TRANSLATION_RULES",

    "proper_name_rules",
    "PROPER_NAME_RULES",

    "money_rules",
    "MONEY_RULES",

    "number_rules",
    "NUMBER_RULES"
}


# ============================================================
# KEEP ORIGINAL
# ============================================================

def is_keep_original(
    value
):

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

        for source, target in values.items():

            source = clean_text(
                source
            )

            if not source:

                continue

            # =================================================
            # Simple mapping
            # =================================================

            if isinstance(
                target,
                str
            ):

                target = clean_text(
                    target
                )

                if not target:

                    continue

                result.append({
                    "category": category,
                    "source": source,
                    "target": target,
                    "keep_original":
                        is_keep_original(
                            target
                        )
                })

            # =================================================
            # Nested mapping
            # =================================================

            elif isinstance(
                target,
                dict
            ):

                for child_source, child_target in target.items():

                    if not isinstance(
                        child_target,
                        str
                    ):

                        continue

                    child_source = clean_text(
                        child_source
                    )

                    child_target = clean_text(
                        child_target
                    )

                    if not child_source:
                        continue

                    if not child_target:
                        continue

                    result.append({
                        "category": category,
                        "source": child_source,
                        "target": child_target,
                        "keep_original":
                            is_keep_original(
                                child_target
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

            if len(matches) >= 80:

                break

    return matches


# ============================================================
# BUILD TERMS TEXT
# ============================================================

def build_terms_text(
    relevant_terms
):

    if not relevant_terms:

        return "No dictionary terms detected."

    lines = []

    for item in relevant_terms:

        category = item.get(
            "category",
            ""
        )

        source = item.get(
            "source",
            ""
        )

        target = item.get(
            "target",
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
# RULE HELPERS
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


def compact_rule_value(
    value
):

    if isinstance(
        value,
        dict
    ):

        result = {}

        for key, child in value.items():

            if str(key) in VERBOSE_RULE_KEYS:

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

            result[key] = compact_child

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
        500
    )

    description = limit_text(
        article.get(
            "description",
            ""
        ),
        1600
    )

    content = limit_text(
        article.get(
            "content",
            ""
        ),
        3500
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
# HARD RULES
# ============================================================

def build_hard_rules(
    terms_data
):

    rules = []

    rules.append(
        "Oriental Kopi / Oriental Coffee in Chinese "
        "must be 华阳咖啡, never 东方咖啡."
    )

    rules.append(
        "mamak in Malaysian Chinese must be 嘛嘛档. "
        "In Malaysian Malay use mamak, gerai mamak or "
        "restoran mamak according to context."
    )

    rules.append(
        "Use Malaysian Chinese terminology, not Mainland "
        "Chinese terminology."
    )

    rules.append(
        "Use Malaysian Malay, not Indonesian Malay."
    )

    rules.append(
        "Never change numbers, percentages, dates, times "
        "or monetary values."
    )

    rules.append(
        "Expected, projected, likely, may, could, alleged "
        "and suspected must remain uncertain."
    )

    rules.append(
        "Never invent a Chinese name for a person if the "
        "dictionary does not provide one."
    )

    keep_original = []

    for item in flatten_terms(
        terms_data
    ):

        if item.get(
            "keep_original",
            False
        ):

            source = item.get(
                "source",
                ""
            )

            if source:

                keep_original.append(
                    source
                )

    if keep_original:

        rules.append(
            "These brands must remain exactly as written: "
            +
            ", ".join(
                keep_original
            )
        )

    return "\n".join(
        "- " + rule
        for rule in rules
    )


# ============================================================
# GROQ PROMPT
# ============================================================

def build_groq_prompt(
    article,
    relevant_terms,
    terms_data
):

    terms_text = (
        build_terms_text(
            relevant_terms
        )
    )

    translation_rules = (
        build_rule_text(
            terms_data,
            "TRANSLATION_RULES",
            2200
        )
    )

    news_structure = (
        build_rule_text(
            terms_data,
            "NEWS_STRUCTURE",
            1800
        )
    )

    malay_style = (
        build_rule_text(
            terms_data,
            "MALAY_STYLE",
            1800
        )
    )

    chinese_style = (
        build_rule_text(
            terms_data,
            "CHINESE_STYLE",
            1800
        )
    )

    local_enforcement = (
        build_rule_text(
            terms_data,
            "LOCAL_TERM_ENFORCEMENT",
            1200
        )
    )

    proper_name_rules = (
        build_rule_text(
            terms_data,
            "proper_name_rules",
            1600
        )
    )

    if proper_name_rules == (
        "No proper_name_rules rules."
    ):

        proper_name_rules = (
            build_rule_text(
                terms_data,
                "PROPER_NAME_RULES",
                1600
            )
        )

    money_rules = (
        build_rule_text(
            terms_data,
            "money_rules",
            1000
        )
    )

    if money_rules == (
        "No money_rules rules."
    ):

        money_rules = (
            build_rule_text(
                terms_data,
                "MONEY_RULES",
                1000
            )
        )

    number_rules = (
        build_rule_text(
            terms_data,
            "number_rules",
            1000
        )
    )

    if number_rules == (
        "No number_rules rules."
    ):

        number_rules = (
            build_rule_text(
                terms_data,
                "NUMBER_RULES",
                1000
            )
        )

    hard_rules = (
        build_hard_rules(
            terms_data
        )
    )

    source_article = (
        build_source_article(
            article
        )
    )

    prompt = f"""
You are MYBUZZ NEWS's professional Malaysian news editor
and bilingual translator.

Rewrite ONE Malaysian news article into:

1. Natural Malaysian Chinese
2. Natural Malaysian Malay

============================================================
PRIORITY
============================================================

1. Factual accuracy
2. Names
3. Places
4. Numbers
5. Money
6. Dates and times
7. Attribution
8. Uncertainty
9. Dictionary terms
10. Natural Malaysian news language

============================================================
ABSOLUTE RULES
============================================================

- Never invent facts.
- Never invent people.
- Never invent places.
- Never invent organizations.
- Never invent dates.
- Never invent numbers.
- Never invent money.
- Never invent quotes.
- Never add unsupported information.
- Never add opinions.
- Never speculate.
- Never change the meaning.
- Allegations must remain allegations.
- Suspicions must remain suspicions.
- Expected events must remain expected.
- Projected figures must remain projected.
- Preserve all important numbers exactly.

============================================================
LOCAL MALAYSIAN TERMS
============================================================

Oriental Kopi / Oriental Coffee
=> 华阳咖啡 in Chinese.

mamak
=> 嘛嘛档 in Chinese.

teh tarik
=> 拉茶.

kopi o
=> 咖啡乌.

kopitiam
=> 咖啡店.

pasar malam
=> 夜市.

wet market
=> 湿巴刹.

hawker centre
=> 小贩中心.

kampung
=> 甘榜.

Hari Kebangsaan
=> 国庆日.

Hari Malaysia
=> 马来西亚日.

Jalur Gemilang
=> 马来西亚国旗.

flood
=> 水灾.

flash flood
=> 突发水灾.

landslide
=> 土崩.

haze
=> 烟霾.

============================================================
HARD RULES
============================================================

{hard_rules}

============================================================
DICTIONARY TERMS
============================================================

{terms_text}

============================================================
TRANSLATION RULES
============================================================

{translation_rules}

============================================================
NEWS STRUCTURE
============================================================

{news_structure}

============================================================
MALAY STYLE
============================================================

{malay_style}

============================================================
CHINESE STYLE
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
CHINESE
============================================================

Use modern Malaysian Chinese news language.

Headline:
- concise
- factual
- natural
- no clickbait
- do not translate English word-for-word

Body:
- 1 to 2 concise sentences
- main fact first
- preserve important context
- do not repeat the headline

Do not invent Chinese names.

============================================================
MALAY
============================================================

Use modern Malaysian Malay news language.

Do NOT use Indonesian vocabulary.

Headline:
- concise
- factual
- natural
- no clickbait

Body:
- 1 to 2 concise sentences
- main fact first
- natural Malaysian Malay

============================================================
NUMBERS AND MONEY
============================================================

Never change numerical values.

85亿 = 8.5 billion
8.5 billion = 85亿
85 billion = 850亿

RM85亿 = RM8.5 bilion
RM8.5 bilion = RM85亿
RM85 bilion = RM850亿

============================================================
UNCERTAINTY
============================================================

expected = 预计 / dijangka
projected = 预计 / diunjurkan
likely = 可能 / berkemungkinan
may = 可能 / mungkin
could = 可能 / boleh
alleged = 被指 / didakwa
suspected = 涉嫌 / disyaki

============================================================
OUTPUT
============================================================

Return ONLY valid JSON.

Exactly:

{{
  "chinese_title": "...",
  "chinese_body": "...",
  "malay_title": "...",
  "malay_body": "..."
}}

No Markdown.
No code fence.
No explanation.
No emojis.
No URL.
No source line.

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
# AI FIELD VALIDATION
# ============================================================

def validate_ai_fields(
    data
):

    if not isinstance(
        data,
        dict
    ):

        print(
            "ERROR AI output is not an object."
        )

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
                f"ERROR invalid AI field: {key}"
            )

            return False

        if not clean_text(
            value
        ):

            print(
                f"ERROR empty AI field: {key}"
            )

            return False

    return True


# ============================================================
# PROPER NOUN VALIDATION
# ============================================================

def validate_proper_nouns(
    article_text,
    ai_data,
    relevant_terms
):

    print(
        "Running PROPER NOUN VALIDATOR V7.1"
    )

    chinese_text = (
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

    malay_text = (
        clean_text(
            ai_data.get(
                "malay_title",
                ""
            )
        )
        +
        " "
        +
        clean_text(
            ai_data.get(
                "malay_body",
                ""
            )
        )
    )

    chinese_lower = (
        chinese_text.lower()
    )

    malay_lower = (
        malay_text.lower()
    )

    article_lower = (
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
            not in article_lower
        ):

            continue

        if not target:

            continue

        source_lower = (
            source.lower()
        )

        target_lower = (
            target.lower()
        )

        # ====================================================
        # KEEP ORIGINAL
        # ====================================================

        if item.get(
            "keep_original",
            False
        ):

            if (
                source_lower not in chinese_lower
                and
                source_lower not in malay_lower
            ):

                print(
                    "KEEP ORIGINAL term missing: "
                    f"{source}"
                )

                return False

            print(
                f"  PASS KEEP ORIGINAL: "
                f"{source}"
            )

            continue

        # ====================================================
        # CHINESE TARGET
        # ====================================================

        if re.search(
            r"[\u4e00-\u9fff]",
            target
        ):

            # =================================================
            # THIS IS THE IMPORTANT FIX
            #
            # First check the translated Chinese target.
            #
            # Example:
            #
            # Bursa Malaysia
            # =>
            # 马来西亚交易所
            #
            # If target exists, PASS immediately.
            # =================================================

            if target_lower in chinese_lower:

                print(
                    f"  PASS Chinese term: "
                    f"{source} -> {target}"
                )

                continue

            # =================================================
            # Only fail if source remains AND target missing.
            # =================================================

            if source_lower in chinese_lower:

                print(
                    "Chinese proper noun not translated: "
                    f"{source} -> {target}"
                )

                return False

            # Source not present in Chinese.
            # Nothing to reject.
            continue

        # ====================================================
        # MALAY TARGET
        # ====================================================

        if (
            target_lower
            == source_lower
        ):

            continue

        if source_lower in malay_lower:

            print(
                "Malay term may not follow dictionary: "
                f"{source} -> {target}"
            )

            return False

    print(
        "PROPER NOUN VALIDATOR V7.1 PASS"
    )

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

    chinese_lower = (
        chinese.lower()
    )

    article_lower = (
        article_text.lower()
    )

    # ========================================================
    # Oriental Kopi
    # ========================================================

    oriental_present = (
        "oriental kopi"
        in article_lower
        or
        "oriental coffee"
        in article_lower
    )

    if oriental_present:

        if "东方咖啡" in chinese:

            print(
                "Hard validation failed: "
                "东方咖啡 is forbidden."
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

        if (
            "mamak"
            in chinese_lower
            and
            "嘛嘛档"
            not in chinese
        ):

            print(
                "Hard validation failed: "
                "mamak should be 嘛嘛档."
            )

            return False

    return True


# ============================================================
# GROQ
# ============================================================

def generate_ai_content(
    article,
    terms_data
):

    if groq_client is None:

        print(
            "ERROR Groq client unavailable."
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
        f"Relevant dictionary terms: "
        f"{len(relevant_terms)}"
    )

    for item in relevant_terms:

        print(
            f'  [{item["category"]}] '
            f'{item["source"]} => '
            f'{item["target"]}'
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
            f"Sending Groq request attempt "
            f"{attempt}/{MAX_AI_ATTEMPTS}"
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

            choice = response.choices[0]

            finish_reason = getattr(
                choice,
                "finish_reason",
                None
            )

            print(
                f"Groq finish reason: "
                f"{finish_reason}"
            )

            content = ""

            if choice.message:

                content = (
                    choice.message.content
                    or ""
                )

            if not content:

                print(
                    "ERROR Groq returned empty content."
                )

                return None

            if finish_reason in (
                "length",
                "max_tokens"
            ):

                print(
                    "ERROR Groq response "
                    "reached token limit."
                )

                return None

            ai_data = extract_json(
                content
            )

            if ai_data is None:

                print(
                    "ERROR AI returned invalid JSON."
                )

                print(
                    content[:1000]
                )

                return None

            if not validate_ai_fields(
                ai_data
            ):

                print(
                    "ERROR AI JSON validation failed."
                )

                return None

            # =================================================
            # PROPER NOUN VALIDATION
            # =================================================

            if not validate_proper_nouns(
                article_text,
                ai_data,
                relevant_terms
            ):

                print(
                    "ERROR AI proper noun "
                    "validation failed."
                )

                return None

            # =================================================
            # LOCAL TERM VALIDATION
            # =================================================

            if not validate_hard_local_terms(
                article_text,
                ai_data
            ):

                print(
                    "ERROR AI local terminology "
                    "validation failed."
                )

                return None

            print(
                "AI generation successful."
            )

            return ai_data

        except Exception as e:

            print(
                f"ERROR Groq request failed: {e}"
            )

            return None

    return None


# ============================================================
# TELEGRAM URL
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
# TELEGRAM HTML MESSAGE
# ============================================================

def build_telegram_news(
    ai_data,
    source_url
):

    chinese_title = html.escape(
        clean_text(
            ai_data.get(
                "chinese_title",
                ""
            )
        )
    )

    chinese_body = html.escape(
        clean_text(
            ai_data.get(
                "chinese_body",
                ""
            )
        )
    )

    malay_title = html.escape(
        clean_text(
            ai_data.get(
                "malay_title",
                ""
            )
        )
    )

    malay_body = html.escape(
        clean_text(
            ai_data.get(
                "malay_body",
                ""
            )
        )
    )

    safe_url = html.escape(
        source_url,
        quote=True
    )

    return (
        "🇲🇾 <b>MYBuzz NEWS</b>\n\n"

        "🇨🇳 <b>"
        + chinese_title
        + "</b>\n"
        + chinese_body
        + "\n\n"

        "🇲🇾 <b>"
        + malay_title
        + "</b>\n"
        + malay_body
        + "\n\n"

        "👉 <b>点击阅读完整新闻</b>\n"
        + safe_url
        + "\n\n"

        "👉 <b>Klik untuk baca berita penuh</b>\n"
        + safe_url
    )


# ============================================================
# TELEGRAM PLAIN MESSAGE
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
# TELEGRAM PHOTO
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
                response.text[:1000]
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
            f"ERROR Telegram photo failed: {e}"
        )

        return False


# ============================================================
# TELEGRAM TEXT
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
                response.text[:1000]
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
            f"ERROR Telegram text failed: {e}"
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
        "MYBUZZ NEWS BOT V7.1"
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
    # POSTED
    # ========================================================

    posted = load_posted()

    print(
        f"Posted database: "
        f"{len(posted)} records"
    )

    # ========================================================
    # DICTIONARY
    # ========================================================

    terms_data = load_terms()

    if not terms_data:

        print(
            "ERROR Dictionary empty."
        )

        return

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
    # SELECT
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
    # TELEGRAM
    # ========================================================

    source_url = normalize_url(
        article.get(
            "url",
            ""
        )
    )

    image_url = article.get(
        "_image",
        ""
    )

    caption = build_telegram_news(
        ai_data,
        source_url
    )

    plain_text = (
        build_telegram_plain_text(
            ai_data,
            source_url
        )
    )

    print(
        f"Telegram caption length: "
        f"{len(caption)}"
    )

    # ========================================================
    # PHOTO
    # ========================================================

    sent = False

    if (
        image_url
        and
        len(caption)
        <= TELEGRAM_CAPTION_LIMIT
    ):

        sent = send_telegram_photo(
            image_url,
            caption
        )

    else:

        if image_url:

            print(
                "Telegram caption too long. "
                "Using text."
            )

    # ========================================================
    # TEXT FALLBACK
    # ========================================================

    if not sent:

        print(
            "Sending Telegram text message..."
        )

        if len(plain_text) > TELEGRAM_TEXT_LIMIT:

            print(
                "ERROR Telegram text exceeds limit."
            )

            return

        sent = send_telegram_text(
            plain_text
        )

    # ========================================================
    # SAVE ONLY AFTER SUCCESS
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
        "MYBUZZ NEWS BOT FINISHED"
    )

    print(
        "=" * 60
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    main()
