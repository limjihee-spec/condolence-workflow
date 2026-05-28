from fastapi import FastAPI
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
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
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    res = requests.get(url, headers=headers, timeout=20)
    res.raise_for_status()
    res.encoding = "utf-8"

    soup = BeautifulSoup(res.text, "html.parser")

    for tag in soup(["style", "noscript"]):
        tag.decompose()

    visible_text = soup.get_text("\n", strip=True)

    script_texts = []

    important_keywords = [
        "고인",
        "별세",
        "부고",
        "빈소",
        "발인",
        "장례식장",
        "장지",
        "상주",
        "입관",
        "호실",
        "특실",
        "영안실",
        "추모관",
        "deceased",
        "funeral",
        "mortuary",
        "burial",
        "departure",
        "결혼",
        "예식",
        "웨딩",
        "호텔",
        "주소",
        "wedding",
        "address"
    ]

    for script in soup.find_all("script"):
        content = script.get_text(" ", strip=True)

        if not content:
            continue

        if any(keyword in content for keyword in important_keywords):
            script_texts.append(content[:3000])

    all_text = visible_text + "\n" + "\n".join(script_texts)

    return clean_text(all_text)


def clean_text(text):

    remove_words = [
        "스크롤",
        "더 보기",
        "갤러리",
        "티맵",
        "카카오내비",
        "네이버지도",
        "COPYRIGHT",
        "All rights reserved",
        "© NAVER Corp.",
        "NeedIT",
        "공유하기",
        "닫기",
        "확인",
        "COPY",
        "복사"
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


def make_compact_context(kind, text):

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    if kind == "조사":

        keywords = [
            "故",
            "고인",
            "별세",
            "부고",
            "빈소",
            "장례식장",
            "발인",
            "발인일",
            "발인일시",
            "장지",
            "상주",
            "입관",
            "호실",
            "특실",
            "층",
            "영안실",
            "추모관",
            "mortuary",
            "funeral",
            "depart",
            "deceased",
            "room",
            "place",
            "date",
            "time"
        ]

    else:

        keywords = [
            "결혼",
            "예식",
            "예식 안내",
            "신랑",
            "신부",
            "아들",
            "딸",
            "웨딩",
            "호텔",
            "컨벤션",
            "예식장",
            "오시는 길",
            "주소",
            "월",
            "일",
            "오전",
            "오후",
            "wedding",
            "place",
            "address",
            "date",
            "time"
        ]

    selected = []

    # 상단 영역 포함
    selected.extend(lines[:80])

    # 키워드 주변 확장
    for i, line in enumerate(lines):

        if any(keyword in line for keyword in keywords):

            start = max(0, i - 8)
            end = min(len(lines), i + 12)

            selected.extend(lines[start:end])

    # 주소 추출 강화
    address_pattern = (
        r"(서울|부산|대구|인천|광주|대전|울산|세종|제주|경기|강원|충북|충남|전북|전남|경북|경남)"
        r"\s+[가-힣0-9\s]+(?:로|길)\s*\d+"
    )

    for line in lines:

        if re.search(address_pattern, line):
            selected.append(line)

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

        raise ValueError(
            "Gemini 응답에서 JSON을 찾지 못했습니다: "
            + text[:500]
        )

    cleaned = cleaned[start:end + 1]

    try:
        return json.loads(cleaned)

    except Exception as e:

        raise ValueError(
            "JSON 파싱 실패: "
            + str(e)
            + " / 응답: "
            + cleaned[:500]
        )


def analyze_with_gemini(kind, url, text):

    context = make_compact_context(kind, text)

    model = genai.GenerativeModel("gemini-2.5-flash")

    if kind == "조사":

        schema_text = """
{
  "type": "조사",
  "deceased": "고인 성함",
  "funeral_home": "빈소",
  "departure": "발인일정"
}
"""

        rules = """
- 고인 성함은 실제 사람 이름만.
- 빈소는 장례식장명, 빈소명, 호실 포함.
- 발인일정은 날짜와 시간이 있으면 함께.
- javascript, window 변수명, bubble 코드는 무시.
- 빈소와 발인은 원문 중간/하단에 있을 수 있으니 전체 문맥에서 찾아.
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
- javascript, window 변수명, bubble 코드는 무시.
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

        result = analyze_with_gemini(
            req.kind,
            req.url,
            text
        )

        compact_debug = make_compact_context(
            req.kind,
            text
        )

        if req.kind == "조사":

            return {
                "type": "조사",
                "deceased": result.get("deceased", ""),
                "funeral_home": result.get("funeral_home", ""),
                "departure": result.get("departure", ""),
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
