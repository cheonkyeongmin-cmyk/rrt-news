"""
RRT.lt news monitor
- Runs daily via GitHub Actions
- Detects new RRT news
- Translates Lithuanian title to English
- Sends NTFY push notification
- Sends "No update" notification even when there is no new article
"""

import os
import json
import html
import re
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


def fetch_article_detail(url: str) -> dict:
    """
    Fetch article title and published date.
    Returns:
    {
        "title": "...",
        "date": "..."
    }
    """

    result = {
        "title": "",
        "date": "Unknown date",
    }

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            result["title"] = html.unescape(og["content"]).strip()
        else:
            h1 = soup.find("h1")
            if h1:
                result["title"] = h1.get_text(" ", strip=True)

        published_time = soup.find("meta", property="article:published_time")
        if published_time and published_time.get("content"):
            result["date"] = published_time["content"].strip()
            return result

        time_tag = soup.find("time")
        if time_tag:
            if time_tag.get("datetime"):
                result["date"] = time_tag["datetime"].strip()
            else:
                result["date"] = time_tag.get_text(" ", strip=True)
            return result

        text = soup.get_text(" ", strip=True)

        date_match = re.search(
            r"\b(20\d{2})[-./](\d{1,2})[-./](\d{1,2})\b",
            text
        )

        if date_match:
            y, m, d = date_match.groups()
            result["date"] = f"{y}-{int(m):02d}-{int(d):02d}"

    except Exception as e:
        print(f"  Failed to fetch article detail: {url}")
        print(f"  Error: {e}")

    return result


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


def send_ntfy(title: str, body: str, priority: str = "default"):
    try:
        resp = requests.post(
            f"{NTFY_SERVER}/{NTFY_TOPIC}",
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": "newspaper",
            },
            data=body.encode("utf-8"),
            timeout=15,
        )

        resp.raise_for_status()
        print("  NTFY sent successfully")

    except Exception as e:
        print("  NTFY failed")
        print(f"  Error: {e}")


def send_new_articles_notification(new_articles: list[dict], total_articles: int):
    total_new = len(new_articles)

    body_lines = [
        f"Status: New RRT news detected",
        f"New articles: {total_new}",
        f"Total articles on page: {total_articles}",
        "",
    ]

    for i, article in enumerate(new_articles, start=1):
        line = (
            f"{i}. {article['en_title']}\n"
            f"Published: {article['published_date']}\n"
            f"{article['url']}"
        )
        body_lines.append(line)

    body = "\n\n".join(body_lines)

    send_ntfy(
        title=f"RRT New News ({total_new})",
        body=body,
        priority="default",
    )


def send_no_update_notification(articles: list[dict]):
    total_articles = len(articles)

    latest = articles[0] if articles else None

    if latest:
        body = (
            "Status: No update\n"
            f"Total articles on page: {total_articles}\n"
            f"Latest published: {latest.get('published_date', 'Unknown date')}\n"
            f"Latest title: {latest.get('en_title', latest.get('title_hint', 'Unknown title'))}\n"
            f"Latest URL: {latest.get('url', '')}"
        )
    else:
        body = (
            "Status: No update\n"
            "Total articles on page: 0\n"
            "Latest published: Unknown date\n"
            "Latest title: Unknown title"
        )

    send_ntfy(
        title="RRT No Update",
        body=body,
        priority="low",
    )


def main():
    print("RRT crawling started")
    print(f"URL: {TARGET_URL}")

    seen = load_seen()
    print(f"Seen articles: {len(seen)}")

    articles = fetch_article_links()
    print(f"Collected articles: {len(articles)}")

    if articles:
        latest_detail = fetch_article_detail(articles[0]["url"])

        latest_title = latest_detail["title"] or articles[0]["title_hint"]
        latest_en_title = translate_to_english(latest_title)

        articles[0]["lt_title"] = latest_title
        articles[0]["en_title"] = latest_en_title
        articles[0]["published_date"] = latest_detail["date"]

        print(f"Latest article: {latest_title}")
        print(f"Latest published: {latest_detail['date']}")

    new_articles = [
        article for article in articles
        if article["url"] not in seen
    ]

    print(f"New articles: {len(new_articles)}")

    if not new_articles:
        print("No new articles. Sending no-update notification.")
        send_no_update_notification(articles)
        return

    for article in new_articles:
        print("")
        print("Processing new article")
        print(article["url"])

        detail = fetch_article_detail(article["url"])

        lt_title = detail["title"] or article["title_hint"]
        en_title = translate_to_english(lt_title)

        article["lt_title"] = lt_title
        article["en_title"] = en_title
        article["published_date"] = detail["date"]

        print(f"LT: {lt_title}")
        print(f"EN: {en_title}")
        print(f"Published: {detail['date']}")

        seen.add(article["url"])

    send_new_articles_notification(new_articles, len(articles))
    save_seen(seen)

    print("Done")


if __name__ == "__main__":
    main()
