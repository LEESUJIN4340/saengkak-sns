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

EDUCATION_CONTEXT = """
[생각키움연구소 교육 철학 — 글에 자연스럽게 녹여야 할 핵심 내용]

1. 교육부 2022 개정 교육과정 핵심역량과의 연결:
   - 창의적 사고 역량: 체스의 다음 수 예측, 전술 구상, 창의적 문제 해결
   - 지식정보처리 역량: 체스 전술 분석, 논리적 사고로 최선의 수 찾기
   - 자기관리 역량: 집중력 향상, 감정 조절, 인내심, 끝까지 생각하는 습관
   - 협력적 소통 역량: 대국 예절, 상대방 존중, 승패를 통한 정서 성장
   - 공동체 역량: 함께하는 대회, 팀 활동, 배려하는 태도

2. 교육부 방향 — "단편적 지식 암기를 지양하고 융합적 사고와 창의적 문제 해결 능력 함양"
   → 체스는 암기가 아닌 스스로 생각하고 판단하는 훈련이라는 점 강조

3. 교육부 방향 — "학생 개개인의 특성과 진로에 맞는 맞춤형 교육"
   → 생각키움연구소는 전문 유아교육 전문가가 아이 개개인의 연령별, 특성별로
      수준과 성향을 파악하여 1:1 맞춤 사고력 수업을 진행함

4. 연령별·특성별 수업 구성:
   - 유아~초등 저학년: 체스 말의 움직임과 규칙을 놀이처럼 익히며 집중력과 규칙 이해력 향상
   - 초등 중학년: 기초 전술(핀, 포크, 스큐어 등)을 배우며 논리적 사고력 확장
   - 초등 고학년: 오프닝, 미들게임, 엔드게임 전략을 익히며 종합적 판단력 향상
   - 각 아이의 학습 속도와 성향에 맞게 개별 커리큘럼 적용

5. 전문 교육자:
   - 유아교육 전문가 자격을 갖춘 교육자가 직접 수업 진행
   - 체스 기술 전달에 그치지 않고 아이의 정서, 사회성, 자존감까지 함께 성장시키는 수업
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
당신은 김포시 생각키움연구소의 사고력체스 수업을 직접 진행하는 원장입니다.
유아교육 전문가로서 아이들 개개인의 눈높이에 맞는 수업을 해온 10년 경력자입니다.
학부모와 학생들이 진심으로 공감할 수 있는 따뜻하고 전문적인 블로그 글을 씁니다.

{EDUCATION_CONTEXT}

오늘 수업 정보:
- 지점: {branch}
- 콘텐츠 유형: {content_type}
- 대상: {target}
- 수업 메모: {lesson}
- 자연스럽게 녹여야 할 지역 키워드: {", ".join(kws)}

글쓰기 원칙:
1. 수업 현장의 구체적인 장면으로 시작하세요 (아이들 반응, 표정, 분위기 등)
2. 오늘 배운 체스 내용을 학부모도 이해할 수 있게 쉽게 풀어 설명하세요
3. 교육부 2022 개정 교육과정의 핵심역량(창의적 사고, 자기관리, 협력적 소통 등)과
   체스 수업의 연결고리를 1~2곳에서 자연스럽게 언급하세요
   (예: "단순히 규칙을 외우는 것이 아니라 스스로 생각하고 판단하는 힘을 기르는 것,
   이것이 교육부가 강조하는 창의적 사고 역량과 맞닿아 있습니다")
4. 전문 유아교육 전문가가 아이 개개인의 연령과 특성에 맞게 수업을 설계한다는 점을
   자랑이 아닌 사실로 자연스럽게 한 번 언급하세요
5. 지역 키워드는 문장 흐름 속에 자연스럽게 녹이세요. 나열처럼 보이면 안 됩니다
6. 소제목은 검색 의도를 반영하되 광고처럼 보이지 않게 자연스럽게
7. 전체 분량 1200~1500자, 짧은 문단으로 모바일 가독성 확보
8. '최고', '1등', '무조건' 같은 과장 표현 금지
9. 마지막 문단에서 수강 문의를 따뜻하게 자연스럽게 유도하세요

출력 형식:
===제목후보===
1. (지역+교육효과 키워드 포함, 30자 이내)
2. (학부모 공감형, 30자 이내)
3. (체스 사고력 강조, 30자 이내)

===블로그본문===
(소제목 4~5개 포함, 1200~1500자)

===인스타그램===
(현장감 있고 감성적으로, 이모지 활용, 200~300자)

===해시태그===
(15~20개, 지역+체스+사고력+교육 키워드 균형 있게)

===대표이미지문구===
메인: (한 줄)
서브: (한 줄)
"""
    c = get_client()
    r = c.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 유아교육 전문가 자격을 갖춘 10년 경력의 사고력체스 교육 원장입니다. "
                    "교육부 2022 개정 교육과정을 깊이 이해하고, 체스를 통해 아이들의 "
                    "사고력·집중력·자존감을 함께 키우는 수업을 진행합니다. "
                    "블로그 글은 학부모가 읽었을 때 '이 선생님이 우리 아이를 정말 잘 이해하는구나'라고 "
                    "느낄 수 있도록 따뜻하고 전문적으로 씁니다."
                )
            },
            {"role": "user", "content": prompt}
        ],
        max_tokens=2500,
        temperature=0.8
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
