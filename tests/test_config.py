"""[리뷰 반영] save_config()의 동시 쓰기/원자성 회귀 테스트.

예전엔 CONFIG_PATH를 곧바로 열어 덮어썼다 - 여러 스레드(background job이 끝나며
add_local()이 save_config()를 부르는 것과, 사용자가 거의 동시에 Local을 추가하는
것 등)가 겹치면 파일이 깨질 수 있었다. 이제는 프로세스 내 락으로 직렬화하고,
임시 파일에 다 쓴 뒤 os.replace()로 원자적으로 바꿔치기한다."""
import json
import shutil
import threading
import unittest
from pathlib import Path

import config as cfgmod


class SaveConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path("/tmp/test_config_suite_" + self.id().split(".")[-1])
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True)
        self._orig_config_path = cfgmod.CONFIG_PATH
        cfgmod.CONFIG_PATH = self.tmp / "config.json"

    def tearDown(self):
        cfgmod.CONFIG_PATH = self._orig_config_path
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_config_writes_atomically_and_leaves_no_tmp_file(self):
        cfg = cfgmod.default_config()
        cfg["masterdb"]["root"] = "/some/path"
        cfgmod.save_config(cfg)

        self.assertTrue(cfgmod.CONFIG_PATH.exists())
        self.assertFalse(cfgmod.CONFIG_PATH.with_suffix(".json.tmp").exists())
        loaded = json.loads(cfgmod.CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(loaded["masterdb"]["root"], "/some/path")

    def test_concurrent_save_config_calls_never_corrupt_the_file(self):
        """[핵심] 여러 스레드가 동시에 save_config()를 불러도, 매 순간 디스크의
        config.json은 항상 완전한(파싱 가능한) JSON이어야 한다 - 두 쓰기가 겹쳐
        절반씩 섞인 깨진 파일이 남으면 안 된다."""
        errors = []
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    text = cfgmod.CONFIG_PATH.read_text(encoding="utf-8")
                    if text:
                        json.loads(text)
                except FileNotFoundError:
                    pass
                except Exception as e:
                    errors.append(e)

        def writer(n):
            for i in range(20):
                cfg = cfgmod.default_config()
                cfg["masterdb"]["root"] = f"/writer{n}/{i}"
                cfgmod.save_config(cfg)

        reader_thread = threading.Thread(target=reader, daemon=True)
        reader_thread.start()
        writers = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
        for t in writers:
            t.start()
        for t in writers:
            t.join(timeout=10)
        stop.set()
        reader_thread.join(timeout=2)

        self.assertEqual(errors, [], f"동시 쓰기 도중 config.json이 깨진 상태로 읽힌 적이 있음: {errors}")


if __name__ == "__main__":
    unittest.main()
