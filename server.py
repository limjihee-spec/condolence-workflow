from fastapi import FastAPI
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import re

app = FastAPI()

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
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers, timeout=20)
    res.raise_for_status()

    soup = BeautifulSoup(res.text, "html.parser")

    for tag in soup(["script", "style"]):
        tag.decompose()

    return soup.get_text("\n", strip=True)

def extract_wedding(text):
    date = re.search(r"\d{4}년\s*\d{1,2}월\s*\d{1,2}일", text)
    time = re.search(r"(오전|오후)\s*\d{1,2}시\s*\d{0,2}분?", text)
    address = re.search(r"(서울|부산|대구|인천|광주|대전|울산|세종|제주)\s+[가-힣]+구\s+[가-힣0-9]+(?:로|길)\s*\d+(?:-\d+)?", text)

    place = ""
    for line in text.splitlines():
        if any(w in line for w in ["호텔", "웨딩", "컨벤션", "예식장", "홀"]):
            place = line.strip()
            break

    return {
        "type": "경사",
        "wedding_date": ((date.group(0) if date else "") + " " + (time.group(0) if time else "")).strip(),
        "place": place,
        "address": address.group(0) if address else ""
    }

def extract_obituary(text):
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    deceased = ""
    funeral_home = ""
    departure = ""

    # 1. 고인 성함
    deceased_patterns = [
        r"(?:故|고인|별세)\s*[:：]?\s*([가-힣]{2,4})",
        r"([가-힣]{2,4})\s*님께서\s*별세",
        r"([가-힣]{2,4})\s*님이\s*별세",
        r"([가-힣]{2,4})\s*별세",
    ]

    for pattern in deceased_patterns:
        match = re.search(pattern, text)
        if match:
            deceased = match.group(1).strip()
            break

    # 2. 빈소: 같은 줄 패턴
    funeral_patterns = [
        r"빈소\s*[:：]?\s*([^\n]+)",
        r"장례식장\s*[:：]?\s*([^\n]+)",
    ]

    for pattern in funeral_patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            if value and value not in ["빈소", "장례식장"]:
                funeral_home = value
                break

    # 3. 빈소: 다음 줄 패턴
    if not funeral_home:
        for i, line in enumerate(lines):
            if line in ["빈소", "장례식장", "분향소"]:
                if i + 1 < len(lines):
                    funeral_home = lines[i + 1].strip()
                    break

    # 4. 빈소: 장례식장/호실/빈소 키워드 포함 줄
    if not funeral_home:
        for line in lines:
            if any(word in line for word in ["장례식장", "빈소", "호실", "특실"]):
                funeral_home = line.strip()
                break

    # 5. 발인: 같은 줄 패턴
    departure_patterns = [
        r"발인\s*[:：]?\s*([^\n]+)",
        r"발인일시\s*[:：]?\s*([^\n]+)",
        r"발인일\s*[:：]?\s*([^\n]+)",
    ]

    for pattern in departure_patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            if value and value not in ["발인", "발인일", "발인일시"]:
                departure = value
                break

    # 6. 발인: 다음 줄 패턴
    if not departure:
        for i, line in enumerate(lines):
            if line in ["발인", "발인일", "발인일시"]:
                if i + 1 < len(lines):
                    departure = lines[i + 1].strip()
                    break

    # 7. 발인: 날짜/시간이 같이 있는 줄 보정
    if not departure:
        for line in lines:
            if re.search(r"\d{1,2}월\s*\d{1,2}일", line) and re.search(r"\d{1,2}시", line):
                departure = line.strip()
                break

       return {
        "type": "조사",
        "deceased": deceased,
        "funeral_home": funeral_home,
        "departure": departure,
        "debug_text": text[:1000]
    }
@app.post("/crawl")
def crawl(req: RequestData):
    try:
        text = crawl_page(req.url)

        if req.kind == "조사":
            return extract_obituary(text)

        return extract_wedding(text)

    except Exception as e:
        return {
            "type": "에러",
            "error": str(e)
        }
