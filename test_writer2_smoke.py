"""Writer 2.0 compatibility smoke tests: no external API calls."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from fastapi.testclient import TestClient
import app

def response(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

class FakeCompletions:
    def __init__(self):
        self.calls = []
    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("response_format"):
            return response('{"pass":true,"issues":[],"fix_instruction":""}')
        branch = "사우점"
        user_prompt = str(kwargs.get("messages", []))
        for candidate in ("사우점", "장기점", "구래점"):
            if "유일한 학원 지점은 생각키움연구소 " + candidate in user_prompt:
                branch = candidate
                break
        return response(
            "===제목후보===\\n김포 사고력 체스 생각키움연구소\\n"
            "===블로그본문===\\n생각키움연구소 " + branch +
            "에서는 기물의 공격과 방어를 비교하고 후보 수를 탐색합니다. "
            + "아이들은 가능한 수를 검토하고 상대의 대응을 예상합니다. " * 12 +
            "\\n===인스타그램===\\n생각키움연구소 " + branch +
            " 사고력 체스 수업\\n===해시태그===\\n#김포체스학원"
        )

class Writer2SmokeTests(unittest.TestCase):
    def test_health(self):
        self.assertEqual(TestClient(app.app).get("/health").status_code, 200)

    def test_three_branches_and_review(self):
        for branch in ("사우점", "장기점", "구래점"):
            with self.subTest(branch=branch):
                fake = FakeCompletions()
                client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
                with patch.object(app, "get_client", return_value=client):
                    result = TestClient(app.app).post("/api/generate", data={
                        "branch": branch, "content_type": "신규모집",
                        "target": "초등학생", "lesson": "기물 교환 판단과 후보 수 비교를 안내합니다."
                    })
                self.assertEqual(result.status_code, 200, result.text[:500])
                payload = result.json()
                self.assertIn(branch, payload["text"])
                self.assertIn("editorial_plan", payload)
                self.assertTrue(any("response_format" in call for call in fake.calls))
                self.assertIn("===블로그본문===", payload["text"])

    def test_editorial_plan_separates_branch_and_target_region(self):
        fake = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
        with patch.object(app, "get_client", return_value=client):
            result = TestClient(app.app).post("/api/generate", data={
                "branch": "사우점", "content_type": "신규모집",
                "target": "초등학생",
                "lesson": "풍무동 학부모 대상. 실제 사우점에서 포크 전술과 복기를 지도합니다."
            })
        self.assertEqual(result.status_code, 200, result.text[:500])
        plan = result.json()["editorial_plan"]
        self.assertIn("사우점(사우동)", plan)
        self.assertIn("풍무동", plan)
        self.assertIn("실제 지점 소재지와 구분", plan)

    def test_generate_review_api_failure_falls_back(self):
        class ReviewOutage(FakeCompletions):
            def create(self, **kwargs):
                if kwargs.get("response_format"):
                    raise RuntimeError("editorial reviewer unavailable")
                return super().create(**kwargs)
        fake = ReviewOutage()
        with patch.object(app, "get_client", return_value=SimpleNamespace(chat=SimpleNamespace(completions=fake))):
            result = TestClient(app.app).post("/api/generate", data={
                "branch": "장기점", "content_type": "신규모집",
                "target": "초등학생", "lesson": "전술 문제와 실전 대국"
            })
        self.assertEqual(result.status_code, 200, result.text[:500])
        self.assertIn("장기점", result.json()["text"])

    def test_daangn_writer2_review(self):
        class DaangnCompletions:
            def __init__(self):
                self.calls = []
            def create(self, **kwargs):
                self.calls.append(kwargs)
                if kwargs.get("response_format") and "검수하세요" in str(kwargs.get("messages")):
                    return response('{"pass":true,"fix_instruction":""}')
                return response('{"title":"구래점 체스 수업","body":"생각키움연구소 구래점에서는 후보 수를 비교하고 복기하는 방법을 소개합니다.","missing_info":[]}')
        fake = DaangnCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
        with patch.object(app, "get_client", return_value=client):
            result = TestClient(app.app).post("/api/daangn-draft", data={
                "branch":"구래점", "post_type":"신규모집", "topic":"후보 수 비교 수업"
            })
        self.assertEqual(result.status_code, 200, result.text[:500])
        self.assertIn("구래점", result.json()["body"])
        self.assertGreaterEqual(len(fake.calls), 2)

    def test_daangn_review_failure_keeps_original(self):
        class FailingReview:
            def __init__(self):
                self.calls = 0
            def create(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return response('{"title":"사우점 체스","body":"생각키움연구소 사우점에서 체스 전술을 안내합니다.","missing_info":[]}')
                raise RuntimeError("review API unavailable")
        fake = FailingReview()
        with patch.object(app, "get_client", return_value=SimpleNamespace(chat=SimpleNamespace(completions=fake))):
            result = TestClient(app.app).post("/api/daangn-draft", data={
                "branch":"사우점","post_type":"신규모집","topic":"전술 수업 안내"
            })
        self.assertEqual(result.status_code, 200, result.text[:500])
        self.assertIn("사우점", result.json()["body"])

    def test_daangn_rejects_wrong_branch(self):
        result = TestClient(app.app).post("/api/daangn-draft", data={
            "branch":"풍무점","post_type":"신규모집","topic":"체스 수업"
        })
        self.assertEqual(result.status_code, 400)

    def test_existing_daangn_page(self):
        self.assertEqual(TestClient(app.app).get("/daangn").status_code, 200)

if __name__ == "__main__":
    unittest.main()
