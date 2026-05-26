from fastapi import FastAPI
from pydantic import BaseModel
from playwright.sync_api import sync_playwright
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

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )

        page = browser.new_page()

        page.goto(
            url,
            wait_until="networkidle",
            timeout=60000
        )

        text = page.locator("body").inner_text()

        browser.close()

        return text

def clean_text(text):

    remove_patterns = [
        r"스크롤",
        r"더 보기",
        r"티맵",
        r"카카오내비",
        r"네이버지도",
        r"COPYRIGHT",
        r"All rights reserved",
        r"© NAVER",
        r"\d+m",
    ]

    lines = text.splitlines()

    cleaned = []

    for line in lines:

        line = line.strip()

        if not line:
            continue

        if len(line) <= 1:
            continue

        skip = False

        for pattern in remove_patterns:

            if re.search(pattern, line):
                skip = True
                break

        if skip:
            continue

        cleaned.append(line)

    return "\n".join(cleaned)

def extract_wedding(text):

    date_patterns = [
        r"\d{4}년\s*\d{1,2}월\s*\d{1,2}일",
        r"\d{1,2}월\s*\d{1,2}일"
    ]

    time_patterns = [
        r"(오전|오후)\s*\d{1,2}시\s*\d{0,2}분?",
    ]

    address_patterns = [
        r"(서울|부산|대구|인천|광주|대전|울산|세종|제주)\s+[가-힣]+구\s+[가-힣0-9]+(?:로|길)\s*\d+(?:-\d+)?",
    ]

    wedding_date = ""
    wedding_time = ""
    address = ""

    for pattern in date_patterns:

        match = re.search(pattern, text)

        if match:
            wedding_date = match.group(0)
            break

    for pattern in time_patterns:

        match = re.search(pattern, text)

        if match:
            wedding_time = match.group(0)
            break

    for pattern in address_patterns:

        match = re.search(pattern, text)

        if match:
            address = match.group(0)
            break

    place = ""

    lines = text.splitlines()

    for line in lines:

        if any(word in line for word in [
            "웨딩",
            "호텔",
            "컨벤션",
            "예식장",
            "홀"
        ]):

            place = line.strip()
            break

    return {
        "type": "경사",
        "wedding_date": wedding_date + " " + wedding_time,
        "place": place,
        "address": address,
    }

def extract_obituary(text):

    deceased_patterns = [
        r"故\s*([가-힣]{2,4})",
        r"고인\s*[:：]?\s*([가-힣]{2,4})",
        r"([가-힣]{2,4})\s*별세",
    ]

    funeral_patterns = [
        r"빈소\s*[:：]?\s*([^\n]+)",
        r"장례식장\s*[:：]?\s*([^\n]+)",
    ]

    departure_patterns = [
        r"발인\s*[:：]?\s*([^\n]+)",
        r"발인일시\s*[:：]?\s*([^\n]+)",
    ]

    deceased = ""
    funeral_home = ""
    departure = ""

    for pattern in deceased_patterns:

        match = re.search(pattern, text)

        if match:
            deceased = match.group(1).strip()
            break

    for pattern in funeral_patterns:

        match = re.search(pattern, text)

        if match:
            funeral_home = match.group(1).strip()
            break

    for pattern in departure_patterns:

        match = re.search(pattern, text)

        if match:
            departure = match.group(1).strip()
            break

    return {
        "type": "조사",
        "deceased": deceased,
        "funeral_home": funeral_home,
        "departure": departure,
    }

@app.post("/crawl")
def crawl(req: RequestData):

    try:

        raw_text = crawl_page(req.url)

        text = clean_text(raw_text)

        if req.kind == "조사":

            result = extract_obituary(text)

        else:

            result = extract_wedding(text)

        return result

    except Exception as e:

        return {
            "type": "에러",
            "error": str(e)
        }
