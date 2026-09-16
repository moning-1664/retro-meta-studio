"""로그 파일이 실제로 생기는지.

예전에는 `app/paths.py`가 `logs/` 폴더를 만들어 두기만 하고 **핸들러를 아무도
붙이지 않았다** - 코드 곳곳의 `log.info(...)`가 어디에도 기록되지 않았고, 기기가
안 잡힌다는 제보를 받고도 볼 로그가 없었다(실사용 피드백 - "로그 자체가 남은 게
없다"). 폴더만 있고 파일이 안 생기는 상태를 테스트로 막는다.
"""

import importlib
import logging
import tempfile
import unittest
from pathlib import Path


class LoggingSetupTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_log_"))
        self.root = logging.getLogger()
        self.before = list(self.root.handlers)
        self.level = self.root.level
        self.addCleanup(self._restore)

    def _restore(self):
        for handler in list(self.root.handlers):
            if handler not in self.before:
                handler.close()
                self.root.removeHandler(handler)
        self.root.setLevel(self.level)

    def _paths_module(self):
        """LOGS_DIR을 임시 폴더로 바꾼 paths 모듈."""
        from app import paths
        importlib.reload(paths)
        paths.LOGS_DIR = self.dir / "logs"
        paths.DB_DIR = self.dir / "db"
        paths.CACHE_DIR = self.dir / "db" / "cache"
        paths.CLIPBOARD_DIR = self.dir / "clipboard"
        return paths

    def test_setup_writes_log_records_to_a_file(self):
        paths = self._paths_module()
        paths.setup_logging()
        logging.getLogger("tests.sample").info("테스트 기록 %s", 42)
        for handler in self.root.handlers:
            handler.flush()

        log_file = paths.LOGS_DIR / "retrometa.log"
        self.assertTrue(log_file.exists(), "로그 파일이 만들어지지 않았다")
        text = log_file.read_text(encoding="utf-8")
        self.assertIn("테스트 기록 42", text)
        self.assertIn("tests.sample", text)

    def test_calling_twice_does_not_stack_handlers(self):
        """창을 여러 개 열어도 같은 줄이 두 번 적히면 안 된다."""
        paths = self._paths_module()
        paths.setup_logging()
        paths.setup_logging()
        ours = [h for h in self.root.handlers if getattr(h, "_retrometa", False)]
        self.assertEqual(len(ours), 1)


if __name__ == "__main__":
    unittest.main()
