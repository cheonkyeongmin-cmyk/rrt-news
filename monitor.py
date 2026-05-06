"""
RRT.lt news monitor
- Runs daily via GitHub Actions
- Detects new RRT news
- Translates Lithuanian title to English
- Sends NTFY push notification
"""

import os
import json
import html
import requests
from bs4 import BeautifulSoup


NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "peter-rrt-news")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")

TARGET_URL = "https://rrt.lt/apie-rrt/naujienos"
BASE_URL = "https://rrt.lt"
STATE_FILE = "seen_articles.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


def load_seen() -> set:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_seen(seen: set):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def fetch_article_links() -> list[dict]:
    resp = requests.get(TARGET_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    articles = []
    seen_urls = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()

        if not href.startswith("/naujienos/"):
            continue

        full_url = BASE_URL + href.split("?")[0]

        if full_url in seen_urls:
            continue

        seen_urls.add(full_url)

        title_hint = a.get_text(" ", strip=True)

        articles.append({
            "url": full_url,
            "title_hint": title_hint,
        })

    return articles


def fetch_article_title(url: str) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return html.unescape(og["content"]).strip()

        h1 = soup.find("h1")
        if h1:
            return h1.get_text(" ", strip=True)

    except Exception as e:
        print(f"  Failed to fetch title: {url}")
        print(f"  Error: {e}")

    return ""


def translate_to_english(text: str) -> str:
    try:
        resp = requests.get(
            "https://api.mymemory.translated.net/get",
            params={
                "q": text,
                "langpair": "lt|en",
            },
            timeout=15,
        )
        resp.raise_for_status()

        data = resp.json()
        translated = data["responseData"]["translatedText"]

        if translated:
            return translated.strip()

    except Exception as e:
        print(f"  Translation failed: {text}")
        print(f"  Error: {e}")

    return text


def send_notification(new_articles: list[dict]):
    total = len(new_articles)

    body_lines = []

    for i, article in enumerate(new_articles, start=1):
        line = (
            f"{i}. {article['en_title']}\n"
            f"{article['url']}"
        )
        body_lines.append(line)

    body = "\n\n".join(body_lines)

    try:
        resp = requests.post(
            f"{NTFY_SERVER}/{NTFY_TOPIC}",
            headers={
                "Title": f"RRT New News ({total})",
                "Priority": "default",
                "Tags": "newspaper",
            },
            data=body.encode("utf-8"),
            timeout=15,
        )

        resp.raise_for_status()
        print(f"  NTFY sent successfully ({total})")

    except Exception as e:
        print("  NTFY failed")
        print(f"  Error: {e}")


def main():
    print("RRT crawling started")
    print(f"URL: {TARGET_URL}")

    seen = load_seen()
    print(f"Seen articles: {len(seen)}")

    articles = fetch_article_links()
    print(f"Collected articles: {len(articles)}")

    new_articles = [
        article for article in articles
        if article["url"] not in seen
    ]

    print(f"New articles: {len(new_articles)}")

    if not new_articles:
        print("No new articles")
        return

    for article in new_articles:
        print("")
        print("Processing article")
        print(article["url"])

        lt_title = fetch_article_title(article["url"])

        if not lt_title:
            lt_title = article["title_hint"]

        en_title = translate_to_english(lt_title)

        article["lt_title"] = lt_title
        article["en_title"] = en_title

        print(f"LT: {lt_title}")
        print(f"EN: {en_title}")

        seen.add(article["url"])

    send_notification(new_articles)
    save_seen(seen)

    print("Done")


if __name__ == "__main__":
    main()
