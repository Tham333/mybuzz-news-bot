import os
import re
import time
import json
import html
import sqlite3
import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import requests
from google import genai
from google.genai import types


# ============================================================
# MYBUZZ NEWS BOT V6
# ============================================================

print("=" * 40)
print("MYBUZZ NEWS BOT V6")
print("=" * 40)


# ============================================================
# ENV
# ============================================================

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-2.5-flash"
)

PUBLISH_COUNT = int(
    os.getenv("MYBUZZ_PUBLISH_COUNT", "8")
)

LOOKBACK_HOURS = int(
    os.getenv("MYBUZZ_LOOKBACK_HOURS", "30")
)

DRY_RUN = os.getenv(
    "MYBUZZ_DRY_RUN",
    "false"
).lower() == "true"

DB_PATH = "mybuzz.db"


# ============================================================
# CATEGORY RATIO
#
# 8 POSTS:
# News          3
# Viral         2
# Entertainment 1
# Food          1
# Tech          1
#
# = 40 / 25 / 15 / 10 / 10 approximately
# ============================================================

TARGETS = {
    "news": 0.40,
    "viral": 0.25,
    "entertainment": 0.15,
    "food": 0.10,
    "tech": 0.10,
}


CATEGORY_LABELS = {
    "news": "📰 NEWS",
    "viral": "🔥 VIRAL",
    "entertainment": "🎬 ENTERTAINMENT",
    "food": "🍜 FOOD / LIFESTYLE",
    "tech": "📱 TECH / GADGET",
}


# ============================================================
# GNEWS SEARCH QUERIES
# ============================================================

QUERIES = {

    "news": [
        "Malaysia government",
        "Malaysia politics",
        "Malaysia economy",
        "Malaysia crime",
        "Malaysia education",
        "Malaysia latest news",
    ],

    "viral": [
        "Malaysia viral",
        "Malaysia trending",
        "Malaysia netizens",
        "Malaysia tular",
        "Malaysia social media",
    ],

    "entertainment": [
        "Malaysia entertainment",
        "Malaysia celebrity",
        "Malaysia singer",
        "Malaysia actor",
        "Malaysia K-pop",
        "Malaysia concert",
        "Malaysia movie",
    ],

    "food": [
        "Malaysia food",
        "Malaysia restaurant",
        "Malaysia cafe",
        "Malaysia new restaurant",
        "Malaysia food trend",
        "Malaysia lifestyle",
    ],

    "tech": [
        "Malaysia technology",
        "Malaysia gadget",
        "Malaysia smartphone",
        "Malaysia AI",
        "Malaysia Apple",
        "Malaysia Android",
        "Malaysia tech",
    ],
}


# ============================================================
# KEYWORDS
# ============================================================

KEYWORDS = {

    "viral": [
        "viral",
        "trending",
        "netizen",
        "tular",
        "sensasi",
        "social media",
        "bizarre",
        "popular",
    ],

    "entertainment": [
        "entertainment",
        "celebrity",
        "singer",
        "actor",
        "actress",
        "k-pop",
        "concert",
        "movie",
        "music",
        "showbiz",
        "drama",
    ],

    "food": [
        "food",
        "restaurant",
        "cafe",
        "donut",
        "dessert",
        "chef",
        "dining",
        "travel",
        "lifestyle",
    ],

    "tech": [
        "technology",
        "tech",
        "gadget",
        "iphone",
        "android",
        "ai",
        "artificial intelligence",
        "smartphone",
        "telco",
        "software",
    ],
}


# ============================================================
# CHECK ENV
# ============================================================

required = {
    "GNEWS_API_KEY": GNEWS_API_KEY,
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
}

missing = [
    name
    for name, value in required.items()
    if not value
]

if missing:
    raise SystemExit(
        "Missing GitHub Secrets: "
        + ", ".join(missing)
    )

print("GNews API: OK")
print("Gemini API: OK")
print("Telegram: OK")


# ============================================================
# DATABASE
# ============================================================

def get_database():

    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen (
            article_key TEXT PRIMARY KEY,
            url TEXT,
            title TEXT,
            published_at TEXT,
            category TEXT,
            posted_at TEXT
        )
    """)

    conn.commit()

    return conn


# ============================================================
# HTTP JSON
# ============================================================

def get_json(url, params):

    full_url = (
        url
        + "?"
        + urlencode(params)
    )

    for attempt in range(3):

        try:

            request = Request(
                full_url,
                headers={
                    "User-Agent":
                    "MYBUZZ-NewsBot/6.0"
                }
            )

            with urlopen(
                request,
                timeout=25
            ) as response:

                return json.loads(
                    response
                    .read()
                    .decode("utf-8")
                )

        except Exception as error:

            print(
                f"[WARN] HTTP attempt "
                f"{attempt + 1}/3: {error}"
            )

            if attempt < 2:
                time.sleep(
                    2 ** attempt
                )

    return {}


# ============================================================
# FETCH GNEWS
# ============================================================

def fetch_category(category):

    since = (
        datetime.now(timezone.utc)
        - timedelta(
            hours=LOOKBACK_HOURS
        )
    ).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    articles = []

    for query in QUERIES[category]:

        params = {
            "q": query,
            "lang": "en",
            "country": "my",
            "max": 10,
            "sortby": "publishedAt",
            "from": since,
            "apikey": GNEWS_API_KEY,
        }

        print(
            f"Fetching [{category}] "
            f"{query}"
        )

        try:

            data = get_json(
                "https://gnews.io/api/v4/search",
                params
            )

            for article in data.get(
                "articles",
                []
            ):

                article[
                    "_requested_category"
                ] = category

                articles.append(article)

        except Exception as error:

            print(
                "[WARN] GNews error:",
                error
            )

    return articles


# ============================================================
# NORMALIZE
# ============================================================

def normalize(text):

    text = (text or "").lower()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    text = re.sub(
        r"[^a-z0-9 ]",
        "",
        text
    )

    return text.strip()


# ============================================================
# ARTICLE HASH
# ============================================================

def article_key(article):

    url = (
        article.get("url")
        or ""
    ).strip()

    title = normalize(
        article.get("title")
    )

    source = url or title

    return hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


# ============================================================
# SIMILAR TITLE KEY
# ============================================================

def title_key(article):

    words = [
        word
        for word in normalize(
            article.get("title")
        ).split()
        if len(word) > 3
    ]

    return " ".join(
        sorted(words[:12])
    )


# ============================================================
# DEDUPLICATE
# ============================================================

def deduplicate(articles):

    seen_urls = set()
    seen_titles = set()

    result = []

    articles.sort(
        key=lambda x:
        x.get(
            "publishedAt",
            ""
        ),
        reverse=True
    )

    for article in articles:

        url_hash = article_key(
            article
        )

        title_hash = title_key(
            article
        )

        if url_hash in seen_urls:
            continue

        if (
            title_hash
            and title_hash in seen_titles
        ):
            continue

        seen_urls.add(
            url_hash
        )

        if title_hash:
            seen_titles.add(
                title_hash
            )

        result.append(
            article
        )

    return result


# ============================================================
# CATEGORY CLASSIFICATION
# ============================================================

def classify(article):

    text = (
        (article.get("title") or "")
        + " "
        + (article.get("description") or "")
    ).lower()

    scores = {
        category: 0
        for category in TARGETS
    }

    requested = article.get(
        "_requested_category",
        "news"
    )

    scores[requested] += 3

    for category, words in KEYWORDS.items():

        for word in words:

            if word in text:
                scores[category] += 1

    return max(
        scores,
        key=scores.get
    )


# ============================================================
# BALANCED SELECTION
# ============================================================

def select_balanced(
    articles,
    total
):

    for article in articles:

        article["_category"] = (
            classify(article)
        )

    quotas = {
        category:
        int(total * ratio)
        for category, ratio
        in TARGETS.items()
    }

    remainder = (
        total
        - sum(quotas.values())
    )

    fractions = sorted(
        (
            (
                total * ratio
                - int(total * ratio),
                category
            )
            for category, ratio
            in TARGETS.items()
        ),
        reverse=True
    )

    for _, category in fractions[
        :remainder
    ]:

        quotas[category] += 1

    print(
        "Target distribution:",
        quotas
    )

    groups = {
        category: []
        for category in TARGETS
    }

    for article in articles:

        groups[
            article["_category"]
        ].append(article)

    for group in groups.values():

        group.sort(
            key=lambda x:
            x.get(
                "publishedAt",
                ""
            ),
            reverse=True
        )

    selected = []
    used = set()

    # First fill the target categories
    for category, quota in quotas.items():

        count = 0

        for article in groups[category]:

            key = article_key(
                article
            )

            if key in used:
                continue

            selected.append(
                article
            )

            used.add(key)

            count += 1

            if count >= quota:
                break

    # Fill any missing slots
    if len(selected) < total:

        remaining = [
            article
            for article in articles
            if article_key(article)
            not in used
        ]

        remaining.sort(
            key=lambda x:
            x.get(
                "publishedAt",
                ""
            ),
            reverse=True
        )

        selected.extend(
            remaining[
                :total - len(selected)
            ]
        )

    return selected[:total]


# ============================================================
# GEMINI
# ============================================================

def generate_translation(
    client,
    article
):

    source = (
        article.get(
            "source",
            {}
        )
        or {}
    ).get(
        "name",
        ""
    )

    prompt = f"""
You are the editor of MYBUZZ,
a Malaysia-focused Telegram channel.

Create a short bilingual post
from the source article.

Return ONLY valid JSON:

{{
  "title_zh": "",
  "summary_zh": "",
  "title_ms": "",
  "summary_ms": "",
  "category": ""
}}

category MUST be one of:
news
viral
entertainment
food
tech

RULES:

1. Chinese = natural Simplified Chinese.
2. Malay = natural Malaysian Bahasa Melayu.
3. Do not invent information.
4. Keep names accurate.
5. Keep numbers accurate.
6. Keep dates accurate.
7. Keep locations accurate.
8. Summary = maximum 2 short sentences.
9. Do not copy long sentences.
10. Sensitive news must be neutral.
11. Make the headline attractive but factual.
12. Do not put emojis inside the title.
13. Category must match the actual article.

SOURCE:
Publisher: {source}

Title:
{article.get("title", "")}

Description:
{article.get("description", "")}

URL:
{article.get("url", "")}
"""

    retry_delays = [
        5,
        15,
        30,
        60
    ]

    for attempt in range(4):

        try:

            print(
                f"Gemini attempt "
                f"{attempt + 1}/4..."
            )

            response = (
                client
                .models
                .generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        response_mime_type="application/json",
                    ),
                )
            )

            if not response.text:

                raise RuntimeError(
                    "Gemini returned empty response"
                )

            result = json.loads(
                response.text
            )

            if (
                result.get("category")
                not in TARGETS
            ):

                result["category"] = (
                    article.get(
                        "_category",
                        "news"
                    )
                )

            return result

        except Exception as error:

            print(
                f"[WARN] Gemini error: "
                f"{error}"
            )

            if attempt < 3:

                print(
                    f"Retrying in "
                    f"{retry_delays[attempt]}"
                    f" seconds..."
                )

                time.sleep(
                    retry_delays[attempt]
                )

    return None


# ============================================================
# IMAGE VALIDATION
# ============================================================

def valid_image(url):

    if not url:
        return False

    if not url.startswith(
        ("http://", "https://")
    ):
        return False

    lowered = url.lower()

    # Prevent logos being used
    # as article images.
    blocked = [
        "logo",
        "favicon",
        "placeholder",
        "default-image",
        "default_image",
        "avatar",
    ]

    for word in blocked:

        if word in lowered:

            print(
                "Image rejected:",
                word
            )

            return False

    try:

        response = requests.get(
            url,
            stream=True,
            timeout=10,
            headers={
                "User-Agent":
                "MYBUZZ-NewsBot/6.0"
            }
        )

        content_type = (
            response
            .headers
            .get(
                "content-type",
                ""
            )
            .lower()
        )

        if response.status_code != 200:
            return False

        if "image/" not in content_type:
            return False

        return True

    except Exception:

        return False


# ============================================================
# TELEGRAM
# ============================================================

def telegram_request(
    method,
    data
):

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/"
        f"{method}"
    )

    for attempt in range(3):

        try:

            response = requests.post(
                url,
                data=data,
                timeout=30
            )

            if response.ok:

                result = (
                    response
                    .json()
                )

                if result.get("ok"):

                    return True

                print(
                    "[WARN] Telegram:",
                    result
                )

            else:

                print(
                    "[WARN] Telegram HTTP:",
                    response.status_code,
                    response.text[:300]
                )

        except Exception as error:

            print(
                "[WARN] Telegram error:",
                error
            )

        if attempt < 2:

            time.sleep(
                2 ** attempt
            )

    return False


# ============================================================
# BUILD TELEGRAM POST
# ============================================================

def build_message(
    article,
    translated
):

    category = translated.get(
        "category",
        article.get(
            "_category",
            "news"
        )
    )

    label = CATEGORY_LABELS.get(
        category,
        CATEGORY_LABELS["news"]
    )

    title_zh = html.escape(
        translated.get(
            "title_zh",
            ""
        )
    )

    summary_zh = html.escape(
        translated.get(
            "summary_zh",
            ""
        )
    )

    title_ms = html.escape(
        translated.get(
            "title_ms",
            ""
        )
    )

    summary_ms = html.escape(
        translated.get(
            "summary_ms",
            ""
        )
    )

    url = article.get(
        "url",
        ""
    )

    safe_url = html.escape(
        url,
        quote=True
    )

    source = html.escape(
        (
            article.get(
                "source",
                {}
            )
            or {}
        ).get(
            "name",
            "Source"
        )
    )

    message = (
        f"<b>{label}｜"
        f"{title_zh}</b>\n\n"

        f"🇨🇳 {summary_zh}\n\n"

        f"<b>🇲🇾 "
        f"{title_ms}</b>\n\n"

        f"{summary_ms}\n\n"

        f"👉 <b>"
        f"<a href=\"{safe_url}\">"
        f"点击阅读完整新闻"
        f"</a>"
        f"</b>\n"

        f"👉 <b>"
        f"<a href=\"{safe_url}\">"
        f"Klik untuk baca berita penuh"
        f"</a>"
        f"</b>\n\n"

        f"🔗 {source}"
    )

    return message


# ============================================================
# PUBLISH
# ============================================================

def publish_article(
    article,
    translated
):

    message = build_message(
        article,
        translated
    )

    if DRY_RUN:

        print("\n")
        print("=" * 70)
        print(message)
        print("=" * 70)
        print("\n")

        return True

    image = article.get(
        "image"
    )

    # IMPORTANT:
    # Never use obvious logos.
    if valid_image(image):

        print(
            "Sending article image..."
        )

        success = telegram_request(
            "sendPhoto",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,

                "photo":
                    image,

                "caption":
                    message,

                "parse_mode":
                    "HTML",
            }
        )

        if success:

            return True

    # If image is missing/bad,
    # send normal Telegram post.
    print(
        "Image unavailable, "
        "sending text post..."
    )

    return telegram_request(
        "sendMessage",
        {
            "chat_id":
                TELEGRAM_CHAT_ID,

            "text":
                message,

            "parse_mode":
                "HTML",

            "disable_web_page_preview":
                "false",
        }
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        f"Lookback: "
        f"{LOOKBACK_HOURS} hours"
    )

    print(
        f"Publish count: "
        f"{PUBLISH_COUNT}"
    )

    # --------------------------------------------------------
    # FETCH
    # --------------------------------------------------------

    all_articles = []

    for category in QUERIES:

        articles = fetch_category(
            category
        )

        all_articles.extend(
            articles
        )

    print(
        f"Raw articles: "
        f"{len(all_articles)}"
    )

    # --------------------------------------------------------
    # DEDUPE
    # --------------------------------------------------------

    all_articles = deduplicate(
        all_articles
    )

    print(
        f"After dedupe: "
        f"{len(all_articles)}"
    )

    # --------------------------------------------------------
    # DATABASE
    # --------------------------------------------------------

    conn = get_database()

    seen = {
        row[0]
        for row in conn.execute(
            "SELECT article_key FROM seen"
        )
    }

    fresh_articles = [
        article
        for article in all_articles
        if article_key(article)
        not in seen
    ]

    print(
        f"Fresh articles: "
        f"{len(fresh_articles)}"
    )

    if not fresh_articles:

        print(
            "No new articles."
        )

        conn.close()

        return

    # --------------------------------------------------------
    # SELECT BALANCED
    # --------------------------------------------------------

    selected = select_balanced(
        fresh_articles,
        PUBLISH_COUNT
    )

    print(
        f"Selected articles: "
        f"{len(selected)}"
    )

    # --------------------------------------------------------
    # GEMINI
    # --------------------------------------------------------

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    posted = 0

    # --------------------------------------------------------
    # PUBLISH
    # --------------------------------------------------------

    for index, article in enumerate(
        selected,
        start=1
    ):

        print()
        print(
            "=" * 60
        )

        print(
            f"[{index}/{len(selected)}]"
        )

        print(
            article.get(
                "title",
                ""
            )
        )

        print(
            "Category:",
            article.get(
                "_category",
                "news"
            )
        )

        # --------------------------------------------
        # AI
        # --------------------------------------------

        translated = (
            generate_translation(
                client,
                article
            )
        )

        if not translated:

            print(
                "Gemini failed after "
                "all retries."
            )

            print(
                "Skipping this article."
            )

            continue

        # Gemini can correct category
        ai_category = translated.get(
            "category"
        )

        if ai_category in TARGETS:

            article["_category"] = (
                ai_category
            )

        # --------------------------------------------
        # TELEGRAM
        # --------------------------------------------

        success = publish_article(
            article,
            translated
        )

        if success:

            posted += 1

            conn.execute(
                """
                INSERT OR IGNORE INTO seen
                (
                    article_key,
                    url,
                    title,
                    published_at,
                    category,
                    posted_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    article_key(article),

                    article.get(
                        "url",
                        ""
                    ),

                    article.get(
                        "title",
                        ""
                    ),

                    article.get(
                        "publishedAt",
                        ""
                    ),

                    article.get(
                        "_category",
                        "news"
                    ),

                    datetime.now(
                        timezone.utc
                    ).isoformat(),
                )
            )

            conn.commit()

            print(
                "Telegram: POSTED"
            )

        else:

            print(
                "Telegram: FAILED"
            )

        # Don't spam Telegram/API
        time.sleep(3)

    conn.close()

    print()
    print("=" * 40)
    print(
        f"DONE | "
        f"Posted {posted}/{len(selected)}"
    )
    print("=" * 40)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
