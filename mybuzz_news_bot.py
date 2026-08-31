import os
import json
import logging
import hashlib
from datetime import datetime, timezone

import feedparser
import requests
from openai import OpenAI


# ============================================================
# MYBUZZ NEWS BOT V6
# ============================================================

BOT_NAME = "MYBUZZ V6"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-20b"

POSTER_FILE = "poster.json"

MAX_ARTICLES = 1
REQUEST_TIMEOUT = 20


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(BOT_NAME)


# ============================================================
# OPENAI CLIENT -> GROQ
# ============================================================

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is missing.")

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url=GROQ_BASE_URL,
)


# ============================================================
# RSS SOURCES
# ============================================================

RSS_SOURCES = [
    {
        "name": "Malay Mail",
        "url": "https://www.malaymail.com/feed/rss/malaysia"
    },
    {
        "name": "New Straits Times",
        "url": "https://www.nst.com.my/feed"
    },
    {
        "name": "The Star",
        "url": "https://www.thestar.com.my/rss/News"
    },
    {
        "name": "The Edge Malaysia",
        "url": "https://theedgemalaysia.com/rss.xml"
    },
    {
        "name": "Bernama",
        "url": "https://bernama.com/en/rss/news.php"
    },
]


# ============================================================
# POSTER / DUPLICATE STORAGE
# ============================================================

def load_posted():
    if not os.path.exists(POSTER_FILE):
        return []

    try:
        with open(POSTER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            return data.get("posted", [])

    except Exception as e:
        logger.warning("Could not read poster.json: %s", e)

    return []


def save_posted(posted):
    try:
        with open(POSTER_FILE, "w", encoding="utf-8") as f:
            json.dump(
                posted[-500:],
                f,
                ensure_ascii=False,
                indent=2
            )
    except Exception as e:
        logger.error("Could not save poster.json: %s", e)


def article_id(article):
    link = article.get("link", "").strip()

    if link:
        return hashlib.sha256(link.encode("utf-8")).hexdigest()

    title = article.get("title", "").strip()

    return hashlib.sha256(
        title.encode("utf-8")
    ).hexdigest()


# ============================================================
# RSS
# ============================================================

def fetch_rss(source):
    name = source["name"]
    url = source["url"]

    logger.info("Fetching RSS: %s", name)

    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "MYBUZZ-News-Bot/6.0"
                )
            }
        )

        response.raise_for_status()

        feed = feedparser.parse(response.content)

        articles = []

        for entry in feed.entries[:50]:

            title = (
                entry.get("title")
                or ""
            ).strip()

            link = (
                entry.get("link")
                or ""
            ).strip()

            summary = (
                entry.get("summary")
                or entry.get("description")
                or ""
            ).strip()

            if not title or not link:
                continue

            image_url = extract_image(entry)

            articles.append({
                "source": name,
                "title": title,
                "link": link,
                "summary": summary,
                "image": image_url,
            })

        logger.info(
            "%s: %s recent articles",
            name,
            len(articles)
        )

        return articles

    except Exception as e:
        logger.warning(
            "RSS failed [%s]: %s",
            name,
            e
        )

        return []


def extract_image(entry):
    # media_content
    media_content = entry.get("media_content")

    if media_content:
        for media in media_content:
            if isinstance(media, dict):
                url = media.get("url")

                if url:
                    return url

    # media_thumbnail
    media_thumbnail = entry.get("media_thumbnail")

    if media_thumbnail:
        for media in media_thumbnail:
            if isinstance(media, dict):
                url = media.get("url")

                if url:
                    return url

    # enclosure
    enclosures = entry.get("enclosures")

    if enclosures:
        for enclosure in enclosures:
            if isinstance(enclosure, dict):
                url = enclosure.get("href") or enclosure.get("url")

                if url:
                    return url

    # links
    links = entry.get("links")

    if links:
        for item in links:
            if not isinstance(item, dict):
                continue

            href = item.get("href", "")
            link_type = item.get("type", "")

            if (
                href
                and (
                    link_type.startswith("image/")
                    or "image" in href.lower()
                )
            ):
                return href

    return None


# ============================================================
# GET IMAGE FROM NEWS PAGE IF RSS HAS NO IMAGE
# ============================================================

def find_image_from_page(url):
    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "Chrome/139.0 Safari/537.36"
                )
            }
        )

        response.raise_for_status()

        html = response.text

        # og:image
        markers = [
            'property="og:image"',
            "property='og:image'",
            'name="twitter:image"',
            "name='twitter:image'",
        ]

        for marker in markers:
            position = html.lower().find(marker.lower())

            if position == -1:
                continue

            section = html[
                max(0, position - 500):
                position + 1000
            ]

            # content="..."
            lower_section = section.lower()

            content_pos = lower_section.find("content=")

            if content_pos != -1:

                start = content_pos + len("content=")

                if start < len(section):

                    quote = section[start]

                    if quote in ('"', "'"):

                        end = section.find(
                            quote,
                            start + 1
                        )

                        if end != -1:
                            image = section[
                                start + 1:end
                            ].strip()

                            if image.startswith("http"):
                                return image

    except Exception as e:
        logger.warning(
            "Could not find page image: %s",
            e
        )

    return None


# ============================================================
# CLEAN HTML
# ============================================================

def clean_text(text):
    import re
    from html import unescape

    text = unescape(text)

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
# GROQ AI
# ============================================================

def generate_translation(article):
    title = clean_text(article["title"])
    summary = clean_text(article["summary"])

    prompt = f"""
You are MYBUZZ Malaysia news editor.

Rewrite the following Malaysian news into a short Telegram news post.

IMPORTANT:
- Do NOT invent facts.
- Keep names, places, numbers and facts accurate.
- Chinese must be Simplified Chinese.
- Malay must be natural Malaysian Malay.
- Keep the Chinese version concise.
- Keep the Malay version concise.
- Do not include URLs.
- Do not use Markdown.
- Do not add headings such as "Chinese" or "Malay".
- Return ONLY valid JSON.

Required JSON format:

{{
  "zh_title": "...",
  "zh_body": "...",
  "ms_title": "...",
  "ms_body": "..."
}}

SOURCE:
{article["source"]}

TITLE:
{title}

SUMMARY:
{summary}
"""

    try:
        response = client.responses.create(
            model=GROQ_MODEL,
            input=prompt,
        )

        output = response.output_text.strip()

        logger.info(
            "AI response received."
        )

        # Remove possible markdown fences
        if output.startswith("```"):
            output = output.replace(
                "```json",
                ""
            ).replace(
                "```",
                ""
            ).strip()

        data = json.loads(output)

        required = [
            "zh_title",
            "zh_body",
            "ms_title",
            "ms_body",
        ]

        for key in required:
            if not data.get(key):
                raise ValueError(
                    f"Missing AI field: {key}"
                )

        return data

    except Exception as e:
        logger.error(
            "Groq/OpenAI API failed: %s",
            e
        )

        return None


# ============================================================
# TELEGRAM FORMAT
# ============================================================

def build_caption(article, ai):
    source = article["source"]
    link = article["link"]

    zh_title = ai["zh_title"].strip()
    zh_body = ai["zh_body"].strip()

    ms_title = ai["ms_title"].strip()
    ms_body = ai["ms_body"].strip()

    caption = (
        f"🇲🇾 {zh_title}\n\n"
        f"🇨🇳 {zh_body}\n\n"
        f"🇲🇾 {ms_title}\n\n"
        f"{ms_body}\n\n"
        f'👉 <a href="{link}">点击阅读完整新闻</a>\n\n'
        f'👉 <a href="{link}">Klik untuk baca berita penuh</a>'
    )

    return caption


# ============================================================
# TELEGRAM SEND PHOTO
# ============================================================

def send_photo(image_url, caption):
    if not TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN is missing."
        )
        return False

    if not TELEGRAM_CHAT_ID:
        logger.error(
            "TELEGRAM_CHAT_ID is missing."
        )
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    )

    try:
        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "photo": image_url,
                "caption": caption,
                "parse_mode": "HTML",
            },
            timeout=REQUEST_TIMEOUT
        )

        if response.ok:
            logger.info(
                "Telegram photo sent successfully."
            )
            return True

        logger.error(
            "Telegram photo failed: %s",
            response.text
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

def send_message(caption):
    if not TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN is missing."
        )
        return False

    if not TELEGRAM_CHAT_ID:
        logger.error(
            "TELEGRAM_CHAT_ID is missing."
        )
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": caption,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=REQUEST_TIMEOUT
        )

        if response.ok:
            logger.info(
                "Telegram message sent successfully."
            )
            return True

        logger.error(
            "Telegram message failed: %s",
            response.text
        )

        return False

    except Exception as e:
        logger.error(
            "Telegram message exception: %s",
            e
        )

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    logger.info("======================================")
    logger.info("MYBUZZ V6 START")
    logger.info(
        "Groq model: %s",
        GROQ_MODEL
    )
    logger.info("======================================")

    posted = load_posted()

    posted_set = set(posted)

    # --------------------------------------------------------
    # FETCH ALL RSS
    # --------------------------------------------------------

    all_articles = []

    for source in RSS_SOURCES:
        articles = fetch_rss(source)
        all_articles.extend(articles)

    logger.info(
        "Total RSS articles: %s",
        len(all_articles)
    )

    # --------------------------------------------------------
    # DUPLICATE FILTER
    # --------------------------------------------------------

    new_articles = []

    for article in all_articles:

        aid = article_id(article)

        if aid in posted_set:
            continue

        new_articles.append(article)

    logger.info(
        "New articles after duplicate filter: %s",
        len(new_articles)
    )

    # --------------------------------------------------------
    # ONE ARTICLE ONLY
    # --------------------------------------------------------

    if not new_articles:
        logger.info(
            "No new articles."
        )

        logger.info(
            "MYBUZZ V6 FINISHED | Sent: 0"
        )

        return

    selected = new_articles[:MAX_ARTICLES]

    logger.info(
        "Selected %s article.",
        len(selected)
    )

    sent_count = 0

    # --------------------------------------------------------
    # PROCESS
    # --------------------------------------------------------

    for index, article in enumerate(
        selected,
        start=1
    ):

        logger.info(
            "[%s/1] Processing: %s",
            index,
            article["title"]
        )

        # ----------------------------------------------------
        # IMAGE
        # ----------------------------------------------------

        image_url = article.get("image")

        if not image_url:
            logger.info(
                "RSS has no image. Trying news page..."
            )

            image_url = find_image_from_page(
                article["link"]
            )

        article["image"] = image_url

        if image_url:
            logger.info(
                "Image found: %s",
                image_url
            )
        else:
            logger.warning(
                "No image found. Will send text."
            )

        # ----------------------------------------------------
        # AI
        # ----------------------------------------------------

        ai = generate_translation(article)

        if not ai:
            logger.warning(
                "Skipping article because AI processing failed."
            )
            continue

        caption = build_caption(
            article,
            ai
        )

        # ----------------------------------------------------
        # TELEGRAM
        # ----------------------------------------------------

        if image_url:
            success = send_photo(
                image_url,
                caption
            )

            # If Telegram rejects image, fallback to message
            if not success:
                logger.warning(
                    "Photo failed. Trying text message..."
                )

                success = send_message(
                    caption
                )

        else:
            success = send_message(
                caption
            )

        # ----------------------------------------------------
        # SAVE ONLY AFTER SUCCESS
        # ----------------------------------------------------

        if success:

            aid = article_id(article)

            posted.append(aid)

            save_posted(posted)

            sent_count += 1

            logger.info(
                "Article marked as posted."
            )

        else:
            logger.error(
                "Telegram send failed. "
                "Article will NOT be marked as posted."
            )

    logger.info("======================================")
    logger.info(
        "MYBUZZ V6 FINISHED | Sent: %s",
        sent_count
    )
    logger.info("======================================")


if __name__ == "__main__":
    main()
