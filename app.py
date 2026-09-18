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

NAVER_HASHTAGS = {
    "공통": [
        "#생각키움연구소", "#김포체스학원", "#사고력체스", "#체스수업",
        "#초등체스", "#어린이체스", "#체스교육", "#사고력향상",
        "#두뇌스포츠", "#체스배우기", "#체스학원추천", "#집중력향상",
        "#창의력교육", "#논리적사고", "#문제해결력", "#자기주도학습"
    ],
    "사우점": ["#사우동학원", "#김포사우동", "#풍무동학원", "#걸포동학원"],
    "장기점": ["#장기동학원", "#장기동체스", "#운양동학원", "#김포장기동"],
    "구래점": ["#구래동학원", "#구래동체스", "#마산동학원", "#김포구래동"],
    "전체": ["#김포학원", "#김포초등학원", "#김포사고력학원"],
    "대회후기": ["#체스대회", "#김포체스대회", "#피데올림피아드", "#체스올림피아드", "#한국체스"],
    "수업후기": ["#체스수업후기", "#학원후기", "#사고력수업", "#체스전술"],
}

EDUCATION_CONTEXT = """
[생각키움연구소 핵심 교육 철학]

■ 핵심 차별점 — 글 전체에서 다양한 표현으로 자연스럽게 2~3번 등장:

(1) 앞부분: "사고력"으로 학부모의 눈길을 끌기
    - "생각키움연구소는 체스를 통해 아이의 사고력을 키웁니다"
    - "단순히 체스 기술을 가르치는 곳이 아닙니다. 스스로 생각하고 판단하는 힘, 즉 사고력을 키우는 곳입니다"
    - "체스판 앞에서 아이가 스스로 고민하는 그 순간, 사고력이 자라납니다"

(2) 본문 중간: 교육부 핵심역량으로 전문성과 신뢰감 추가
    - "스스로 생각하고 판단하는 힘은 교육부가 강조하는 창의적 사고 역량으로 이어집니다"
    - "끝까지 집중하고 해내는 경험이 자기관리 역량을 키웁니다"
    - "상대를 배려하고 예의를 지키는 대국 문화는 협력적 소통 역량을 자연스럽게 길러줍니다"
    (※ '2022 개정 교육과정'이라는 표현은 쓰지 말 것. 그냥 '교육부가 강조하는'으로 표현)

(3) 마무리 부분: 다시 "사고력"으로 마무리
    - "체스 실력보다 더 중요한 것은 스스로 문제와 마주하는 용기와 사고력입니다"
    - "이 수업에서 아이들은 답을 받는 것이 아니라, 답을 만드는 법을 배웁니다"

■ 전문 교육:
    - 유아교육 전문가가 아이 개개인의 연령과 특성에 맞는 맞춤 수업 설계
    - 기술 전달을 넘어 정서, 사회성, 자존감까지 함께 성장
"""

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

def build_hashtags(branch, ctype):
    tags = list(NAVER_HASHTAGS["공통"])
    tags += NAVER_HASHTAGS.get(branch, [])
    if ctype == "대회후기":
        tags += NAVER_HASHTAGS["대회후기"]
    else:
        tags += NAVER_HASHTAGS["수업후기"]
    seen = []
    for t in tags:
        if t not in seen:
            seen.append(t)
    return " ".join(seen[:20])

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
    hashtags = build_hashtags(branch, content_type)

    prompt = f"""
당신은 김포시 생각키움연구소의 원장입니다.
유아교육 전문가로서 10년간 아이들의 사고력을 키워온 교육자입니다.

{EDUCATION_CONTEXT}

오늘 수업/소식:
- 지점: {branch}
- 유형: {content_type}
- 대상: {target}
- 내용: {lesson}
- 지역 키워드 (자연스럽게 녹이기): {", ".join(kws)}

===글쓰기 원칙===
1. 수업 현장의 구체적인 장면이나 에피소드로 자연스럽게 시작
   (아이들의 표정, 반응, 대화, 순간 등)

2. "사고력" → 본문 앞부분에서 학부모 눈길 끌기
   "교육부가 강조하는 창의적 사고 역량" → 중간에 전문성 추가
   "사고력" → 마무리에서 다시 한 번 강조
   (총 2~3번, 매번 다른 문장과 표현으로)

3. 소제목 형식: **🔹 소제목** (굵고 크게, 이모지 포함)

4. 문장은 짧고 리듬감 있게. 한 문단 3~4줄 이내

5. 유아교육 전문가가 아이 개개인에 맞는 맞춤 수업을 한다는 점을
   자연스럽게 한 번 언급

6. 지역 키워드는 문장 속에 녹이되 나열하지 말 것

7. 분량: 1200~1500자

8. 마지막 문단에서 수강 문의를 따뜻하게 자연스럽게 유도

9. '최고', '1등', '무조건' 등 과장 표현 금지

===출력 형식===
===제목후보===
1. (사고력+지역 키워드 포함, 30자 이내)
2. (학부모 공감형, 30자 이내)
3. (교육 효과 강조, 30자 이내)

===블로그본문===
(소제목 4~5개, 각 소제목 앞에 이모지, 1200~1500자)

===인스타그램===
(현장감 있는 짧은 이야기 + 감성 마무리, 이모지 활용, 200~300자)

===해시태그===
{hashtags}

===대표이미지문구===
메인: (사고력 관련 핵심 가치 한 줄)
서브: (오늘 수업 내용 한 줄)
"""
    c = get_client()
    r = c.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 유아교육 전문가 자격을 갖춘 10년 경력의 사고력체스 교육 원장입니다. "
                    "체스를 통해 아이들이 스스로 생각하고 문제를 해결하는 사고력을 키우는 교육을 합니다. "
                    "제목과 앞부분은 '사고력'으로 학부모의 관심을 끌고, "
                    "본문 중간에 '교육부가 강조하는 창의적 사고 역량' 등으로 전문성을 더하며, "
                    "마무리에서 다시 '사고력'으로 여운을 남기는 구조로 글을 씁니다. "
                    "광고처럼 들리지 않고 원장이 학부모에게 편지를 쓰듯 따뜻하고 자연스럽게 씁니다."
                )
            },
            {"role": "user", "content": prompt}
        ],
        max_tokens=2500,
        temperature=0.85
    )
    return {"text": r.choices[0].message.content.strip(), "keywords": kws}

@app.post("/api/privacy-check")
async def privacy_check(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 15*1024*1024:
        raise HTTPException(400, "사진은 15MB 이하로 선택해 주세요.")
    prompt = """
학원 수업 홍보 후보 사진이다.
정면 얼굴이 선명하거나 개인정보가 보이면 needs_edit=true.
뒷모습/측면이고 얼굴이 작으면 false.
JSON 한 줄만: {"needs_edit":true,"reason":"이유"}
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
        return {"needs_edit":True,"reason":"판별 불명확"}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"needs_edit":True,"reason":"판별 오류"}

@app.post("/api/privacy-edit")
async def privacy_edit(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 15*1024*1024:
        raise HTTPException(400, "사진은 15MB 이하로 선택해 주세요.")
    prompt = (
        "Realistic photo of Korean elementary school children aged 8-12 "
        "playing chess in a bright classroom. Side view, faces not visible. "
        "Chess board clearly shown. Warm lighting. No text. Square format."
    )
    c = get_client()
    try:
        res = c.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1024x1024",
            n=1
        )
        item = res.data[0]
        b64 = getattr(item, "b64_json", None)
        if b64:
            out = OUT / f"privacy_{uuid.uuid4().hex}.png"
            out.write_bytes(base64.b64decode(b64))
            return {"url": f"/outputs/{out.name}"}
        img_url = getattr(item, "url", None)
        if img_url:
            out = OUT / f"privacy_{uuid.uuid4().hex}.png"
            out.write_bytes(urllib.request.urlopen(img_url, timeout=120).read())
            return {"url": f"/outputs/{out.name}"}
        raise RuntimeError("이미지 없음")
    except Exception as e:
        raise HTTPException(500, f"이미지 생성 오류: {str(e)}")
