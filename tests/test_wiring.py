"""tests/test_wiring.py
=======================
app.js -> api-client.js -> bridge/api.py 3단 체인의 **이름과 인자 개수**를 정적으로 맞춰본다.

이전 프로젝트(RetroGameManager)에서 이 체인이 어긋나 "버튼은 있는데 아무 일도 안
일어나는" P0가 실제로 났었다(`api.startExportToLocal()`이 app.js에만 있고 아래
두 단계에는 없었음). 거기서는 이 검사가 두 파일로 나뉘어 있었고
(`tests/test_api_wiring.py` + `tests_ui/api-wiring.spec.js`), 후자는 Playwright
러너를 통해서만 돌아 Node가 없으면 아예 실행되지 않았다. 브라우저가 필요 없는
검사였으므로 여기서는 **한 파일로 합치고 Python만으로** 돌린다.

추가로 인자 개수(arity)까지 본다 - 이름만 맞고 인자 수가 어긋나는 호출은
런타임에야 TypeError로 터지는데, 그건 사용자가 그 버튼을 누른 순간이다.
"""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "gui_web" / "app.js"
API_CLIENT_JS = ROOT / "gui_web" / "api-client.js"
API_PY = ROOT / "bridge" / "api.py"
WINDOWS_PY = ROOT / "bridge" / "windows.py"


def strip_js_comments(src: str) -> str:
    """주석 안의 `api.foo()` 예시가 오탐되지 않도록 지운다."""
    return re.sub(r"//.*$", "", re.sub(r"/\*[\s\S]*?\*/", "", src), flags=re.M)


def api_client_methods(src: str) -> dict:
    """`window.api = { ... }` 리터럴에 정의된 메서드 -> 그 본문 문자열."""
    block = re.search(r"window\.api = \{([\s\S]*)\n  \};", src)
    assert block, "api-client.js에서 window.api 객체 리터럴을 못 찾음 - 파일 구조가 바뀌었다"
    body = block.group(1)
    methods = {}
    for m in re.finditer(r"^\s{4}([a-zA-Z_][a-zA-Z0-9_]*):\s*(.*?)(?=^\s{4}[a-zA-Z_][a-zA-Z0-9_]*:|\Z)",
                         body, re.M | re.S):
        methods[m.group(1)] = m.group(2)
    return methods


def python_api_methods() -> dict:
    """창의 js_api가 가진 공개 메서드 -> (필수 인자 수, 전체 인자 수). self 제외.

    실제 js_api는 창마다 붙는 WindowBridge(bridge/windows.py)이고, 그 외 메서드는 Api로 넘긴다.
    그래서 Api 메서드에 WindowBridge에만 있는 창 메서드(window_info 등)를 더한다."""
    out = {}
    for path, name in ((API_PY, "Api"), (ROOT / "bridge/scraper.py", "ScraperBridge"), (ROOT / "bridge/translation.py", "TranslationBridge"), (WINDOWS_PY, "WindowBridge")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        cls = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and n.name == name)
        out.update(_class_methods(cls))
    return out


def _class_methods(cls) -> dict:
    out = {}
    for node in cls.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        args = node.args.args[1:]  # self 제외
        total = len(args) + len(node.args.kwonlyargs)
        required = len(args) - len(node.args.defaults)
        if node.args.vararg:
            total = 99
        out[node.name] = (required, total)
    return out


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.app_js = strip_js_comments(APP_JS.read_text(encoding="utf-8")
            + "\n" + "\n".join((ROOT / "gui_web" / name).read_text(encoding="utf-8")
                for name in ['scraper-ui.js', 'transfer-ui.js', 'translation-ui.js', 'archive-settings-ui.js', 'collection-setup-ui.js']))
        self.client_src = API_CLIENT_JS.read_text(encoding="utf-8")
        self.client = api_client_methods(strip_js_comments(self.client_src))
        self.python = python_api_methods()

    def test_parsers_actually_found_something(self):
        """정규식이 파일 구조와 어긋나 0개를 뽑고도 '통과'하는 사고를 막는다."""
        self.assertGreater(len(self.client), 10)
        self.assertGreater(len(self.python), 10)

    def test_every_app_js_call_exists_in_api_client(self):
        called = {m.group(1) for m in re.finditer(r"\bapi\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", self.app_js)}
        self.assertGreater(len(called), 10)
        missing = sorted(called - set(self.client) - {"isMock"})
        self.assertEqual(missing, [], f"app.js가 부르지만 api-client.js에 없는 메서드: {missing}")

    def test_every_api_client_call_exists_in_python_api(self):
        called = set(re.findall(r'call\(\s*"([a-z0-9_]+)"', strip_js_comments(self.client_src)))
        self.assertGreater(len(called), 10)
        missing = sorted(called - set(self.python))
        self.assertEqual(missing, [], f"api-client.js가 부르지만 bridge/api.py의 Api에 없는 메서드: {missing}")

    def test_argument_counts_match(self):
        """`call("x", a, b)`가 넘기는 인자 수가 Python 시그니처 범위 안인지."""
        problems = []
        for js_name, body in self.client.items():
            m = re.search(r'call\(\s*"([a-z0-9_]+)"\s*(,[\s\S]*)?\)\s*,?\s*$', body.strip())
            if not m:
                continue
            py_name, arg_src = m.group(1), (m.group(2) or "")
            if py_name not in self.python:
                continue  # 위 테스트가 따로 잡는다
            count = _count_top_level_args(arg_src)
            required, total = self.python[py_name]
            if not (required <= count <= total):
                problems.append(f"{js_name} -> {py_name}: JS는 {count}개를 넘기는데 "
                                f"Python은 {required}~{total}개를 받는다")
        self.assertEqual(problems, [], "인자 개수가 어긋난 호출:\n" + "\n".join(problems))

    def test_mock_covers_every_call(self):
        """목업이 실제 호출 이름을 전부 갖고 있어야 한다.

        GUI 테스트(tests_ui/)는 pywebview 없이 목업 위에서 돈다. 목업에 없는 이름은
        `{ok:false}`로 떨어지므로, 빠뜨리면 그 화면은 검증한 것처럼 보이면서 실제로는
        오류 경로만 지나간다 - 즉 목업 커버리지가 곧 GUI 테스트의 유효성이다.
        """
        src = strip_js_comments(self.client_src)
        called = set(re.findall(r'call\(\s*"([a-z0-9_]+)"', src))
        mock_block = re.search(r"const mock = \{([\s\S]*?)\n  \};", src)
        self.assertIsNotNone(mock_block, "api-client.js에서 mock 객체를 못 찾음")
        mocked = set(re.findall(r"^\s{4}([a-z0-9_]+):", mock_block.group(1), re.M))
        missing = sorted(called - mocked)
        self.assertEqual(missing, [], f"목업에 없어서 GUI 테스트가 검증할 수 없는 호출: {missing}")


def _count_top_level_args(arg_src: str) -> int:
    """`, a, b || c, {x: 1}` 형태에서 최상위 콤마로 나뉜 인자 수를 센다."""
    arg_src = arg_src.strip()
    if not arg_src.startswith(","):
        return 0
    depth, count, buf = 0, 0, ""
    for ch in arg_src[1:]:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            count += 1 if buf.strip() else 0
            buf = ""
        else:
            buf += ch
    return count + (1 if buf.strip() else 0)


if __name__ == "__main__":
    unittest.main()
