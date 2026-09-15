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
import re
import logging
from collections import OrderedDict
import traceback
import time
from pathlib import Path

from adapters import get_adapter
from app import paths
from app.model.collection import STORAGE_INTERNAL
from app.model.constants import MEDIA_TYPES, VIDEO_MEDIA_TYPE, normalize_system
from app import dashboard
from app import media_cleanup
from app import system_ops
from app import storage_layout
from app import title_affix
from app.launch import retroarch
from app.model.plan import OP_STORAGE_CHANGE, OP_TITLE_EDIT, RESOLVE_OVERWRITE, RESOLVE_SKIP, Plan
from app.plan import builder, clipboard
from app.plan.applier import apply_plan
from app.plan.validator import check_capacity, validate
from app.archive import service as archive_service
from app.compare import engine as compare_engine
from app.convert import service as convert_service
from app.match import service as match_service
from app.metadata import service as metadata_service
import storage
from app.store.archive import ArchiveStore
from app.store.registry import CHANGE_APPLIED, RegistryError, RegistryStore
from app.workspace import Workspace, WorkspaceError
from bridge.jobs import JobManager
from bridge.media_server import MediaServer
import file_ops
from utils import normalize_title

log = logging.getLogger(__name__)

#: JS가 쓰는 표시용 라벨 <-> 저장소의 소문자 키
MEDIA_LABELS = {
    "covers": "Covers", "marquees": "Marquees", "miximages": "Miximages",
    "screenshots": "Screenshots", "videos": "Videos", "wheel": "Wheel",
    "3dboxes": "3DBoxes", "backcovers": "BackCovers", "fanart": "FanArt",
    "manuals": "Manuals", "physicalmedia": "PhysicalMedia",
    "titlescreens": "TitleScreens",
}
MEDIA_KEYS = {v: k for k, v in MEDIA_LABELS.items()}

THUMBNAIL_MAX = 256

#: 캐시해 둘 썸네일 개수. 카드 한 화면이 수십 개이므로 몇 화면 분량이면 충분하다.
THUMBNAIL_CACHE_MAX = 256

#: "캐시에 없음"과 "캐시된 값이 None(=그릴 수 없는 파일)"을 구분하는 표식.
_MISS = object()


def _sorted_systems(entries, games, *, with_storage=False, stats=None):
    """게임이 있는 System을 먼저, 없는 것을 뒤에. 같은 상태끼리는 이름순.

    빈 System을 별도의 "Empty Systems" 묶음으로 만들지 않는다 - 사용자가 보는 것은
    하나의 System 목록이고, 비어 있다는 사실은 개수(0)가 이미 말해 준다. 정렬
    우선순위만 다르게 준다.
    """
    def item(entry):
        # 목록에 뜨는 게임 수와 같은 값이어야 한다(`count_by_system`).
        row = {"system": entry.system, "count": games.get(entry.system, 0)}
        if with_storage:
            row["storageId"] = entry.storage_id
        # Metadata가 없는 항목 수. 개수 자체를 따로 주지 않고 "빠진 수"만 주는 이유는,
        # 화면이 `count - missingMetadata`로 계산하면 목록에 뜨는 수(count)와 항상
        # 아귀가 맞기 때문이다 - 두 곳에서 따로 센 숫자가 어긋나는 일이 없다.
        #
        # 용량과 Media 누락 수도 같이 준다. Scan이 이미 세어 둔 값이라 추가 비용이
        # 없고, 헤더를 펼쳤을 때 "이 System이 얼마나 차지하고 무엇이 빠졌는지"를
        # Dashboard까지 가지 않고 바로 볼 수 있다.
        if stats is not None:
            stat = stats.get(entry.system) or {}
            row["missingMetadata"] = int(stat.get("missing_metadata") or 0)
            row["missingMedia"] = int(stat.get("missing_media") or 0)
            row["romBytes"] = int(stat.get("rom_bytes") or 0)
            row["mediaBytes"] = int(stat.get("media_bytes") or 0)
        return row

    return sorted((item(e) for e in entries),
                  key=lambda r: (r["count"] == 0, r["system"].lower()))


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
        except (WorkspaceError, RegistryError, KeyError, ValueError) as e:
            return err(e)
        except Exception as e:  # noqa: BLE001 - 사용자에게 보여줄 오류로 바꾼다
            traceback.print_exc()
            return err(e)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _reveal_path(path, select=False):
    """파일 탐색기로 연다. 테스트는 이 함수를 바꿔 끼운다.

    `select=True`면 폴더를 열지 않고 **그 파일을 고른 채로** 탐색기를 연다(개별
    게임의 ROM/Media 파일을 가리킬 때 - 폴더만 열면 수백 개 파일 중에서 다시
    찾아야 한다). Linux는 탐색기마다 파일 선택 방법이 달라 통일된 방법이 없으므로
    부모 폴더를 여는 것으로 대신한다.
    """
    import os
    import subprocess
    import sys
    if sys.platform.startswith("win"):
        if select:
            subprocess.Popen(["explorer", f"/select,{path}"])  # noqa: S603,S607
        else:
            os.startfile(path)  # noqa: S606 - 사용자가 고른 Collection 폴더다
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path] if select else ["open", path])
    else:
        subprocess.Popen(["xdg-open", str(Path(path).parent) if select else path])


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
        # 썸네일 캐시(LRU). 파일이 그대로면 인코딩 결과도 그대로다.
        self._thumb_cache: OrderedDict = OrderedDict()
        self._clipboard_dir = (Path(cache_dir).parent / "clipboard") if cache_dir else paths.CLIPBOARD_DIR
        archive_path = (Path(cache_dir).parent / "archive.db") if cache_dir else paths.ARCHIVE_DB
        self.archive = ArchiveStore(archive_path)
        clipboard.prune(self._clipboard_dir)
        # 파일 복사 엔진 선택. 기본은 Robocopy다 - 서명 없는 자체 워커는 백신 행동
        # 기반 탐지에 걸린다는 실사용 보고가 있다(file_ops.py 참고).
        file_ops.select_engine(self.registry.get_setting("copy_engine", file_ops.ENGINE_AUTO))
        self._window = None
        # 창 버튼의 최대화/복원 토글 상태. pywebview가 현재 상태를 알려주지 않아
        # 우리가 들고 있는다.
        self._maximized = False
        # Compare Mode도 Plan처럼 세션 한정이다 - 껐다 켜면 비교 상태는 사라진다.
        # {"baseId":..., "otherId":..., "rows":[...]} 또는 None.
        self._compare = None
        # 영상 전용 로컬 서버(bridge/media_server.py). 처음 영상을 볼 때 켜진다.
        self._media_server = MediaServer()

    def close(self):
        """앱 종료. 진행 중인 작업을 먼저 멈춘 뒤에 DB를 닫는다.

        워커 스레드가 쓰고 있는 sqlite 연결을 닫으면 프로세스가 죽는다. 시간 안에
        멈추지 못한 작업이 남아 있으면 연결을 닫지 않고 그대로 둔다 - 어차피 프로세스가
        끝나면서 정리되고, 크래시로 끝나는 것보다 낫다.
        """
        self._media_server.stop()
        if not self.jobs.shutdown(timeout=5.0):
            return
        self.workspace.close()
        self.archive.close()
        self.registry.close()

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------
    @guarded
    def list_collections(self):
        return ok([self._collection_summary(c) for c in self.registry.list_collections()])

    @guarded
    def create_collection(self, name, frontend, root_path=None, target=None, arch=None,
                          rom_path=None, media_path=None, storage_label=None):
        """`root_path`는 메타데이터가 있는 곳, `rom_path`는 ROM이 있는 곳이다.

        ES-DE는 이 둘을 떼어 놓는 것이 기본이라 하나만 받으면 반쪽짜리 Collection만
        만들 수 있다(§9). **둘 다 선택 사항이다** - 스크래핑을 한 번도 안 한 사용자는
        ROM만 가지고 있고, 그것도 정상적인 Collection이다. 유효하지 않은 것은 둘 다
        비어 있을 때뿐이며, 그 판단은 Workspace가 한다.
        """
        extra = {}
        if storage_label:
            # 기기 Collection은 Storage 이름이 "Internal"이면 어느 기기인지 알 수 없다.
            extra["internal_label"] = str(storage_label)
        collection = self.workspace.create_collection(
            name, frontend, root_path, target=target or None, arch=arch or None,
            rom_path=rom_path or None, media_path=media_path or None, **extra)
        return ok(self._collection_summary(collection))

    # ------------------------------------------------------------------
    # MTP 기기 (storage/mtp.py) - Metadata(gamelist) 전용 연결
    # ------------------------------------------------------------------
    #: ES-DE 폴더를 찾을 때 기기를 얼마나 깊이 훑을지. MTP는 폴더 하나 여는 것도 비싸서
    #: 기기 전체를 뒤지면 몇 분씩 걸린다 - 안드로이드 ES-DE는 저장소 바로 아래
    #: (`/storage/emulated/0/ES-DE`)에 있으므로 두 단계면 충분하다.
    MTP_SEARCH_DEPTH = 2

    @guarded
    def mtp_devices(self):
        """연결된 안드로이드 기기 목록.

        **기기가 없는 것과 못 읽는 것을 구분해서 돌려준다** - 빈 목록만 주면 화면이
        "USB를 꽂으라는 건지, 뭔가 잘못된 건지"를 말해줄 수 없다.
        """
        from storage import mtp

        try:
            devices = mtp.provider().devices()
        except mtp.MtpError as e:
            return ok({"devices": [], "reason": str(e)})
        return ok({"devices": [{"key": d.key, "name": d.name, "path": mtp.join_path(d.key, [])}
                               for d in devices], "reason": None})

    @guarded
    def mtp_browse(self, path):
        """기기 폴더 한 단계(폴더만). `path`가 기기 루트면 저장소 목록이 나온다."""
        from storage import mtp

        if not mtp.is_mtp_path(path):
            return err("MTP 경로가 아닙니다.")
        device_key, segments = mtp.split_path(path)
        entries = [e for e in mtp.provider().scandir(path) if e.is_dir]
        return ok({
            "path": mtp.join_path(device_key, segments),
            "parent": mtp.join_path(device_key, segments[:-1]) if segments else None,
            "entries": sorted(({"name": e.name, "path": e.path} for e in entries),
                              key=lambda e: e["name"].lower()),
        })

    @guarded
    def mtp_find_esde(self, device_key):
        """기기에서 ES-DE 폴더(`gamelists`를 품은 폴더)와 ROM 폴더 후보를 찾는다.

        얕게만 훑는다(MTP_SEARCH_DEPTH) - 못 찾으면 화면에서 직접 고르면 된다.
        """
        from storage import mtp

        provider = mtp.provider()
        found: list[dict] = []
        roms: list[str] = []

        def walk(segments, depth):
            if depth > self.MTP_SEARCH_DEPTH or len(found) >= 4:
                return
            for entry in provider.scandir(mtp.join_path(device_key, segments)):
                if not entry.is_dir:
                    continue
                here = [*segments, entry.name]
                if provider.exists(mtp.join_path(device_key, [*here, "gamelists"])):
                    found.append({"path": mtp.join_path(device_key, here), "name": entry.name})
                elif entry.name.lower() in ("roms", "rom"):
                    roms.append(mtp.join_path(device_key, here))
                walk(here, depth + 1)

        try:
            walk([], 0)
        except mtp.MtpError as e:
            return err(e)
        return ok({"esde": found, "roms": roms})

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
        games = cache.count_by_system()
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
                "systems": _sorted_systems(collection.systems_in(storage.storage_id), games),
                "deviceId": storage.device_id or "",
                "deviceRoot": storage.device_root or "",
            })

        systems = _sorted_systems(collection.systems, games, with_storage=True, stats=stats)
        clash = self._conflicts(collection)
        for row in systems:
            sides = clash.get(row["system"].lower())
            if sides:
                row["conflict"] = sides

        return ok({
            **self._collection_summary(collection),
            "storages": storages,
            # **좌측 내비게이션이 그리는 것은 이 목록이다.**
            #
            # 예전에는 화면이 `storages[].systems`를 순회해서 Storage를 System의 부모
            # 노드로 그렸고, 그래서 사용자가 요구한 적 없는 `Internal` / `ROM` 분류가
            # 나타났다. Storage는 용량·볼륨·파일 작업을 위한 내부 개념이고, 사용자가
            # 보는 단위는 System이다. 어느 Storage에 있는지는 각 항목이 들고만 있고
            # (배지/툴팁용), 계층을 만들지 않는다.
            "systems": systems,
            "totalGames": cache.count_rows(),
            "totalMissingMetadata": sum(int(s.get("missing_metadata") or 0) for s in stats.values()),
            "totalMissingMedia": sum(int(s.get("missing_media") or 0) for s in stats.values()),
            "totalRomBytes": sum(int(s.get("rom_bytes") or 0) for s in stats.values()),
            "totalMediaBytes": sum(int(s.get("media_bytes") or 0) for s in stats.values()),
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
            # 화면이 기기 Collection을 다르게 그려야 하는 두 가지.
            # isDevice: 편집이 Plan을 거친다. metadataOnly: ROM이 없는 것이 정상이다.
            "isDevice": collection.is_device,
            "metadataOnly": collection.metadata_only,
        }

    # ------------------------------------------------------------------
    # Storage / System
    # ------------------------------------------------------------------
    @guarded
    def save_ui_state(self, collection_id, state):
        """컬럼 너비/정렬/미리보기처럼 **사용자가 맞춰 놓은 화면 상태**를 저장한다.

        Collection마다 다르게 기억한다 - System 구성이 다르면 보고 싶은 컬럼 폭도
        다르다. 저장 위치(`collections.ui_state_json`)는 처음부터 있었는데 읽고 쓰는
        길이 없어서, 앱을 닫으면 사용자가 맞춰 놓은 것이 전부 사라졌다.
        """
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        merged = {**(collection.ui_state or {}), **(state or {})}
        self.registry.update_collection(collection_id, ui_state=merged)
        return ok(merged)

    @guarded
    def get_ui_state(self, collection_id):
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        return ok(collection.ui_state or {})

    #: 앱 전역 설정(Settings 화면)이 registry의 app_settings에 들어가는 키.
    APP_SETTINGS_KEY = "ui.settings"
    #: Collection → Collection 복사(붙여넣기) 정책의 기본값. Settings > Import / Export가 바꾼다.
    #: conflict가 "ask"면 지금처럼 Plan에 충돌로 남겨 사용자가 고른다.
    #: unmatchedRom*은 **원본에 ROM 파일이 없는 항목**(Archive처럼 메타데이터만 있는 항목)의
    #: 처리 방식이다(사용자 결정) - 기본은 아무것도 복사하지 않고, 켜면 Metadata/Media/Video를
    #: 독립적으로 고른다. registry에는 평평하게 저장한다 - "transfer" 섹션 patch는 한 단계
    #: 깊이까지만 병합되므로(save_app_settings), 중첩 객체로 두면 필드 하나만 바꿔도 나머지가
    #: 지워진다.
    TRANSFER_DEFAULTS = {
        "includeRom": True, "includeMedia": True, "conflict": "ask",
        "unmatchedRomMode": "skip",
        "unmatchedRomMetadata": True, "unmatchedRomMedia": True, "unmatchedRomVideo": True,
    }

    @guarded
    def get_app_settings(self):
        """Settings 화면의 값. Collection마다가 아니라 **앱 전체에 하나**다.

        ui/stitch-v2-redesign은 이것을 브라우저 localStorage에 뒀다 - 그러면 백엔드
        (복사 정책 같은 것)가 읽을 수 없고, WebView 저장소가 지워지면 함께 사라진다.
        """
        return ok(self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {})

    @guarded
    def save_app_settings(self, patch):
        """바뀐 부분만 받아 합친다. 섹션(appearance, gamelist...) 단위로 한 단계
        깊이까지 병합한다 - 한 섹션의 값 하나를 바꾸려고 나머지를 다 보낼 필요가 없다."""
        if not isinstance(patch, dict):
            return err("설정 형식이 올바르지 않습니다.")
        merged = dict(self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {})
        for section, value in patch.items():
            if isinstance(value, dict) and isinstance(merged.get(section), dict):
                merged[section] = {**merged[section], **value}
            else:
                merged[section] = value
        self.registry.set_setting(self.APP_SETTINGS_KEY, merged)
        return ok(merged)

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    @guarded
    def dashboard_stats(self, collection_id):
        """Dashboard 화면의 숫자들. 읽기만 한다 - 스캔도 파일 변경도 하지 않는다.

        ui/stitch-v2-redesign은 이것을 main.py에서 Api 인스턴스에 런타임으로 붙였다
        (`install_dashboard`) - 오류 처리(@guarded)도 테스트도 없이 Cache 내부
        연결을 밖에서 직접 썼다. 계산은 app/dashboard.py로 옮겼다.
        """
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        cache = self.workspace.open(collection_id)
        data = dashboard.collection_stats(collection, cache)
        # 용량/여유 공간은 collection_detail과 같은 곳(볼륨 정보)에서 읽는다.
        provider = self.workspace.provider_for(collection)
        for storage, bucket in zip(collection.storages, data["storages"]):
            volume = provider.volume_info(storage.root_path)
            bucket["capacityBytes"] = volume.capacity_bytes
            bucket["freeBytes"] = volume.free_bytes
        return ok({"collectionId": collection.id, "collectionName": collection.name, **data})

    @guarded
    def validate_collection(self, collection_id):
        """Metadata 파일이 실제로 읽히는지부터 ROM/Media 연결까지 본다. 고치지는 않는다.

        집계(Complete/Missing Media/Missing Description)는 Dashboard 통계와 같은
        기준(cache.metadata_health())을 쓴다 - app/dashboard.py의 docstring 참고.
        """
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")

        # **검사 전에 Cache를 맞춘다.** 이 리포트는 두 곳에서 나온다 - 깨진 XML이나
        # 없는 ROM 같은 것은 파일을 그 자리에서 읽어 알아내지만, Complete/Missing
        # Description 같은 집계는 Cache(=지난 스캔의 기억)에서 온다. 맞춰 두지 않으면
        # 한 리포트 안에서 절반은 지금 상태, 절반은 지난번 상태가 되어 사용자가
        # 어느 쪽을 믿어야 할지 알 수 없다(실제로 앱 밖에서 설명을 채운 뒤 검사하면
        # "Missing Description 2"가 그대로 남았다).
        #
        # 스캔은 지문으로 걸러지므로 바뀐 게 없으면 거의 공짜다 - 바뀐 게 있다면
        # 그 재스캔이야말로 정확한 숫자를 내는 데 꼭 필요한 일이다.
        #
        # **스캔이 실패하면 그 사실을 숨기지 않는다.** 조용히 넘어가면 옛 Cache로
        # 계산한 숫자가 지금 숫자인 척 나가고, 이 재스캔이 막으려던 바로 그 상태로
        # 되돌아간다 - 게다가 이번엔 사용자가 알아챌 방법조차 없다. 파일을 직접 읽어
        # 얻는 항목(깨진 XML·없는 ROM·중복)은 Cache와 무관하게 여전히 정확하므로
        # 검사 자체는 끝까지 하고, Cache에서 온 숫자만 «믿을 수 없음»으로 표시한다.
        stale_reason = None
        try:
            self.workspace.scan(collection_id)
        except Exception as e:  # noqa: BLE001
            stale_reason = str(e) or e.__class__.__name__

        cache = self.workspace.open(collection_id)
        provider = self.workspace.provider_for(collection)
        report = dashboard.validate_collection(collection, get_adapter(collection.frontend),
                                               cache, provider)
        # 화면이 숫자를 흐리게 보여주고 이유를 말할 수 있도록 함께 내보낸다.
        report["countsStale"] = stale_reason is not None
        report["staleReason"] = stale_reason
        return ok(report)

    @guarded
    def set_favorite(self, collection_id, rom_uid, favorite=True):
        """즐겨찾기를 켜고 끈다. **Frontend의 파일에 그대로 기록한다.**

        사용자에게는 별표 하나지만 저장 위치는 Frontend마다 다르다(ES-DE는
        gamelist.xml의 `<favorite>`). 우리가 아는 공통 필드가 아니므로
        `frontend_raw`를 통해 다룬다 - 그래야 ES-DE가 다음에 열었을 때 그 별표를
        똑같이 본다. 우리 DB에만 적어 두면 Frontend에서는 즐겨찾기가 아니다.
        """
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        cache = self.workspace.open(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        blocked = self._ensure_writable(collection, [row["system"]])
        if blocked:
            return blocked

        adapter = get_adapter(collection.frontend)
        tag = getattr(adapter, "FAVORITE_TAG", None)
        if not tag:
            return err(f"{adapter.display_name}는 즐겨찾기를 지원하지 않습니다.")

        # **해제는 태그를 지우는 것이 아니라 false로 적는 것이다.** Adapter는 "모르는
        # 태그를 버리지 않는다"가 원칙이라, raw에서 빼도 파일에 이미 있는 요소는
        # 그대로 남는다. ES-DE도 `<favorite>false</favorite>`를 정상으로 읽는다.
        raw = dict(row.get("frontend_raw") or {})
        extra = [dict(item) for item in (raw.get("extra") or [])
                 if (item.get("tag") or item.get("key")) != tag]
        extra.append(adapter.favorite_raw(bool(favorite)))
        raw["extra"] = extra

        saved = self.save_fields(collection_id, rom_uid, row.get("fields") or {},
                                 frontend_raw=raw)
        if not saved["ok"]:
            return saved
        cache.set_favorite(int(rom_uid), favorite)
        return ok({"romUid": int(rom_uid), "favorite": bool(favorite)})

    @guarded
    def add_external_storage(self, collection_id, label, root_path):
        # **한 Collection은 한 종류의 저장소만 쓴다.** Provider는 Collection의
        # root_path 하나로 정해지므로(workspace.provider_for), 다른 종류의 경로를
        # Storage로 붙이면 그 경로를 엉뚱한 Provider가 읽는다. 로컬 Provider에게
        # `mtp://...`를 읽히면 **오류도 없이 빈 목록**이 와서, 사용자에게는 System이
        # 그냥 비어 보인다 - 왜 비었는지 알 길이 없는 것이 가장 나쁘다.
        from storage import mtp

        collection = self.registry.get_collection(collection_id)
        if collection is not None and \
                mtp.is_mtp_path(root_path) != mtp.is_mtp_path(collection.root_path):
            return err("기기(MTP) 저장소와 일반 저장소는 한 Collection에 함께 둘 수 없습니다. "
                       "기기는 별도 Collection으로 열어주세요.")
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
        collection = self.registry.get_collection(collection_id)
        blocked = self._ensure_writable(collection, [system]) if collection else None
        if blocked:
            return blocked
        self.registry.move_system(collection_id, system, storage_id)
        return ok(True)

    def _system_context(self, collection_id):
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            raise WorkspaceError("Collection을 찾을 수 없습니다.")
        return (collection, self.workspace.open(collection_id),
                self.workspace.provider_for(collection), get_adapter(collection.frontend))

    @guarded
    def system_removal_preview(self, collection_id, system, force=False):
        """System 삭제 전에 무엇이 지워지고 무엇이 남는지, 지울 수 없는 이유를 알려준다."""
        collection, cache, provider, adapter = self._system_context(collection_id)
        try:
            return ok(system_ops.removal_preview(collection, cache, provider, adapter, system,
                                                 force=bool(force)))
        except system_ops.SystemOpError as e:
            return err(e)

    @guarded
    def remove_system(self, collection_id, system, force=False):
        """System의 파일을 지우고 목록에서 뺀다(app/system_ops.py).

        force=False면 게임이 없는 System만 지운다. force=True는 System 우클릭의 [전체 삭제]다 -
        화면이 경고 + "확인하였습니다" 체크 + 확인으로 두 번 물은 뒤에만 부른다(사용자 결정).
        그 System을 가리키던 Plan 항목도 함께 뺀다 - 남기면 없는 파일을 대상으로 Apply한다."""
        if self.jobs.busy_targets(collection_id):
            return err("작업이 진행 중이라 지금은 System을 삭제할 수 없습니다.")
        collection, cache, provider, adapter = self._system_context(collection_id)
        try:
            result = system_ops.remove_system(self.registry, collection, cache, provider, adapter,
                                              system, force=bool(force))
        except system_ops.SystemOpError as e:
            return err(e)
        plan = self._plans.get(collection_id)
        stale = [e.key for e in plan.entries if e.system == system] if plan else []
        for key in stale:
            plan.remove(key)
        return ok({**result, "planRemoved": len(stale)})

    @guarded
    def open_system_folder(self, collection_id, system, kind):
        """System의 ROM/Metadata/Media 폴더를 파일 탐색기로 연다.

        경로는 Adapter의 layout이 정한다 - Storage 배치와 System별 경로 지정을 그대로 따른다."""
        collection, _cache, provider, adapter = self._system_context(collection_id)
        if not any(entry.system == system for entry in collection.systems):
            return err(f"System을 찾을 수 없습니다: {system}")
        try:
            path = system_ops.folder_path(adapter.layout(collection, system), kind)
        except system_ops.SystemOpError as e:
            return err(e)
        if not path or not provider.exists(path):
            return err(f"폴더가 없습니다: {path}")
        _reveal_path(path)
        return ok({"path": path})

    @guarded
    def open_row_folder(self, collection_id, rom_uid, kind):
        """게임 한 개의 ROM/Metadata/Media를 파일 탐색기에서 **그 파일을 고른 채로** 연다
        (실사용 피드백 §5 - "각 롬별로도 지원"). System 폴더 열기(open_system_folder)는
        폴더까지만 열어서, System 안에 파일이 많으면 다시 찾아야 했다.

        Metadata는 이 게임 하나만의 파일이 아니라 System이 공유하는 gamelist.xml이다 -
        그래도 "이 게임의 데이터가 있는 곳"이므로 그 파일을 고른 채로 연다. Media는
        종류가 여럿일 수 있어(cover/video/...) 있는 것 중 처음 것을 고른다.
        """
        collection, cache, provider, adapter = self._system_context(collection_id)
        blocked = self._ensure_file_ops(collection)
        if blocked:
            return blocked
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        layout = adapter.layout(collection, row["system"])
        if kind == "rom":
            if not row["present"]:
                return err("ROM 파일이 없습니다.")
            path = str(Path(layout.rom_dir) / row["filename"])
        elif kind == "metadata":
            if not layout.metadata_file:
                return err("Metadata 파일이 없습니다.")
            path = layout.metadata_file
        elif kind == "media":
            if not row["media"]:
                return err("Media 파일이 없습니다.")
            path = row["media"][0]["rel_path"]
        else:
            return err(f"알 수 없는 종류입니다: {kind}")
        if not path or not provider.exists(path):
            return err(f"파일이 없습니다: {path}")
        _reveal_path(path, select=True)
        return ok({"path": path})

    @guarded
    def orphan_metadata_preview(self, collection_id, system):
        """이 System에서 Metadata/Media는 있는데 **ROM 파일이 없는** 항목들(System
        우클릭 > ROM 없는 항목 정리). 목록에서 파일명이 흐리게 보이는 것과 같은 기준
        (row.present)이다.
        """
        collection, cache, _provider, _adapter = self._system_context(collection_id)
        if not any(entry.system == system for entry in collection.systems):
            return err(f"System을 찾을 수 없습니다: {system}")
        # Metadata 전용 Collection에서는 ROM이 없는 것이 정상이다 - 여기서 목록을
        # 내주면 멀쩡한 메타데이터 전부가 "정리 대상"으로 보인다.
        blocked = self._ensure_file_ops(collection)
        if blocked:
            return blocked
        rows = cache.query_rows(systems=[system], present=False, order="title")
        return ok({"system": system, "items": [
            {"romUid": r["rom_uid"], "filename": r["filename"], "title": r["title"]} for r in rows]})

    @guarded
    def media_cleanup_preview(self, collection_id, system):
        """System 우클릭 > "System 전체 미디어 정리" 대화상자의 체크박스 - type별
        개수·용량을 보여준다. 실제로 하나도 없는 type은 목록에서 뺀다."""
        collection, cache, _provider, _adapter = self._system_context(collection_id)
        if not any(entry.system == system for entry in collection.systems):
            return err(f"System을 찾을 수 없습니다: {system}")
        counts = media_cleanup.media_type_counts(cache, system)
        return ok({"system": system, "types": [
            {"type": key, "label": MEDIA_LABELS.get(key, key), "count": info["count"], "bytes": info["bytes"]}
            for key, info in sorted(counts.items(), key=lambda kv: -kv[1]["count"]) if info["count"]]})

    @guarded
    def media_cleanup(self, collection_id, system, media_types):
        """선택한 media type의 파일만 지운다(사용자 결정) - ROM·Metadata·다른 타입은
        그대로 둔다. 지운 뒤 그 System을 다시 스캔해 Cache를 실제 디스크 상태로
        맞춘다(app/media_cleanup.py)."""
        if not media_types:
            return err("지울 media 종류를 골라주세요.")
        if self.jobs.busy_targets(collection_id):
            return err("작업이 진행 중이라 지금은 정리할 수 없습니다.")
        collection, cache, provider, _adapter = self._system_context(collection_id)
        if not any(entry.system == system for entry in collection.systems):
            return err(f"System을 찾을 수 없습니다: {system}")
        blocked = self._ensure_file_ops(collection) or self._ensure_writable(collection, [system])
        if blocked:
            return blocked
        result = media_cleanup.cleanup_media(cache, provider, self.workspace, collection_id,
                                             system, media_types)
        return ok(result)

    # ------------------------------------------------------------------
    # Storage 충돌 / External 연결 / 폴더 이름 바꾸기·삭제 (app/storage_layout.py)
    # ------------------------------------------------------------------
    def _conflicts(self, collection):
        return storage_layout.conflicts(collection, self.workspace.provider_for(collection),
                                        get_adapter(collection.frontend))

    def _ensure_writable(self, collection, systems):
        """같은 System 폴더가 여러 Storage에 있으면 그 System에는 쓰지 않는다(사용자 결정).
        막히면 화면에 그대로 보여줄 err를, 괜찮으면 None을 돌려준다."""
        wanted = {str(s).lower() for s in systems if s}
        if not wanted:
            return None
        clash = self._conflicts(collection)
        hit = sorted(s for s in wanted if s in clash)
        if not hit:
            return None
        return err(f"{', '.join(h.upper() for h in hit)} System 폴더가 여러 Storage에 함께 있어 쓰기가 막혀 "
                   "있습니다. System 우클릭에서 한쪽 폴더를 지우거나 이름을 바꾸면 풀립니다.")

    @staticmethod
    def _ensure_file_ops(collection):
        """파일을 옮기고 지우는 작업을 할 수 있는 Collection인가.

        MTP로 연결한 기기는 Metadata 전용이다(사용자 결정) - 대량 전송은 MTP로
        감당할 수 없어서 ADB 모드를 따로 두기로 했다. 막히면 화면에 그대로 보여줄
        err를, 괜찮으면 None을 돌려준다.
        """
        if collection is not None and collection.is_device:
            return err("기기 Collection은 Metadata만 다룹니다. 파일 복사·이동·삭제는 "
                       "ADB 모드에서 지원할 예정입니다.")
        return None

    def _drop_plan_entries(self, collection_id, system):
        plan = self._plans.get(collection_id)
        if plan:
            for key in [e.key for e in plan.entries if e.system.lower() == str(system).lower()]:
                plan.remove(key)

    @guarded
    def update_storage(self, collection_id, storage_id, label=None, root_path=None, device_id=None,
                       device_root=None):
        """Storage 설정 - 이름, PC 경로(External만), 안드로이드 Storage ID와 기기 경로."""
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        storage_entry = collection.storage(storage_id)
        if storage_entry is None:
            return err("Storage를 찾을 수 없습니다.")
        fields = {}
        if label is not None:
            fields["label"] = str(label).strip() or storage_entry.label
        if root_path is not None and storage_entry.is_external and str(root_path).strip():
            fields["root_path"] = str(root_path).strip()
        if device_id is not None:
            value = str(device_id).strip()
            if value and not re.match(r"^[A-Za-z0-9\-]+$", value):
                return err("Storage ID는 영문·숫자와 - 만 쓸 수 있습니다(예: 1234-ABCD).")
            fields["device_id"] = value or None
        if device_root is not None:
            value = str(device_root).strip().rstrip("/")
            if value and not value.startswith("/"):
                return err("기기 경로는 /로 시작해야 합니다(예: /storage/1234-ABCD/ROMs).")
            fields["device_root"] = value or None
        self.registry.update_storage(collection_id, storage_id, **fields)
        return ok(True)

    @guarded
    def attach_storage_systems(self, collection_id, storage_id):
        """External Storage root 밑의 System 폴더를 Collection에 붙인다. 파일은 건드리지 않는다."""
        collection, _cache, provider, adapter = self._system_context(collection_id)
        try:
            return ok(storage_layout.attach_storage(self.registry, collection, provider, adapter, storage_id))
        except storage_layout.StorageLayoutError as e:
            return err(e)

    @guarded
    def rename_system_folder(self, collection_id, system, storage_id, new_name):
        """한 Storage 쪽 System 폴더의 이름을 바꾼다(충돌 해결). 바꾼 뒤 그 System을 다시 스캔한다."""
        if self.jobs.busy_targets(collection_id):
            return err("작업이 진행 중이라 지금은 이름을 바꿀 수 없습니다.")
        collection, cache, provider, adapter = self._system_context(collection_id)
        try:
            result = storage_layout.rename_folder(self.registry, collection, provider, adapter, cache,
                                                  system, storage_id, new_name)
        except (storage_layout.StorageLayoutError, OSError) as e:
            return err(e)
        if result["registered"]:
            self._drop_plan_entries(collection_id, system)
        self.workspace.scan(collection_id, force=True, systems=[result["to"]])
        return ok(result)

    @guarded
    def system_folder_preview(self, collection_id, system, storage_id):
        collection, _cache, provider, adapter = self._system_context(collection_id)
        try:
            return ok(storage_layout.folder_preview(collection, provider, adapter, system, storage_id))
        except storage_layout.StorageLayoutError as e:
            return err(e)

    @guarded
    def remove_system_folder(self, collection_id, system, storage_id):
        """한 Storage 쪽의 ROM 폴더만 지운다(충돌 해결). gamelist/media는 남긴다."""
        if self.jobs.busy_targets(collection_id):
            return err("작업이 진행 중이라 지금은 지울 수 없습니다.")
        collection, cache, provider, adapter = self._system_context(collection_id)
        try:
            result = storage_layout.remove_folder(self.registry, collection, provider, adapter, cache,
                                                  system, storage_id)
        except (storage_layout.StorageLayoutError, OSError) as e:
            return err(e)
        self._drop_plan_entries(collection_id, system)
        self.workspace.scan(collection_id, force=True, systems=[system])
        return ok(result)

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
                  order="title", descending=False, limit=200, offset=0,
                  favorites_only=False, priority=None):
        """가상 스크롤이 요청한 구간만 돌려준다. 정렬/필터/검색은 전부 SQL이 처리한다."""
        cache = self.workspace.open(collection_id)
        query = {"systems": systems or None, "storage_ids": storage_ids or None,
                 "search": search or None, "favorites_only": bool(favorites_only)}
        rows = cache.query_rows(**query, order=order, descending=bool(descending),
                                limit=int(limit), offset=int(offset), priority=priority or None)
        return ok({"rows": [self._row_summary(r) for r in rows],
                   "total": cache.count_rows(**query), "offset": int(offset)})

    @guarded
    def list_uids(self, collection_id, systems=None, storage_ids=None, search=None,
                  order="title", descending=False, favorites_only=False, priority=None):
        """지금 목록 전체의 rom_uid(필터·정렬 그대로). Ctrl+A가 쓴다."""
        cache = self.workspace.open(collection_id)
        return ok(cache.query_uids(systems=systems or None, storage_ids=storage_ids or None,
                                   search=search or None, order=order,
                                   descending=bool(descending), favorites_only=bool(favorites_only),
                                   priority=priority or None))

    @guarded
    def find_row_index(self, collection_id, prefix, after=-1, systems=None, storage_ids=None,
                       search=None, order="title", descending=False, favorites_only=False,
                       priority=None):
        """영문키 점프: `after` 다음 줄부터 파일명이 `prefix`로 시작하는 줄의 위치(없으면 -1).

        가상 스크롤이라 화면에 그려진 행만 뒤지면 목록 뒤쪽으로 갈 수 없다 - 그래서
        목록 전체를 같은 정렬로 백엔드가 찾는다."""
        cache = self.workspace.open(collection_id)
        return ok(cache.index_of_prefix(prefix, int(after), systems=systems or None,
                                        storage_ids=storage_ids or None, search=search or None,
                                        order=order, descending=bool(descending),
                                        favorites_only=bool(favorites_only), priority=priority or None))

    @staticmethod
    def _row_summary(row):
        """Gamelist 한 행. 이전 프로젝트의 컬럼을 그리는 데 필요한 것을 전부 싣는다.

            No. │ File │ Title │ Description │ Region │ Rating │ ★ │ Genre │ Status

        Description이 여기 있는 것이 중요하다 - 이전 프로젝트의 목록은 제목이 아니라
        설명 위주였고, 그래야 어떤 게임인지 목록에서 바로 판단할 수 있다.
        """
        return {
            "romUid": row["rom_uid"], "system": row["system"], "file": row["filename"],
            "title": row["title"], "size": row["size"], "storageId": row["storage_id"],
            "hasMetadata": bool(row["has_metadata"]), "hasMedia": bool(row["has_media"]),
            "present": bool(row["present"]),
            "desc": row["desc_text"] if "desc_text" in row.keys() else "",
            "region": row["region"] if "region" in row.keys() else "",
            "genre": row["genre"] if "genre" in row.keys() else "",
            "rating": row["rating"] if "rating" in row.keys() else "",
            "favorite": bool(row["favorite"]) if "favorite" in row.keys() else False,
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
            # 상세 패널의 별표도 목록과 같은 곳을 가리켜야 한다.
            "favorite": bool(row.get("favorite")),
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

    @guarded
    def get_media_video_url(self, collection_id, rom_uid):
        """이 게임의 영상을 재생할 URL(로컬 전용 서버). 영상이 없거나 재생할 수 없는 형식이면 None.

        이미지처럼 base64로 실어 보내지 않는다 - 영상은 수~수십 MB라 브릿지가 감당하지 못한다."""
        row = self.workspace.open(collection_id).get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        item = next((m for m in row["media"] if m["media_type"] == VIDEO_MEDIA_TYPE), None)
        url = self._media_server.url_for(item["rel_path"]) if item else None
        return ok({"url": url} if url else None)

    def _encode_image(self, path, max_size=None):
        # 썸네일은 카드 하나마다 한 번씩 불린다. 목록을 오갈 때마다 같은 파일을 다시
        # 열어 축소하고 base64로 만드는 것은 순전히 낭비다 - 파일이 그대로면 결과도
        # 그대로이므로 (경로, 크기, 수정시각, 목표 크기)를 열쇠로 캐시한다.
        if max_size:
            cached = self._thumbnail_cache_get(path, max_size)
            if cached is not _MISS:
                return cached
        payload = self._encode_image_uncached(path, max_size)
        if max_size:
            self._thumbnail_cache_put(path, max_size, payload)
        return payload

    def _thumbnail_key(self, path, max_size):
        try:
            stat = storage.for_path(path).stat(path)
        except Exception:
            return None
        if stat is None:
            return None
        return (str(path), stat.size, stat.mtime_ns, max_size)

    def _thumbnail_cache_get(self, path, max_size):
        key = self._thumbnail_key(path, max_size)
        if key is None or key not in self._thumb_cache:
            return _MISS
        self._thumb_cache.move_to_end(key)
        return self._thumb_cache[key]

    def _thumbnail_cache_put(self, path, max_size, payload):
        key = self._thumbnail_key(path, max_size)
        if key is None:
            return
        self._thumb_cache[key] = payload
        self._thumb_cache.move_to_end(key)
        while len(self._thumb_cache) > THUMBNAIL_CACHE_MAX:
            self._thumb_cache.popitem(last=False)

    @staticmethod
    def _encode_image_uncached(path, max_size=None):
        """이미지 한 장을 data URL로 만든다.

        **바이트는 Provider를 통해서만 읽는다.** 로컬에서는 결과가 같지만, MTP
        기기 Collection에서는 `Path.read_bytes()`가 아예 동작하지 않는다 - 커버를
        "선택한 항목부터" 한 장씩 읽어 오는 것이 기기에서 그림이 보이는 유일한
        길이다(사용자 결정).
        """
        suffix = Path(path).suffix.lower()
        if suffix in (".mp4", ".avi"):
            return None
        try:
            data = storage.for_path(path).read_bytes(path)
            if data is None:
                return None
            if max_size:
                from PIL import Image
                import io
                with Image.open(io.BytesIO(data)) as image:
                    image.thumbnail((max_size, max_size))
                    buffer = io.BytesIO()
                    # WebP는 같은 화질에서 JPEG보다 작다. 브릿지로 넘어가는 base64
                    # 문자열이 그만큼 짧아지므로 카드가 많을수록 차이가 커진다.
                    image.convert("RGB").save(buffer, format="WEBP", quality=82, method=4)
                    payload, mime = buffer.getvalue(), "image/webp"
            else:
                payload = data
                mime = {"png": "image/png", "webp": "image/webp"}.get(suffix.lstrip("."), "image/jpeg")
        except Exception:
            # 깨진 이미지 하나가 상세 패널 전체를 막으면 안 된다.
            return None
        return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"

    # ------------------------------------------------------------------
    # 편집 (결정 D1 - 저장 즉시 파일에 기록, Plan 미경유)
    # ------------------------------------------------------------------
    @guarded
    def save_fields(self, collection_id, rom_uid, fields, frontend_raw=None):
        """메타데이터를 그 자리에서 Collection 파일에 쓴다.

        Plan을 거치지 않는다(D1) - Plan은 저장 용량이 변하는 작업만 담는다. 대신
        Adapter에 이 항목 하나만 넘기므로 gamelist.xml의 다른 항목과 우리가
        해석하지 않는 요소는 그대로 남는다.

        **기기(MTP) Collection만 예외로 Plan을 거친다(사용자 결정).** MTP에는
        덮어쓰기가 없어서 한 글자 고칠 때마다 gamelist 전체를 지우고 다시 만든다 -
        편집을 모아서 Apply 한 번에 쓰는 편이 안전하고 빠르다. 자세한 이유는
        app/model/collection.py의 `Collection.is_device` 참고.
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
        blocked = self._ensure_writable(collection, [row["system"]])
        if blocked:
            return blocked

        merged = {**row["fields"], **{k: v for k, v in (fields or {}).items()}}
        if collection.is_device:
            entry = builder.plan_metadata_edit(self._plan(collection_id), cache, int(rom_uid),
                                               fields or {}, frontend_raw=frontend_raw)
            title = (entry.payload.get("name") or "").strip() or Path(row["filename"]).stem
            return ok({"title": title, "planned": True})

        # frontend_raw는 보통 읽은 그대로 다시 쓴다. 즐겨찾기처럼 사용자가 직접 바꾸는
        # Frontend 고유 값일 때만 새 것이 들어온다.
        raw = row["frontend_raw"] if frontend_raw is None else frontend_raw
        adapter = get_adapter(collection.frontend)
        layout = adapter.layout(collection, row["system"])
        adapter.write_index(layout, [GameEntry(filename=row["filename"], fields=merged,
                                               frontend_raw=raw)])

        title = (merged.get("name") or "").strip() or Path(row["filename"]).stem
        cache.update_metadata(int(rom_uid), merged, title=title, title_norm=normalize_title(title),
                              frontend_raw=None if frontend_raw is None else raw)
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
            # 사용자가 결정해야 하는 것과 지난 Apply에서 실패한 것을 명확히 노출한다.
            # 이게 안 보이면 "Apply 했으니 끝났다"고 오해한다.
            "conflictEntries": [self._entry_summary(e) for e in plan.conflict_entries()],
            "failedEntries": [self._entry_summary(e) for e in plan.failed_entries()],
            # Navigator가 드래그로 옮긴 System을 Apply 전에도 목표 Storage 밑에
            # 미리 보여주려면 어디로 갈 예정인지 알아야 한다(실사용 피드백 - 예전엔
            # Apply할 때까지 원래 자리에 그대로 있어서 "드래그가 안 먹혔다"처럼 보였다).
            "pendingMoves": {e.system: e.storage_to for e in plan.entries if e.op == OP_STORAGE_CHANGE},
        })

    @staticmethod
    def _entry_summary(entry):
        summary = {
            "key": entry.key, "op": entry.op, "system": entry.system,
            "filename": entry.filename or entry.system,
            "status": entry.status, "error": entry.error,
            "resolution": entry.resolution,
            "conflicts": entry.conflicts,
        }
        if entry.op == OP_TITLE_EDIT:
            summary["oldTitle"], summary["newTitle"] = entry.old_title, entry.new_title
        return summary

    @guarded
    def plan_resolve_conflict(self, collection_id, key, resolution):
        """충돌 항목을 어떻게 처리할지 정한다: skip(그대로 둠) 또는 overwrite(덮어씀).

        덮어쓰기를 고르면 용량 계산이 "새 파일 크기 전부"가 아니라 기존 파일과의
        차이로 다시 계산된다.
        """
        collection, _, provider = self._plan_context(collection_id)
        result = builder.resolve_conflict(self._plan(collection_id), collection, provider,
                                          key, resolution)
        return ok(result)

    @guarded
    def plan_resolve_all_conflicts(self, collection_id, resolution):
        """충돌 전체를 같은 방식으로 처리한다.

        수백 개를 하나씩 누르게 하면 도구로 쓸 수 없다. 다만 기본값을 자동으로
        적용하지는 않는다 - 사용자가 명시적으로 고른 경우에만 여기로 온다.
        """
        collection, _, provider = self._plan_context(collection_id)
        plan = self._plan(collection_id)
        keys = [e.key for e in plan.conflict_entries()]
        for key in keys:
            builder.resolve_conflict(plan, collection, provider, key, resolution)
        return ok({"resolved": len(keys), "resolution": resolution})

    @guarded
    def plan_delete(self, collection_id, rom_uids):
        collection, cache, provider = self._plan_context(collection_id)
        blocked = self._ensure_file_ops(collection) or self._ensure_writable(
            collection, [(cache.get_row(int(uid)) or {}).get("system")
                         for uid in rom_uids or []])
        if blocked:
            return blocked
        result = builder.plan_delete(self._plan(collection_id), collection, cache, rom_uids,
                                     provider)
        return ok(result)

    @guarded
    def plan_storage_change(self, collection_id, system, storage_to):
        collection, cache, _ = self._plan_context(collection_id)
        blocked = self._ensure_file_ops(collection) or self._ensure_writable(collection, [system])
        if blocked:
            return blocked
        result = builder.plan_storage_change(self._plan(collection_id), collection, cache,
                                             system, storage_to)
        return ok(result)

    # ------------------------------------------------------------------
    # Title Prefix/Postfix (app/title_affix.py) - Plan을 거치는 예외(D1, app/model/plan.py)
    # ------------------------------------------------------------------
    def _title_affix_config(self):
        stored = (self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {}).get("titleAffix") or {}
        return title_affix.normalize_config(stored)

    def _title_affix_rows(self, cache, rom_uids=None, system=None):
        """대상 행. `rom_uids`가 있으면 Gamelist에서 고른 항목들, 없으면 System 전체다."""
        if rom_uids:
            rows = (cache.get_row(int(uid)) for uid in rom_uids)
            return [row for row in rows if row is not None]
        if system:
            return cache.query_rows(systems=[system], order="title")
        return []

    @guarded
    def title_affix_preview(self, collection_id, rom_uids=None, system=None):
        """이 게임들에 실제로 적용될 새 제목 미리보기(Gamelist 우클릭 - 선택 항목,
        System 우클릭 - 그 System 전체 중 하나를 넘긴다). 아직 아무것도 바꾸지 않는다."""
        collection, cache, _provider = self._plan_context(collection_id)
        rows = self._title_affix_rows(cache, rom_uids, system)
        if not rows:
            return err("대상을 찾을 수 없습니다.")
        changes = title_affix.preview_titles(rows, self._title_affix_config())
        return ok({"items": changes, "changed": sum(1 for c in changes if c["changed"])})

    @guarded
    def plan_title_edit(self, collection_id, rom_uids=None, system=None):
        """미리보기에서 확인한 대로 Plan에 올린다. 실제 파일은 Apply를 눌러야 바뀐다(사용자 결정).

        미리보기와 똑같은 대상 선택을 다시 받아 서버에서 새로 계산한다 - 클라이언트가
        준 결과를 그대로 믿지 않는다(다른 Plan 만들기 메서드들과 같은 태도).
        """
        collection, cache, _provider = self._plan_context(collection_id)
        rows = self._title_affix_rows(cache, rom_uids, system)
        if not rows:
            return err("대상을 찾을 수 없습니다.")
        blocked = self._ensure_writable(collection, sorted({row["system"] for row in rows}))
        if blocked:
            return blocked
        changes = title_affix.preview_titles(rows, self._title_affix_config())
        result = builder.plan_title_edit(self._plan(collection_id), cache, changes)
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
        """붙여넣기. **Settings의 복사 정책(transfer)을 따른다.**

        - ROM/Media를 빼기로 했으면 Plan에 올리기 전에 그 부분을 뺀다(메타데이터는 늘 간다).
        - **원본에 ROM 파일이 없는 항목**(unmatched - Archive처럼 메타데이터만 있는 항목)은
          `unmatchedRom` 정책을 따로 적용한다. 기본은 아무것도 복사하지 않고 건너뛴다.
          "복사"를 골랐으면 Metadata/Media/Video를 독립적으로 골라 그것만 담는다.
        - 충돌 기본 처리가 skip/overwrite면 **이번 붙여넣기로 생긴 충돌만** 그렇게 정한다.
          원래 Plan에 있던 충돌은 사용자가 고를 몫이라 건드리지 않는다.
        """
        collection, _, provider = self._plan_context(collection_id)
        descriptor, items = clipboard.read_items(self.registry)
        if not items:
            return err("붙여넣을 항목이 없습니다.")
        blocked = self._ensure_file_ops(collection) or self._ensure_writable(
            collection, [item.get("system") for item in items])
        if blocked:
            return blocked
        policy = self._transfer_policy()
        unmatched = policy["unmatchedRom"]

        prepared, extra_skipped = [], []
        for item in items:
            if item.get("rom"):
                prepared.append({**item,
                                 "rom": item["rom"] if policy["includeRom"] else None,
                                 "media": item.get("media") if policy["includeMedia"] else []})
                continue
            # ROM 미매칭 - 이 항목의 원본에는 애초에 ROM 파일이 없었다(unmatchedRom, 사용자 결정).
            if unmatched["mode"] != "copy":
                extra_skipped.append({"filename": item["filename"], "reason": "ROM 미매칭 - 정책에 따라 건너뜀"})
                continue
            media = []
            for m in item.get("media") or []:
                wanted = unmatched["video"] if m.get("type") == VIDEO_MEDIA_TYPE else unmatched["media"]
                if wanted:
                    media.append(m)
            fields = item.get("fields") if unmatched["metadata"] else {}
            if not unmatched["metadata"] and not media:
                extra_skipped.append({"filename": item["filename"], "reason": "ROM 미매칭 - 정책에 따라 건너뜀"})
                continue
            prepared.append({**item, "fields": fields, "media": media})

        if not prepared:
            return ok({"added": 0, "skipped": extra_skipped, "conflicts": 0,
                      "source": descriptor.get("sourceName"), "policy": policy})

        plan = self._plan(collection_id)
        result = builder.plan_add(plan, collection, provider, prepared)
        keys = result.pop("conflictKeys", [])
        if policy["conflict"] in (RESOLVE_SKIP, RESOLVE_OVERWRITE):
            for key in keys:
                builder.resolve_conflict(plan, collection, provider, key, policy["conflict"])
            result["autoResolved"] = len(keys)
            result["conflicts"] = 0
        result["skipped"] = [*extra_skipped, *result.get("skipped", [])]
        return ok({**result, "source": descriptor.get("sourceName"), "policy": policy})

    def _transfer_policy(self):
        stored = (self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {}).get("transfer") or {}
        merged = {**self.TRANSFER_DEFAULTS, **{k: v for k, v in stored.items() if k in self.TRANSFER_DEFAULTS}}
        conflict = merged["conflict"] if merged["conflict"] in ("ask", RESOLVE_SKIP, RESOLVE_OVERWRITE) else "ask"
        mode = merged["unmatchedRomMode"] if merged["unmatchedRomMode"] in ("skip", "copy") else "skip"
        return {
            "includeRom": bool(merged["includeRom"]),
            "includeMedia": bool(merged["includeMedia"]),
            "conflict": conflict,
            # 화면과 테스트가 다루기 쉽도록 중첩된 모양으로 돌려준다. 저장은 평평하게 한다(위 참고).
            "unmatchedRom": {
                "mode": mode,
                "metadata": bool(merged["unmatchedRomMetadata"]),
                "media": bool(merged["unmatchedRomMedia"]),
                "video": bool(merged["unmatchedRomVideo"]),
            },
        }

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
        blocked = self._ensure_writable(collection, [entry.system for entry in plan.entries])
        if blocked:
            return blocked
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
                # Apply가 건드린 System만 다시 읽어 Cache를 실제 상태에 맞춘다.
                # 이걸 안 하면 방금 지운 게임이 목록에 남고 용량도 예전 값이 보인다.
                # 전체 Full Scan은 규모가 커지면 감당이 안 되므로 범위를 좁힌다.
                if result.get("systems"):
                    self.workspace.scan(collection_id, force=True, systems=result["systems"])
                self.registry.append_change(CHANGE_APPLIED, collection_id,
                                            {"applied": result["applied"]})
                return result
            finally:
                self.registry.release_lock(lock_name)

        job_id = self.jobs.run_phased((collection_id,), [("적용", run)], kind="apply")
        return ok({"jobId": job_id})

    # ------------------------------------------------------------------
    # Archive (스펙 §37-44)
    # ------------------------------------------------------------------
    @guarded
    def archive_ingest(self, collection_id, rom_uids=None, scope=None):
        """동기 수집. 프로그램 호출과 테스트용이다.

        **화면은 이 경로를 쓰지 않는다** - GUI는 `start_archive_ingest()`로 scope를
        명시해서 부른다. 여기서 `rom_uids=None`을 전체로 보는 것은 호출부가 대상을
        직접 나열하는 프로그램 경로에서만 통하는 편의다.
        """
        collection, cache, _ = self._plan_context(collection_id)
        if scope is not None:
            _kind, rom_uids = archive_service.resolve_scope(cache, scope)
        return ok(archive_service.ingest_collection(self.archive, collection, cache, rom_uids))

    @guarded
    def archive_ingest_preview(self, collection_id, scope=None):
        """이 scope로 수집하면 몇 개가 들어가는지. 버튼 라벨과 확인용이다."""
        _collection, cache, _ = self._plan_context(collection_id)
        kind, uids = archive_service.resolve_scope(cache, scope)
        return ok({"kind": kind, "count": len(uids),
                   "system": (scope or {}).get("system")})

    @guarded
    def start_archive_ingest(self, collection_id, scope=None):
        """Collection의 항목을 Archive에 수집한다. 출처는 Collection ID로 남는다.

        **대상은 화면이 준 scope로만 정한다**(§13). 예전에는 선택이 없으면 `None`을
        보냈고 백엔드가 그것을 "Collection 전체"로 해석해서, MSX1만 보고 있던 사용자가
        Collection 전체를 Archive에 넣게 되었다.

        수집은 게임 수만큼 DB 쓰기가 일어나므로 job으로 돌린다 - 동기로 부르면 큰
        Collection에서 창이 멈춘 것처럼 보이고 취소할 방법도 없다.
        """
        collection, cache, _ = self._plan_context(collection_id)
        kind, uids = archive_service.resolve_scope(cache, scope)
        log.info("archive ingest requested: collection=%s scope=%s system=%s targets=%d",
                 collection_id, kind, (scope or {}).get("system"), len(uids))

        def run(cb):
            result = archive_service.ingest_collection(
                self.archive, collection, cache, uids, progress_cb=cb)
            log.info("archive ingest done: scope=%s requested=%d ingested=%d",
                     kind, len(uids), len(result["ingestedRomUids"]))
            return {**result, "scope": kind}

        job_id = self.jobs.run_heavy(run, mutates_state=True, target_ids=(collection_id,),
                                     kind="archive-ingest")
        return ok({"jobId": job_id, "count": len(uids), "scope": kind})

    @guarded
    def archive_rows(self, search=None, systems=None, limit=200, offset=0):
        """Archive Gamelist. Collection 목록과 같은 모양으로 돌려준다(§43).

        Description/Genre/Rating은 `rom_identities`가 아니라 Revision의
        `fields_json`에 있다 - 여기서 안 채우면 화면은 Metadata 탭에는 값이
        보이는데 목록의 Description 칸만 늘 비어 있게 된다. Detail이 보여주는
        값과 같아야 하므로 `resolve_fields()`로 같은 우선순위(Preferred →
        Archive 편집 → Latest)를 쓴다.
        """
        query = {"search": search or None, "systems": systems or None}
        rows = self.archive.list_rows(**query, limit=int(limit), offset=int(offset))
        out_rows = []
        for r in rows:
            fields, _ = self.archive.resolve_fields(r["rom_identity_id"])
            out_rows.append({
                "romUid": r["rom_identity_id"], "romIdentityId": r["rom_identity_id"],
                "system": r["system"], "file": r["filename"], "title": r["title"],
                "sources": r["source_count"], "updatedAt": r["updated_at"],
                # 예전에는 False로 박아뒀다. Archive에 media가 저장돼 있어도
                # 목록에서는 영영 없는 것으로 보였다.
                "hasMetadata": True, "hasMedia": bool(r["media_count"]),
                "present": True, "size": 0,
                "storageId": "archive",
                "desc": fields.get("desc") or "",
                "region": r["region"] or fields.get("region") or "",
                "genre": fields.get("genre") or "",
                "rating": fields.get("rating") or "",
            })
        return ok({
            "rows": out_rows,
            "total": self.archive.count_rows(**query), "offset": int(offset),
        })

    @guarded
    def archive_uids(self, systems=None):
        """지금 필터(System)에 맞는 Archive 항목 전체의 romIdentityId.

        HERO의 "메타데이터 가져오기"가 쓴다(§4) - Archive에서 이 Collection으로
        당겨올 대상을 정할 때, 화면에 보이는 첫 페이지(archive_rows의 limit=200)만
        가져오면 Archive가 그보다 크면 뒷부분이 조용히 빠진다. list_rows(limit=None)은
        LIMIT 절 자체를 안 붙이므로 전부 온다.
        """
        rows = self.archive.list_rows(systems=systems or None, limit=None)
        return ok([r["rom_identity_id"] for r in rows])

    @guarded
    def archive_systems(self):
        return ok(self.archive.systems())

    @guarded
    def archive_detail(self, rom_identity_id):
        data = archive_service.detail(self.archive, rom_identity_id)
        return ok(data) if data else err("Archive 항목을 찾을 수 없습니다.")

    @guarded
    def get_archive_media_image(self, rom_identity_id, media_label, thumbnail=False):
        """Archive 항목의 media 이미지.

        Collection용 `get_media_image()`는 `collection_id` + `rom_uid`로 Cache를 뒤진다.
        Archive에는 그 둘 다 없다(식별자가 rom_identity_id다). 그래서 화면이 Archive
        탭에서도 Collection용 경로를 부르고 있었고, 조회가 조용히 실패해서 **Archive에
        media가 저장되어 있는데도 영영 보이지 않았다.**

        Archive는 파일을 복제하지 않고 원본 경로만 들고 있으므로(§37, D3), 그 경로가
        사라졌으면 그 media만 건너뛴다.
        """
        media_type = MEDIA_KEYS.get(media_label, str(media_label).lower())
        item = next((m for m in self.archive.media_refs(rom_identity_id)
                     if m["media_type"] == media_type), None)
        if item is None:
            return ok(None)
        return ok(self._encode_image(item["abs_path"], THUMBNAIL_MAX if thumbnail else None))

    @guarded
    def get_archive_media_video_url(self, rom_identity_id):
        """Archive 항목의 영상 URL. Archive는 원본 경로만 들고 있으므로 그 파일이 사라졌으면 None."""
        item = next((m for m in self.archive.media_refs(rom_identity_id)
                     if m["media_type"] == VIDEO_MEDIA_TYPE), None)
        url = self._media_server.url_for(item["abs_path"]) if item else None
        return ok({"url": url} if url else None)

    @guarded
    def archive_edit(self, rom_identity_id, fields):
        """Archive의 Metadata를 고친다. **Collection에는 반영되지 않는다**(§40)."""
        return ok(archive_service.edit(self.archive, rom_identity_id, fields))

    @guarded
    def archive_revisions(self, rom_identity_id, source_collection_id):
        """한 출처의 Revision 이력(ARCHIVE_REVISION_POLICY.md §14 Revision History)."""
        return ok(self.archive.revisions_of(rom_identity_id, source_collection_id))

    @guarded
    def archive_set_preferred(self, rom_identity_id, record_id):
        """이 Revision을 Preferred로 지정한다(정책 §8). 내용은 바뀌지 않는다."""
        return ok(archive_service.set_preferred(self.archive, rom_identity_id, int(record_id)))

    @guarded
    def archive_clear_preferred(self, rom_identity_id):
        return ok(archive_service.clear_preferred(self.archive, rom_identity_id))

    @guarded
    def archive_to_collection(self, collection_id, rom_identity_ids):
        """Archive 항목을 Collection으로 보낸다(§41).

        이미 있는 항목은 메타데이터만 즉시 반영하고(D1), 없는 항목은 파일을 옮겨야
        하므로 Plan에 올린다.
        """
        collection, cache, provider = self._plan_context(collection_id)
        result = archive_service.to_collection(self.archive, collection, cache, provider,
                                               rom_identity_ids)
        added = {"added": 0, "skipped": [], "conflicts": 0}
        if result["items"]:
            added = builder.plan_add(self._plan(collection_id), collection, provider,
                                     result["items"])
        return ok({
            "updated": result["updated"],
            "planned": added["added"], "conflicts": added.get("conflicts", 0),
            "skipped": result["skipped"] + added.get("skipped", []),
        })

    # ------------------------------------------------------------------
    # Match (스펙 §45-49)
    # ------------------------------------------------------------------
    @guarded
    def match_candidates(self, collection_id, rom_uid):
        """이 ROM과 같은 것일 수 있는 Archive 항목들. **자동으로 붙이지 않는다**(§49).

        사용자가 Match 버튼을 눌렀을 때만 불리는 경로이므로 Heuristic까지 본다.
        """
        cache = self.workspace.open(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        return ok(match_service.candidates_for(self.archive, collection_id, row, deep=True))

    @guarded
    def match_counts(self, collection_id, rom_uids):
        """Gamelist 뱃지용 후보 개수. 화면에 보이는 행만 넘길 것.

        가벼운 티어(Exact/Normalized)만 세므로, 여기서 0이어도 Match 다이얼로그를
        열면 Heuristic 후보가 나올 수 있다.
        """
        cache = self.workspace.open(collection_id)
        rows = [cache.get_row(int(uid)) for uid in (rom_uids or [])]
        rows = [r for r in rows if r is not None]
        counts = match_service.counts_for_rows(self.archive, collection_id, rows)
        return ok({str(uid): n for uid, n in counts.items()})

    @guarded
    def apply_match(self, collection_id, rom_uid, rom_identity_id, manual=False):
        """사용자가 고른 후보를 확정한다. 파일도 Metadata도 아직 건드리지 않는다.

        후보 목록에 없는 Identity는 거절한다 - `manual=True`를 명시해야 강제로 잇고,
        그때는 티어가 `manual`로 남아 엔진 판정과 구분된다. 지금 UI에는 강제 연결
        경로가 없고, Compare(Phase 6)처럼 사용자가 좌우를 직접 지목하는 화면이
        생길 때 쓰라고 열어 둔 것이다.
        """
        cache = self.workspace.open(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        return ok(match_service.apply_match(self.archive, collection_id, row,
                                            rom_identity_id, manual=bool(manual)))

    @guarded
    def clear_match(self, collection_id, rom_uid):
        cache = self.workspace.open(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        return ok({"cleared": match_service.clear_match(self.archive, collection_id, row)})

    # ------------------------------------------------------------------
    # Metadata 없는 Collection 시작하기
    # ------------------------------------------------------------------
    @guarded
    def metadata_status(self, collection_id):
        """gamelist가 없는 System이 있는지. Collection을 연 직후 물어보기 위한 것이다."""
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        provider = storage.for_path(collection.root_path)
        return ok(metadata_service.status(collection, provider))

    @guarded
    def generate_metadata(self, collection_id, systems=None):
        """ROM 목록만 담은 gamelist를 만든다. 이미 있는 파일은 건드리지 않는다."""
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        provider = storage.for_path(collection.root_path)
        clash = self._conflicts(collection)
        if systems:
            blocked = self._ensure_writable(collection, systems)
            if blocked:
                return blocked
        elif clash:
            # 전체 대상이면 충돌한 System만 빼고 만든다 - 하나 때문에 전부 막을 이유는 없다.
            systems = [e.system for e in collection.systems if e.system.lower() not in clash]
        return ok(metadata_service.generate(collection, provider, systems))

    # ------------------------------------------------------------------
    # Convert (스펙 §53)
    # ------------------------------------------------------------------
    @guarded
    def convert_preview(self, source_collection_id, target_collection_id):
        """이 변환에서 무엇이 넘어가고 무엇이 사라지는지. **아무것도 바꾸지 않는다.**

        Frontend 간 변환은 반드시 무언가를 잃으므로(§50-51), 실행 전에 그것을 보여줘야
        사용자가 판단할 수 있다.
        """
        if source_collection_id == target_collection_id:
            return err("같은 Collection으로는 변환할 수 없습니다.")
        source = self.registry.get_collection(source_collection_id)
        target = self.registry.get_collection(target_collection_id)
        if source is None or target is None:
            return err("Collection을 찾을 수 없습니다.")
        cache = self.workspace.open(source_collection_id)
        return ok(convert_service.preview(source, cache, target))

    @guarded
    def start_convert(self, source_collection_id, target_collection_id):
        """변환 결과를 target의 Plan에 올린다. Auto Plan이 꺼져 있어도 여기서는
        파일을 건드리지 않는다 - 확정은 언제나 Apply의 몫이다."""
        if source_collection_id == target_collection_id:
            return err("같은 Collection으로는 변환할 수 없습니다.")
        source = self.registry.get_collection(source_collection_id)
        if source is None:
            return err("원본 Collection을 찾을 수 없습니다.")
        source_cache = self.workspace.open(source_collection_id)
        target, _cache, provider = self._plan_context(target_collection_id)
        result = convert_service.plan_convert(self._plan(target_collection_id), source,
                                              source_cache, target, provider)
        return ok(result)

    # ------------------------------------------------------------------
    # Compare (스펙 §54-59)
    # ------------------------------------------------------------------
    @guarded
    def start_compare(self, base_collection_id, other_collection_id):
        """두 Collection을 맞대어 비교를 시작한다.

        비교 결과는 **여기서 한 번 계산해 들고 있는다**. 필터를 누를 때마다 두
        Collection을 다시 훑으면 만 단위 목록에서 버튼이 먹통이 되고, 무엇보다 그
        사이에 스캔이 끼면 필터마다 다른 스냅샷을 보게 된다. 최신 상태로 다시 보려면
        사용자가 명시적으로 다시 시작하면 된다.
        """
        if base_collection_id == other_collection_id:
            return err("같은 Collection끼리는 비교할 수 없습니다.")
        base = self.registry.get_collection(base_collection_id)
        other = self.registry.get_collection(other_collection_id)
        if base is None or other is None:
            return err("Collection을 찾을 수 없습니다.")

        left = self.workspace.open(base_collection_id).all_entries()
        right = self.workspace.open(other_collection_id).all_entries()
        rows = compare_engine.compare(left, right)
        self._compare = {"baseId": base_collection_id, "otherId": other_collection_id,
                         "rows": rows, "takenAt": time.time()}
        return ok(self._compare_state())

    @guarded
    def compare_state(self):
        """지금 Compare Mode인지와 요약. 아니면 data=None."""
        return ok(self._compare_state() if self._compare else None)

    def _compare_state(self):
        base = self.registry.get_collection(self._compare["baseId"])
        other = self.registry.get_collection(self._compare["otherId"])
        rows = self._compare["rows"]
        return {
            "baseId": self._compare["baseId"], "otherId": self._compare["otherId"],
            "baseName": base.name if base else "?",
            "otherName": other.name if other else "?",
            "counts": compare_engine.summarize(rows),
            "systems": sorted({r["system"] for r in rows}),
            # 이 결과는 시작 시점의 스냅샷이다. 그 사이 Collection이 바뀌었을 수
            # 있으므로 언제 찍은 것인지 화면이 말해줄 수 있어야 한다.
            "takenAt": self._compare.get("takenAt"),
        }

    @guarded
    def compare_rows(self, status=None, systems=None, search=None, limit=200, offset=0):
        """Compare Gamelist. 일반 Gamelist와 같은 모양으로 돌려준다."""
        if not self._compare:
            return err("Compare Mode가 아닙니다.")
        rows = compare_engine.filter_rows(self._compare["rows"], status)
        if systems:
            rows = [r for r in rows if r["system"] in systems]
        if search:
            needle = str(search).strip().lower()
            rows = [r for r in rows
                    if needle in r["file"].lower()
                    or needle in ((r["left"] or r["right"] or {}).get("title") or "").lower()]
        total = len(rows)
        page = rows[int(offset):int(offset) + int(limit)]
        return ok({"rows": [self._compare_row_summary(r) for r in page],
                   "total": total, "offset": int(offset)})

    @staticmethod
    def _compare_row_summary(row):
        side = row["left"] or row["right"] or {}
        return {
            # 좌우 어느 쪽에만 있을 수 있으므로 romUid는 목록의 키로 쓰지 않는다 -
            # (system, file)이 Compare 행의 안정적인 식별자다.
            "key": f"{row['system']}|{row['file']}",
            "system": row["system"], "file": row["file"],
            "title": side.get("title") or "",
            "size": side.get("size") or 0,
            "status": row["status"], "mediaDiff": row["mediaDiff"],
            "changedFields": row["changedFields"],
            "leftRomUid": (row["left"] or {}).get("romUid"),
            "rightRomUid": (row["right"] or {}).get("romUid"),
        }

    @guarded
    def compare_detail(self, key):
        """한 행의 좌우 Metadata를 나란히. 다른 필드는 changedFields로 알린다."""
        if not self._compare:
            return err("Compare Mode가 아닙니다.")
        row = next((r for r in self._compare["rows"]
                    if f"{r['system']}|{r['file']}" == key), None)
        if row is None:
            return err("항목을 찾을 수 없습니다.")
        state = self._compare_state()
        return ok({
            "key": key, "system": row["system"], "file": row["file"],
            "status": row["status"], "changedFields": row["changedFields"],
            "mediaDiff": row["mediaDiff"],
            "baseName": state["baseName"], "otherName": state["otherName"],
            "left": row["left"], "right": row["right"],
        })

    @guarded
    def exit_compare(self):
        """Compare Mode 종료(§58의 [Exit Compare])."""
        self._compare = None
        return ok(True)

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
        # **후속 job id를 결과에 실어 보낸다.** 단계마다 job이 새로 생기므로, 1단계
        # job만 지켜보면 그것이 끝나는 순간 화면은 "스캔 완료"로 알고 목록을 그린다.
        # 그런데 2단계가 여전히 Cache를 쓰고 있어서, 그 직후 보이는 개수가 실행할
        # 때마다 다르다(실제 백업에서 1,539 / 1,533 / 1,519로 흔들렸다).
        job_id = self.jobs.run_phased((collection_id,), phases, kind="scan",
                                      attach_followup_job_id=True)
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
        return ok([{"id": a.id, "label": a.display_name,
                    "mediaTypes": list(a.media_types)} for a in available()])

    @guarded
    def adapter_actions(self, collection_id):
        """이 Collection의 Frontend가 제공하는 고유 기능 목록(§22).

        Storage 같은 일반 기능으로 올리지 않는다 - ES-DE의 custom systems XML은
        ES-DE의 사정이고, 다른 Frontend는 같은 문제를 다른 방식으로 푼다.
        """
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        adapter = get_adapter(collection.frontend)
        return ok([{"id": a.id, "label": a.label} for a in adapter.extras()])

    @guarded
    def run_adapter_action(self, collection_id, action_id, storage_id=None):
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            return err("Collection을 찾을 수 없습니다.")
        adapter = get_adapter(collection.frontend)
        if action_id not in {a.id for a in adapter.extras()}:
            return err("이 Frontend가 지원하지 않는 기능입니다.")
        if action_id == getattr(adapter, "CUSTOM_SYSTEMS_ACTION", None):
            # storage_id를 주면 그 Storage만 대상으로 한다(실사용 피드백 - External이
            # 여러 개일 때 어느 그룹에서 눌러도 전체를 다시 쓰는 것은 의도와 다르다).
            return ok(adapter.write_custom_systems(collection, storage_id=storage_id))
        return err("아직 구현되지 않은 기능입니다.")

    # ------------------------------------------------------------------
    # RetroArch 실행 (app/launch/retroarch.py)
    # ------------------------------------------------------------------
    #: 설정은 앱 전역 Settings의 `emulator` 섹션에 둔다.
    #:   retroarchPath, coresDir - Settings 화면이 바로 고친다.
    #:   systemCores {system: core파일명}, gameCores {"system/파일명": core파일명} - 아래 메서드로만
    #:   고친다. save_app_settings는 한 단계 깊이까지만 병합하므로, 화면이 dict 일부만 보내면
    #:   나머지가 지워진다 - 그래서 여기서 읽고 고쳐서 통째로 쓴다.
    def _emulator(self):
        stored = (self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {}).get("emulator") or {}
        return {
            "retroarchPath": str(stored.get("retroarchPath") or ""),
            "coresDir": str(stored.get("coresDir") or ""),
            "systemCores": dict(stored.get("systemCores") or {}),
            "gameCores": dict(stored.get("gameCores") or {}),
        }

    @staticmethod
    def _game_core_key(system, filename):
        #: 게임 단위 Core는 System+파일명으로 기억한다. rom_uid는 다시 스캔하면 바뀌고, 같은 ROM을
        #: 다른 Collection에서 열어도 같은 Core로 실행되는 편이 자연스럽다.
        return f"{str(system or '').lower()}/{filename}"

    def _system_core(self, emulator, frontend, system):
        cores = emulator["systemCores"]
        key = str(system or "").lower()
        return cores.get(key) or cores.get(str(normalize_system(frontend, key)).lower())

    @guarded
    def retroarch_settings(self):
        emulator = self._emulator()
        return ok({**emulator, "cores": retroarch.list_cores(emulator["coresDir"]),
                   "unverified": sorted(retroarch.UNVERIFIED_SYSTEMS)})

    @guarded
    def set_retroarch_paths(self, retroarch_path, cores_dir):
        self.save_app_settings({"emulator": {"retroarchPath": str(retroarch_path or "").strip(),
                                             "coresDir": str(cores_dir or "").strip()}})
        return self.retroarch_settings()

    @guarded
    def set_system_core(self, system, core):
        """System 기본 Core. core가 비면 지정을 지운다. cores 폴더에 없는 파일은 거절한다."""
        key = str(system or "").strip().lower()
        if not key:
            return err("System이 필요합니다.")
        emulator = self._emulator()
        if core:
            if core not in retroarch.list_cores(emulator["coresDir"]):
                return err(f"Core 폴더에 없는 파일입니다: {core}")
            emulator["systemCores"][key] = core
        else:
            emulator["systemCores"].pop(key, None)
        self.save_app_settings({"emulator": {"systemCores": emulator["systemCores"]}})
        return ok(emulator["systemCores"])

    @guarded
    def set_game_core(self, system, filename, core):
        """이 게임에만 쓸 Core(System 기본값보다 우선). core가 비면 지정을 지운다."""
        if not system or not filename:
            return err("System과 파일명이 필요합니다.")
        emulator = self._emulator()
        key = self._game_core_key(system, filename)
        if core:
            if core not in retroarch.list_cores(emulator["coresDir"]):
                return err(f"Core 폴더에 없는 파일입니다: {core}")
            emulator["gameCores"][key] = core
        else:
            emulator["gameCores"].pop(key, None)
        self.save_app_settings({"emulator": {"gameCores": emulator["gameCores"]}})
        return ok(emulator["gameCores"])

    @guarded
    def apply_default_cores(self, systems):
        """아직 Core가 없는 System에 알려진 기본 Core를 채운다. 이미 정한 것은 덮어쓰지 않는다."""
        emulator = self._emulator()
        available = retroarch.list_cores(emulator["coresDir"])
        if not available:
            return err("Core 폴더가 없거나 비어 있습니다. Settings > Emulator에서 Core 폴더를 지정하세요.")
        applied = retroarch.default_cores_for(systems or [], available, emulator["systemCores"])
        if applied:
            self.save_app_settings({"emulator": {"systemCores": {**emulator["systemCores"], **applied}}})
        return ok({"applied": applied, "count": len(applied)})

    def _launch_target(self, collection_id, rom_uid):
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            raise WorkspaceError("Collection을 찾을 수 없습니다.")
        row = self.workspace.open(collection_id).get_row(int(rom_uid))
        if row is None:
            raise WorkspaceError("항목을 찾을 수 없습니다.")
        return collection, row

    @guarded
    def retroarch_game_info(self, collection_id, rom_uid):
        """Core 선택 창에 필요한 것 - 이 게임의 System 기본값/게임 지정/설치된 Core 목록."""
        collection, row = self._launch_target(collection_id, rom_uid)
        emulator = self._emulator()
        system_core = self._system_core(emulator, collection.frontend, row["system"])
        game_core = emulator["gameCores"].get(self._game_core_key(row["system"], row["filename"]))
        return ok({
            "system": row["system"], "file": row["filename"], "present": bool(row["present"]),
            "verified": retroarch.is_verified(row["system"]),
            "systemCore": system_core, "gameCore": game_core, "effectiveCore": game_core or system_core,
            "cores": retroarch.list_cores(emulator["coresDir"]), "coresDir": emulator["coresDir"],
        })

    @guarded
    def launch_game(self, collection_id, rom_uid):
        """게임을 RetroArch로 실행한다. 실패하면 화면이 다음 동작을 고를 수 있게 errorKind를 준다
        (core_unset/core_missing이면 Core 선택 창, retroarch_missing이면 Settings)."""
        collection, row = self._launch_target(collection_id, rom_uid)
        emulator = self._emulator()
        if not row["present"]:
            return {"ok": False, "error": "ROM 파일이 없는 항목입니다.", "errorKind": "rom_missing",
                    "system": row["system"]}
        layout = get_adapter(collection.frontend).layout(collection, row["system"])
        rom_path = Path(layout.rom_dir) / row["filename"]
        core = (emulator["gameCores"].get(self._game_core_key(row["system"], row["filename"]))
                or self._system_core(emulator, collection.frontend, row["system"]))
        result = retroarch.launch(emulator["retroarchPath"], emulator["coresDir"], core, rom_path, row["system"])
        log.info("RETROARCH_LAUNCH system=%s rom=%s core=%s ok=%s %s", row["system"], rom_path, core,
                 result.ok, result.error or "")
        if result.ok:
            return ok({"launched": True, "core": core})
        return {"ok": False, "error": result.error, "errorKind": result.error_kind, "system": row["system"]}

    @guarded
    def pick_file(self, title="", file_types=None, directory=""):
        """파일 하나를 고르는 대화상자(RetroArch 실행 파일 등). pywebview 버전별 인자 차이를 흡수한다."""
        import webview
        window = self._window or (webview.windows[0] if webview.windows else None)
        if window is None:
            return err("창을 찾을 수 없습니다.")
        base = {"file_types": tuple(file_types)} if file_types else {}
        result = None
        for kwargs in ({**base, "directory": directory or ""}, base, {}):
            try:
                result = window.create_file_dialog(webview.OPEN_DIALOG, **kwargs)
                break
            except TypeError:
                continue
        if not result:
            return ok(None)
        return ok(result[0] if isinstance(result, (list, tuple)) else result)

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
            # 전체화면(toggle_fullscreen)이 아니라 **최대화/복원**이다. frameless 창에서는
            # 이 버튼이 네이티브 제목 표시줄의 최대화를 대신하므로, 전체화면으로 들어가
            # 작업 표시줄까지 덮으면 사용자가 빠져나올 방법을 잃는다.
            if self._maximized:
                window.restore()
            else:
                window.maximize()
            self._maximized = not self._maximized
        elif action == "close":
            window.destroy()
        return ok(True)

    @guarded
    def window_resize(self, width, height):
        """창 크기를 바꾼다. frameless 창의 크기 조절 손잡이가 쓴다.

        frameless 창은 네이티브 크기 조절 테두리를 잃는다. 그 스타일을 Win32로
        되붙이는 방법은 창 생성 자체를 불안정하게 만들어 쓰지 않기로 했고, 대신
        UI의 손잡이가 이 메서드를 부른다.
        """
        import webview
        window = self._window or (webview.windows[0] if webview.windows else None)
        if window is None:
            return err("창을 찾을 수 없습니다.")
        window.resize(max(1, int(width)), max(1, int(height)))
        self._maximized = False
        return ok(True)

    @guarded
    def window_set_bounds(self, x, y, width, height):
        """창 위치와 크기를 함께 바꾼다. 위/왼쪽 테두리를 끌 때 쓴다.

        오른쪽/아래는 크기만 바꾸면 되지만, 왼쪽이나 위를 끌면 반대편 모서리가 제자리에
        있어야 하므로 위치도 같이 옮겨야 한다."""
        import webview
        window = self._window or (webview.windows[0] if webview.windows else None)
        if window is None:
            return err("창을 찾을 수 없습니다.")
        window.move(int(x), int(y))
        window.resize(max(1, int(width)), max(1, int(height)))
        self._maximized = False
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
