import os, json, base64, re, uuid
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from openai import OpenAI
import urllib.request

BASE = Path(__file__).resolve().parent
OUT = BASE / "outputs"
OUT.mkdir(exist_ok=True)

app = FastAPI(title="생각키움 SNS 매니저 Mobile")
app.mount("/static", StaticFiles(directory=BASE/"static"), name="static")
app.mount("/outputs", StaticFiles(directory=OUT), name="outputs")
templates = Jinja2Templates(directory=BASE/"templates")

KEYWORDS = [
"사우동사고력학원","김포체스학원","풍무동사고력학원","걸포동사고력학원","운양동사고력학원",
"장기동사고력학원","구래동사고력학원","마산동사고력학원","고촌사고력학원","향산리사고력학원",
"풍무동체스","걸포동체스","장기동체스","운양동체스","구래동체스","마산동체스","고촌체스",
"강화도체스","강화체스","검단사고력체스학원","검단체스학원","김포체스대회","생각키움연구소체스"
]

BRANCH = {
    "사우점":["사우동사고력학원","김포체스학원","걸포동사고력학원","운양동사고력학원","생각키움연구소체스"],
    "장기점":["장기동사고력학원","장기동체스","운양동체스","김포체스학원","생각키움연구소체스"],
    "구래점":["구래동사고력학원","구래동체스","마산동사고력학원","마산동체스","김포체스학원","생각키움연구소체스"],
    "전체":["김포체스학원","생각키움연구소체스"]
}

def get_client():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise HTTPException(500, "서버에 OPENAI_API_KEY가 설정되어 있지 않습니다.")
    return OpenAI(api_key=key)

def pick_keywords(branch, lesson, ctype):
    selected = list(BRANCH.get(branch, []))
    t = (lesson or "").replace(" ","")
    for k in KEYWORDS:
        core = k.replace("사고력학원","").replace("사고력체스학원","").replace("체스학원","").replace("체스","")
        if core and core in t and k not in selected:
            selected.append(k)
    if ctype == "대회후기" or "대회" in t:
        selected.append("김포체스대회")
    out=[]
    for x in selected:
        if x not in out: out.append(x)
    return out[:7]

def image_to_data_url(data: bytes, content_type: str):
    return f"data:{content_type or 'image/jpeg'};base64,{base64.b64encode(data).decode()}"

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request":request})

@app.get("/health")
async def health():
    return {"ok":True}

@app.post("/api/generate")
async def generate(
    branch: str = Form(...),
    content_type: str = Form(...),
    target: str = Form(...),
    lesson: str = Form(...)
):
    kws = pick_keywords(branch, lesson, content_type)
    prompt = f"""
너는 '생각키움연구소'의 네이버 블로그/인스타그램 콘텐츠 에디터다.

지점: {branch}
콘텐츠유형: {content_type}
대상: {target}
수업 메모: {lesson}
우선 키워드: {", ".join(kws)}

작성 원칙:
- 실제 수업 후기처럼 구체적이고 자연스럽게.
- 네이버 검색을 의식하되 키워드를 억지로 나열하지 말 것.
- 제목에는 핵심 키워드 1~2개만.
- 본문에는 관련 키워드 4~7개를 문맥 속에 자연스럽게 분산.
- 같은 핵심 키워드는 본문에서 2회 넘게 반복하지 말 것.
- 모바일에서 읽기 좋게 문단을 짧게.

출력 형식:
===제목후보===
1.
2.
3.

===블로그본문===
900~1500자, 소제목 3~5개

===인스타그램===
220~500자, 블로그 문장 그대로 복사하지 말 것

===해시태그===
10~18개

===대표이미지문구===
메인:
서브:
"""
    c = get_client()
    r = c.chat.completions.create(
        model="gpt-4o",
        messages=[{"role":"user","content":prompt}],
        max_tokens=2000
    )
    return {"text": r.choices[0].message.content.strip(), "keywords": kws}

@app.post("/api/privacy-check")
async def privacy_check(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 15*1024*1024:
        raise HTTPException(400, "사진은 15MB 이하로 선택해 주세요.")
    prompt = """
학원 수업 홍보 후보 사진이다.
다음 중 하나라도 해당하면 needs_edit=true:
- 아동/학생의 정면 또는 준정면 얼굴이 알아볼 수 있을 정도로 선명함
- 이름표, 이름, 학교명, 전화번호 등 식별정보가 읽힐 가능성이 있음
뒷모습/측면 위주이고 얼굴이 작아 식별이 어려우면 false.
JSON 한 줄만 출력: {"needs_edit":true,"reason":"짧은 이유"}
"""
    c = get_client()
    r = c.chat.completions.create(
        model="gpt-4o",
        messages=[{"role":"user","content":[
            {"type":"text","text":prompt},
            {"type":"image_url","image_url":{"url": image_to_data_url(data, file.content_type or "image/jpeg")}}
        ]}],
        max_tokens=100
    )
    txt = r.choices[0].message.content.strip()
    m = re.search(r'\{.*\}', txt, re.S)
    if not m:
        return {"needs_edit":True,"reason":"판별 불명확 — 안전하게 편집 대상으로 처리"}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"needs_edit":True,"reason":"판별 오류 — 안전하게 편집 대상으로 처리"}

@app.post("/api/privacy-edit")
async def privacy_edit(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 15*1024*1024:
        raise HTTPException(400, "사진은 15MB 이하로 선택해 주세요.")

    image_prompt = (
        "A natural realistic photo of elementary school children aged 8-12 "
        "sitting at desks in a bright Korean classroom, playing chess. "
        "Children are shown from the side or looking down at the chess board, "
        "deeply focused and thinking. Faces are not clearly visible. "
        "Chess pieces and board clearly shown. Warm natural lighting. "
        "Wholesome educational setting. No text, no logos. Square composition."
    )

    c = get_client()
    try:
        res = c.images.generate(
            model="gpt-image-1",
            prompt=image_prompt,
            size="1024x1024",
            n=1
        )
        item = res.data[0]
        b64 = getattr(item, "b64_json", None)
        if b64:
            out = OUT / f"privacy_{uuid.uuid4().hex}.png"
            out.write_bytes(base64.b64decode(b64))
            return {"url": f"/outputs/{out.name}", "mode": "generated"}

        img_url = getattr(item, "url", None)
        if img_url:
            out = OUT / f"privacy_{uuid.uuid4().hex}.png"
            img_data = urllib.request.urlopen(img_url, timeout=120).read()
            out.write_bytes(img_data)
            return {"url": f"/outputs/{out.name}", "mode": "generated"}

        raise RuntimeError("이미지 데이터 없음")

    except Exception as e:
        raise HTTPException(500, f"이미지 생성 오류: {str(e)}")
