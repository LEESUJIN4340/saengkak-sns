"""외부 API 과금 없이 계약·지역·오류·이미지 기능을 검증하는 회귀 검사."""
import unittest
from copy import deepcopy
from datetime import datetime
from unittest.mock import patch
from fastapi.testclient import TestClient
import app as module

ARTICLE = {'titles': ['구래동 체스학원 수업 이야기','후보 수를 비교하는 수업','핀과 포크를 배워요'],
           'recommended_index':0, 'recommend_reason':'지역과 수업 주제가 연결됩니다.',
           'body':'구래동 체스학원에서 핀과 포크를 비교했습니다.', 'instagram':'후보 수를 함께 비교해요.',
           'hashtags':['#엉뚱한태그'], 'image_text':'스스로 생각하는 한 수', 'review':['핀과 포크의 개념을 구분했습니다.'], 'missing_info':['실제 주소']}

class AppTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(module.app)
        self.form={'branch':'구래점','content_type':'수업후기','target':'초등 저학년 (1~3학년)','lesson':'핀과 포크 비교'}
    def test_health_and_mobile_ui(self):
        self.assertEqual(self.client.get('/health').status_code,200)
        html=self.client.get('/').text
        for name in ['keyword','intent','profileAddress','sns_branch_profiles','recent_posts']:
            self.assertIn(name,html)
    def test_generation_passes_context_and_preserves_markers(self):
        f={**self.form,'keyword':'마산동 체스학원','branch_profile':'{"phone":"010-0000-0000"}', 'recent_posts':'[{"title":"지난 글","body":"이전 소재"}]'}
        with patch.object(module,'call_model',return_value=deepcopy(ARTICLE)) as ai:
            r=self.client.post('/api/generate',data=f)
        self.assertEqual(r.status_code,200,r.text)
        data=r.json();ctx=ai.call_args.args[1]
        self.assertEqual(ctx['keyword'],'마산동 체스학원')
        self.assertEqual(ctx['recent_posts'][0]['title'],'지난 글')
        self.assertEqual(ctx['profile']['phone'],'010-0000-0000')
        self.assertIn('date_kst',ctx);self.assertIn('chess_terms',ctx)
        self.assertIn('생각키움연구소 구래점',data['article']['body'])
        for t in data['article']['titles']: self.assertIn('생각키움연구소',t)
        self.assertIn('===SEO품질점수===',data['text'])
        self.assertIn('editor_review',data['checks'])
        self.assertNotIn('total',data['checks'])
        self.assertNotIn('#엉뚱한태그',data['article']['hashtags'])
    def test_nearby_mapping(self):
        self.assertIn('풍무동',module.BRANCHES['사우점']['nearby'])
        self.assertIn('운양동',module.BRANCHES['장기점']['nearby'])
        self.assertIn('실제 있는 것처럼 쓰지',module.SYSTEM)
    def test_rejects_bad_input(self):
        for change in [{'branch':'없는점'}, {'lesson':' '}, {'branch_profile':'[]'}, {'recent_posts':'{}'}, {'keyword':'가'*101}]:
            self.assertEqual(self.client.post('/api/generate',data={**self.form,**change}).status_code,422)
    def test_malformed_model_output_rejected(self):
        for result in [[],{}, {**ARTICLE,'titles':[]}, {**ARTICLE,'body':''}]:
            with patch.object(module,'call_model',return_value=result):
                self.assertEqual(self.client.post('/api/generate',data=self.form).status_code,502)
    def test_error_surfaces(self):
        from fastapi import HTTPException
        with patch.object(module,'call_model',side_effect=HTTPException(503,'사용 한도 확인')):
            r=self.client.post('/api/generate',data=self.form)
        self.assertEqual(r.status_code,503);self.assertEqual(r.json()['detail'],'사용 한도 확인')
    def test_single_scene_replan(self):
        scene={k:'내용' for k in ['title','paragraph','educational_meaning','camera_angle','characters','description','prompt','tactical_note']}
        with patch.object(module,'call_model',return_value={'scenes':[scene]}):
            r=self.client.post('/api/plan-images',data={'blog_text':'체스 수업','count':1,'ref_mode':'preserve','classroom_ref':'사진.jpg','gemini_mode':'continuous'})
        self.assertEqual(r.status_code,200,r.text)
        scenes=r.json()['scenes'];self.assertEqual(len(scenes),1)
        self.assertIn('8×8',scenes[0]['prompt']);self.assertIn('직접 첨부',scenes[0]['prompt'])
        self.assertIn('첫 이미지',scenes[0]['prompt'])
        self.assertEqual(scenes[0]['id'],'scene_0')
    def test_scene_count_mismatch_and_invalid_ratio(self):
        with patch.object(module,'call_model',return_value={'scenes':[]}):
            self.assertEqual(self.client.post('/api/plan-images',data={'blog_text':'내용','count':1}).status_code,502)
        self.assertEqual(self.client.post('/api/plan-images',data={'blog_text':'내용','ratio':'bad'}).status_code,422)
    def test_no_unrelated_promotion_tags(self):
        tags=module.build_hashtags('장기점','이벤트','연령 무관 (오픈)','운양동 체스학원','체스 모임 안내')
        self.assertIn('#운양동체스학원',tags)
        self.assertFalse(any('FIDE' in t or '무료' in t or '아이체스' in t for t in tags))
    def test_season_boundaries(self):
        for month,day,allow in [(3,20,True),(3,21,False),(7,20,False),(8,20,False),(8,21,True),(9,10,True),(9,11,False),(10,20,False),(12,20,False)]:
            season=module.get_school_season(datetime(2026,month,day,tzinfo=module.KST))
            self.assertEqual(season['allow_new_semester'],allow)
    def test_suspect_season_is_flagged_without_broken_replacement(self):
        data=deepcopy(ARTICLE);data['body']='새 학기를 맞아 개원 예정입니다.'
        with patch.object(module,'get_kst_now',return_value=datetime(2026,10,20,tzinfo=module.KST)):
            checks=module.check_article(data,'구래동 체스학원','구래점',{},[])
        self.assertTrue(any(x['name']=='날짜·학사 시기' for x in checks['items']))
        self.assertTrue(any(x['name']=='구래점 개원 상태' for x in checks['items']))
    def test_legacy_contract(self):
        with patch.object(module,'call_model',return_value=deepcopy(ARTICLE)):
            r=self.client.post('/generate',data={'content_type':'수업후기','class_topic':'핀 비교','branch':'운양'})
        self.assertEqual(r.status_code,200,r.text);self.assertIn('blog_body',r.json())
    def test_photo_validation(self):
        r=self.client.post('/api/privacy-check',files={'file':('bad.txt',b'bad','text/plain')})
        self.assertEqual(r.status_code,422)

if __name__=='__main__':unittest.main()
