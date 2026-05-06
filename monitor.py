"""
RRT.lt 뉴스 모니터
- GitHub Actions에서 매일 실행
- 신규 뉴스 감지
- 리투아니아어 제목 → 한국어 번역
- NTFY 푸시 알림 전송
"""

import os
import re
import json
import html
import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────
# 환경변수 (GitHub Secrets)
# ─────────────────────────────────────────────
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

# ─────────────────────────────────────────────
# 상태 파일
# ─────────────────────────────────────────────
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


# ─────────────────────────────────────────────
# 뉴스 목록 수집
# ─────────────────────────────────────────────
def fetch_article_links() -> list[dict]:
    """
    실제 뉴스 링크만 수집
    """

    resp = requests.get(TARGET_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    articles = []
    seen_urls = set()

    for a in soup.find_all("a", href=True):

        href = a["href"].strip()

        # /naujienos/xxx 형태만 허용
        if not href.startswith("/naujienos/"):
            continue

        # pagination, category 제외
        if href.count("/") < 2:
            continue

        full_url = BASE_URL + href.split("?")[0]

        # 중복 제거
        if full_url in seen_urls:
            continue

        seen_urls.add(full_url)

        title = a.get_text(" ", strip=True)

        articles.append({
            "url": full_url,
            "title_hint": title
        })

    return articles


# ─────────────────────────────────────────────
# 기사 제목 추출
# ─────────────────────────────────────────────
def fetch_article_title(url: str) -> str:

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # og:title 우선
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return html.unescape(og["content"]).strip()

        # h1 fallback
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(" ", strip=True)

    except Exception as e:
        print(f"  제목 추출 실패: {url}")
        print(f"  오류: {e}")

    return ""


# ─────────────────────────────────────────────
# 번역
# ─────────────────────────────────────────────
def translate_to_korean(text: str) -> str:

    try:
        resp = requests.get(
            "https://api.mymemory.translated.net/get",
            params={
                "q": text,
                "langpair": "lt|ko"
            },
            timeout=15,
        )

        resp.raise_for_status()

        data = resp.json()

        translated = data["responseData"]["translatedText"]

        if translated:
            return translated.strip()

    except Exception as e:
        print(f"  번역 실패: {text}")
        print(f"  오류: {e}")

    return text


# ─────────────────────────────────────────────
# NTFY 알림
# ─────────────────────────────────────────────
def send_notification(new_articles: list[dict]):

    total = len(new_articles)

    body_lines = []

    for i, article in enumerate(new_articles, start=1):

        line = (
            f"{i}. {article['ko_title']}\n"
            f"{article['url']}"
        )

        body_lines.append(line)

    body = "\n\n".join(body_lines)

    try:
        resp = requests.post(
            f"{NTFY_SERVER}/{NTFY_TOPIC}",
            headers={
                "Title": f"RRT 신규 뉴스 {total}건",
                "Priority": "default",
                "Tags": "newspaper",
            },
            data=body.encode("utf-8"),
            timeout=15,
        )

        resp.raise_for_status()

        print(f"  ✅ NTFY 전송 완료 ({total}건)")

    except Exception as e:
        print("  ❌ NTFY 전송 실패")
        print(f"  오류: {e}")


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
def main():

    print(f"🔍 크롤링 시작")
    print(f"URL: {TARGET_URL}")

    seen = load_seen()

    print(f"기존 저장 기사 수: {len(seen)}")

    articles = fetch_article_links()

    print(f"수집 기사 수: {len(articles)}")

    # 신규 기사 탐색
    new_articles = []

    for article in articles:

        if article["url"] not in seen:
            new_articles.append(article)

    print(f"신규 기사 수: {len(new_articles)}")

    if not new_articles:
        print("✅ 신규 뉴스 없음")
        return

    # 신규 기사 처리
    for article in new_articles:

        print(f"\n📰 처리 중")
        print(article["url"])

        lt_title = fetch_article_title(article["url"])

        if not lt_title:
            lt_title = article["title_hint"]

        ko_title = translate_to_korean(lt_title)

        article["lt_title"] = lt_title
        article["ko_title"] = ko_title

        print(f"LT: {lt_title}")
        print(f"KO: {ko_title}")

        seen.add(article["url"])

    # 알림 전송
    send_notification(new_articles)

    # 저장
    save_seen(seen)

    print("\n✅ 완료")


# ─────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────
if __name__ == "__main__":
    main()
