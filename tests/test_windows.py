"""Collection 탭 떼어 내기/붙이기 - 한 프로세스 여러 창(bridge/windows.py)."""

import inspect
import unittest

from bridge.api import Api
from bridge.windows import MAIN_WINDOW, WindowBridge, WindowManager
from tests.fixtures import build_esde_tree, temp_root


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FakeEvents:
    def __init__(self):
        self.closed = FakeEvent()


class FakeWindow:
    def __init__(self, title, detached):
        self.title, self.detached = title, detached
        self.events = FakeEvents()
        self.scripts, self.calls = [], []
        self.destroyed = False

    def evaluate_js(self, script):
        self.scripts.append(script)

    def maximize(self): self.calls.append("maximize")
    def restore(self): self.calls.append("restore")
    def minimize(self): self.calls.append("minimize")

    def destroy(self):
        if self.destroyed:
            return
        self.destroyed = True
        for handler in self.events.closed.handlers:
            handler()


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_windows_")
        root = build_esde_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("Main", "es-de", str(root))["data"]["id"]
        self.windows = []

        def create(title, js_api, detached):
            window = FakeWindow(title, detached)
            self.windows.append(window)
            return window

        self.manager = WindowManager(self.api, create)
        self.main = self.manager.create_main()

    def detach(self):
        self.assertTrue(self.main.open_collection(self.cid)["ok"])
        r = self.main.detach_collection(self.cid)
        self.assertTrue(r["ok"], r.get("error"))
        return self.manager.bridge(r["data"]["windowId"])

    def test_bridge_exposes_api_methods_like_pywebview_sees_them(self):
        exposed = {}
        for name in dir(self.main):
            if name.startswith("_"):
                continue
            attr = getattr(self.main, name)
            if inspect.ismethod(attr) or inspect.isfunction(attr):
                exposed[name] = list(inspect.getfullargspec(attr).args)[1:]
        for name in ("list_collections", "collection_detail", "window_info", "detach_collection",
                     "merge_window", "window_control", "save_app_settings"):
            self.assertIn(name, exposed)
        # 창 전용으로 다시 구현한 메서드도 원래 Api와 같은 모양으로 노출된다
        self.assertEqual(exposed["open_collection"],
                         list(inspect.getfullargspec(self.api.open_collection).args)[1:])
        self.assertNotIn("registry", dir(self.main))   # 내부 객체는 노출하지 않는다
        self.assertTrue(self.main.list_collections()["ok"])

    def test_window_info_and_per_window_controls(self):
        detached = self.detach()
        self.assertEqual(self.main.window_info()["data"], {"id": MAIN_WINDOW, "role": "main", "collectionId": None})
        self.assertEqual(detached.window_info()["data"]["role"], "detached")
        self.assertEqual(detached.window_info()["data"]["collectionId"], self.cid)
        detached.window_control("maximize")
        self.assertEqual(detached._window.calls, ["maximize"])
        self.assertEqual(self.main._window.calls, [])
        self.main.window_control("maximize")   # 최대화 상태도 창마다 따로
        self.assertEqual(self.main._window.calls, ["maximize"])

    def test_a_collection_is_open_in_one_window_only(self):
        detached = self.detach()
        self.assertTrue(detached._window.detached)
        self.assertIn("Main", detached._window.title)
        blocked = self.main.open_collection(self.cid)
        self.assertEqual(blocked["errorKind"], "other_window")
        self.assertTrue(detached.open_collection(self.cid)["ok"])
        self.assertFalse(self.main.delete_collection(self.cid)["ok"])
        # 메인 창이 닫는다고 해도 다른 창의 Collection은 닫지 않는다
        self.main.close_collection(self.cid)
        self.assertIn(self.cid, self.api.workspace.open_ids)

    def test_detached_window_cannot_detach_or_open_others(self):
        detached = self.detach()
        self.assertFalse(detached.detach_collection(self.cid)["ok"])
        self.assertFalse(detached.open_collection("other")["ok"])
        self.assertFalse(self.main.merge_window()["ok"])

    def test_merge_hands_the_collection_back_to_the_main_window(self):
        detached = self.detach()
        detached.open_collection(self.cid)
        self.assertTrue(detached.merge_window()["ok"])
        self.assertTrue(detached._window.destroyed)
        self.assertTrue(any("__rmsAdoptCollection" in s and self.cid in s for s in self.main._window.scripts))
        self.assertIn(self.cid, self.api.workspace.open_ids)   # 합칠 때는 Cache를 닫지 않는다
        self.assertTrue(self.main.open_collection(self.cid)["ok"])

    def test_closing_a_detached_window_closes_its_collection(self):
        detached = self.detach()
        detached.open_collection(self.cid)
        detached.window_control("close")
        self.assertNotIn(self.cid, self.api.workspace.open_ids)
        self.assertIsNone(self.manager.owner(self.cid))
        self.assertTrue(self.main.open_collection(self.cid)["ok"])

    def test_settings_and_collection_changes_reach_other_windows(self):
        detached = self.detach()
        self.assertTrue(detached.save_app_settings({"appearance": {"scale": 110}})["ok"])
        self.assertTrue(any("__rmsSettingsChanged" in s and '"scale": 110' in s for s in self.main._window.scripts))
        self.assertFalse(any("__rmsSettingsChanged" in s for s in detached._window.scripts))
        self.main.rename_collection(self.cid, "새 이름")
        self.assertTrue(any("__rmsCollectionsChanged" in s for s in detached._window.scripts))

    def test_closing_the_main_window_closes_every_window(self):
        detached = self.detach()
        self.main._window.destroy()
        self.assertTrue(detached._window.destroyed)
        self.assertEqual(self.manager.window_ids(), [])


if __name__ == "__main__":
    unittest.main()
