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
    deceased = re.search(r"(?:故|고인)\s*[:：]?\s*([가-힣]{2,4})", text)
    funeral = re.search(r"빈소\s*[:：]?\s*([^\n]+)", text)
    departure = re.search(r"발인\s*[:：]?\s*([^\n]+)", text)

    return {
        "type": "조사",
        "deceased": deceased.group(1) if deceased else "",
        "funeral_home": funeral.group(1).strip() if funeral else "",
        "departure": departure.group(1).strip() if departure else ""
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
