"""
bridge/windows.py
==================
Collection 탭을 새 창으로 떼어 내고 다시 붙이기(사용자 결정 - Collection 탭만).

한 프로세스, 여러 창이다. Registry·Cache·Plan·작업은 `Api` 하나를 모든 창이 함께 쓰고, 창마다
다른 것(창 핸들, 최대화 상태, 어떤 Collection을 맡았는지)만 `WindowBridge`가 따로 들고 있다.
pywebview의 `js_api`는 창마다 하나씩 붙으므로 창마다 `WindowBridge`를 하나씩 준다.

규칙:
- 메인 창은 Archive와 여러 Collection 탭을 가진다. 떼어 낸 창은 **Collection 하나만** 가진다.
- 한 Collection은 **한 창에서만** 열린다. 같은 Cache를 두 창이 따로 고치면 화면이 서로 어긋난다.
- Settings를 바꾸면 다른 창에도 알린다. Collection 목록(이름 변경/제거)도 알린다.
- 떼어 낸 창을 닫으면 그 Collection도 닫힌다(Cache와 파일은 그대로 - §2.2). 메인 창을 닫으면
  앱이 끝나므로 다른 창도 모두 닫는다.
"""

from __future__ import annotations

import json
import logging
import threading

from bridge.api import Api, err, guarded, ok

log = logging.getLogger(__name__)

MAIN_WINDOW = "main"
ROLE_MAIN = "main"
ROLE_DETACHED = "detached"


class WindowBridge:
    """창 하나의 `js_api`. 창마다 달라야 하는 메서드만 여기서 구현하고 나머지는 `Api`로 넘긴다.

    pywebview는 `dir(js_api)`로 노출할 함수를 찾는다(webview/util.py `get_functions`) - 그래서
    `__getattr__`만으로는 부족하고 `__dir__`도 `Api`의 공개 메서드를 돌려줘야 한다. `registry`
    같은 속성은 목록에서 뺀다 - pywebview가 객체 속성 안까지 훑어 내려가 내부를 노출한다.
    """

    #: `Api`에 있는 창 메서드는 `self._window`/`self._maximized`만 쓴다. 함수를 그대로 가져와
    #: 이 객체에 묶으면 각 창이 자기 창을 조작한다.
    window_control = Api.window_control
    window_resize = Api.window_resize
    window_set_bounds = Api.window_set_bounds
    pick_file = Api.pick_file
    pick_folder = Api.pick_folder

    def __init__(self, api, manager, window_id, collection_id=None):
        self._api = api
        self._manager = manager
        self._window_id = window_id
        self._collection_id = collection_id
        self._window = None
        self._maximized = False

    # --- 노출 -----------------------------------------------------------
    def __dir__(self):
        names = {n for n in dir(type(self)) if not n.startswith("_")}
        names.update(n for n in dir(type(self._api))
                     if not n.startswith("_") and callable(getattr(type(self._api), n, None)))
        return sorted(names)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._api, name)

    @property
    def role(self):
        return ROLE_MAIN if self._window_id == MAIN_WINDOW else ROLE_DETACHED

    # --- 창 정보 / 떼기 / 붙이기 ------------------------------------------
    @guarded
    def window_info(self):
        return ok({"id": self._window_id, "role": self.role, "collectionId": self._collection_id})

    @guarded
    def detach_collection(self, collection_id):
        """메인 창의 Collection 탭을 새 창으로 옮긴다. Collection은 닫지 않고 맡은 창만 바꾼다."""
        if self.role != ROLE_MAIN:
            return err("떼어 낸 창에서는 다시 떼어 낼 수 없습니다.")
        if self._api.registry.get_collection(collection_id) is None:
            return err("Collection을 찾을 수 없습니다.")
        return ok({"windowId": self._manager.detach(self._window_id, collection_id)})

    @guarded
    def merge_window(self):
        """떼어 낸 창의 Collection을 메인 창 탭으로 돌려보내고 이 창을 닫는다."""
        if self.role != ROLE_DETACHED:
            return err("메인 창은 합칠 대상이 없습니다.")
        self._manager.merge(self._window_id)
        return ok(True)

    # --- 공유 상태를 건드리는 호출: 소유권 확인·다른 창에 알림 --------------
    @guarded
    def open_collection(self, collection_id):
        if self.role == ROLE_DETACHED and collection_id != self._collection_id:
            return err("떼어 낸 창에는 Collection을 하나만 열 수 있습니다.")
        if not self._manager.claim(self._window_id, collection_id):
            return {"ok": False, "error": "이 Collection은 다른 창에서 열려 있습니다.", "errorKind": "other_window"}
        result = self._api.open_collection(collection_id)
        if not result.get("ok"):
            self._manager.release(self._window_id, collection_id)
        return result

    @guarded
    def close_collection(self, collection_id):
        if self._manager.owner(collection_id) not in (None, self._window_id):
            return ok(True)   # 다른 창이 맡은 Collection - 그 창의 화면을 깨지 않는다
        self._manager.release(self._window_id, collection_id)
        return self._api.close_collection(collection_id)

    @guarded
    def save_app_settings(self, patch):
        result = self._api.save_app_settings(patch)
        if result.get("ok"):
            self._manager.broadcast(self._window_id, "__rmsSettingsChanged", result["data"])
        return result

    @guarded
    def rename_collection(self, collection_id, name):
        result = self._api.rename_collection(collection_id, name)
        if result.get("ok"):
            self._manager.broadcast(self._window_id, "__rmsCollectionsChanged", None)
        return result

    @guarded
    def delete_collection(self, collection_id):
        owner = self._manager.owner(collection_id)
        if owner not in (None, self._window_id):
            return err("다른 창에서 열려 있는 Collection은 제거할 수 없습니다. 그 창을 먼저 닫아주세요.")
        self._manager.release(self._window_id, collection_id)
        result = self._api.delete_collection(collection_id)
        if result.get("ok"):
            self._manager.broadcast(self._window_id, "__rmsCollectionsChanged", None)
        return result


class WindowManager:
    """창 목록과 Collection 소유권. `create_window(title, js_api, detached)`는 main.py가 준다
    (테스트는 가짜 창을 만든다)."""

    def __init__(self, api, create_window):
        self.api = api
        self._create_window = create_window
        self._lock = threading.RLock()
        self._bridges: dict[str, WindowBridge] = {}
        self._owners: dict[str, str] = {}
        self._seq = 0

    # --- 창 -------------------------------------------------------------
    def create_main(self):
        bridge = WindowBridge(self.api, self, MAIN_WINDOW)
        window = self._create_window("RetroMeta Studio", bridge, False)
        self._attach(bridge, window)
        self.api._window = window   # 창 핸들을 직접 찾는 기존 경로 호환
        return bridge

    def _attach(self, bridge, window):
        bridge._window = window
        with self._lock:
            self._bridges[bridge._window_id] = bridge
        window_id = bridge._window_id
        window.events.closed += lambda *args: self._closed(window_id)
        closing = getattr(window.events, "closing", None)
        if closing is not None:
            def request_close(*args):
                if getattr(window, "_rms_close_confirmed", False):
                    return True
                if getattr(window, "_rms_close_request_pending", False):
                    return False
                window._rms_close_request_pending = True
                def ask():
                    try:
                        uninitialized = window.evaluate_js(
                            "typeof window.__RMS_REQUEST_CLOSE !== 'function' || "
                            "(window.__RMS_REQUEST_CLOSE(), false)")
                        if uninitialized is True:
                            window._rms_close_confirmed = True
                            window.destroy()
                    except Exception:
                        log.exception("Could not request close confirmation")
                        window._rms_close_confirmed = True
                        window.destroy()
                    finally:
                        window._rms_close_request_pending = False
                threading.Thread(target=ask, daemon=True).start()
                return False
            window.events.closing += request_close

    def bridge(self, window_id):
        return self._bridges.get(window_id)

    def window_ids(self):
        with self._lock:
            return list(self._bridges)

    # --- 소유권 ---------------------------------------------------------
    def owner(self, collection_id):
        with self._lock:
            return self._owners.get(collection_id)

    def claim(self, window_id, collection_id):
        with self._lock:
            current = self._owners.get(collection_id)
            if current not in (None, window_id) and current in self._bridges:
                return False
            self._owners[collection_id] = window_id
            return True

    def release(self, window_id, collection_id):
        with self._lock:
            if self._owners.get(collection_id) == window_id:
                del self._owners[collection_id]

    # --- 떼기 / 붙이기 --------------------------------------------------
    def detach(self, from_window_id, collection_id):
        with self._lock:
            self._seq += 1
            window_id = f"w{self._seq}"
            bridge = WindowBridge(self.api, self, window_id, collection_id)
            # 새 창이 뜨기 전에 소유권을 넘긴다 - 그 창의 init이 open_collection을 부른다.
            self._owners[collection_id] = window_id
        collection = self.api.registry.get_collection(collection_id)
        title = f"{collection.name} - RetroMeta Studio" if collection else "RetroMeta Studio"
        window = self._create_window(title, bridge, True)
        self._attach(bridge, window)
        log.info("WINDOW_DETACH collection=%s window=%s from=%s", collection_id, window_id, from_window_id)
        return window_id

    def merge(self, window_id):
        bridge = self._bridges.get(window_id)
        main = self._bridges.get(MAIN_WINDOW)
        if bridge is None or bridge._collection_id is None:
            return
        collection_id = bridge._collection_id
        with self._lock:
            # 창이 닫히며 Collection을 닫지 않도록 소유권부터 메인으로 옮긴다.
            self._owners[collection_id] = MAIN_WINDOW
        if main is not None:
            self._call(main, "__rmsAdoptCollection", collection_id)
        log.info("WINDOW_MERGE collection=%s window=%s", collection_id, window_id)
        bridge._window._rms_close_confirmed = True
        bridge._window.destroy()

    # --- 알림 -----------------------------------------------------------
    def broadcast(self, from_window_id, hook, payload):
        for window_id, bridge in list(self._bridges.items()):
            if window_id != from_window_id:
                self._call(bridge, hook, payload)

    @staticmethod
    def _call(bridge, hook, payload):
        script = f"window.{hook} && window.{hook}({json.dumps(payload, ensure_ascii=False)})"
        try:
            bridge._window.evaluate_js(script)
        except Exception as e:  # noqa: BLE001 - 닫히는 중인 창에 보낸 알림 실패는 무시한다
            log.warning("WINDOW_NOTIFY_FAILED hook=%s error=%s", hook, e)

    def _closed(self, window_id):
        with self._lock:
            self._bridges.pop(window_id, None)
            owned = [cid for cid, owner in self._owners.items() if owner == window_id]
            for cid in owned:
                del self._owners[cid]
            others = list(self._bridges.values())
        if window_id == MAIN_WINDOW:
            for bridge in others:   # 메인 창이 닫히면 앱이 끝난다
                try:
                    bridge._window._rms_close_confirmed = True
                    bridge._window.destroy()
                except Exception:  # noqa: BLE001
                    pass
            return
        for cid in owned:
            self.api.workspace.close_collection(cid)
