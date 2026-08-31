import os
import re
import html
import json
import time
import hashlib
import logging
from urllib.parse import urljoin

import feedparser
import requests
from groq import Groq


# ============================================================
# MYBUZZ NEWS BOT V6
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("MYBUZZ")


# ============================================================
# CONFIG
# ============================================================

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Groq model
GROQ_MODEL = "openai/gpt-oss-20b"

# IMPORTANT:
# One execution = maximum ONE news
MAX_ARTICLES = 1

REQUEST_TIMEOUT = 20

SEEN_FILE = "seen_articles.json"


# ============================================================
# RSS SOURCES
# ============================================================

RSS_SOURCES = [
    {
        "name": "Malay Mail",
        "url": "https://www.malaymail.com/feed/rss/malaysia",
    },
    {
        "name": "New Straits Times",
        "url": "https://www.nst.com.my/feed",
    },
    {
        "name": "The Star",
        "url": "https://www.thestar.com.my/rss/News",
    },
    {
        "name": "The Edge Malaysia",
        "url": "https://theedgemalaysia.com/rss.xml",
    },
    {
        "name": "Bernama",
        "url": "https://bernama.com/en/rss/news.php",
    },
]


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    )
}


# ============================================================
# CHECK ENVIRONMENT
# ============================================================

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is missing.")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing.")

if not TELEGRAM_CHAT_ID:
    raise RuntimeError("TELEGRAM_CHAT_ID is missing.")


# ============================================================
# GROQ CLIENT
# ============================================================

groq_client = Groq(
    api_key=GROQ_API_KEY
)


# ============================================================
# SEEN ARTICLES
# ============================================================

def load_seen():
    try:
        if not os.path.exists(SEEN_FILE):
            return set()

        with open(
            SEEN_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if isinstance(data, list):
            return set(data)

    except Exception as e:
        logger.warning(
            "Could not load seen articles: %s",
            e
        )

    return set()


def save_seen(seen):
    try:
        data = list(seen)

        # Keep database small
        if len(data) > 1000:
            data = data[-1000:]

        with open(
            SEEN_FILE,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:
        logger.warning(
            "Could not save seen articles: %s",
            e
        )


SEEN = load_seen()


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_html(text):
    if not text:
        return ""

    text = html.unescape(str(text))

    text = re.sub(
        r"<script.*?</script>",
        " ",
        text,
        flags=re.I | re.S
    )

    text = re.sub(
        r"<style.*?</style>",
        " ",
        text,
        flags=re.I | re.S
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


def escape_html(text):
    return html.escape(
        str(text),
        quote=False
    )


def make_article_id(title, link):
    raw = (
        f"{title}|{link}"
        .encode("utf-8")
    )

    return hashlib.sha256(
        raw
    ).hexdigest()


# ============================================================
# IMAGE DETECTION
# ============================================================

def get_image_from_entry(entry):

    # --------------------------------------------------------
    # media_content
    # --------------------------------------------------------

    try:
        media_content = entry.get(
            "media_content",
            []
        )

        for media in media_content:
            url = media.get("url")

            if url:
                return url

    except Exception:
        pass


    # --------------------------------------------------------
    # media_thumbnail
    # --------------------------------------------------------

    try:
        thumbnails = entry.get(
            "media_thumbnail",
            []
        )

        for media in thumbnails:
            url = media.get("url")

            if url:
                return url

    except Exception:
        pass


    # --------------------------------------------------------
    # enclosure
    # --------------------------------------------------------

    try:
        enclosures = entry.get(
            "enclosures",
            []
        )

        for enclosure in enclosures:

            url = (
                enclosure.get("href")
                or enclosure.get("url")
            )

            if not url:
                continue

            content_type = (
                enclosure.get("type", "")
                .lower()
            )

            if (
                content_type.startswith("image/")
                or re.search(
                    r"\.(jpg|jpeg|png|webp)(\?.*)?$",
                    url,
                    re.I
                )
            ):
                return url

    except Exception:
        pass


    # --------------------------------------------------------
    # image field
    # --------------------------------------------------------

    try:
        image = entry.get("image")

        if isinstance(image, dict):

            url = (
                image.get("href")
                or image.get("url")
            )

            if url:
                return url

    except Exception:
        pass


    # --------------------------------------------------------
    # Search <img> in RSS content
    # --------------------------------------------------------

    try:
        content = ""

        content += entry.get(
            "summary",
            ""
        )

        for item in entry.get(
            "content",
            []
        ):
            content += item.get(
                "value",
                ""
            )

        match = re.search(
            r'<img[^>]+(?:src|data-src)=["\']([^"\']+)',
            content,
            re.I
        )

        if match:
            return html.unescape(
                match.group(1)
            )

    except Exception:
        pass


    return None


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(
    image_url,
    article_url
):

    if not image_url:
        return None

    try:

        image_url = urljoin(
            article_url,
            image_url
        )

        logger.info(
            "Downloading image: %s",
            image_url
        )

        response = requests.get(
            image_url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            stream=True
        )

        response.raise_for_status()

        content_type = (
            response.headers
            .get("content-type", "")
            .lower()
        )

        if (
            not content_type.startswith("image/")
            and not re.search(
                r"\.(jpg|jpeg|png|webp)(\?.*)?$",
                image_url,
                re.I
            )
        ):
            logger.warning(
                "URL is not an image: %s",
                content_type
            )

            return None


        extension = ".jpg"

        if "png" in content_type:
            extension = ".png"

        elif "webp" in content_type:
            extension = ".webp"


        filename = (
            f"mybuzz_{int(time.time() * 1000)}"
            f"{extension}"
        )

        filepath = os.path.join(
            "/tmp",
            filename
        )


        total = 0

        with open(
            filepath,
            "wb"
        ) as f:

            for chunk in response.iter_content(
                chunk_size=8192
            ):

                if not chunk:
                    continue

                total += len(chunk)

                # Maximum 10MB
                if total > 10 * 1024 * 1024:

                    logger.warning(
                        "Image larger than 10MB."
                    )

                    return None

                f.write(chunk)


        if not os.path.exists(filepath):
            return None


        if os.path.getsize(filepath) < 1000:

            os.remove(filepath)

            return None


        logger.info(
            "Image downloaded: %s bytes",
            total
        )

        return filepath


    except Exception as e:

        logger.warning(
            "Image download failed: %s",
            e
        )

        return None


# ============================================================
# FETCH RSS
# ============================================================

def fetch_rss(source):

    name = source["name"]
    url = source["url"]

    logger.info(
        "Fetching RSS: %s",
        name
    )

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        feed = feedparser.parse(
            response.content
        )

        articles = []

        for entry in feed.entries[:50]:

            title = clean_html(
                entry.get(
                    "title",
                    ""
                )
            )

            link = (
                entry.get(
                    "link",
                    ""
                )
                or ""
            ).strip()


            if not title or not link:
                continue


            summary = clean_html(
                entry.get(
                    "summary",
                    ""
                )
            )


            if not summary:

                summary = clean_html(
                    entry.get(
                        "description",
                        ""
                    )
                )


            image_url = (
                get_image_from_entry(
                    entry
                )
            )


            articles.append({

                "source": name,

                "title": title,

                "link": link,

                "summary": summary,

                "image_url": image_url,

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


# ============================================================
# GET ALL NEWS
# ============================================================

def get_all_articles():

    all_articles = []

    for source in RSS_SOURCES:

        articles = fetch_rss(
            source
        )

        all_articles.extend(
            articles
        )

    logger.info(
        "Total RSS articles: %s",
        len(all_articles)
    )

    return all_articles


# ============================================================
# GROQ PROCESSING
# ============================================================

def process_with_groq(article):

    title = article["title"]

    summary = article["summary"]


    prompt = f"""
You are the editor of MYBUZZ, a Malaysian news channel.

Rewrite this news into a concise bilingual Telegram news post.

LANGUAGE REQUIREMENTS:

1. Chinese:
- Simplified Chinese.
- Natural Malaysian Chinese news style.
- Create a short attractive headline.
- Summary should be 1-2 sentences.
- Keep all names, places, numbers and facts accurate.

2. Malay:
- Natural Malaysian Malay.
- Create a short headline.
- Summary should be 1-2 sentences.
- Keep all names, places, numbers and facts accurate.

IMPORTANT:
- Do NOT invent information.
- Do NOT add opinions.
- Do NOT add facts not contained in the source.
- Do NOT include links.
- Do NOT use markdown.
- Return ONLY valid JSON.

JSON FORMAT:

{{
  "zh_title": "...",
  "zh_summary": "...",
  "ms_title": "...",
  "ms_summary": "..."
}}

SOURCE:
{article["source"]}

ORIGINAL TITLE:
{title}

ORIGINAL SUMMARY:
{summary[:6000]}
"""


    try:

        response = groq_client.chat.completions.create(

            model=GROQ_MODEL,

            messages=[

                {
                    "role": "system",
                    "content": (
                        "You are a professional "
                        "Malaysian bilingual news editor. "
                        "Return only valid JSON."
                    )
                },

                {
                    "role": "user",
                    "content": prompt
                }

            ],

            temperature=0.2,

            max_tokens=1000,

        )


        content = (
            response
            .choices[0]
            .message
            .content
        )


        if not content:
            raise ValueError(
                "Empty Groq response."
            )


        content = content.strip()


        # Remove ```json
        content = re.sub(
            r"^```json\s*",
            "",
            content,
            flags=re.I
        )


        content = re.sub(
            r"\s*```$",
            "",
            content
        )


        data = json.loads(
            content
        )


        required = [
            "zh_title",
            "zh_summary",
            "ms_title",
            "ms_summary"
        ]


        for key in required:

            if not data.get(key):

                raise ValueError(
                    f"Missing Groq field: {key}"
                )


        return data


    except Exception as e:

        logger.error(
            "Groq API failed: %s",
            e
        )

        return None


# ============================================================
# TELEGRAM URL
# ============================================================

def telegram_api(
    method
):

    return (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/"
        f"{method}"
    )


# ============================================================
# SEND PHOTO
# ============================================================

def send_photo(
    image_path,
    caption
):

    try:

        with open(
            image_path,
            "rb"
        ) as photo:

            response = requests.post(

                telegram_api(
                    "sendPhoto"
                ),

                data={

                    "chat_id":
                        TELEGRAM_CHAT_ID,

                    "caption":
                        caption,

                    "parse_mode":
                        "HTML",

                },

                files={

                    "photo":
                        photo

                },

                timeout=60
            )


        if response.ok:

            logger.info(
                "Telegram photo sent successfully."
            )

            return True


        logger.error(
            "Telegram sendPhoto failed: %s",
            response.text
        )

        return False


    except Exception as e:

        logger.error(
            "Telegram sendPhoto error: %s",
            e
        )

        return False


# ============================================================
# SEND TEXT
# ============================================================

def send_message(
    text
):

    try:

        response = requests.post(

            telegram_api(
                "sendMessage"
            ),

            data={

                "chat_id":
                    TELEGRAM_CHAT_ID,

                "text":
                    text,

                "parse_mode":
                    "HTML",

                "disable_web_page_preview":
                    False,

            },

            timeout=60
        )


        if response.ok:

            logger.info(
                "Telegram text sent successfully."
            )

            return True


        logger.error(
            "Telegram sendMessage failed: %s",
            response.text
        )

        return False


    except Exception as e:

        logger.error(
            "Telegram sendMessage error: %s",
            e
        )

        return False


# ============================================================
# BUILD TELEGRAM CAPTION
# ============================================================

def build_caption(
    article,
    data
):

    zh_title = escape_html(
        data["zh_title"]
    )

    zh_summary = escape_html(
        data["zh_summary"]
    )

    ms_title = escape_html(
        data["ms_title"]
    )

    ms_summary = escape_html(
        data["ms_summary"]
    )

    link = escape_html(
        article["link"]
    )


    caption = (

        f"🇲🇾 <b>{zh_title}</b>\n\n"

        f"🇨🇳 {zh_summary}\n\n"

        f"🇲🇾 <b>{ms_title}</b>\n\n"

        f"{ms_summary}\n\n"

        f'👉 <a href="{link}">'
        f'点击阅读完整新闻'
        f'</a>\n\n'

        f'👉 <a href="{link}">'
        f'Klik untuk baca berita penuh'
        f'</a>'

    )


    return caption


# ============================================================
# PROCESS ONE ARTICLE
# ============================================================

def process_article(
    article
):

    logger.info(
        "Processing: %s",
        article["title"]
    )


    # --------------------------------------------------------
    # AI
    # --------------------------------------------------------

    data = process_with_groq(
        article
    )


    if not data:

        logger.warning(
            "AI processing failed."
        )

        return False


    # --------------------------------------------------------
    # Build caption
    # --------------------------------------------------------

    caption = build_caption(
        article,
        data
    )


    # --------------------------------------------------------
    # Image
    # --------------------------------------------------------

    image_path = download_image(

        article.get(
            "image_url"
        ),

        article["link"]

    )


    # --------------------------------------------------------
    # Send photo
    # --------------------------------------------------------

    if image_path:

        sent = send_photo(

            image_path,

            caption

        )


        try:

            os.remove(
                image_path
            )

        except Exception:

            pass


        if sent:

            return True


        logger.warning(
            "Photo failed. "
            "Trying text message."
        )


    # --------------------------------------------------------
    # Fallback to text
    # --------------------------------------------------------

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
        "MYBUZZ V6 START"
    )

    logger.info(
        "Groq model: %s",
        GROQ_MODEL
    )

    logger.info(
        "Maximum articles per run: %s",
        MAX_ARTICLES
    )

    logger.info(
        "======================================"
    )


    # --------------------------------------------------------
    # Get RSS
    # --------------------------------------------------------

    articles = get_all_articles()


    if not articles:

        logger.warning(
            "No RSS articles found."
        )

        return


    # --------------------------------------------------------
    # Remove duplicates
    # --------------------------------------------------------

    new_articles = []


    for article in articles:

        aid = make_article_id(

            article["title"],

            article["link"]

        )


        if aid in SEEN:

            continue


        article["_id"] = aid

        new_articles.append(
            article
        )


    logger.info(
        "New articles after duplicate filter: %s",
        len(new_articles)
    )


    # --------------------------------------------------------
    # IMPORTANT:
    # ONLY ONE ARTICLE
    # --------------------------------------------------------

    selected = new_articles[
        :MAX_ARTICLES
    ]


    logger.info(
        "Selected %s article(s).",
        len(selected)
    )


    if not selected:

        logger.info(
            "No new article to send."
        )

        return


    sent_count = 0


    # --------------------------------------------------------
    # Process
    # --------------------------------------------------------

    for index, article in enumerate(

        selected,

        start=1

    ):

        logger.info(

            "[%s/%s] Processing: %s",

            index,

            len(selected),

            article["title"]

        )


        success = process_article(
            article
        )


        # IMPORTANT:
        # Only mark as seen AFTER successful Telegram send
        if success:

            SEEN.add(
                article["_id"]
            )

            save_seen(
                SEEN
            )

            sent_count += 1


            logger.info(
                "News sent successfully."
            )

        else:

            logger.warning(
                "News was NOT sent."
            )


        time.sleep(2)


    logger.info(
        "======================================"
    )

    logger.info(
        "MYBUZZ V6 FINISHED | Sent: %s",
        sent_count
    )

    logger.info(
        "======================================"
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
