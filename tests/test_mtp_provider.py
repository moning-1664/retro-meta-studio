"""storage/mtp.py - 경로 해석, 문서 읽기/쓰기, 안전한 교체, 캐시.

기기 없이 검증하기 위해 COM backend 자리에 메모리 트리를 끼운다(app/launch/retroarch.py의
`popen` 주입과 같은 수법) - 그래서 이 파일이 검증하는 것은 **COM 위쪽 전부**다.
실제 WPD 호출(storage/mtp_wpd.py)은 기기가 있어야 확인할 수 있다.
"""

import time
import sys
import unittest

import storage
from storage.mtp import MtpError, MtpProvider, is_mtp_path, join_path, set_provider, split_path
from tests.fixtures import FakeMtpBackend


GAMELIST_REL = "Internal shared storage/ES-DE/gamelists/ps2/gamelist.xml"
GAMELIST = "mtp://R58N30ABCDE/" + GAMELIST_REL


class PathTests(unittest.TestCase):
    def test_recognizes_the_scheme_even_after_Path_mangles_it(self):
        # 앱 곳곳이 경로를 Path()에 태우면 `mtp://a/b`가 `mtp:\a\b`가 된다.
        for text in ("mtp://dev/a/b", "mtp:/dev/a/b", r"mtp:\dev\a\b", "MTP://dev/a"):
            self.assertTrue(is_mtp_path(text), text)
        for text in ("D:\\ES-DE", "\\\\nas\\share", "", None):
            self.assertFalse(is_mtp_path(text))

    def test_split_accepts_both_separators_and_keeps_spaces_in_names(self):
        self.assertEqual(split_path(GAMELIST),
                         ("R58N30ABCDE", ["Internal shared storage", "ES-DE", "gamelists", "ps2", "gamelist.xml"]))
        self.assertEqual(split_path(r"mtp:\dev\Internal shared storage\ES-DE"),
                         ("dev", ["Internal shared storage", "ES-DE"]))

    def test_join_always_produces_the_canonical_form(self):
        self.assertEqual(join_path("dev", ["a", "b"]), "mtp://dev/a/b")
        self.assertEqual(join_path("dev", []), "mtp://dev")

    def test_a_non_mtp_path_is_rejected_loudly(self):
        with self.assertRaises(MtpError):
            split_path("D:\\ES-DE\\gamelist.xml")


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeMtpBackend()
        self.backend.put(GAMELIST_REL, b"<gameList/>")
        self.provider = MtpProvider(self.backend)

    def test_exists_and_stat_walk_the_device_tree(self):
        self.assertTrue(self.provider.exists(GAMELIST))
        st = self.provider.stat(GAMELIST)
        self.assertEqual((st.size, st.is_dir), (len(b"<gameList/>"), False))
        # 세션마다 object_id가 바뀌므로 파일 동일성 판정에는 쓸 수 없다.
        self.assertIsNone(st.file_id)

        self.assertTrue(self.provider.stat("mtp://R58N30ABCDE/Internal shared storage/ES-DE").is_dir)
        self.assertFalse(self.provider.exists("mtp://R58N30ABCDE/Internal shared storage/없는폴더"))
        self.assertIsNone(self.provider.stat("mtp://R58N30ABCDE/Internal shared storage/없는.xml"))

    def test_scandir_lists_storages_at_the_device_root(self):
        names = [e.name for e in self.provider.scandir("mtp://R58N30ABCDE")]
        self.assertEqual(sorted(names), ["Internal shared storage", "SD card"])
        entry = next(e for e in self.provider.scandir("mtp://R58N30ABCDE") if e.name == "SD card")
        self.assertTrue(entry.is_dir)
        self.assertEqual(entry.path, "mtp://R58N30ABCDE/SD card")

    def test_scandir_of_a_file_or_missing_folder_is_empty_not_an_error(self):
        self.assertEqual(self.provider.scandir(GAMELIST), [])
        self.assertEqual(self.provider.scandir("mtp://R58N30ABCDE/없는스토리지"), [])

    def test_read_bytes_returns_the_document(self):
        self.assertEqual(self.provider.read_bytes(GAMELIST), b"<gameList/>")
        self.assertIsNone(self.provider.read_bytes(GAMELIST + ".missing"))
        self.assertIsNone(self.provider.read_bytes("mtp://R58N30ABCDE/Internal shared storage"))

    def test_write_replaces_the_existing_document(self):
        self.assertTrue(self.provider.write_bytes(GAMELIST, b"<gameList>new</gameList>"))
        self.assertEqual(self.provider.read_bytes(GAMELIST), b"<gameList>new</gameList>")

    def test_write_creates_missing_folders_under_an_existing_storage(self):
        path = "mtp://R58N30ABCDE/SD card/ES-DE/gamelists/snes/gamelist.xml"
        self.assertTrue(self.provider.write_bytes(path, b"<gameList/>"))
        self.assertEqual(self.provider.read_bytes(path), b"<gameList/>")

    def test_write_cannot_invent_a_storage(self):
        self.assertFalse(self.provider.write_bytes("mtp://R58N30ABCDE/없는스토리지/a.xml", b"x"))

    def test_a_failed_write_restores_the_original(self):
        """MTP는 덮어쓰기가 없어서 지우고 새로 만든다 - 실패하면 원본을 되돌린다."""
        self.backend.fail_next_creates = 1   # 새로 쓰기만 실패하고 되돌리기는 된다
        self.assertFalse(self.provider.write_bytes(GAMELIST, b"never"))
        self.assertEqual(self.provider.read_bytes(GAMELIST), b"<gameList/>")

    def test_when_even_the_restore_fails_it_says_so_instead_of_pretending(self):
        self.backend.fail_next_creates = 2   # 새로 쓰기도, 되돌리기도 실패
        with self.assertRaises(MtpError) as caught:
            self.provider.write_bytes(GAMELIST, b"never")
        self.assertIn("되돌리지 못했습니다", str(caught.exception))

    def test_paths_are_resolved_case_insensitively_like_the_device_shows_them(self):
        self.assertTrue(self.provider.exists(GAMELIST.replace("ES-DE", "es-de")))

    def test_repeated_lookups_do_not_re_ask_the_device(self):
        self.provider.exists(GAMELIST)
        after_first = self.backend.children_calls
        self.assertGreater(after_first, 0)
        for _ in range(5):
            self.provider.exists(GAMELIST)
        self.assertEqual(self.backend.children_calls, after_first)

    def test_the_cache_does_not_hide_a_write(self):
        self.provider.read_bytes(GAMELIST)
        self.provider.write_bytes(GAMELIST, b"fresh")
        self.assertEqual(self.provider.read_bytes(GAMELIST), b"fresh")

    def test_volume_info_reports_the_storage_and_allows_unknown(self):
        info = self.provider.volume_info(GAMELIST)
        self.assertEqual(info.capacity_bytes, 64 * 1024 ** 3)
        self.assertEqual(info.volume_key, "R58N30ABCDE/Internal shared storage")
        # 용량을 못 읽는 스토리지는 Unknown이다 - 오류가 아니다(스펙 §5).
        unknown = self.provider.volume_info("mtp://R58N30ABCDE/SD card/x.xml")
        self.assertIsNone(unknown.capacity_bytes)

    def test_bulk_copy_is_refused_with_a_reason(self):
        with self.assertRaises(MtpError) as caught:
            self.provider.copy_engine()
        self.assertIn("ADB", str(caught.exception))

    def test_does_not_claim_to_watch_the_device(self):
        self.assertFalse(self.provider.supports_watch)


class RoutingTests(unittest.TestCase):
    """`storage.for_path()`가 유일한 분기점이다 - MTP 경로면 이 Provider가 와야 한다."""

    def setUp(self):
        backend = FakeMtpBackend()
        backend.put(GAMELIST_REL, b"<gameList/>")
        self.provider = MtpProvider(backend)
        set_provider(self.provider)
        self.addCleanup(set_provider, None)

    def test_mtp_paths_route_to_the_mtp_provider(self):
        self.assertIs(storage.for_path(GAMELIST), self.provider)
        self.assertIs(storage.for_path(r"mtp:\R58N30ABCDE\Internal shared storage"), self.provider)

    def test_local_paths_still_route_to_the_local_provider(self):
        self.assertEqual(storage.for_path("D:\\ES-DE").id, "local")

    def test_adapters_read_and_write_documents_through_the_router(self):
        """Adapter는 Provider를 인자로 못 받는 자리가 있어서 경로만으로 라우팅된다 -
        그 경로가 실제로 동작하는지 여기서 확인한다(adapters/base.py의 _provider_for)."""
        from adapters.base import read_document, write_document

        self.assertEqual(read_document(GAMELIST), b"<gameList/>")
        self.assertTrue(write_document(GAMELIST, b"<gameList>written</gameList>"))
        self.assertEqual(read_document(GAMELIST), b"<gameList>written</gameList>")


class ComThreadTests(unittest.TestCase):
    """COM 전용 스레드 - **부르는 쪽이 멈추면 안 된다.**

    실제로 comtypes가 없는 환경에서 첫 호출이 영원히 기다리는 버그가 있었다(스레드가
    import 실패로 죽어서 아무도 응답하지 않았다).
    """

    def test_a_failed_initialization_is_reported_instead_of_hanging(self):
        from storage.mtp_wpd import _ComThread

        def boom():
            raise ImportError("comtypes 없음")

        com = _ComThread(initialize=boom)
        with self.assertRaises(MtpError) as caught:
            com.run(lambda: "never", timeout=1.0)
        self.assertIn("comtypes", str(caught.exception))

    def test_a_non_import_failure_reports_its_real_cause(self):
        """COM 초기화가 실패한 진짜 원인을 알린다. 예전에는 무슨 오류든 "comtypes가 필요합니다"라고
        답해서, 설치돼 있는 사람이 목록이 빈 이유를 알 수 없었다(실사용 피드백)."""
        from storage.mtp_wpd import _ComThread

        def boom():
            raise OSError("RPC_E_CHANGED_MODE 같은 것")

        com = _ComThread(initialize=boom)
        with self.assertRaises(MtpError) as caught:
            com.run(lambda: "never", timeout=1.0)
        self.assertIn("RPC_E_CHANGED_MODE", str(caught.exception))
        self.assertNotIn("pip install", str(caught.exception))

    def test_thread_already_initialized_in_another_mode_is_tolerated(self):
        """`import comtypes`가 스레드를 STA로 초기화해 둔 뒤 MTA 초기화가 RPC_E_CHANGED_MODE로
        거절돼도 실패로 치지 않는다 - COM 호출은 그 스레드 하나에서만 일어난다."""
        from unittest import mock
        import comtypes
        from storage import mtp_wpd

        err = OSError("changed mode")
        err.winerror = -2147417850           # 0x80010106 (부호 있는 32비트)
        with mock.patch.object(comtypes, "CoInitializeEx", side_effect=err):
            mtp_wpd._coinitialize()          # 예외 없이 끝나야 한다

        other = OSError("something else")
        other.winerror = -2147024809         # E_INVALIDARG
        with mock.patch.object(comtypes, "CoInitializeEx", side_effect=other):
            with self.assertRaises(OSError):
                mtp_wpd._coinitialize()

    @unittest.skipUnless(sys.platform == "win32", "Windows 전용")
    def test_raw_enumeration_runs_without_crashing(self):
        """기기가 없어도 vtable 호출이 죽지 않고 목록(빈 것일 수 있다)을 돌려준다."""
        from storage import mtp_wpd
        com = mtp_wpd._ComThread()
        result = com.run(mtp_wpd._raw_enumerate, timeout=30)
        self.assertIsInstance(result, list)

    def test_a_device_that_never_answers_times_out_with_a_readable_reason(self):
        import threading as _threading
        from storage.mtp_wpd import _ComThread

        com = _ComThread(initialize=lambda: None)
        with self.assertRaises(MtpError) as caught:
            com.run(lambda: _threading.Event().wait(30), timeout=0.2)
        self.assertIn("응답하지 않습니다", str(caught.exception))

    def test_normal_calls_run_on_the_com_thread_and_return_values(self):
        from storage.mtp_wpd import _ComThread

        com = _ComThread(initialize=lambda: None)
        self.assertEqual(com.run(lambda: 40 + 2, timeout=5.0), 42)
        # 기기 쪽 오류는 부르는 스레드로 그대로 전달된다.
        def fails():
            raise MtpError("기기 오류")
        with self.assertRaises(MtpError):
            com.run(fails, timeout=5.0)

    def test_all_calls_share_one_thread(self):
        from storage.mtp_wpd import _ComThread
        import threading as _threading

        com = _ComThread(initialize=lambda: None)
        seen = {com.run(lambda: _threading.current_thread().name, timeout=5.0) for _ in range(5)}
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen.pop(), "mtp-com")


class ComThreadRecoveryTests(unittest.TestCase):
    """**응답 없는 호출 하나가 MTP 전체를 영영 막으면 안 된다.**

    기기가 잠들거나 케이블이 흔들리면 COM 호출이 돌아오지 않는다. 부르는 쪽은
    timeout으로 풀려나지만 일하던 스레드는 그 호출 안에 그대로 갇혀 있다. 그 위에
    다음 일감을 쌓으면 뒤에 줄만 서다가 똑같이 timeout이 나고, 기기를 다시 꽂아도
    앱을 껐다 켜기 전에는 MTP가 안 됐다 - 그래서 굳은 스레드는 버리고 새로 세운다.
    """

    def setUp(self):
        import threading as _threading
        self.blocker = _threading.Event()
        self.addCleanup(self.blocker.set)   # 테스트가 끝나면 갇힌 스레드를 풀어 준다

    def _hang(self, com):
        """스레드를 묶어 둔 채 timeout을 한 번 일으킨다."""
        with self.assertRaises(MtpError) as caught:
            com.run(lambda: self.blocker.wait(30), timeout=0.2)
        self.assertIn("응답하지 않습니다", str(caught.exception))

    def test_the_call_after_a_timeout_works_instead_of_queueing_behind_it(self):
        from storage.mtp_wpd import _ComThread

        com = _ComThread(initialize=lambda: None)
        self._hang(com)
        # 고치기 전에는 이 호출이 갇힌 일감 뒤에 줄을 서서 또 timeout이 났다.
        self.assertEqual(com.run(lambda: 42, timeout=5.0), 42)

    def test_a_restart_runs_on_a_different_thread(self):
        from storage.mtp_wpd import _ComThread
        import threading as _threading

        com = _ComThread(initialize=lambda: None)
        before = com.run(lambda: _threading.get_ident(), timeout=5.0)
        self._hang(com)
        after = com.run(lambda: _threading.get_ident(), timeout=5.0)
        self.assertNotEqual(before, after, "굳은 스레드를 그대로 다시 썼다")

    def test_the_old_thread_does_not_steal_jobs_from_the_new_queue(self):
        """갇혔던 스레드가 나중에 풀려도 새 큐를 넘보면 안 된다.

        넘보면 두 스레드가 서로 다른 COM 아파트에서 같은 큐를 나눠 먹게 되는데,
        이 클래스가 있는 이유(아파트 하나로 직렬화) 자체가 무너진다.
        """
        from storage.mtp_wpd import _ComThread
        import threading as _threading

        com = _ComThread(initialize=lambda: None)
        self._hang(com)
        fresh = com.run(lambda: _threading.get_ident(), timeout=5.0)

        self.blocker.set()          # 옛 스레드를 풀어 준다
        idents = {com.run(lambda: _threading.get_ident(), timeout=5.0) for _ in range(8)}
        self.assertEqual(idents, {fresh}, "풀려난 옛 스레드가 새 큐의 일감을 가져갔다")

    def test_many_callers_at_once_still_run_one_at_a_time(self):
        """Browse/Scan/Apply가 겹쳐 MTP를 동시에 부르는 경우(실기 확인 항목 P2).

        COM 아파트 하나로 몰아 직렬화하는 것이 이 클래스의 존재 이유다. 동시에
        들어온 호출이 겹쳐 실행되면 그 전제가 깨진다.
        """
        from storage.mtp_wpd import _ComThread
        import threading as _threading

        com = _ComThread(initialize=lambda: None)
        inside, overlap, results = [], [], []
        guard = _threading.Lock()

        def work(n):
            with guard:
                inside.append(n)
                if len(inside) > 1:
                    overlap.append(tuple(inside))
            time.sleep(0.01)
            with guard:
                inside.remove(n)
            return n

        def caller(n):
            results.append(com.run(lambda: work(n), timeout=10.0))

        threads = [_threading.Thread(target=caller, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)

        self.assertEqual(overlap, [], "두 호출이 동시에 기기를 만졌다")
        self.assertEqual(sorted(results), list(range(12)), "잃어버린 호출이 있다")

    def test_a_hang_does_not_lose_the_calls_queued_behind_it(self):
        """굳은 호출 하나 때문에 뒤따르던 호출이 조용히 사라지면 안 된다 -
        사라지면 화면은 «불러오는 중»에서 영영 멈춘다."""
        from storage.mtp_wpd import _ComThread
        import threading as _threading

        com = _ComThread(initialize=lambda: None)
        self._hang(com)

        errors, done = [], []

        def caller(n):
            try:
                done.append(com.run(lambda: n, timeout=10.0))
            except MtpError as e:   # 실패해도 «답»은 와야 한다 - 매달려 있으면 안 된다
                errors.append(e)

        threads = [_threading.Thread(target=caller, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        self.assertEqual(len(done) + len(errors), 5, "답을 못 받고 매달린 호출이 있다")

    def test_the_backend_asks_to_be_told_when_the_thread_is_replaced(self):
        """배선 확인 - 실제 WpdBackend가 재시작 통지를 받도록 걸어 두었는가."""
        from storage.mtp_wpd import WpdBackend

        backend = WpdBackend()
        self.assertEqual(backend._com._on_restart, backend._forget_com_state)

    def test_the_backend_forgets_com_pointers_when_the_thread_is_replaced(self):
        """열어 둔 기기 포인터는 만든 아파트에 묶여 있다 - 스레드가 바뀌면 버려야 한다.

        이 환경에는 COM이 없어 진짜 초기화가 실패하므로, 통지 배선은 위 테스트가 보고
        여기서는 빈 초기화를 끼워 **버리는 동작**만 본다.
        """
        from storage.mtp_wpd import WpdBackend, _ComThread

        backend = WpdBackend()
        backend._com = _ComThread(initialize=lambda: None,
                                  on_restart=backend._forget_com_state)
        backend._api = object()
        backend._opened = {"dev": object()}
        backend._device_ids = {"KEY": "dev"}

        self._hang(backend._com)
        backend._com.run(lambda: None, timeout=5.0)   # 여기서 스레드를 새로 세운다

        self.assertIsNone(backend._api)
        self.assertEqual(backend._opened, {})
        self.assertEqual(backend._device_ids, {})


class DeviceKeyTests(unittest.TestCase):
    """기기 키는 **재실행해도 같은 값이어야 한다.**

    Collection이 저장하는 경로가 `mtp://<기기키>/...`라, 키가 실행마다 달라지면
    저장해 둔 Collection이 다음 실행에서 엉뚱한 곳을 가리킨다. 일련번호를 주는
    기기는 그 값을 쓰지만, 안 주는 기기는 fallback을 타므로 그쪽을 검증한다.
    """

    DEVICE_ID = r"usb#vid_04e8&pid_6860#7&1a2b&0&2#{guid}"

    def _key(self):
        from storage.mtp_wpd import WpdBackend
        # 기기가 없으니 일련번호 조회가 실패하고 fallback으로 떨어진다.
        return WpdBackend()._device_key(self.DEVICE_ID, "Galaxy S21")

    def test_fallback_key_is_the_same_value_every_run(self):
        # 값을 못 박아 둔다 - 파이썬 내장 hash()는 프로세스마다 시드가 달라(PEP 456)
        # 이 값을 절대 만들어 내지 못한다. 예전 코드는 그 hash()를 썼다.
        self.assertEqual(self._key(), "Galaxy-S21-03814637fe")

    def test_fallback_key_survives_a_different_hash_seed(self):
        import subprocess
        import sys

        code = (
            "from storage.mtp_wpd import WpdBackend\n"
            f"print(WpdBackend()._device_key(r'{self.DEVICE_ID}', 'Galaxy S21'))\n"
        )
        seen = set()
        for seed in ("0", "1", "12345"):
            out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                 text=True, env={"PYTHONHASHSEED": seed, "PATH": ""})
            seen.add(out.stdout.strip())
        self.assertEqual(seen, {"Galaxy-S21-03814637fe"})

    def test_key_has_only_path_safe_characters(self):
        self.assertRegex(self._key(), r"^[A-Za-z0-9._-]+$")


if __name__ == "__main__":
    unittest.main()
