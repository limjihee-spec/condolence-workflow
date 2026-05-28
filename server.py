from fastapi import FastAPI
from pydantic import BaseModel
import re
import os
import json
import google.generativeai as genai

app = FastAPI()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)


class RequestData(BaseModel):
    kind: str
    target: str
    team: str
    relation: str
    url: str


@app.get("/")
def home():
    return {"status": "ok"}


def crawl_page(url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        page = browser.new_page(
            viewport={"width": 390, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/16.0 Mobile/15E148 Safari/604.1"
            )
        )

        page.goto(url, wait_until="commit", timeout=20000)
        page.wait_for_timeout(3000)

        for _ in range(6):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(800)

        text = page.locator("body").inner_text()
        browser.close()

        return clean_text(text)


def clean_text(text):
    remove_words = [
        "스크롤", "더 보기", "갤러리", "티맵", "카카오내비", "네이버지도",
        "COPYRIGHT", "All rights reserved", "© NAVER Corp.", "NeedIT",
        "공유하기", "닫기", "확인", "COPY", "복사"
    ]

    lines = []

    for line in text.splitlines():
        line = line.strip()

        if not line:
            continue

        if len(line) <= 1:
            continue

        if line in remove_words:
            continue

        if any(word in line for word in remove_words):
            continue

        lines.append(line)

    unique_lines = []
    seen = set()

    for line in lines:
        if line not in seen:
            unique_lines.append(line)
            seen.add(line)

    return "\n".join(unique_lines)


def extract_korean_address(text):
    pattern = (
        r"(서울특별시|서울|부산광역시|부산|대구광역시|대구|인천광역시|인천|광주광역시|광주|대전광역시|대전|울산광역시|울산|세종특별자치시|세종|"
        r"경기도|경기|강원특별자치도|강원|충청북도|충북|충청남도|충남|전북특별자치도|전북|전라남도|전남|경상북도|경북|경상남도|경남|제주특별자치도|제주)"
        r"\s+[가-힣]+(?:시|군|구)\s+[가-힣0-9]+(?:로|길)\s*\d+(?:-\d+)?"
    )

    match = re.search(pattern, text)

    if match:
        return match.group(0).strip()

    return ""


def make_compact_context(kind, text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if kind == "조사":
        keywords = [
            "故", "고인", "별세", "부고", "빈소", "장례식장", "발인",
            "발인일", "발인일시", "장지", "상주", "입관", "호실",
            "특실", "층", "영안실", "추모관", "주소", "오시는 길",
            "mortuary", "funeral", "depart", "deceased", "room",
            "place", "date", "time", "address"
        ]
    else:
        keywords = [
            "결혼", "예식", "예식 안내", "신랑", "신부", "아들", "딸",
            "웨딩", "호텔", "컨벤션", "예식장", "오시는 길", "주소",
            "월", "일", "오전", "오후", "wedding", "place",
            "address", "date", "time"
        ]

    selected = []
    selected.extend(lines[:80])

    for i, line in enumerate(lines):
        if any(keyword in line for keyword in keywords):
            start = max(0, i - 8)
            end = min(len(lines), i + 12)
            selected.extend(lines[start:end])

    address = extract_korean_address(text)
    if address:
        selected.append(address)

    compact = []
    seen = set()

    for line in selected:
        if line not in seen:
            compact.append(line)
            seen.add(line)

    if kind == "조사":
        return "\n".join(compact)[:6000]

    return "\n".join(compact)[:3500]


def extract_json(text):
    cleaned = text.strip()
    cleaned = cleaned.replace("```json", "")
    cleaned = cleaned.replace("```", "")
    cleaned = cleaned.strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start == -1 or end == -1:
        raise ValueError("Gemini 응답에서 JSON을 찾지 못했습니다: " + text[:500])

    cleaned = cleaned[start:end + 1]

    try:
        return json.loads(cleaned)
    except Exception as e:
        raise ValueError("JSON 파싱 실패: " + str(e) + " / 응답: " + cleaned[:500])


def analyze_with_gemini(kind, url, text):
    context = make_compact_context(kind, text)
    model = genai.GenerativeModel("gemini-2.5-flash")

    if kind == "조사":
        schema_text = """
{
  "type": "조사",
  "deceased": "고인 성함",
  "funeral_home": "빈소",
  "departure": "발인일정",
  "address": "장례식장 주소"
}
"""
        rules = """
- 고인 성함은 실제 사람 이름만.
- 빈소는 장례식장명, 빈소명, 호실 포함.
- 발인일정은 날짜와 시간이 있으면 함께.
- 주소는 실제 장례식장 도로명 주소.
- 빈소와 발인과 주소는 원문 중간/하단에 있을 수 있으니 전체 문맥에서 찾아.
- 실제 장례 정보만 추출해.
- 모르면 "".
"""
    else:
        schema_text = """
{
  "type": "경사",
  "wedding_date": "예식일정",
  "place": "예식장소",
  "address": "주소"
}
"""
        rules = """
- 예식일정은 날짜와 시간이 있으면 함께.
- 예식장소는 호텔/웨딩홀/컨벤션 이름.
- 주소는 실제 도로명 주소.
- 장소명과 주소를 섞지 마.
- 실제 예식 정보만 추출해.
- 모르면 "".
"""

    prompt = f"""
JSON만 반환.
설명 금지.
코드블록 금지.

구분: {kind}

형식:
{schema_text}

규칙:
{rules}

원문:
{context}
"""

    response = model.generate_content(
        prompt,
        generation_config={
            "temperature": 0,
            "max_output_tokens": 1000,
        }
    )

    if not response.text:
        raise ValueError("Gemini 응답이 비어 있습니다.")

    return extract_json(response.text)


@app.post("/crawl")
def crawl(req: RequestData):
    try:
        text = crawl_page(req.url)

        result = analyze_with_gemini(req.kind, req.url, text)
        compact_debug = make_compact_context(req.kind, text)

        if req.kind == "조사":
            address = extract_korean_address(text) or result.get("address", "")

            return {
                "type": "조사",
                "deceased": result.get("deceased", ""),
                "funeral_home": result.get("funeral_home", ""),
                "departure": result.get("departure", ""),
                "address": address,
                "debug_text": compact_debug
            }

        return {
            "type": "경사",
            "wedding_date": result.get("wedding_date", ""),
            "place": result.get("place", ""),
            "address": result.get("address", ""),
            "debug_text": compact_debug
        }

    except Exception as e:
        return {
            "type": "에러",
            "error": str(e)
        }
