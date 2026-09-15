"""storage/mtp.py - 경로 해석, 문서 읽기/쓰기, 안전한 교체, 캐시.

기기 없이 검증하기 위해 COM backend 자리에 메모리 트리를 끼운다(app/launch/retroarch.py의
`popen` 주입과 같은 수법) - 그래서 이 파일이 검증하는 것은 **COM 위쪽 전부**다.
실제 WPD 호출(storage/mtp_wpd.py)은 기기가 있어야 확인할 수 있다.
"""

import unittest

import storage
from storage.mtp import (
    MtpBackend, MtpDeviceInfo, MtpError, MtpObject, MtpProvider,
    is_mtp_path, join_path, set_provider, split_path,
)


class FakeBackend(MtpBackend):
    """메모리 트리. node = {"id", "name", "is_dir", "data"|"children"}"""

    def __init__(self):
        self.tree = {
            "id": "DEVICE", "name": "", "is_dir": True, "children": {
                "Internal shared storage": {
                    "id": "s1", "name": "Internal shared storage", "is_dir": True, "children": {
                        "ES-DE": {"id": "o1", "name": "ES-DE", "is_dir": True, "children": {
                            "gamelists": {"id": "o2", "name": "gamelists", "is_dir": True, "children": {
                                "ps2": {"id": "o3", "name": "ps2", "is_dir": True, "children": {
                                    "gamelist.xml": {"id": "o4", "name": "gamelist.xml",
                                                     "is_dir": False, "data": b"<gameList/>"},
                                }},
                            }},
                        }},
                    },
                },
                "SD card": {"id": "s2", "name": "SD card", "is_dir": True, "children": {}},
            },
        }
        self.reads = 0
        self.children_calls = 0
        #: 앞으로 올 create() 호출 중 몇 번을 실패시킬지. 1이면 "새로 쓰기만 실패"(되돌리기는
        #: 성공), 2면 "되돌리기까지 실패"를 만든다.
        self.fail_next_creates = 0
        self._next_id = 100

    # --- 헬퍼 -----------------------------------------------------------
    def _find(self, node, object_id):
        if node.get("id") == object_id:
            return node
        for child in node.get("children", {}).values():
            found = self._find(child, object_id)
            if found:
                return found
        return None

    def _node(self, object_id):
        node = self._find(self.tree, object_id if object_id is not None else "DEVICE")
        if node is None:
            raise MtpError(f"없는 객체: {object_id}")
        return node

    # --- MtpBackend -----------------------------------------------------
    def devices(self):
        return [MtpDeviceInfo(key="R58N30ABCDE", name="Galaxy Test", device_id="\\\\?\\usb#vid")]

    def children(self, device_key, object_id):
        self.children_calls += 1
        node = self._node(object_id)
        return [MtpObject(object_id=c["id"], name=c["name"], is_dir=c["is_dir"],
                          size=len(c.get("data", b"")), mtime_ns=0)
                for c in node.get("children", {}).values()]

    def read(self, device_key, object_id):
        self.reads += 1
        return self._node(object_id)["data"]

    def create(self, device_key, parent_id, name, data):
        if self.fail_next_creates > 0:
            self.fail_next_creates -= 1
            raise MtpError("기기 쓰기 실패")
        parent = self._node(parent_id)
        self._next_id += 1
        new_id = f"n{self._next_id}"
        parent.setdefault("children", {})[name] = {
            "id": new_id, "name": name, "is_dir": False, "data": data}
        return new_id

    def create_folder(self, device_key, parent_id, name):
        parent = self._node(parent_id)
        self._next_id += 1
        new_id = f"d{self._next_id}"
        parent.setdefault("children", {})[name] = {
            "id": new_id, "name": name, "is_dir": True, "children": {}}
        return new_id

    def delete(self, device_key, object_id):
        node = self._node(object_id)
        parent = self._parent_of(self.tree, object_id)
        del parent["children"][node["name"]]

    def _parent_of(self, node, object_id):
        for child in node.get("children", {}).values():
            if child["id"] == object_id:
                return node
            found = self._parent_of(child, object_id)
            if found:
                return found
        return None

    def storage_info(self, device_key, object_id):
        return (64 * 1024 ** 3, 20 * 1024 ** 3) if object_id == "s1" else (None, None)


GAMELIST = "mtp://R58N30ABCDE/Internal shared storage/ES-DE/gamelists/ps2/gamelist.xml"


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
        self.backend = FakeBackend()
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
        self.provider = MtpProvider(FakeBackend())
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


if __name__ == "__main__":
    unittest.main()
