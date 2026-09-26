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
    "수업후기": ["#체스수업후기", "#학원후기", "#사고력수업", "#체스전술"],
    "대회후기": ["#체스대회", "#김포체스대회", "#피데올림피아드", "#체스올림피아드", "#한국체스"],
    "대회안내": ["#체스대회", "#김포체스대회", "#체스대회일정", "#어린이체스대회", "#한국체스"],
    "신규모집": ["#체스학원등록", "#체스체험수업", "#김포학원추천", "#초등방과후", "#어린이사고력"],
    "이벤트": ["#체스이벤트", "#김포체스", "#체스체험", "#학원이벤트", "#사고력체험"],
    "자격증": ["#체스자격증", "#체스급수", "#FIDE자격증", "#체스검정", "#체스실력향상"],
    "체스클럽": ["#체스클럽", "#김포체스클럽", "#체스동아리", "#주말체스", "#성인체스"],
}

# ──────────────────────────────────────────────────────
# 콘텐츠 유형별 글쓰기 방향 (톤 + 구조 + 예시)
# ──────────────────────────────────────────────────────
CONTENT_GUIDE = {
    "수업후기": {
        "hashtag_keys": ["수업후기"],
        "guide": """
[수업 후기 — 글쓰기 방향]
오늘 실제 수업에서 있었던 장면이나 아이들의 반응을 중심으로 씁니다.
원장이 학부모에게 따뜻하게 전하는 편지 같은 톤으로, 광고처럼 들리지 않게.

좋은 시작 예시:
"오늘 수업 중 한 아이가 체스판을 한참 들여다보다 혼잣말을 했습니다. '이거 여기 두면 나중에 어떻게 되지?' 그 순간이 참 좋았습니다."

자연스럽게 담아주세요:
- 사고력이라는 단어를 앞부분과 마무리에서 각각 다른 문장으로
- 교육부가 강조하는 핵심역량(창의적 사고, 자기관리 등) 한 번
- 유아교육 전문가로서 아이 개개인 맞춤 수업이라는 점
- 마지막에 따뜻한 수강 문의 유도
""",
    },
    "대회후기": {
        "hashtag_keys": ["대회후기"],
        "guide": """
[대회 후기 — 글쓰기 방향]
대회에 참가한 아이들의 긴장, 집중, 성장의 순간을 생생하게 전합니다.
결과보다 과정과 경험에서 배운 것을 중심으로. 학부모가 읽고 뭉클할 수 있게.

좋은 시작 예시:
"대회장에 들어서는 아이의 뒷모습이 생각납니다. 조금 긴장한 어깨, 그래도 단단한 걸음걸이."

자연스럽게 담아주세요:
- 대회 현장의 구체적인 분위기나 순간
- 이기고 지는 결과보다, 스스로 결정하고 버텨낸 경험의 가치
- 사고력과 담대함, 집중력이 이런 자리에서 빛난다는 것
- 다음 도전을 응원하는 마무리
""",
    },
    "대회안내": {
        "hashtag_keys": ["대회안내"],
        "guide": """
[대회 안내 — 글쓰기 방향]
곧 열리는 대회 정보를 안내하되, 딱딱한 공지문이 아니라 학부모의 마음을 움직이는 글로.
"우리 아이도 도전해볼 수 있을까?" 하는 마음이 생기도록 써주세요.

좋은 시작 예시:
"체스 대회, 아이에게 어떤 경험이 될까요? 이기고 지는 것보다 훨씬 많은 것을 가져옵니다."

자연스럽게 담아주세요:
- 대회 일시, 장소, 대상, 참가 방법 등 핵심 정보를 중간에 자연스럽게
- 대회 경험이 아이에게 주는 성장과 사고력 발달
- 생각키움연구소에서 어떻게 대회를 준비하는지
- 참가 문의 유도 마무리
""",
    },
    "신규모집": {
        "hashtag_keys": ["신규모집"],
        "guide": """
[신규 원생 모집 — 글쓰기 방향]
처음 체스를 접하는 학부모의 궁금증에 먼저 답하듯이 씁니다.
"우리 아이가 잘 할 수 있을까?" "무엇을 배우는 거지?" 하는 마음을 읽어주세요.

좋은 시작 예시:
"체스, 어렵지 않을까요? 아이들이 처음 체스판 앞에 앉을 때 저도 똑같이 걱정했습니다."

자연스럽게 담아주세요:
- 처음 시작하는 아이도 괜찮다는 안심
- 어떤 아이에게 맞는지 (연령, 성향 등)
- 유아교육 전문가의 맞춤 수업 방식
- 사고력 향상이라는 실질적인 교육 효과
- 체험수업 또는 상담 신청 유도
""",
    },
    "이벤트": {
        "hashtag_keys": ["이벤트"],
        "guide": """
[이벤트/공지 — 글쓰기 방향]
이벤트 내용을 흥미롭고 참여하고 싶게 전합니다.
혜택을 나열하는 느낌보다, 이 이벤트가 왜 의미 있는지 먼저 이야기해주세요.

좋은 시작 예시:
"새 학기가 시작되는 이 시기, 아이들의 마음도 새로운 도전을 원하고 있습니다."

자연스럽게 담아주세요:
- 이벤트 배경이나 이유 (왜 지금, 왜 이 기회인지)
- 이벤트 내용과 혜택을 구체적으로
- 생각키움연구소와 사고력 체스의 교육 가치 한 번 언급
- 신청 방법과 기간, 문의처로 마무리
""",
    },
    "자격증": {
        "hashtag_keys": ["자격증"],
        "guide": """
[자격증/급수 과정 — 글쓰기 방향]
체스 자격증이나 급수 시험이 아이에게 어떤 의미인지를 중심으로 씁니다.
"스펙 쌓기"보다 "성취 경험"과 "도전 정신"의 관점으로.

좋은 시작 예시:
"급수증을 받아든 아이의 표정이 있습니다. 이긴 게 아닌데도 환하게 웃는 그 얼굴."

자연스럽게 담아주세요:
- 자격증/급수가 아이에게 주는 성취감과 자신감
- 어떻게 준비하고 어떤 과정인지
- 생각키움연구소의 체계적인 자격증 대비 수업
- 사고력과 실력이 함께 성장한다는 점
- 준비 시작 방법 / 문의 유도
""",
    },
    "체스클럽": {
        "hashtag_keys": ["체스클럽"],
        "guide": """
[체스클럽 안내 — 글쓰기 방향]
학원 수업과 다른, 클럽만의 자유롭고 즐거운 분위기를 살려 씁니다.
체스를 좋아하는 아이들이 함께 성장하는 커뮤니티 느낌으로.

좋은 시작 예시:
"수업이 끝나도 체스판을 놓지 못하는 아이들이 있습니다. 그 아이들을 위한 공간을 열었습니다."

자연스럽게 담아주세요:
- 클럽이 생긴 이유와 어떤 분위기인지
- 어떤 활동을 하는지 (대국, 분석, 친선전 등)
- 체스를 통해 쌓이는 우정과 사고력
- 가입 방법과 대상, 문의 유도
""",
    },
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
    if ctype in ("대회후기","대회안내") or "대회" in t:
        selected.append("김포체스대회")
    out=[]
    for x in selected:
        if x not in out: out.append(x)
    return out[:7]

def build_hashtags(branch, ctype):
    tags = list(NAVER_HASHTAGS["공통"])
    tags += NAVER_HASHTAGS.get(branch, [])
    guide = CONTENT_GUIDE.get(ctype, CONTENT_GUIDE["수업후기"])
    for key in guide["hashtag_keys"]:
        tags += NAVER_HASHTAGS.get(key, [])
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
    guide = CONTENT_GUIDE.get(content_type, CONTENT_GUIDE["수업후기"])

    system_prompt = (
        "당신은 생각키움연구소의 원장입니다. "
        "유아교육 전문가 자격을 갖춘 10년 경력의 사고력체스 교육자로, "
        "학부모에게 편지를 쓰듯 따뜻하고 진솔하게 글을 씁니다. "
        "광고 문구 느낌 없이, 수업 현장과 교육 철학을 담아 자연스럽게 씁니다. "
        "생각키움연구소의 핵심은 '단순히 체스 기술이 아닌, "
        "스스로 생각하고 문제를 해결하는 사고력을 키우는 것'입니다."
    )

    prompt = f"""
오늘 쓸 글의 소재입니다:
- 지점: {branch}
- 콘텐츠 유형: {content_type}
- 대상: {target}
- 내용/메모: {lesson}
- 지역 키워드 (문장 속에 자연스럽게 1~2개만 녹이기): {", ".join(kws[:3])}

{guide["guide"]}

위 글쓰기 방향을 따라, 오늘 소재를 바탕으로 자연스럽고 읽기 편한 글을 써주세요.

출력 형식:

===제목후보===
1.
2.
3.

===블로그본문===
**🔹 소제목** 형식으로 소제목 4~5개, 전체 1200~1500자.
각 소제목 아래 본문은 3~4줄 짧은 문단으로.

===인스타그램===
블로그와 다른 표현으로. 현장감 있고 감성적으로. 이모지 자연스럽게 활용. 200~300자.

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
