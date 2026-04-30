"""
RRT.lt 뉴스 모니터
- 매일 KST 07:00 (UTC 22:00) GitHub Actions에서 실행
- 신규 뉴스 감지 → Gemini로 한글 번역 → NTFY 푸시 알림
"""

import os
import re
import json
import requests
from google import genai

# ── 환경변수 (GitHub Secrets) ────────────────────────────
GOOGLE_API_KEY  = os.environ["GOOGLE_API_KEY"]
NTFY_TOPIC      = os.environ.get("NTFY_TOPIC", "peter-rrt-news")
NTFY_SERVER     = os.environ.get("NTFY_SERVER", "https://ntfy.sh")

TARGET_URL  = "https://rrt.lt/apie-rrt/naujienos"
BASE_URL    = "https://rrt.lt"
STATE_FILE  = "seen_articles.json"

# 뉴스 기사 URL 패턴: /naujienos/[slug] 형태
NEWS_PATTERN = re.compile(r'href="(/naujienos/[^"/?#]+)"')

# ── 상태 파일 ────────────────────────────────────────────
def load_seen() -> set:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(seen: set):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)

# ── 크롤링 ───────────────────────────────────────────────
def fetch_article_links() -> list[dict]:
    """
    rrt.lt 뉴스 페이지 HTML에서 /naujienos/[slug] 형태의 링크를 추출.
    JS 렌더링 없이 초기 HTML만 파싱 → 네비게이션 미리보기 링크 포함해서 수집.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }
    resp = requests.get(TARGET_URL, headers=headers, timeout=15)
    resp.raise_for_status()

    slugs = set(NEWS_PATTERN.findall(resp.text))
    articles = []
    for slug in slugs:
        full_url = BASE_URL + slug
        title_hint = slug.split("/")[-1].replace("-", " ")
        articles.append({"url": full_url, "title_hint": title_hint})

    return articles

def fetch_article_title(url: str) -> str:
    """기사 페이지에서 실제 제목 추출 (og:title 또는 <h1>)"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()

        # og:title 우선
        og = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', resp.text)
        if og:
            return og.group(1).strip()

        # h1 폴백
        h1 = re.search(r'<h1[^>]*>([^<]+)</h1>', resp.text)
        if h1:
            return h1.group(1).strip()

    except Exception:
        pass
    return ""

# ── 한글 번역 (Gemini Flash - 무료) ─────────────────────
def translate_to_korean(lt_text: str) -> str:
    client = genai.Client(api_key=GOOGLE_API_KEY)
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=(
            "다음 리투아니아어 텍스트를 자연스러운 한국어로 번역해줘. "
            "번역문만 출력하고 설명은 생략해.\n\n" + lt_text
        )
    )
    return response.text.strip()

# ── NTFY 알림 ────────────────────────────────────────────
def send_notification(ko_title: str, article_url: str):
    requests.post(
        f"{NTFY_SERVER}/{NTFY_TOPIC}",
        headers={
            "Title":    "🇱🇹 RRT 신규 뉴스",
            "Click":    article_url,
            "Priority": "default",
            "Tags":     "newspaper",
        },
        data=ko_title.encode("utf-8"),
        timeout=10,
    )
    print(f"  ✅ 알림 전송: {ko_title}")
    print(f"     {article_url}")

# ── 메인 ─────────────────────────────────────────────────
def main():
    print(f"🔍 크롤링 시작: {TARGET_URL}")

    seen     = load_seen()
    articles = fetch_article_links()
    print(f"  수집된 링크: {len(articles)}건 / 기존 등록: {len(seen)}건")

    new_articles = [a for a in articles if a["url"] not in seen]
    print(f"  신규 기사: {len(new_articles)}건")

    if not new_articles:
        print("  변동 없음. 종료.")
        return

    for article in new_articles:
        lt_title = fetch_article_title(article["url"])
        if not lt_title:
            lt_title = article["title_hint"]

        ko_title = translate_to_korean(lt_title)
        send_notification(ko_title, article["url"])
        seen.add(article["url"])

    save_seen(seen)
    print("✅ 완료.")

if __name__ == "__main__":
    main()
