
import os, json, base64, re, mimetypes, uuid
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from openai import OpenAI

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

def client():
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

def response_text(r):
    if getattr(r, "output_text", None):
        return r.output_text
    texts=[]
    for item in getattr(r, "output", []) or []:
        for c in getattr(item, "content", []) or []:
            t=getattr(c,"text",None)
            if t: texts.append(t)
    return "\n".join(texts)

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
- '최고', '무조건', '1등' 같은 과장 표현 금지.
- 학생 신원이나 얼굴 특징을 추측하거나 쓰지 말 것.
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
    r = client().responses.create(model="gpt-5.6-luna", input=prompt)
    return {"text":response_text(r).strip(), "keywords":kws}

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
- 특정 학생을 쉽게 알아볼 수 있는 매우 선명한 얼굴 클로즈업

뒷모습/측면 위주이고 얼굴이 작아 식별이 어려우면 false 가능.
JSON 한 줄만 출력:
{"needs_edit":true,"reason":"짧은 이유"}
"""
    r = client().responses.create(
        model="gpt-5.6-luna",
        input=[{"role":"user","content":[
            {"type":"input_text","text":prompt},
            {"type":"input_image","image_url":image_to_data_url(data, file.content_type or "image/jpeg")}
        ]}]
    )
    txt=response_text(r).strip()
    m=re.search(r'\{.*\}',txt,re.S)
    if not m:
        return {"needs_edit":True,"reason":"판별 불명확하여 안전하게 편집 대상으로 처리"}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"needs_edit":True,"reason":"판별 결과 오류로 안전하게 편집 대상으로 처리"}

@app.post("/api/privacy-edit")
async def privacy_edit(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 15*1024*1024:
        raise HTTPException(400, "사진은 15MB 이하로 선택해 주세요.")
    ext = Path(file.filename or "photo.jpg").suffix.lower()
    if ext not in [".jpg",".jpeg",".png",".webp"]:
        ext = ".jpg"
    tmp = OUT / f"src_{uuid.uuid4().hex}{ext}"
    tmp.write_bytes(data)
    out = OUT / f"privacy_{uuid.uuid4().hex}.png"
    edit_prompt = """
이 이미지는 어린이 체스학원의 실제 수업 홍보사진이다.
수업 장소감, 인원수, 체스판, 책상 배치, 수업 활동과 자연스러운 분위기는 최대한 유지한다.

개인 식별을 막기 위해:
1. 정면/준정면으로 선명하게 보이는 학생은 '원본과 동일인이 아님이 분명한' 자연스러운 비식별 학생으로 재구성한다.
2. 모자이크나 블러처럼 보이지 않게 실제 촬영 사진처럼 자연스럽게 한다.
3. 가능하면 시선과 얼굴 방향을 체스판 쪽, 옆쪽, 아래쪽으로 자연스럽게 바꾼다.
4. 이름표, 학생이름, 학교명, 전화번호 등 읽힐 수 있는 개인정보는 제거한다.
5. 원본 얼굴의 고유 특징을 복제하지 않는다.
6. 체스판과 기물은 정상적인 체스 수업처럼 자연스럽게 유지한다.
7. 만화화, 과도한 피부보정, 광고합성 느낌은 피한다.
8. 새 로고나 글자를 임의로 넣지 않는다.
"""
    c=client()
    try:
        with open(tmp,"rb") as f:
            res=c.images.edit(model="gpt-image-2", image=f, prompt=edit_prompt, size="1024x1024")
        item=res.data[0]
        b64=getattr(item,"b64_json",None)
        if b64:
            out.write_bytes(base64.b64decode(b64))
        else:
            url=getattr(item,"url",None)
            if not url:
                raise RuntimeError("편집 이미지 데이터 없음")
            import urllib.request
            out.write_bytes(urllib.request.urlopen(url,timeout=120).read())
        return {"url":f"/outputs/{out.name}"}
    finally:
        try: tmp.unlink()
        except: pass
