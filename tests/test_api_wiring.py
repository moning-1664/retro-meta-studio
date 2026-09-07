"""
tests/test_api_wiring.py
==========================
[P2 리뷰 반영] gui_web/api-client.js가 RMApi._call("snake_case_name", ...)로 호출하는
모든 이름이 실제 api.py의 Api 클래스에 그 이름의 메서드로 존재하는지 정적으로 확인한다.
이번에 발견된 P0(app.js의 api.startExportToLocal() -> api-client.js에 없음)의
자매 문제(api-client.js는 있는데 Python 쪽이 없는 경우)를 잡기 위한 회귀 테스트다.
tests_ui/api-wiring.spec.js가 app.js<->api-client.js 쪽을 담당하고, 이 파일은
api-client.js<->api.py 쪽을 담당한다 - 둘을 합치면 3단 체인 전체가 커버된다.
"""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ApiWiringTestCase(unittest.TestCase):
    def test_every_call_name_in_api_client_exists_as_an_api_method(self):
        api_client_js = (ROOT / "gui_web" / "api-client.js").read_text(encoding="utf-8")
        called_names = set(re.findall(r'RMApi\._call\(\s*"([a-zA-Z0-9_]+)"', api_client_js))
        self.assertGreater(len(called_names), 10, "정규식이 api-client.js 구조와 어긋나 0개만 뽑힘")

        tree = ast.parse((ROOT / "api.py").read_text(encoding="utf-8"))
        api_class = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "Api")
        defined_methods = {
            n.name for n in api_class.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
        }
        self.assertGreater(len(defined_methods), 10)

        missing = sorted(called_names - defined_methods)
        self.assertEqual(missing, [], f"api-client.js가 호출하지만 api.py의 Api 클래스에 없는 메서드: {missing}")


if __name__ == "__main__":
    unittest.main()
