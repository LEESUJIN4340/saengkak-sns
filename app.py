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

# ──────────────────────────────────────────────────────
# 우선 관리 검색어 (요청 문서 §1 기반)
# 실제 지점이 위치한 지역 키워드만 사용
# ──────────────────────────────────────────────────────
KEYWORDS = [
    # 지역+업종 조합
    "김포체스학원", "김포사고력체스", "김포어린이체스",
    "사우동체스", "사우동체스학원", "사우동사고력학원",
    "장기동체스", "장기동체스학원", "장기동사고력학원",
    "구래동체스", "구래동체스학원", "구래동사고력학원",
    "풍무동체스", "걸포동체스", "운양동체스",
    # 브랜드
    "생각키움연구소", "생각키움체스",
    # 대회
    "김포체스대회", "어린이체스대회", "노비스체스대회", "FIDE체스대회",
]

BRANCH = {
    "사우점": ["김포체스학원", "사우동체스학원", "사우동사고력학원", "걸포동체스", "생각키움연구소"],
    "장기점": ["김포체스학원", "장기동체스학원", "장기동사고력학원", "운양동체스", "생각키움연구소"],
    "구래점": ["김포체스학원", "구래동체스학원", "구래동사고력학원", "구래동체스", "생각키움연구소"],
    "전체":   ["김포체스학원", "김포사고력체스", "생각키움연구소"],
}

# ──────────────────────────────────────────────────────
# 네이버·인스타 해시태그
# ──────────────────────────────────────────────────────
NAVER_HASHTAGS = {
    "공통": [
        "#생각키움연구소", "#김포체스학원", "#김포사고력체스",
        "#사고력체스", "#어린이체스", "#체스교육",
        "#사고력향상", "#집중력향상", "#논리적사고력",
        "#문제해결력", "#자기주도학습", "#두뇌스포츠",
    ],
    "사우점": ["#사우동체스", "#사우동학원", "#풍무동체스", "#걸포동체스", "#김포사우동학원"],
    "장기점": ["#장기동체스", "#장기동학원", "#운양동체스", "#김포장기동학원"],
    "구래점": ["#구래동체스", "#구래동학원", "#구래동사고력학원", "#김포구래동학원"],
    "전체":   ["#김포어린이체스", "#김포초등체스", "#김포사고력학원"],

    "수업후기": ["#체스수업후기", "#사고력수업", "#체스배우기", "#초등체스수업", "#체스전술", "#어린이체스후기"],
    "대회후기": ["#김포체스대회", "#체스대회후기", "#피데올림피아드", "#한국체스대회", "#FIDE대회"],
    "대회안내": ["#김포체스대회", "#어린이체스대회", "#노비스체스대회", "#체스대회일정", "#FIDE대회"],
    "신규모집": ["#체스학원추천", "#김포학원추천", "#체스체험수업", "#초등방과후체스", "#체스입문"],
    "이벤트":   ["#체스체험", "#김포체스이벤트", "#사고력체험", "#무료체험수업", "#체스학원이벤트"],
    "자격증":   ["#체스자격증", "#체스급수", "#FIDE자격증", "#체스타이틀", "#CM타이틀", "#FM타이틀"],
    "체스클럽": ["#체스클럽", "#김포체스클럽", "#체스동호회", "#성인체스", "#주말체스", "#체스모임"],

    "유아·초등": ["#유아체스", "#초등체스", "#초등사고력", "#어린이두뇌발달", "#초등방과후"],
    "중고등":    ["#청소년체스", "#중학생체스", "#FIDE레이팅", "#체스실력향상", "#두뇌트레이닝"],
    "성인":      ["#성인체스", "#취미체스", "#FIDE대회", "#두뇌트레이닝", "#체스동호회"],
    "fide":      ["#FIDE", "#피데", "#체스타이틀", "#CM타이틀", "#FM타이틀", "#국제체스"],
}

# ──────────────────────────────────────────────────────
# 콘텐츠 유형별 글쓰기 방향
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

# ──────────────────────────────────────────────────────
# 대상별 글쓰기 강조점
# ──────────────────────────────────────────────────────
TARGET_GUIDE = {
    "유아 (5~7세)": """
대상이 유아(5~7세)입니다.
- 체스를 처음 접하는 어린 아이들도 즐겁게 배울 수 있다는 점
- 놀이처럼 자연스럽게 규칙을 익히며 집중력과 인내심이 자란다는 점
- 유아교육 전문가의 눈높이 맞춤 수업이라 부모님이 안심할 수 있다는 점
- 체스판 앞에서 '스스로 생각하는 힘'이 이 나이부터 자란다는 점을 강조하세요.
""",
    "초등 저학년 (1~3학년)": """
대상이 초등 저학년(1~3학년)입니다.
- 학교 수업과 연계되는 집중력, 논리적 사고, 문제해결력이 자란다는 점
- 승부를 통해 이기고 지는 감정을 조절하는 경험
- 유아교육 전문가의 연령별 맞춤 수업으로 아이 속도에 맞게 배운다는 점
- 교육부가 강조하는 창의적 사고 역량이 체스를 통해 자연스럽게 길러진다는 점을 강조하세요.
""",
    "초등 고학년 (4~6학년)": """
대상이 초등 고학년(4~6학년)입니다.
- 전략적 사고, 수 읽기, 집중력이 이 나이에 급격히 발전한다는 점
- 대회 출전, 급수 취득 등 실질적인 성취 목표를 가질 수 있다는 점
- 스스로 분석하고 판단하는 힘, 즉 사고력이 학습 전반에도 이어진다는 점
- 자기주도학습 역량과 자기관리 역량으로 연결되는 경험을 강조하세요.
""",
    "초등 전체": """
대상이 초등학생 전체입니다.
- 저학년은 기초 집중력과 규칙 이해, 고학년은 전략과 대회 도전으로 각자의 속도로 성장한다는 점
- 유아교육 전문가의 개인별 맞춤 수업
- 사고력과 자기주도학습 역량이 학교생활 전반에 도움이 된다는 점을 강조하세요.
""",
    "유아·초등 전체": """
대상이 유아부터 초등학생까지 전체입니다.
- 나이에 상관없이 각자의 눈높이에 맞는 맞춤 수업이 이루어진다는 점
- 유아는 놀이로, 초등은 전략으로 — 같은 체스판이지만 배우는 깊이가 다르다는 점
- 사고력은 어릴수록 더 빨리, 더 깊이 뿌리내린다는 점을 강조하세요.
""",
    "중학생": """
대상이 중학생입니다.
- 체스가 단순한 취미가 아닌, 수능에도 연결되는 논리력·집중력·판단력 훈련이라는 점
- 자기주도학습과 메타인지 — 내가 어디서 실수했는지 스스로 분석하는 능력
- 대회 성적, FIDE 레이팅, 자격증 취득 등 구체적인 목표를 향해 성장하는 과정
- 또래 경쟁과 협력 속에서 사회성과 멘탈이 함께 성장한다는 점을 강조하세요.
""",
    "고등학생": """
대상이 고등학생입니다.
- 체스는 논리적 사고력과 집중력을 극한까지 끌어올리는 훈련이라는 점
- 입시와 수능에서 필요한 비판적 사고, 문제 분석 능력과 직결된다는 점
- FIDE 공인 타이틀(CM, FM 등) 취득은 대외 활동 실적으로도 가치가 있다는 점
- 스스로 선택하고 책임지는 경험 — 체스판 위의 결정이 삶의 태도가 된다는 점을 강조하세요.
""",
    "중·고등학생": """
대상이 중·고등학생입니다.
- 체스가 논리력·집중력·자기분석력을 기르는 최적의 훈련임을 강조
- 중학생은 기초 전략과 대회 첫 도전, 고등학생은 FIDE 레이팅과 타이틀 취득으로 나아가는 성장 경로
- 입시와 수능 사고력에 실질적으로 연결되는 경험
- 자기주도적으로 판단하고 분석하는 힘이 공부에도 이어진다는 점을 강조하세요.
""",
    "청소년 (초~고)": """
대상이 초등학생부터 고등학생까지 청소년 전체입니다.
- 각 나이에 맞는 성장 목표가 다르고, 생각키움연구소는 그 각각을 지원한다는 점
- 초등은 사고력의 씨앗, 중등은 전략의 뿌리, 고등은 판단력의 열매
- FIDE 대회, 급수 취득, 타이틀 도전까지 — 단계별 성장 경로가 있다는 점을 강조하세요.
""",
    "성인": """
대상이 성인입니다.
- 체스는 나이에 상관없이 시작할 수 있고, 오히려 성인이 되어 배울 때 더 빠르게 이해된다는 점
- 두뇌 활성화, 스트레스 해소, 집중력 회복 등 성인에게 체스가 주는 실질적 효과
- FIDE 공인 대회 출전, 레이팅 취득 등 나만의 목표를 가질 수 있다는 점
- 혼자 두는 스포츠가 아닌, 커뮤니티와 함께 성장하는 경험을 강조하세요.
""",
    "연령 무관 (오픈)": """
대상이 연령 무관 오픈 대회/행사입니다.
- 초등학생부터 성인까지 같은 대회에서 실력으로 겨루는 특별한 경험
- 나이 차이를 넘어 체스판 위에서 동등하게 경쟁하고 배운다는 점
- 어린 선수가 성인을 이기는 순간, 성인이 어린 선수에게 배우는 순간의 가치
- 오픈 대회를 통해 FIDE 레이팅과 실력이 함께 성장한다는 점을 강조하세요.
""",
}

def get_target_context(target: str) -> str:
    if target in TARGET_GUIDE:
        return TARGET_GUIDE[target]
    t = target.lower()
    if "유아" in t and "초등" in t:
        return TARGET_GUIDE["유아·초등 전체"]
    if "유아" in t:
        return TARGET_GUIDE["유아 (5~7세)"]
    if "고등" in t and "중" in t:
        return TARGET_GUIDE["중·고등학생"]
    if "고등" in t:
        return TARGET_GUIDE["고등학생"]
    if "중학" in t or ("중" in t and "등" in t):
        return TARGET_GUIDE["중학생"]
    if "성인" in t:
        return TARGET_GUIDE["성인"]
    if "오픈" in t or "무관" in t:
        return TARGET_GUIDE["연령 무관 (오픈)"]
    if "초등" in t:
        return TARGET_GUIDE["초등 전체"]
    return ""

def get_client():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise HTTPException(500, "서버에 OPENAI_API_KEY가 설정되어 있지 않습니다.")
    return OpenAI(api_key=key)

def pick_keywords(branch, lesson, ctype):
    selected = list(BRANCH.get(branch, []))
    t = (lesson or "").replace(" ", "")
    for k in KEYWORDS:
        core = k.replace("사고력학원","").replace("사고력체스학원","").replace("체스학원","").replace("체스","")
        if core and core in t and k not in selected:
            selected.append(k)
    if ctype in ("대회후기","대회안내") or "대회" in t:
        for dk in ["김포체스대회","어린이체스대회","노비스체스대회"]:
            if dk not in selected:
                selected.append(dk)
    out = []
    for x in selected:
        if x not in out:
            out.append(x)
    return out[:7]

def build_hashtags(branch, ctype, target=""):
    tags = list(NAVER_HASHTAGS["공통"])
    tags += NAVER_HASHTAGS.get(branch, [])
    guide = CONTENT_GUIDE.get(ctype, CONTENT_GUIDE["수업후기"])
    for key in guide["hashtag_keys"]:
        tags += NAVER_HASHTAGS.get(key, [])
    t_lower = target.lower()
    if "중" in t_lower or "고등" in t_lower or "청소년" in t_lower:
        tags += NAVER_HASHTAGS.get("중고등", [])
    elif "성인" in t_lower:
        tags += NAVER_HASHTAGS.get("성인", [])
    else:
        tags += NAVER_HASHTAGS.get("유아·초등", [])
    if "fide" in t_lower or "오픈" in t_lower or "무관" in t_lower or ctype in ("대회후기","대회안내"):
        tags += NAVER_HASHTAGS.get("fide", [])
    seen = []
    for t in tags:
        if t not in seen:
            seen.append(t)
    return " ".join(seen[:22])

def image_to_data_url(data: bytes, content_type: str):
    return f"data:{content_type or 'image/jpeg'};base64,{base64.b64encode(data).decode()}"

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/api/generate")
async def generate(
    branch: str = Form(...),
    content_type: str = Form(...),
    target: str = Form(...),
    lesson: str = Form(...)
):
    kws = pick_keywords(branch, lesson, content_type)
    hashtags = build_hashtags(branch, content_type, target)
    guide = CONTENT_GUIDE.get(content_type, CONTENT_GUIDE["수업후기"])
    target_ctx = get_target_context(target)

    system_prompt = (
        "당신은 생각키움연구소의 원장입니다. "
        "유아교육 전문가 자격을 갖춘 10년 경력의 사고력체스 교육자로, "
        "학부모·학생·성인 독자에게 편지를 쓰듯 따뜻하고 진솔하게 씁니다. "
        "광고 문구 느낌 없이, 수업 현장의 실제 경험을 바탕으로 자연스럽게 씁니다. "
        "생각키움연구소의 핵심은 '단순히 체스 기술이 아닌, "
        "스스로 생각하고 문제를 해결하는 사고력을 키우는 것'입니다. "
        "대상이 유아·초등이면 학부모에게, 중·고등이면 학생과 학부모 모두에게, "
        "성인이면 본인에게 직접 말을 거는 톤으로 써주세요. "
        "네이버 블로그 SEO 원칙: "
        "① 각 제목 유형별로 서로 다른 각도에서 접근할 것 "
        "② 같은 키워드를 3번 이상 반복하지 말 것 "
        "③ 한 게시물에 여러 지역 키워드를 혼합하지 말 것 "
        "④ 실제 수업에서 없었던 내용을 만들어내지 말 것 "
        "⑤ 과장된 교육 효과 표현을 쓰지 말 것"
    )

    target_section = f"\n[대상별 강조점]\n{target_ctx}" if target_ctx else ""
    title_keyword = kws[0] if kws else "김포체스학원"
    secondary_kws = ", ".join(kws[1:4]) if len(kws) > 1 else ""

    prompt = f"""
오늘 쓸 글의 소재입니다:
- 지점: {branch}
- 콘텐츠 유형: {content_type}
- 대상: {target}
- 내용/메모: {lesson}

[SEO 키워드 활용 방법]
- 제목에 반드시 포함할 핵심 키워드: "{title_keyword}"
- 본문에 자연스럽게 녹일 보조 키워드 (2~3개 선택, 억지로 넣지 말 것): {secondary_kws}
- 키워드는 문장 속에서 자연스럽게, 읽는 사람이 의식하지 못하게 사용
- 같은 키워드 3번 이상 반복 금지
- 제목은 30자 이내

{guide["guide"]}
{target_section}

위 내용을 바탕으로 네이버 검색 상위 노출에 유리하면서도 읽기 편하고 자연스러운 글을 써주세요.
독자가 끝까지 읽고 싶어지는 글, 학원 문의로 이어지는 글이 목표입니다.

출력 형식 (반드시 아래 구분자를 정확히 사용):

===제목후보===
1. [지역검색어형] {title_keyword} 포함, 30자 이내, 검색 의도 명확
2. [학부모궁금증형] 학부모가 검색할 질문 형태, 30자 이내
3. [수업사례형] 실제 수업 장면이 담긴 제목, 30자 이내
4. [사고력전문성형] 사고력·교육 전문성 강조, 30자 이내
5. [성과도전형] 대회·성취·성장 강조, 30자 이내
추천: 위 1~5번 중 하나를 선택하고 한 줄로 선정 이유 설명

===블로그본문===
**🔹 소제목** 형식으로 소제목 4~5개, 전체 1200~1500자.
각 소제목 아래 본문은 3~4줄 짧은 문단으로.
첫 단락과 마지막 단락에 핵심 키워드 자연스럽게 포함.
학부모의 검색 목적에 맞는 도입부로 시작.

===인스타그램===
블로그와 다른 표현으로. 현장감 있고 감성적으로. 이모지 자연스럽게 활용. 200~300자.
인스타는 해시태그 없이 본문만.

===해시태그===
{hashtags}

===대표이미지문구===
메인: (핵심 가치 한 줄, 10자 이내)
서브: (오늘 내용 한 줄, 20자 이내)

===SEO품질점수===
아래 10개 항목을 각 10점 만점으로 채점하고 합계를 100점 만점으로 표시하세요.
1. 검색의도적합성: X점 — 한 줄 평가
2. 지역관련성: X점 — 한 줄 평가
3. 제목본문일치: X점 — 한 줄 평가
4. 정보구체성: X점 — 한 줄 평가
5. 문장반복여부: X점 — 한 줄 평가
6. 키워드적정사용: X점 — 한 줄 평가
7. 체스전문용어정확성: X점 — 한 줄 평가
8. 교육효과표현: X점 — 한 줄 평가
9. 학부모유용정보: X점 — 한 줄 평가
10. 상담연결명확성: X점 — 한 줄 평가
총점: XX점/100점
개선권장: (미흡한 항목이 있으면 구체적 수정 이유와 개선안 1~2줄)
"""

    c = get_client()
    r = c.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        max_tokens=3000,
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
