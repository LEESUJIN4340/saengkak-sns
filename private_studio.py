"""Private photo studio. Originals stay in private S3-compatible storage, never /outputs."""
import asyncio, io, os, secrets, uuid, hashlib
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
    if branch not in BRANCHES or kind not in ('interior','owner'): raise HTTPException(422,'지점 또는 사진 유형이 올바르지 않습니다.')
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
async def generate(request:Request,branch:str=Form(...),platform:str=Form(...),body:str=Form(...),reference_key:str=Form(...),owner_key:str=Form('')):
    guard(request)
    if branch not in BRANCHES or platform not in ('당근','블로그','인스타그램') or not 10<=len(body)<=3000:
        raise HTTPException(422,'지점·채널·본문을 확인해 주세요.')
    prefix=f'studio/original/{branch}/'
    if not reference_key.startswith(prefix+'interior/'): raise HTTPException(422,'해당 지점의 실내 사진을 선택해 주세요.')
    if owner_key and not owner_key.startswith(prefix+'owner/'): raise HTTPException(422,'해당 지점의 원장 사진을 선택해 주세요.')
    if not os.getenv('OPENAI_API_KEY'): raise HTTPException(503,'이미지 생성 API 키가 설정되지 않았습니다.')
    refs=[await asyncio.to_thread(get_bytes,reference_key)]
    if owner_key: refs.append(await asyncio.to_thread(get_bytes,owner_key))
    def create():
        from openai import OpenAI
        client=OpenAI(api_key=os.environ['OPENAI_API_KEY'],timeout=180)
        images=[]
        for i,data in enumerate(refs):
            stream=io.BytesIO(data);stream.name=f'reference_{i}.jpg';images.append(stream)
        prompt=('Create a photorealistic, natural-looking promotional illustration for a Korean chess academy. '
                'Preserve the reference classroom layout and furniture closely. If a portrait is provided, '
                'use it as reference for the adult instructor only; do not invent identifiable real students. '
                'Use chess pieces on a credible 8x8 board. No text, logos, labels or watermarks. '
                'Do not imply a fabricated scene is a documentary photograph. '
                f'Branch: {branch}. Channel: {platform}. Content theme: {body[:1400]}.')
        result=client.images.edit(model=os.getenv('OPENAI_IMAGE_MODEL','gpt-image-1'),image=images,prompt=prompt,size='1024x1024')
        import base64
        return base64.b64decode(result.data[0].b64_json)
    try:
        generated=await asyncio.to_thread(create)
        key=f'studio/generated/{branch}/{uuid.uuid4().hex}.png'
        await asyncio.to_thread(put_bytes,key,generated,'image/png')
    except Exception:
        raise HTTPException(502,'이미지 생성 또는 비공개 저장에 실패했습니다. API 설정과 저장소를 확인해 주세요.')
    return {'key':key,'url':'/api/studio/file?key='+key,'note':'게시 전에 실제 학원 환경과 일치하는지 검수해 주세요.'}
