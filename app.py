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
# 지점별 지역 검색 전략
# 핵심·확장 지역을 분리, 게시물마다 1개 핵심+보조 조합
# ──────────────────────────────────────────────────────
KEYWORDS = [
    "김포체스학원", "김포사고력체스", "김포어린이체스",
    # 장기점
    "장기동체스", "장기동체스학원", "운양동체스", "운양동체스학원",
    # 사우점
    "사우동체스", "사우동체스학원", "걸포동체스", "북변동체스", "풍무동체스",
    # 구래점
    "구래동체스", "구래동체스학원", "마산동체스", "구래역체스",
    # 브랜드
    "생각키움연구소", "생각키움체스",
    # 대회
    "김포체스대회", "어린이체스대회", "노비스체스대회", "FIDE체스대회",
]

# 지점별: 핵심 검색어(index 0) + 확장 검색어
BRANCH = {
    "사우점": ["사우동체스학원", "사우동체스", "걸포동체스", "북변동체스", "풍무동체스", "김포체스학원", "생각키움연구소"],
    "장기점": ["장기동체스학원", "장기동체스", "운양동체스", "운양동체스학원", "김포체스학원", "생각키움연구소"],
    "구래점": ["구래동체스학원", "구래동체스", "마산동체스", "구래역체스", "김포체스학원", "생각키움연구소"],
    "전체":   ["김포체스학원", "김포사고력체스", "생각키움연구소"],
}

# 지점별 지역 설명 (본문에서 자연스럽게 활용)
BRANCH_AREA = {
    "사우점": "사우동·걸포동·북변동·풍무동 일대",
    "장기점": "장기동·운양동 일대",
    "구래점": "구래동·마산동·구래역 일대",
    "전체":   "김포 전 지역",
}

# ──────────────────────────────────────────────────────
# 체스 전문용어 설명 사전 ((설명) 명령어용)
# ──────────────────────────────────────────────────────
CHESS_TERMS = {
    "포크": {
        "name": "포크(Fork)",
        "concept": "한 기물이 동시에 두 개 이상의 상대 기물을 공격하는 전술",
        "how": "나이트가 가장 많이 활용하며, 왕과 퀸을 동시에 공격하는 '로열 포크'가 대표적",
        "use": "상대가 한 기물을 지키면 나머지를 잡을 수 있어 반드시 이득을 얻는 전술",
        "caution": "포크를 치기 전, 포크를 치는 기물이 먼저 잡히지 않는지 확인 필요",
        "easy": "한 손으로 두 개를 동시에 집으려는 것처럼, 한 기물이 두 곳을 한꺼번에 위협하는 것",
        "thinking": "미리 2~3수를 내다보는 전략적 사고력을 키우는 대표 전술"
    },
    "핀": {
        "name": "핀(Pin)",
        "concept": "기물을 움직이면 그 뒤에 있는 더 가치 있는 기물이 공격받는 상황",
        "how": "비숍·룩·퀸 같은 장거리 기물이 상대 기물 두 개를 일직선으로 겨냥할 때 발생",
        "use": "핀된 기물은 움직이기 어려워 상대의 행동을 제한하고 공격 기회를 만든다",
        "caution": "핀을 활용할 때는 핀된 기물을 계속 압박하며 이득을 극대화해야 함",
        "easy": "뒤에 더 중요한 것이 있어서 앞에 있는 것을 비켜줄 수 없는 상황",
        "thinking": "상황을 전체적으로 파악하고 약점을 찾는 분석력을 키우는 전술"
    },
    "스큐어": {
        "name": "스큐어(Skewer)",
        "concept": "핀의 반대. 가치 높은 기물이 공격받아 피하면 뒤에 있는 기물이 잡히는 전술",
        "how": "장거리 기물(룩·비숍·퀸)이 왕이나 퀸을 직접 공격, 피하면 뒤 기물을 잡음",
        "use": "왕을 직접 위협하기 때문에 상대가 반드시 반응해야 하는 강력한 전술",
        "caution": "스큐어를 치기 전 상대가 체크를 막으면서 뒤 기물도 지킬 수 있는지 확인",
        "easy": "중요한 것이 먼저 공격받아서 피하면, 그 뒤에 있던 것을 잃는 상황",
        "thinking": "우선순위를 판단하는 사고력과 연결되는 전술"
    },
    "오포지션": {
        "name": "오포지션(Opposition)",
        "concept": "두 왕이 같은 줄이나 열에 홀수 칸 간격으로 마주 보는 포지션",
        "how": "상대 왕과 1칸·3칸·5칸 간격으로 마주 보면 오포지션. 직접·먼·대각선 오포지션이 있음",
        "use": "엔드게임에서 왕을 전진시키거나 막는 핵심 기술. 폰 엔드게임에서 승패를 결정하는 요소",
        "caution": "오포지션을 빼앗기면 왕이 전진하지 못하고 비기거나 질 수 있음",
        "easy": "체스판에서 두 왕이 서로 마주 보며 '네가 가면 나도 간다'는 식으로 버티는 것",
        "thinking": "끝까지 집중하고 계산하는 인내력과 정확성을 키우는 기술"
    },
    "이탈리안게임": {
        "name": "이탈리안 게임(Italian Game)",
        "concept": "1.e4 e5 2.Nf3 Nc6 3.Bc4로 시작하는 오프닝. 비숍이 f7 폰을 겨냥",
        "how": "중앙을 빠르게 장악하고 킹사이드 공격을 준비하는 공격적 오프닝",
        "use": "초보자부터 그랜드마스터까지 폭넓게 사용. 논리적 전개 원칙을 배우기 좋음",
        "caution": "조에반 수비(Giuoco Piano)와 두 기사 방어 등 다양한 변화가 있어 상대 반응에 따른 대비 필요",
        "easy": "기물을 빠르게 꺼내서 공격 준비를 하는 오래된 오프닝",
        "thinking": "오프닝 원칙(기물 전개·중앙 장악·킹 안전)을 이해하며 계획적 사고를 기르는 오프닝"
    },
    "룩": {
        "name": "룩(Rook) 활용",
        "concept": "룩은 가로·세로 전 방향으로 이동하는 강력한 장거리 기물(가치 5점)",
        "how": "열린 파일(폰 없는 줄)에 위치시키고, 엔드게임에서 왕을 앞세워 폰을 밀면서 활용",
        "use": "룩 더블링(두 룩을 같은 열에)으로 강력한 압박. 7번째 줄(랭크)에 위치하면 매우 강함",
        "caution": "오프닝에서 너무 일찍 꺼내면 공격받기 쉬움. 기물 전개 후 활용",
        "easy": "체스판의 직선 도로를 달리는 기물. 막힘 없이 달릴 수 있어야 강해짐",
        "thinking": "기물의 활동성과 팀워크를 이해하는 전략적 사고력을 키우는 기물"
    },
}

def get_chess_term_explanation(lesson: str) -> str:
    """수업 내용에서 (설명) 명령어가 붙은 체스 용어를 찾아 설명 반환"""
    explanations = []
    lesson_lower = lesson.lower().replace(" ", "")
    for key, data in CHESS_TERMS.items():
        pattern = key + "(설명)"
        if pattern in lesson_lower or pattern.replace("(","（").replace(")","）") in lesson:
            explanations.append(data)
    if not explanations:
        # 괄호 없이 용어만 있어도 감지
        for key, data in CHESS_TERMS.items():
            if key in lesson_lower:
                explanations.append(data)
    return explanations

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
    "사우점": ["#사우동체스", "#사우동체스학원", "#걸포동체스", "#북변동체스", "#풍무동체스"],
    "장기점": ["#장기동체스", "#장기동체스학원", "#운양동체스", "#운양동체스학원"],
    "구래점": ["#구래동체스", "#구래동체스학원", "#마산동체스", "#구래역체스"],
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

대화 유형 선택 (수업 내용에 따라 자연스러운 쪽으로):
- [유형 A] 학생↔선생님 중심: 수업 현장에서 아이가 고민하고 발견하는 장면
- [유형 B] 학부모↔선생님 중심: 수업 후 학부모가 전한 아이의 변화 이야기
- [유형 C] 혼합: 수업 장면(학생↔선생님) + 학부모가 집에서 관찰한 변화를 연결

좋은 시작 예시 A:
"오늘 수업 중 한 아이가 체스판을 한참 들여다보다 혼잣말을 했습니다. '이거 여기 두면 나중에 어떻게 되지?' 그 순간이 참 좋았습니다."

좋은 시작 예시 B:
"얼마 전 한 어머니께서 이런 이야기를 전해주셨습니다. '요즘 아이가 밥 먹다가도 갑자기 생각에 잠기더니, 체스에서 배운 거 생각하는 거라고 하더라고요.'"

자연스럽게 담아주세요:
- 선택한 유형의 대화 장면 1~2회 (자연스럽게, 과장 없이)
- 사고력이라는 단어를 앞부분과 마무리에서 각각 다른 문장으로
- 마지막에 따뜻한 수강 문의 유도
""",
    },
    "대회후기": {
        "hashtag_keys": ["대회후기"],
        "guide": """
[대회 후기 — 글쓰기 방향]
대회에 참가한 아이들의 긴장, 집중, 성장의 순간을 생생하게 전합니다.
결과보다 과정과 경험에서 배운 것을 중심으로. 학부모가 읽고 뭉클할 수 있게.

대화 유형 선택:
- [유형 A] 대회 준비 과정의 선생님↔학생 대화
- [유형 B] 대회 후 학부모가 전한 아이의 반응 ("지고 왔는데 또 나가고 싶대요")
- [유형 C] 준비~당일~이후를 선생님·학생·학부모 시선으로 연결

좋은 시작 예시 A:
"대회장에 들어서는 아이의 뒷모습이 생각납니다. 조금 긴장한 어깨, 그래도 단단한 걸음걸이."

좋은 시작 예시 B:
"대회를 마치고 한 어머니께서 연락을 주셨습니다. '지고 왔는데도 풀이 죽지 않고, 어디서 잘못됐는지 생각해보겠다고 하더라고요.'"

자연스럽게 담아주세요:
- 선택한 유형의 대화 장면 1~2회
- 이기고 지는 결과보다, 스스로 결정하고 버텨낸 경험의 가치
- 학부모 대화는 확인되지 않은 수상 결과나 성적 향상을 넣지 않습니다
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
- 대회 일시, 장소, 대상, 참가 방법 등 핵심 정보
- 대회 경험이 아이에게 주는 성장과 사고력 발달
- 참가 문의 유도 마무리
""",
    },
    "신규모집": {
        "hashtag_keys": ["신규모집"],
        "guide": """
[신규 원생 모집 — 글쓰기 방향]
처음 체스를 접하는 학부모의 궁금증에 먼저 답하듯이 씁니다.
학부모 시선이 가장 자연스러운 유형입니다.

대화 유형 선택:
- [유형 A] 체험 수업에 온 아이와 선생님의 첫 만남 장면
- [유형 B] 체험 전 학부모가 선생님에게 먼저 물어보는 대화 ("우리 아이가 산만한데 괜찮을까요?")
- [유형 C] 체험 전 학부모 고민 → 체험 중 아이 반응 → 체험 후 학부모 이야기 흐름

좋은 시작 예시 A:
"체스, 어렵지 않을까요? 아이들이 처음 체스판 앞에 앉을 때 저도 똑같이 걱정했습니다."

좋은 시작 예시 B:
"한 어머니께서 처음 상담 오셨을 때 이런 말씀을 하셨습니다. '집중력이 워낙 짧아서 체스 같은 게 맞을까 싶어서요.' 그 이야기가 오히려 저를 기대하게 했습니다."

자연스럽게 담아주세요:
- 처음 시작하는 아이도 괜찮다는 안심
- 학부모의 현실적인 고민에 차분하게 답하는 선생님
- 유아교육 전문가의 맞춤 수업 방식
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
- 신청 방법과 기간, 문의처로 마무리
""",
    },
    "자격증": {
        "hashtag_keys": ["자격증"],
        "guide": """
[자격증/급수 과정 — 글쓰기 방향]
체스 자격증이나 급수 시험이 아이에게 어떤 의미인지를 중심으로 씁니다.

대화 유형 선택:
- [유형 A] 급수 시험을 준비하는 아이와 선생님의 대화
- [유형 B] 급수증을 받은 후 학부모가 전한 이야기 ("받아들고 자기 방에 붙여두더라고요")

좋은 시작 예시:
"급수증을 받아든 아이의 표정이 있습니다. 이긴 게 아닌데도 환하게 웃는 그 얼굴."

자연스럽게 담아주세요:
- 선택한 유형의 대화 장면 1회
- 자격증/급수가 아이에게 주는 성취감과 자신감
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
- 대국·분석·친선전 등의 활동
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
- 교육부가 강조하는 창의적 사고 역량이 체스를 통해 자연스럽게 길러진다는 점을 강조하세요.
""",
    "초등 고학년 (4~6학년)": """
대상이 초등 고학년(4~6학년)입니다.
- 전략적 사고, 수 읽기, 집중력이 이 나이에 급격히 발전한다는 점
- 대회 출전, 급수 취득 등 실질적인 성취 목표를 가질 수 있다는 점
- 자기주도학습 역량과 자기관리 역량으로 연결되는 경험을 강조하세요.
""",
    "초등 전체": """
대상이 초등학생 전체입니다.
- 저학년은 기초 집중력, 고학년은 전략과 대회 도전으로 각자의 속도로 성장한다는 점
- 사고력과 자기주도학습 역량이 학교생활 전반에 도움이 된다는 점을 강조하세요.
""",
    "유아·초등 전체": """
대상이 유아부터 초등학생까지 전체입니다.
- 나이에 상관없이 각자의 눈높이에 맞는 맞춤 수업이 이루어진다는 점
- 유아는 놀이로, 초등은 전략으로 — 같은 체스판이지만 배우는 깊이가 다르다는 점
""",
    "중학생": """
대상이 중학생입니다.
- 체스가 수능에도 연결되는 논리력·집중력·판단력 훈련이라는 점
- 대회 성적, FIDE 레이팅, 자격증 취득 등 구체적인 목표를 향해 성장하는 과정
""",
    "고등학생": """
대상이 고등학생입니다.
- 입시와 수능에서 필요한 비판적 사고, 문제 분석 능력과 직결된다는 점
- FIDE 공인 타이틀(CM, FM 등) 취득은 대외 활동 실적으로도 가치가 있다는 점
""",
    "중·고등학생": """
대상이 중·고등학생입니다.
- 체스가 논리력·집중력·자기분석력을 기르는 최적의 훈련임을 강조
- 입시와 수능 사고력에 실질적으로 연결되는 경험
""",
    "청소년 (초~고)": """
대상이 청소년 전체입니다.
- 초등은 사고력의 씨앗, 중등은 전략의 뿌리, 고등은 판단력의 열매
- FIDE 대회, 급수 취득, 타이틀 도전까지 단계별 성장 경로가 있다는 점을 강조하세요.
""",
    "성인": """
대상이 성인입니다.
- 체스는 나이에 상관없이 시작할 수 있고, 두뇌 활성화·스트레스 해소 효과
- FIDE 공인 대회 출전, 레이팅 취득 등 나만의 목표를 가질 수 있다는 점
""",
    "연령 무관 (오픈)": """
대상이 연령 무관 오픈 대회/행사입니다.
- 초등학생부터 성인까지 같은 대회에서 실력으로 겨루는 특별한 경험
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

def build_chess_term_section(lesson: str) -> str:
    """수업 내용에서 체스 용어를 감지해 프롬프트용 설명 섹션 생성"""
    terms = get_chess_term_explanation(lesson)
    if not terms:
        return ""
    lines = ["[체스 전문용어 설명 — 본문에 자연스럽게 녹여주세요]"]
    for t in terms[:2]:  # 최대 2개
        lines.append(f"""
▶ {t['name']}
  개념: {t['concept']}
  작동원리: {t['how']}
  활용법: {t['use']}
  주의점: {t['caution']}
  쉬운설명: {t['easy']}
  사고력연결: {t['thinking']}
""")
    lines.append("위 설명을 학생과 선생님의 대화 형식으로 자연스럽게 녹여주세요. '(설명)'이라는 단어는 최종 글에 표시하지 마세요.")
    return "\n".join(lines)

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
    chess_term_section = build_chess_term_section(lesson)
    area_desc = BRANCH_AREA.get(branch, "김포")

    system_prompt = (
        "당신은 생각키움연구소의 원장입니다. "
        "유아교육 전문가 자격을 갖춘 10년 경력의 사고력체스 교육자로, "
        "학부모·학생·성인 독자에게 편지를 쓰듯 따뜻하고 진솔하게 씁니다. "
        "광고 문구 느낌 없이, 수업 현장의 실제 경험을 바탕으로 자연스럽게 씁니다. "
        "생각키움연구소의 핵심은 '단순히 체스 기술이 아닌, "
        "스스로 생각하고 문제를 해결하는 사고력을 키우는 것'입니다. "
        "\n\n"
        "[대화 유형 선택 원칙]\n"
        "글의 주제와 분위기에 따라 다음 4가지 대화 유형 중 가장 자연스러운 것을 선택하세요:\n"
        "A) 학생↔선생님 대화 중심: 수업 현장에서 아이가 고민하고 발견하는 장면\n"
        "B) 학부모↔선생님 대화 중심: 아이의 변화를 관찰한 학부모가 선생님에게 전하는 이야기\n"
        "C) 학생·학부모·선생님 대화 혼합: 두 유형을 자연스럽게 연결\n"
        "D) 대화 + 체스 전문 설명 결합: 대화 장면 속에서 개념을 풀어 설명\n"
        "모든 글에 학부모 대화를 넣지는 않습니다. 수업 후기나 신규 모집처럼 "
        "학부모 시선이 자연스러운 유형에서만 B·C 유형을 활용합니다.\n\n"
        "[학부모 대화 작성 원칙]\n"
        "학부모 대화를 쓸 때는 다음 원칙을 지키세요:\n"
        "① 자동 생성 예시 대화에는 실명, 확인되지 않은 성적 향상·수상 결과를 부여하지 않습니다\n"
        "② 과장된 칭찬('완전히 달라졌어요', '천재가 됐어요')과 반복적인 감탄사는 피합니다\n"
        "③ 학부모가 관찰한 구체적인 행동 변화(집에서 체스 이야기, 한 수 전 생각하는 모습)로 씁니다\n"
        "④ 선생님은 교육적 의도와 방향을 차분하게 설명하는 역할입니다\n"
        "⑤ 사용자가 실제 학부모 후기를 직접 입력한 경우에만 '실제 후기'로 표시합니다\n\n"
        "[학부모 대화 예시 소재]\n"
        "• 아이가 집에서도 체스 이야기를 자주 한다\n"
        "• 한 수를 두기 전에 잠깐 생각하는 모습이 보인다\n"
        "• 어려운 문제를 쉽게 포기하지 않고 버티는 태도가 생겼다\n"
        "• 스스로 판단하고 선택하려는 모습이 느껴진다\n"
        "• 대회 준비 과정에서 긴장하면서도 성장하는 모습\n"
        "• 수업 방식이 주입식이 아닌 스스로 생각하게 한다는 점에 만족\n\n"
        "[학생 대화 작성 원칙]\n"
        "학생과 선생님의 대화 장면을 생생하게 표현하되, "
        "확인되지 않은 구체적 발언을 사실처럼 단정하지 않습니다. "
        "학생이 고민하고 질문하며 스스로 답을 발견하는 과정을 자연스럽게 담습니다.\n\n"
        "네이버 블로그 SEO 원칙: "
        "① 한 게시물에 핵심 검색어 1개 + 보조 검색어 1~2개만 사용 "
        "② 여러 지역명을 한 글에 혼합하지 말 것 "
        "③ 같은 키워드 3번 이상 반복 금지 "
        "④ 실제 수업 내용 외 없었던 사실을 만들어내지 말 것 "
        "⑤ 과장된 교육 효과 표현 금지"
    )

    target_section = f"\n[대상별 강조점]\n{target_ctx}" if target_ctx else ""
    title_keyword = kws[0] if kws else "김포체스학원"
    secondary_kws = ", ".join(kws[1:3]) if len(kws) > 1 else ""

    # 대화 유형 힌트 생성 (수업 내용에 학부모 언급이 있으면 B/C 유형 우선 안내)
    parent_hint = ""
    lesson_lower = (lesson or "").lower()
    has_parent_mention = any(w in lesson_lower for w in ["학부모", "어머니", "아버지", "부모", "엄마", "아빠", "보호자"])
    if has_parent_mention:
        parent_hint = "\n[대화 유형 힌트] 사용자가 학부모 관련 내용을 언급했습니다. 유형 B 또는 C를 우선 활용하세요.\n"
    elif content_type in ("대회후기", "자격증"):
        parent_hint = "\n[대화 유형 힌트] 이 콘텐츠 유형은 학부모 시선 대화(유형 B)를 자연스럽게 1회 포함해도 좋습니다.\n"

    prompt = f"""
오늘 쓸 글의 소재입니다:
- 지점: {branch} ({area_desc})
- 콘텐츠 유형: {content_type}
- 대상: {target}
- 내용/메모: {lesson}

[SEO 키워드 활용]
- 제목에 반드시 포함: "{title_keyword}"
- 본문 보조 키워드 (1~2개만, 억지로 넣지 말 것): {secondary_kws}
- 지역명 반복 금지, 한 글에 여러 지역명 혼합 금지
- 제목은 30자 이내

{guide["guide"]}
{parent_hint}
{chess_term_section}
{target_section}

위 내용을 바탕으로 네이버 검색 상위 노출에 유리하면서도 읽기 편하고 자연스러운 글을 써주세요.
독자가 끝까지 읽고 싶어지는 글, 학원 문의로 이어지는 글이 목표입니다.

출력 형식 (구분자를 정확히 사용):

===제목후보===
1. [지역검색어형] {title_keyword} 포함, 30자 이내
2. [학부모궁금증형] 학부모가 검색할 질문 형태, 30자 이내
3. [수업스토리형] 실제 수업 장면이 담긴 제목, 30자 이내
추천: 위 1~3번 중 하나 선택 + 한 줄 선정 이유

===블로그본문===
**🔹 소제목** 형식으로 소제목 4~5개, 전체 1200~1500자.
첫 단락: 학부모가 검색하는 목적에 맞는 도입 + 핵심 키워드 자연스럽게.
중간: 학생↔선생님 자연스러운 대화 장면 1~2회 포함.
마지막 단락: 핵심 키워드 한 번 더 + 따뜻한 상담 안내.

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
