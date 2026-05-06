"""
RRT.lt news monitor
- Detects new RRT news
- Gets published date from listing page
- Translates Lithuanian title to English
- Sends NTFY push notification
- Sends No Update notification even when there is no new article
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

LT_MONTHS = {
    "Sausio": "01",
    "Vasario": "02",
    "Kovo": "03",
    "Balandžio": "04",
    "Gegužės": "05",
    "Birželio": "06",
    "Liepos": "07",
    "Rugpjūčio": "08",
    "Rugsėjo": "09",
    "Spalio": "10",
    "Lapkričio": "11",
    "Gruodžio": "12",
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


def parse_lt_date(text: str) -> str:
    """
    Example:
    Gegužės 5, 2026 -> 2026-05-05
    Balandžio 29, 2026 -> 2026-04-29
    """

    pattern = r"(Sausio|Vasario|Kovo|Balandžio|Gegužės|Birželio|Liepos|Rugpjūčio|Rugsėjo|Spalio|Lapkričio|Gruodžio)\s+(\d{1,2}),\s+(20\d{2})"
    match = re.search(pattern, text)

    if not match:
        return "Unknown date"

    month_lt, day, year = match.groups()
    month = LT_MONTHS.get(month_lt)

    if not month:
        return "Unknown date"

    return f"{year}-{month}-{int(day):02d}"


def clean_title_from_listing(text: str) -> str:
    """
    Removes Lithuanian date, category, and 'Skaityti' from listing text.
    """

    text = re.sub(r"\s+", " ", text).strip()

    date_pattern = r"(Sausio|Vasario|Kovo|Balandžio|Gegužės|Birželio|Liepos|Rugpjūčio|Rugsėjo|Spalio|Lapkričio|Gruodžio)\s+\d{1,2},\s+20\d{2}"
    text = re.sub(date_pattern, "", text).strip()

    categories = [
        "Elektroniniai ryšiai",
        "Skaitmeninė erdvė",
        "Elektroninis parašas",
        "Paštas",
        "Geležinkeliai",
        "Vartotojų teisių apsauga",
        "RRT Veikla",
        "Kita",
    ]

    for category in categories:
        if text.startswith(category):
            text = text[len(category):].strip()

    text = text.replace("Skaityti", "").strip()

    return text


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

        listing_text = a.get_text(" ", strip=True)
        published_date = parse_lt_date(listing_text)
        title_hint = clean_title_from_listing(listing_text)

        articles.append({
            "url": full_url,
            "title_hint": title_hint,
            "published_date": published_date,
            "listing_text": listing_text,
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
        return True

    except Exception as e:
        print("  NTFY failed")
        print(f"  Error: {e}")
        return False


def send_new_articles_notification(new_articles: list[dict], total_articles: int):
    body_lines = [
        "Status: New RRT news detected",
        f"New articles: {len(new_articles)}",
        f"Total articles on page: {total_articles}",
        "",
    ]

    for i, article in enumerate(new_articles, start=1):
        body_lines.append(
            f"{i}. {article['en_title']}\n"
            f"Published: {article['published_date']}\n"
            f"{article['url']}"
        )

    body = "\n\n".join(body_lines)

    return send_ntfy(
        title=f"RRT New News ({len(new_articles)})",
        body=body,
        priority="default",
    )


def send_no_update_notification(articles: list[dict]):
    latest = articles[0] if articles else None

    if latest:
        body = (
            "Status: No update\n"
            f"Total articles on page: {len(articles)}\n"
            f"Latest published: {latest['published_date']}\n"
            f"Latest title: {latest.get('en_title', latest.get('title_hint', 'Unknown title'))}\n"
            f"Latest URL: {latest['url']}"
        )
    else:
        body = (
            "Status: No update\n"
            "Total articles on page: 0\n"
            "Latest published: Unknown date\n"
            "Latest title: Unknown title"
        )

    return send_ntfy(
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
        latest = articles[0]
        latest_title = fetch_article_title(latest["url"]) or latest["title_hint"]
        latest["lt_title"] = latest_title
        latest["en_title"] = translate_to_english(latest_title)

        print(f"Latest title: {latest_title}")
        print(f"Latest published: {latest['published_date']}")

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

        lt_title = fetch_article_title(article["url"]) or article["title_hint"]
        en_title = translate_to_english(lt_title)

        article["lt_title"] = lt_title
        article["en_title"] = en_title

        print(f"LT: {lt_title}")
        print(f"EN: {en_title}")
        print(f"Published: {article['published_date']}")

    success = send_new_articles_notification(new_articles, len(articles))

    if success:
        for article in new_articles:
            seen.add(article["url"])

        save_seen(seen)
        print("Seen file updated")
    else:
        print("Seen file not updated because NTFY failed")

    print("Done")


if __name__ == "__main__":
    main()
