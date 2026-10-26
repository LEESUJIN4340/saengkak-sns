"""Private photo studio. Originals stay in private S3-compatible storage, never /outputs."""
import asyncio, io, os, secrets, uuid, hashlib, time
from datetime import datetime, timezone
from pathlib import PurePosixPath
import boto3
from botocore.config import Config
from fastapi import APIRouter, Request, Response, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from PIL import Image, UnidentifiedImageError

router=APIRouter()
BRANCHES={'구래점','사우점','장기점'}
MAX_BYTES=8*1024*1024
COOKIE='saenggak_studio'
# Prevent simultaneous paid image calls within this single-worker service.
_GENERATION_LOCK=asyncio.Lock()
_RECENT_REQUESTS={}
_REQUEST_TTL=600
def configured():
    return all(os.getenv(x) for x in ('STUDIO_PASSWORD','STUDIO_SESSION_SECRET','STUDIO_BUCKET','STUDIO_S3_ENDPOINT','STUDIO_S3_ACCESS_KEY','STUDIO_S3_SECRET_KEY'))
def require_config():
    if not configured(): raise HTTPException(503,'사진 스튜디오의 비공개 저장소와 로그인 설정이 필요합니다.')
def signer():
    return URLSafeTimedSerializer(os.environ['STUDIO_SESSION_SECRET'],salt='photo-studio-v1')
def authorized(request):
    require_config()
    token=request.cookies.get(COOKIE,'')
    try:
        return signer().loads(token,max_age=12*3600)=='owner'
    except (BadSignature,SignatureExpired): return False
def guard(request):
    if not authorized(request): raise HTTPException(401,'로그인이 필요합니다.')
def store():
    require_config()
    return boto3.client('s3',endpoint_url=os.environ['STUDIO_S3_ENDPOINT'],
        aws_access_key_id=os.environ['STUDIO_S3_ACCESS_KEY'],
        aws_secret_access_key=os.environ['STUDIO_S3_SECRET_KEY'],
        region_name=os.getenv('STUDIO_S3_REGION','auto'),
        config=Config(signature_version='s3v4'))
def bucket(): return os.environ['STUDIO_BUCKET']
def safe_key(key):
    if not key or len(key)>250 or not key.startswith('studio/') or '..' in PurePosixPath(key).parts: raise HTTPException(422,'파일 경로가 올바르지 않습니다.')
    return key
def get_bytes(key):
    return store().get_object(Bucket=bucket(),Key=safe_key(key))['Body'].read()
def put_bytes(key,data,mime):
    store().put_object(Bucket=bucket(),Key=key,Body=data,ContentType=mime,CacheControl='private, no-store')
def validate_image(data):
    if len(data)>MAX_BYTES or len(data)<100: raise HTTPException(413,'사진은 8MB 이하만 가능합니다.')
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ('JPEG','PNG','WEBP'): raise ValueError()
            if im.width*im.height>28_000_000: raise ValueError()
            im.load()
            output=io.BytesIO()
            im.convert('RGB').save(output,format='JPEG',quality=90)
            return output.getvalue()
    except (UnidentifiedImageError,ValueError,OSError,Image.DecompressionBombError):
        raise HTTPException(422,'올바른 JPG, PNG 또는 WEBP 사진만 등록해 주세요.')
def no_cache(response):
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response
@router.get('/studio',response_class=HTMLResponse)
def studio_page():
    from pathlib import Path
    return no_cache(HTMLResponse((Path(__file__).resolve().parent/'static/studio.html').read_text(encoding='utf-8')))
@router.get('/api/studio/status')
def status(request:Request):
    return {'configured':configured(),'logged_in':authorized(request) if configured() else False}
@router.post('/api/studio/login')
def login(request:Request,password:str=Form(...)):
    require_config()
    expected=os.environ['STUDIO_PASSWORD']
    if len(password)>200 or not secrets.compare_digest(hashlib.sha256(password.encode()).digest(),hashlib.sha256(expected.encode()).digest()):
        raise HTTPException(401,'비밀번호가 일치하지 않습니다.')
    response=JSONResponse({'ok':True})
    response.set_cookie(COOKIE,signer().dumps('owner'),max_age=12*3600,httponly=True,secure=True,samesite='strict',path='/')
    return no_cache(response)
@router.post('/api/studio/logout')
def logout():
    response=JSONResponse({'ok':True})
    response.delete_cookie(COOKIE,path='/',secure=True,samesite='strict')
    return no_cache(response)
@router.post('/api/studio/upload')
async def upload(request:Request,branch:str=Form(...),kind:str=Form(...),file:UploadFile=File(...)):
    guard(request)
    if branch not in BRANCHES or kind not in ('interior','owner','pieces'): raise HTTPException(422,'지점 또는 사진 유형이 올바르지 않습니다.')
    data=await file.read(MAX_BYTES+1)
    photo=validate_image(data)
    key=f'studio/original/{branch}/{kind}/{uuid.uuid4().hex}.jpg'
    await asyncio.to_thread(put_bytes,key,photo,'image/jpeg')
    return {'key':key,'branch':branch,'kind':kind}
@router.get('/api/studio/list')
async def list_photos(request:Request,branch:str):
    guard(request)
    if branch not in BRANCHES: raise HTTPException(422,'지점을 선택해 주세요.')
    def load():
        pages=store().get_paginator('list_objects_v2').paginate(Bucket=bucket(),Prefix=f'studio/original/{branch}/')
        return [{'key':item['Key'],'size':item['Size']} for page in pages for item in page.get('Contents',[])][:150]
    return {'items':await asyncio.to_thread(load)}
@router.get('/api/studio/generated')
async def generated_list(request:Request,branch:str):
    guard(request)
    if branch not in BRANCHES: raise HTTPException(422,'지점을 선택해 주세요.')
    def load():
        pages=store().get_paginator('list_objects_v2').paginate(Bucket=bucket(),Prefix=f'studio/generated/{branch}/')
        return [{'key':item['Key'],'size':item['Size']} for page in pages for item in page.get('Contents',[])][:100]
    return {'items':await asyncio.to_thread(load)}
@router.get('/api/studio/file')
async def private_file(request:Request,key:str):
    guard(request)
    if not (key.startswith('studio/original/') or key.startswith('studio/generated/')): raise HTTPException(403,'접근할 수 없는 파일입니다.')
    try: data=await asyncio.to_thread(get_bytes,key)
    except Exception: raise HTTPException(404,'파일을 찾지 못했습니다.')
    return no_cache(StreamingResponse(io.BytesIO(data),media_type='image/png' if key.endswith('.png') else 'image/jpeg'))
@router.delete('/api/studio/file')
async def delete_file(request:Request,key:str):
    guard(request)
    if not (key.startswith('studio/original/') or key.startswith('studio/generated/')): raise HTTPException(403,'접근할 수 없는 파일입니다.')
    await asyncio.to_thread(lambda:store().delete_object(Bucket=bucket(),Key=safe_key(key)))
    return {'ok':True}
@router.post('/api/studio/generate')
async def generate(request:Request,branch:str=Form(...),platform:str=Form(...),body:str=Form(...),reference_key:str=Form(...),owner_key:str=Form(''),pieces_keys:str=Form(''),scene_mode:str=Form('preserve'),activity:str=Form('auto'),request_id:str=Form('')):
    guard(request)
    if branch not in BRANCHES or platform not in ('당근','블로그','인스타그램') or not 10<=len(body)<=3000:
        raise HTTPException(422,'지점·채널·본문을 확인해 주세요.')
    if scene_mode not in ('preserve','students'): raise HTTPException(422,'이미지 제작 방식을 확인해 주세요.')
    if activity not in ('auto','discussion','review','decision','language'): raise HTTPException(422,'수업 장면을 선택해 주세요.')
    prefix=f'studio/original/{branch}/'
    if not reference_key.startswith(prefix+'interior/'): raise HTTPException(422,'해당 지점의 실내 사진을 선택해 주세요.')
    if owner_key and not owner_key.startswith(prefix+'owner/'): raise HTTPException(422,'해당 지점의 원장 사진을 선택해 주세요.')
    piece_keys=[k.strip() for k in pieces_keys.split(',') if k.strip()]
    if len(piece_keys)>5 or len(set(piece_keys))!=len(piece_keys) or any(not k.startswith(prefix+'pieces/') or not k.endswith('.jpg') for k in piece_keys):
        raise HTTPException(422,'체스 기물 참고사진은 같은 지점에서 최대 5장까지 선택해 주세요.')
    if not os.getenv('OPENAI_API_KEY'): raise HTTPException(503,'이미지 생성 API 키가 설정되지 않았습니다.')
    if not request_id or len(request_id)>100 or not all(ch.isalnum() or ch in '-_' for ch in request_id):
        raise HTTPException(422,'이미지 요청 식별자가 올바르지 않습니다. 페이지를 새로고침해 주세요.')
    now=time.monotonic()
    for token,stamp in list(_RECENT_REQUESTS.items()):
        if now-stamp>_REQUEST_TTL: _RECENT_REQUESTS.pop(token,None)
    if request_id in _RECENT_REQUESTS: raise HTTPException(409,'이미 요청한 이미지입니다. 완성 이미지 목록을 확인해 주세요.')
    if _GENERATION_LOCK.locked(): raise HTTPException(429,'이미지 제작이 진행 중입니다. 중복 요청하지 마세요.')
    refs=[await asyncio.to_thread(get_bytes,reference_key)]
    if owner_key and scene_mode == 'students': raise HTTPException(422,'학생 연출 모드에서는 원장 사진을 사용하지 않습니다.')
    if owner_key: refs.append(await asyncio.to_thread(get_bytes,owner_key))
    for piece_key in piece_keys: refs.append(await asyncio.to_thread(get_bytes,piece_key))
    def create():
        from openai import OpenAI
        client=OpenAI(api_key=os.environ['OPENAI_API_KEY'],timeout=180)
        images=[]
        for i,data in enumerate(refs):
            stream=io.BytesIO(data);stream.name=f'reference_{i}.jpg';images.append(stream)
        # First image is the classroom; later piece images are reference-only.
        piece_guidance = ('The last '+str(len(piece_keys))+' input photographs show the REAL chess set used at this academy. '
            'Use them strictly as identity references for the physical pieces and board, not as backgrounds. '
            'Match ivory and black plastic shapes, relative size, matte finish and the plum-and-cream board. '
            'Do not paste a large close-up of pieces into the scene. '
            'Prefer leaving existing photographed boards and pieces untouched. '
            'Do not invent impossible positions or extra pieces. ') if piece_keys else ''
        # The classroom photo is the image to EDIT, not merely an inspiration.
        # Keep the original academy recognisable; never hallucinate a teacher.
        activity_prompts = {'discussion':'Two students face each other over one chessboard and discuss a move together.', 'review':'Two students sit together, one replays a chess move and the other checks the scoresheet.', 'decision':'Two students face each other and attentively play a chess game.', 'language':'Two students point to chess pieces together while practicing vocabulary.'}
        selected = activity if activity != 'auto' else ('review' if '복기' in body else 'language' if '영어' in body or '중국어' in body else 'discussion' if '토론' in body or '의견' in body else 'decision')
        scene_instruction = (
            'Do not add any new people. Retouch the real classroom photograph only, '
            'preserving its original composition and actual occupants.'
            if scene_mode == 'preserve' else
            'Create a clearly staged, fictional promotional illustration based on this REAL room. '
            'Add exactly two fictional Korean elementary-age students at one existing desk, '
            'engaged with each other and the same chessboard. ' + activity_prompts[selected] + ' ' 
            'They should be visibly collaborating, discussing or actively playing, not merely posing. ' 
            'Avoid isolated, bored, upset or sulking expressions and disconnected activities. ' 
            'Children must share attention, eye-lines, and a believable conversational gesture. ' 
            'Do not pose with two fingers pointing to an unrelated paper. ' 
            'They should be thoughtfully '
            'studying chessboards and reviewing moves. Keep the REAL room architecture unchanged. '
            'Do not add any adults or instructors. Do not portray the scene as a documentary photograph.'
        )
        prompt=(scene_instruction + ' ' + piece_guidance + ' '
            'Edit the FIRST provided photograph. It is the actual interior of a Korean chess academy, '
            'and must remain the recognisable main subject of the finished promotional image. '
            'This is PHOTO EDITING, NOT a new imagined classroom or a stock photograph. '
            'Keep the original walls, windows, flooring, shelves, tables, chairs, furniture placement, '
            'perspective, colors and architectural details as close to the source as possible. '
            'Do not replace the room, introduce a different building, or change the academy identity. '
            'Natural professional photography, coherent realistic lighting, sharp details, no artificial gloss. ' 
            'Match the camera height, lens perspective, depth of field, contact shadows and reflections. ' 
            'The dark classroom windows are reflective: any newly inserted pupils should have ' 
            'physically plausible subtle reflections ONLY where geometry allows; do not fabricate ' 
            'mirror-like reflections or change existing window reflections. '
            'The promotion is about chess education, concentration, observation, choice and review. '
            'Never create an adult instructor or celebrity. '
            'If a second portrait is provided, treat it only as an identity reference for an existing '
            'adult in the source photo; never add an adult to the room. '
            'Keep any visible chessboards eight-by-eight with correctly alternating squares and '
            'plausible chess pieces. Preserve the photographed chess pieces instead of redrawing them. ' 
            'If they cannot be preserved, avoid prominent close-ups of distorted pieces. ' 
            'Keep a consistent 8x8 board with one piece per square, correct proportions and ' 
            'clearly distinct kings, queens, rooks, bishops, knights and pawns. ' 
            'No duplicated fingers, malformed hands, garbled papers, text, logos, watermarks, ' 
            'fake signage, or overlays. '
            'Do not imply an AI-created scene is a documentary record of an actual lesson. '
            f'Academy branch: {branch}. Publication channel: {platform}. '
            f'Post theme for atmosphere only (do not invent objects or people): {body[:1200]}.'
        )
        result=client.images.edit(model=os.getenv('OPENAI_IMAGE_MODEL','gpt-image-1'),image=images,
                                  prompt=prompt,size='1024x1024',input_fidelity='high',quality='high')
        import base64
        return base64.b64decode(result.data[0].b64_json)
    try:
        async with _GENERATION_LOCK:
            if request_id in _RECENT_REQUESTS: raise HTTPException(409,'중복 요청입니다. 완성 이미지 목록을 확인해 주세요.')
            _RECENT_REQUESTS[request_id]=time.monotonic()
            generated=await asyncio.to_thread(create)
            key=f'studio/generated/{branch}/{uuid.uuid4().hex}.png'
            await asyncio.to_thread(put_bytes,key,generated,'image/png')
    except HTTPException:
        raise
    except Exception as exc:
        # Do not expose private storage credentials or API error bodies to clients.
        import logging
        logging.getLogger(__name__).exception('Private studio image creation failed')
        raise HTTPException(502,'이미지 제작에 실패했습니다. 서버 로그의 오류 유형과 이미지 모델 설정을 확인해 주세요.') from exc
    return {'key':key,'url':'/api/studio/file?key='+key,'activity':(activity if activity != 'auto' else ('review' if '복기' in body else 'language' if '영어' in body or '중국어' in body else 'decision')),'note':'게시 전에 실제 학원 환경과 일치하는지 검수해 주세요.'}
