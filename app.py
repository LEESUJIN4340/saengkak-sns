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

# ─────────────────────────────────────────────
# 글쓰기 예시 — 규칙 나열 대신 "이런 느낌"으로 보여주기
# ─────────────────────────────────────────────
STYLE_EXAMPLE = """
[참고 예시 — 이런 톤과 흐름으로 써주세요]

오늘 수업 중 한 아이가 체스판을 한참 들여다보다 혼잣말을 했습니다.
"이거 여기 두면 나중에 어떻게 되지?"

그 순간이 참 좋았습니다.
이기고 싶은 마음보다 먼저 생각하려는 그 자세.
그것이 우리가 수업에서 키우고 싶은 힘, 바로 사고력입니다.

생각키움연구소는 체스 기술을 가르치는 곳이 아닙니다.
스스로 생각하고, 스스로 결정하고, 스스로 배우는 힘을 기르는 곳입니다.

유아교육 전문가로서 아이 한 명 한 명의 나이와 기질에 맞춰 수업을 설계합니다.
같은 나이라도 어떤 아이는 전략에, 어떤 아이는 집중에, 어떤 아이는 자존감 회복에 집중합니다.
교육부가 강조하는 창의적 사고 역량과 자기관리 역량이 이 과정에서 차곡차곡 쌓입니다.

수업이 끝나고 아이가 "오늘 내가 이겼어"보다
"오늘 내가 잘 생각했어"라고 말할 때,
그것이 저희 수업이 제대로 된 날입니다.

수강 문의는 편하게 연락 주세요.
아이의 이야기를 먼저 듣겠습니다.
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

    system_prompt = (
        "당신은 생각키움연구소의 원장입니다. "
        "유아교육 전문가 자격을 갖춘 10년 경력의 사고력체스 교육자로, "
        "학부모에게 편지를 쓰듯 따뜻하고 진솔하게 글을 씁니다. "
        "광고 문구 느낌 없이, 수업 현장의 실제 이야기를 담아 자연스럽게 씁니다. "
        "생각키움연구소의 핵심 차별점은 '단순히 체스 기술이 아닌, "
        "스스로 생각하고 문제를 해결하는 사고력을 키우는 것'임을 "
        "글 전체에서 자연스럽게 느낄 수 있도록 합니다."
    )

    prompt = f"""
오늘 쓸 글의 소재입니다:
- 지점: {branch}
- 유형: {content_type}
- 대상: {target}
- 수업 내용: {lesson}
- 지역 키워드 (문장 속에 자연스럽게 1~2개만): {", ".join(kws[:3])}

{STYLE_EXAMPLE}

위 예시의 톤과 흐름을 참고해서, 오늘 수업 내용을 바탕으로 글을 써주세요.

글을 쓸 때 자연스럽게 담아주세요:
- 수업 현장의 구체적인 장면이나 아이들의 반응으로 시작
- '사고력'이라는 단어를 앞부분과 마무리에서 각각 한 번씩, 다른 문장으로
- 교육부가 강조하는 핵심역량(창의적 사고, 자기관리 등) 한 번 언급
- 유아교육 전문가로서 아이 개개인 맞춤 수업이라는 점 자연스럽게 한 번
- 마지막에 따뜻한 수강 문의 유도

출력:

===제목후보===
1.
2.
3.

===블로그본문===
**🔹 소제목** 형식으로 소제목 4~5개, 전체 1200~1500자.
소제목 사이 본문은 짧은 문단(3~4줄)으로.

===인스타그램===
블로그와 다른 문장으로. 현장감 있게 짧고 감성적으로. 이모지 활용. 200~300자.

===해시태그===
{hashtags}

===대표이미지문구===
메인:
서브:
"""

    c = get_client()
    r = c.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        max_tokens=2500,
        temperature=0.9
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
