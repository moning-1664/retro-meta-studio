"""
bridge/api.py
==============
pywebview 브릿지. JS에서 부를 수 있는 유일한 표면이다.

**얇게 유지한다.** 이전 프로젝트의 `api.py`는 3,400줄짜리 모놀리스로, 브릿지와
비즈니스 로직이 섞여 있어 손대기 어려웠다. 여기서는 인자 변환과 오류 포장만 하고
실제 일은 전부 `app/`으로 내려보낸다. 이 파일에 로직이 쌓이기 시작하면 그건
`app/` 어딘가로 가야 한다는 신호다.

모든 메서드는 `{"ok": True, "data": ...}` 또는 `{"ok": False, "error": "..."}`를
돌려준다. JS 쪽은 이 형태만 알면 된다.
"""

from __future__ import annotations

import base64
import traceback
from pathlib import Path

from adapters import get_adapter
from app import paths
from app.model.collection import STORAGE_INTERNAL
from app.model.constants import MEDIA_TYPES
from app.model.plan import Plan
from app.plan import builder, clipboard
from app.plan.applier import apply_plan
from app.plan.validator import check_capacity, validate
from app.store.registry import CHANGE_APPLIED, RegistryError, RegistryStore
from app.workspace import Workspace, WorkspaceError
from bridge.jobs import JobManager
import file_ops
from utils import normalize_title

#: JS가 쓰는 표시용 라벨 <-> 저장소의 소문자 키
MEDIA_LABELS = {"3dboxes": "3DBoxes", "covers": "Covers", "marquees": "Marquees",
                "miximages": "Miximages", "screenshots": "Screenshots",
                "videos": "Videos", "wheel": "Wheel"}
MEDIA_KEYS = {v: k for k, v in MEDIA_LABELS.items()}

THUMBNAIL_MAX = 256


def ok(data=None):
    return {"ok": True, "data": data}


def err(message):
    return {"ok": False, "error": str(message)}


def guarded(fn):
    """브릿지 메서드에서 새어나간 예외가 JS 쪽 Promise를 깨뜨리지 않게 한다.

    도메인 오류(Collection 없음, Storage에 System이 남아 있음 등)는 사용자에게
    그대로 보여줄 메시지이므로 조용히 돌려보낸다. 예상 못 한 예외만 traceback을
    남긴다 - 둘을 구분하지 않으면 정상 동작 중에도 로그가 traceback으로 뒤덮인다.
    """
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (WorkspaceError, RegistryError, KeyError) as e:
            return err(e)
        except Exception as e:  # noqa: BLE001 - 사용자에게 보여줄 오류로 바꾼다
            traceback.print_exc()
            return err(e)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


class Api:
    def __init__(self, registry_path=None, cache_dir=None):
        """registry_path/cache_dir는 테스트에서만 넘긴다. 실행 시에는 app/paths.py의
        기본 위치(실행 파일 옆 db/)를 쓴다."""
        if registry_path is None:
            paths.ensure_dirs()
        self.registry = RegistryStore(registry_path or paths.REGISTRY_DB)
        self.workspace = Workspace(self.registry, cache_dir=cache_dir or paths.CACHE_DIR)
        self.jobs = JobManager()
        # Plan은 세션 한정이다(D2). DB에 저장하지 않고 여기서만 들고 있다가 앱이
        # 꺼지면 사라진다.
        self._plans: dict[str, Plan] = {}
        self._clipboard_dir = (Path(cache_dir).parent / "clipboard") if cache_dir else paths.CLIPBOARD_DIR
        clipboard.prune(self._clipboard_dir)
        # 파일 복사 엔진 선택. 기본은 Robocopy다 - 서명 없는 자체 워커는 백신 행동
        # 기반 탐지에 걸린다는 실사용 보고가 있다(file_ops.py 참고).
        file_ops.select_engine(self.registry.get_setting("copy_engine", file_ops.ENGINE_AUTO))
        self._window = None

    def close(self):
        """앱 종료. 진행 중인 작업을 먼저 멈춘 뒤에 DB를 닫는다.

        워커 스레드가 쓰고 있는 sqlite 연결을 닫으면 프로세스가 죽는다. 시간 안에
        멈추지 못한 작업이 남아 있으면 연결을 닫지 않고 그대로 둔다 - 어차피 프로세스가
        끝나면서 정리되고, 크래시로 끝나는 것보다 낫다.
        """
        if not self.jobs.shutdown(timeout=5.0):
            return
        self.workspace.close()
        self.registry.close()

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------
    @guarded
    def list_collections(self):
        return ok([self._collection_summary(c) for c in self.registry.list_collections()])

    @guarded
    def create_collection(self, name, frontend, root_path, target=None, arch=None):
        collection = self.workspace.create_collection(
            name, frontend, root_path, target=target or None, arch=arch or None)
        return ok(self._collection_summary(collection))

    @guarded
    def rename_collection(self, collection_id, name):
        self.registry.update_collection(collection_id, name=name)
        return ok(True)

    @guarded
    def update_collection_target(self, collection_id, target=None, arch=None, os_name=None):
        """Target/OS/Architecture는 별개 값이다(스펙 §5). Frontend는 여기서 못 바꾼다 -
        실제 형식 변환은 Convert가 담당한다."""
        self.registry.update_collection(collection_id, target=target or None,
                                        arch=arch or None, os=os_name or None)
        return ok(True)

    @guarded
    def delete_collection(self, collection_id):
        self._plans.pop(collection_id, None)
        self.workspace.close_collection(collection_id)
        self.registry.delete_collection(collection_id)
        return ok(True)

    @guarded
    def open_collection(self, collection_id):
        self.workspace.open(collection_id)
        return ok(self.collection_detail(collection_id)["data"])

    @guarded
    def close_collection(self, collection_id):
        self.workspace.close_collection(collection_id)
        return ok(True)

    @guarded
    def collection_detail(self, collection_id):
        """헤더와 좌측 내비게이션이 필요로 하는 모든 것."""
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        cache = self.workspace.open(collection_id)
        stats = {s["system"]: s for s in cache.system_stats()}
        usage = cache.storage_usage()
        provider = self.workspace.provider_for(collection)

        storages = []
        for storage in collection.storages:
            volume = provider.volume_info(storage.root_path)
            storages.append({
                "id": storage.storage_id,
                "kind": storage.kind,
                "label": storage.label or storage.storage_id,
                "rootPath": storage.root_path,
                "actualBytes": usage.get(storage.storage_id, 0),
                # capacity/free가 None이면 Unknown이다 - UI는 용량 막대를 숨긴다.
                "capacityBytes": volume.capacity_bytes,
                "freeBytes": volume.free_bytes,
                "systems": [
                    {"system": s.system, "count": stats.get(s.system, {}).get("rom_count", 0)}
                    for s in collection.systems_in(storage.storage_id)
                ],
            })

        return ok({
            **self._collection_summary(collection),
            "storages": storages,
            "totalGames": cache.count_rows(),
        })

    def _collection_summary(self, collection):
        return {
            "id": collection.id,
            "name": collection.name,
            "frontend": collection.frontend,
            "frontendLabel": get_adapter(collection.frontend).display_name,
            "target": collection.target,
            "os": collection.os,
            "arch": collection.arch,
            "rootPath": collection.root_path,
            "systemCount": len(collection.systems),
        }

    # ------------------------------------------------------------------
    # Storage / System
    # ------------------------------------------------------------------
    @guarded
    def add_external_storage(self, collection_id, label, root_path):
        storage_id = self._next_storage_id(collection_id)
        self.registry.add_storage(collection_id, storage_id, kind="external",
                                  label=label or "External", root_path=root_path)
        return ok(storage_id)

    @guarded
    def remove_storage(self, collection_id, storage_id):
        self.registry.remove_storage(collection_id, storage_id)
        return ok(True)

    @guarded
    def move_system(self, collection_id, system, storage_id):
        """배치 정보만 바꾼다. 실제 파일 이동은 Plan Apply가 한다(스펙 §10)."""
        self.registry.move_system(collection_id, system, storage_id)
        return ok(True)

    def _next_storage_id(self, collection_id):
        existing = {s.storage_id for s in self.registry.get_collection(collection_id).storages}
        index = 1
        while f"ext-{index}" in existing:
            index += 1
        return f"ext-{index}"

    # ------------------------------------------------------------------
    # Gamelist
    # ------------------------------------------------------------------
    @guarded
    def list_rows(self, collection_id, systems=None, storage_ids=None, search=None,
                  order="title", descending=False, limit=200, offset=0):
        """가상 스크롤이 요청한 구간만 돌려준다. 정렬/필터/검색은 전부 SQL이 처리한다."""
        cache = self.workspace.open(collection_id)
        query = {"systems": systems or None, "storage_ids": storage_ids or None,
                 "search": search or None}
        rows = cache.query_rows(**query, order=order, descending=bool(descending),
                                limit=int(limit), offset=int(offset))
        return ok({"rows": [self._row_summary(r) for r in rows],
                   "total": cache.count_rows(**query), "offset": int(offset)})

    @staticmethod
    def _row_summary(row):
        return {
            "romUid": row["rom_uid"], "system": row["system"], "file": row["filename"],
            "title": row["title"], "size": row["size"], "storageId": row["storage_id"],
            "hasMetadata": bool(row["has_metadata"]), "hasMedia": bool(row["has_media"]),
            "present": bool(row["present"]),
        }

    @guarded
    def get_row(self, collection_id, rom_uid):
        cache = self.workspace.open(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        media = {}
        for item in row["media"]:
            label = MEDIA_LABELS.get(item["media_type"], item["media_type"])
            # 실제 이미지는 화면에 보일 때 낱개로 가져온다. 여기서 전부 base64로
            # 실어 보내면 media가 많은 항목에서 브릿지가 과부하된다.
            media[label] = "video://exists" if item["media_type"] == "videos" else "pending"
        return ok({
            "romUid": row["rom_uid"], "system": row["system"], "file": row["filename"],
            "fields": row["fields"], "media": media, "size": row["size"],
            "present": bool(row["present"]), "sha256": row["sha256"],
        })

    @guarded
    def get_media_image(self, collection_id, rom_uid, media_label, thumbnail=False):
        cache = self.workspace.open(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        media_type = MEDIA_KEYS.get(media_label, str(media_label).lower())
        item = next((m for m in row["media"] if m["media_type"] == media_type), None)
        if item is None:
            return ok(None)
        return ok(self._encode_image(item["rel_path"], THUMBNAIL_MAX if thumbnail else None))

    @staticmethod
    def _encode_image(path, max_size=None):
        path = Path(path)
        if not path.exists():
            return None
        suffix = path.suffix.lower()
        if suffix in (".mp4", ".avi"):
            return None
        try:
            if max_size:
                from PIL import Image
                import io
                with Image.open(path) as image:
                    image.thumbnail((max_size, max_size))
                    buffer = io.BytesIO()
                    image.convert("RGB").save(buffer, format="JPEG", quality=82)
                    payload, mime = buffer.getvalue(), "image/jpeg"
            else:
                payload = path.read_bytes()
                mime = {"png": "image/png", "webp": "image/webp"}.get(suffix.lstrip("."), "image/jpeg")
        except Exception:
            # 깨진 이미지 하나가 상세 패널 전체를 막으면 안 된다.
            return None
        return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"

    # ------------------------------------------------------------------
    # 편집 (결정 D1 - 저장 즉시 파일에 기록, Plan 미경유)
    # ------------------------------------------------------------------
    @guarded
    def save_fields(self, collection_id, rom_uid, fields):
        """메타데이터를 그 자리에서 Collection 파일에 쓴다.

        Plan을 거치지 않는다(D1) - Plan은 저장 용량이 변하는 작업만 담는다. 대신
        Adapter에 이 항목 하나만 넘기므로 gamelist.xml의 다른 항목과 우리가
        해석하지 않는 요소는 그대로 남는다.
        """
        from adapters.base import GameEntry

        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        busy = self.jobs.busy_targets(collection_id)
        if busy and self.jobs.busy_kind(collection_id) != "scan":
            return err("작업이 진행 중이라 지금은 편집할 수 없습니다. 완료 후 다시 시도해주세요.")

        cache = self.workspace.open(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")

        merged = {**row["fields"], **{k: v for k, v in (fields or {}).items()}}
        adapter = get_adapter(collection.frontend)
        layout = adapter.layout(collection, row["system"])
        adapter.write_index(layout, [GameEntry(filename=row["filename"], fields=merged,
                                               frontend_raw=row["frontend_raw"])])

        title = (merged.get("name") or "").strip() or Path(row["filename"]).stem
        cache.update_metadata(int(rom_uid), merged, title=title, title_norm=normalize_title(title))
        return ok({"title": title})

    # ------------------------------------------------------------------
    # Plan (세션 한정 - 결정 D2)
    # ------------------------------------------------------------------
    def _plan(self, collection_id) -> Plan:
        plan = self._plans.get(collection_id)
        if plan is None:
            plan = self._plans[collection_id] = Plan(collection_id)
        return plan

    def _plan_context(self, collection_id):
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            raise WorkspaceError("Collection을 찾을 수 없습니다.")
        return collection, self.workspace.open(collection_id), self.workspace.provider_for(collection)

    @guarded
    def plan_state(self, collection_id):
        """Gamelist의 Status 기호와 하단 바가 필요로 하는 것."""
        plan = self._plan(collection_id)
        collection, cache, provider = self._plan_context(collection_id)
        return ok({
            **plan.summary(),
            "marks": plan.marks(),
            "capacity": check_capacity(plan, collection, cache, provider),
            "clipboard": clipboard.peek(self.registry),
        })

    @guarded
    def plan_delete(self, collection_id, rom_uids):
        collection, cache, _ = self._plan_context(collection_id)
        result = builder.plan_delete(self._plan(collection_id), collection, cache, rom_uids)
        return ok(result)

    @guarded
    def plan_storage_change(self, collection_id, system, storage_to):
        collection, cache, _ = self._plan_context(collection_id)
        result = builder.plan_storage_change(self._plan(collection_id), collection, cache,
                                             system, storage_to)
        return ok(result)

    @guarded
    def plan_remove_entry(self, collection_id, key):
        return ok(self._plan(collection_id).remove(key))

    @guarded
    def plan_clear(self, collection_id):
        self._plan(collection_id).clear()
        return ok(True)

    @guarded
    def copy_selection(self, collection_id, rom_uids):
        """다른 인스턴스에서도 붙여넣을 수 있게 내보낸다(결정 D5)."""
        collection, cache, _ = self._plan_context(collection_id)
        return ok(clipboard.copy_selection(self.registry, collection, cache, rom_uids,
                                           self._clipboard_dir))

    @guarded
    def paste(self, collection_id):
        collection, _, provider = self._plan_context(collection_id)
        descriptor, items = clipboard.read_items(self.registry)
        if not items:
            return err("붙여넣을 항목이 없습니다.")
        result = builder.plan_add(self._plan(collection_id), collection, provider, items)
        return ok({**result, "source": descriptor.get("sourceName")})

    @guarded
    def validate_plan(self, collection_id):
        plan = self._plan(collection_id)
        collection, cache, provider = self._plan_context(collection_id)
        return ok(validate(plan, collection, cache, provider))

    @guarded
    def start_apply(self, collection_id):
        """Plan을 실제 파일 변경으로 실행한다(스펙 §31).

        같은 Collection을 다른 인스턴스가 동시에 Apply하지 못하도록 프로세스 간
        락을 잡는다(§9.4). 끝나면 반드시 놓는다.
        """
        plan = self._plan(collection_id)
        if not len(plan):
            return err("적용할 Plan이 없습니다.")

        collection, cache, provider = self._plan_context(collection_id)
        report = validate(plan, collection, cache, provider)
        if report["blocked"]:
            return err("용량이 부족합니다. Plan을 줄이거나 저장 공간을 확보해주세요.")

        lock_name = f"apply:{collection_id}"
        if not self.registry.acquire_lock(lock_name, kind="apply"):
            owner = self.registry.lock_owner(lock_name) or {}
            return err(f"다른 창에서 같은 Collection을 적용하는 중입니다({owner.get('instance_id', '?')[:8]}).")

        def run(cb):
            try:
                result = apply_plan(plan, collection, cache, self.registry, provider, progress_cb=cb)
                self.workspace.scan(collection_id, force=True)
                self.registry.append_change(CHANGE_APPLIED, collection_id,
                                            {"applied": result["applied"]})
                return result
            finally:
                self.registry.release_lock(lock_name)

        job_id = self.jobs.run_phased((collection_id,), [("적용", run)], kind="apply")
        return ok({"jobId": job_id})

    # ------------------------------------------------------------------
    # Job
    # ------------------------------------------------------------------
    @guarded
    def start_scan(self, collection_id, force=False):
        """커버를 먼저 끝내고 나머지 media를 뒤로 미룬다 - 카드 이미지가 먼저 보인다."""
        phases = [
            ("메타데이터+커버", lambda cb: self.workspace.scan(
                collection_id, media_types=["covers"], force=force, progress_cb=cb)),
            ("나머지 미디어", lambda cb: self.workspace.scan(
                collection_id, force=force, progress_cb=cb)),
        ]
        job_id = self.jobs.run_phased((collection_id,), phases, kind="scan")
        return ok({"jobId": job_id})

    @guarded
    def get_job_progress(self, job_id):
        job = self.jobs.get(job_id)
        return ok(job) if job else err("작업을 찾을 수 없습니다.")

    @guarded
    def cancel_job(self, job_id):
        return ok(self.jobs.cancel(job_id))

    # ------------------------------------------------------------------
    # 환경
    # ------------------------------------------------------------------
    @guarded
    def media_types(self):
        return ok([{"key": k, "label": MEDIA_LABELS.get(k, k)} for k in MEDIA_TYPES])

    @guarded
    def frontends(self):
        from adapters import available
        return ok([{"id": a.id, "label": a.display_name} for a in available()])

    @guarded
    def pick_folder(self, title=""):
        import webview
        window = self._window or (webview.windows[0] if webview.windows else None)
        if window is None:
            return err("창을 찾을 수 없습니다.")
        result = window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return ok(None)
        return ok(result[0] if isinstance(result, (list, tuple)) else result)

    @guarded
    def window_control(self, action):
        import webview
        window = self._window or (webview.windows[0] if webview.windows else None)
        if window is None:
            return err("창을 찾을 수 없습니다.")
        if action == "minimize":
            window.minimize()
        elif action == "maximize":
            window.toggle_fullscreen()
        elif action == "close":
            window.destroy()
        return ok(True)

    @guarded
    def default_storage_id(self):
        return ok(STORAGE_INTERNAL)

    @guarded
    def get_copy_engine(self):
        """지금 어떤 엔진으로 파일을 옮기는지. 백신 문제로 바꿔야 할 때 쓴다."""
        from engines.robocopy_engine import robocopy_available
        return ok({
            "setting": self.registry.get_setting("copy_engine", file_ops.ENGINE_AUTO),
            "active": file_ops.active_engine_name(),
            "robocopyAvailable": robocopy_available(),
        })

    @guarded
    def set_copy_engine(self, name):
        if name not in (file_ops.ENGINE_AUTO, file_ops.ENGINE_ROBOCOPY, file_ops.ENGINE_WORKER):
            return err(f"알 수 없는 엔진입니다: {name}")
        self.registry.set_setting("copy_engine", name)
        file_ops.select_engine(name)
        return ok({"active": file_ops.active_engine_name()})
