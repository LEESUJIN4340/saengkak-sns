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

    def test_existing_daangn_page(self):
        self.assertEqual(TestClient(app.app).get("/daangn").status_code, 200)

if __name__ == "__main__":
    unittest.main()
