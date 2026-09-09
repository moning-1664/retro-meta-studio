"""
app/workspace.py
=================
열려 있는 Collection들을 관리하는 서비스 계층.

UI(브릿지)는 이 클래스만 상대한다. Registry(등록 정보) / Cache(스캔 결과) /
Adapter(Frontend 지식) / Provider(물리 접근)를 어떻게 조합하는지는 여기서만 안다.

동시에 Open 가능한 Collection은 10개다(스펙 §2.2). 저장 가능한 개수 제한이 아니라
화면에 동시에 띄울 수 있는 개수 제한이다. Collection을 닫으면 Cache DB 연결만 닫고
캐시 파일과 실제 Collection은 그대로 둔다 - 다시 열 때 그 캐시로 즉시 화면을 그린다.
"""

from __future__ import annotations

from pathlib import Path

from adapters import get_adapter
from app import paths
from app.model.collection import (Collection, StorageLocation,
                                  STORAGE_INTERNAL)
from app.store.cache import CacheStore
from app.store.registry import CHANGE_SCAN_UPDATED, MAX_OPEN_COLLECTIONS, RegistryStore
from app.scan.scanner import scan_collection
import storage

import adapters.es_de             # noqa: F401  - Adapter 등록을 위한 import
import adapters.pegasus           # noqa: F401
import adapters.launchbox         # noqa: F401
import adapters.emulationstation  # noqa: F401


class WorkspaceError(Exception):
    pass


class Workspace:
    def __init__(self, registry: RegistryStore, cache_dir=None):
        self.registry = registry
        self.cache_dir = Path(cache_dir or paths.CACHE_DIR)
        self._open: dict[str, CacheStore] = {}

    def close(self):
        for cache in list(self._open.values()):
            cache.close()
        self._open.clear()

    # ------------------------------------------------------------------
    # Collection 생성 / 열기
    # ------------------------------------------------------------------
    def create_collection(self, name, frontend, root_path=None, *, rom_path=None,
                          media_path=None, **kwargs):
        """경로를 훑어 System을 찾아내고 Collection을 만든다.

        `root_path`는 **메타데이터가 있는 곳**(ES-DE라면 `gamelists/`가 있는 폴더),
        `rom_path`는 **ROM이 있는 곳**이다. 둘은 서로 독립이고 **둘 다 선택 사항**이다.
        ES-DE는 원래 이 둘을 떼어 놓는 Frontend이며(안드로이드의 외장 SD가 그 경우다),
        스크래핑을 한 번도 안 한 사용자는 ROM만 가지고 있다. 유효하지 않은 것은 **둘 다
        없을 때뿐이다**.

        **ROM 폴더를 별도 Storage로 만들지 않는다.** 예전에는 그렇게 했는데, Navigation이
        Storage → System 계층을 그대로 그리기 때문에 사용자에게 요구한 적 없는
        `Internal` / `ROM` 분류가 화면에 나타났다. Storage는 용량·볼륨·파일 작업을 위한
        내부 개념이고, 사용자가 보는 단위는 Collection → System → Game이다. ROM이 어디에
        있는지는 그 System의 속성(`rom_path`)으로 적는다 - Adapter가 이미 그것을 우선해서
        읽는다.

        `media_path`는 media가 또 다른 곳에 있을 때만 준다. 대개는 root 밑이다.
        """
        adapter = get_adapter(frontend)
        meta_root = str(root_path).strip() if root_path else ""
        rom_root = str(rom_path).strip() if rom_path else ""
        if not meta_root and not rom_root:
            raise WorkspaceError(
                "Metadata 디렉토리와 ROM 디렉토리 중 최소 하나는 지정해야 합니다.")

        # Collection root는 Metadata 위치를 우선한다. Metadata가 없는 ROM-only
        # Collection에서는 ROM 위치가 곧 root다.
        collection_root = meta_root or rom_root

        detection = (adapter.detect(storage.for_path(meta_root), meta_root)
                     if meta_root else None)
        meta_systems = tuple(detection.systems) if detection else ()

        rom_elsewhere = bool(rom_root) and not self._same_path(rom_root, collection_root)
        if rom_elsewhere:
            rom_systems = self._systems_under(adapter, frontend, rom_root)
        elif rom_root:
            # ROM 폴더가 곧 Collection root다 - Metadata를 안 줬거나(ROM-only) 두 경로가
            # 같은 경우다. 메타데이터로 찾은 것이 없으면 ROM 폴더를 직접 훑는다.
            rom_systems = meta_systems or self._systems_under(adapter, frontend, rom_root)
        else:
            rom_systems = ()

        systems = sorted(set(meta_systems) | set(rom_systems))
        if not systems:
            raise WorkspaceError(
                f"{adapter.display_name} 구조를 찾을 수 없습니다: "
                f"{detection.message if detection else '지정한 ROM 폴더에서 System을 찾지 못했습니다.'}")

        collection = self.registry.create_collection(name, frontend, collection_root, **kwargs)
        for system in systems:
            # ROM이 실제로 그 폴더에 있는 System만 경로를 적는다. 메타데이터만 있는
            # System에 ROM 경로를 적으면 있지도 않은 곳을 가리키게 된다.
            self.registry.upsert_system(
                collection.id, system, STORAGE_INTERNAL,
                rom_path=(str(Path(rom_root) / system)
                          if rom_elsewhere and system in rom_systems else None),
                media_path=str(Path(media_path) / system) if media_path else None)
        return self.registry.get_collection(collection.id)

    @staticmethod
    def _same_path(a, b) -> bool:
        return str(a).replace("/", "\\").rstrip("\\").lower() == \
               str(b).replace("/", "\\").rstrip("\\").lower()

    @staticmethod
    def _systems_under(adapter, frontend, rom_root) -> tuple:
        """그 폴더에서 ROM이 있는 System 이름들. 없으면 빈 튜플."""
        probe = Collection(id="probe", name="probe", frontend=frontend, root_path=rom_root,
                           storages=[StorageLocation(STORAGE_INTERNAL, STORAGE_INTERNAL,
                                                     "ROM", rom_root)])
        return tuple(adapter.list_systems(storage.for_path(rom_root), probe))

    def open(self, collection_id) -> CacheStore:
        if collection_id in self._open:
            return self._open[collection_id]
        if len(self._open) >= MAX_OPEN_COLLECTIONS:
            raise WorkspaceError(
                f"동시에 열 수 있는 Collection은 {MAX_OPEN_COLLECTIONS}개까지입니다. "
                "먼저 하나를 닫아주세요.")
        if self.registry.get_collection(collection_id) is None:
            raise WorkspaceError("Collection을 찾을 수 없습니다.")
        cache = CacheStore.open_for_collection(self.cache_dir, collection_id)
        self._open[collection_id] = cache
        return cache

    def close_collection(self, collection_id):
        """UI 상태만 없앤다. Cache와 실제 Collection 파일은 유지된다(스펙 §2.2)."""
        cache = self._open.pop(collection_id, None)
        if cache:
            cache.close()

    @property
    def open_ids(self) -> list[str]:
        return list(self._open)

    # ------------------------------------------------------------------
    # 스캔
    # ------------------------------------------------------------------
    def provider_for(self, collection):
        return storage.for_path(collection.root_path)

    def scan(self, collection_id, *, media_types=None, force=False, progress_cb=None,
             systems=None) -> dict:
        collection = self.registry.get_collection(collection_id)
        if collection is None:
            raise WorkspaceError("Collection을 찾을 수 없습니다.")
        cache = self.open(collection_id)
        adapter = get_adapter(collection.frontend)
        provider = self.provider_for(collection)

        result = scan_collection(collection, cache, provider, adapter,
                                 media_types=media_types, force=force,
                                 progress_cb=progress_cb, systems=systems)

        # 스캔으로 새로 발견된 System을 등록해 둬야 좌측 내비게이션과 Storage 배치가
        # 실제 디스크 상태를 따라간다.
        #
        # **어느 Storage에 넣을지는 실제 ROM 경로가 정한다.** 무조건 Internal로 넣으면
        # 외장 SD에 있는 System이 Internal로 등록되고, 그 순간부터 용량 표시가 통째로
        # 틀어진다(내장은 부풀고 외장은 비어 보인다).
        #
        # 이미 registry에 있는 System은 건드리지 않는다 - 사용자가 정해 둔 배치를
        # 스캔이 마음대로 되돌리면 안 된다.
        known = {s.system for s in collection.systems}
        for system in result["systems"]:
            if system not in known:
                self.registry.upsert_system(collection_id, system,
                                            self._storage_for_new_system(collection, provider, system))

        # 다른 인스턴스가 이 Collection을 열어두고 있다면 캐시를 다시 읽어야 한다(§9.3).
        self.registry.append_change(CHANGE_SCAN_UPDATED, collection_id,
                                    {"scanned": result["scanned"], "roms": result["roms"]})
        return result

    @staticmethod
    def _storage_for_new_system(collection, provider, system) -> str:
        """새로 발견된 System이 **실제로 놓여 있는** Storage.

        `adapter.layout()`에 물어보면 안 된다 - layout은 registry에 등록된 배치를
        근거로 경로를 만들기 때문에, 아직 등록되지 않은 System에 대해서는 언제나
        Collection root를 가리킨다(순환이다). 그래서 각 Storage의 root 밑에 그 이름의
        폴더가 실제로 있는지를 직접 본다.

        External을 먼저 본다. 양쪽에 같은 이름의 폴더가 있는 경우는 판단할 근거가
        없는데, 사용자가 명시적으로 추가한 쪽이 External이므로 그쪽을 택한다.
        """
        for storage in collection.storages:
            if storage.storage_id == STORAGE_INTERNAL or not storage.root_path:
                continue
            if provider.exists(Path(storage.root_path) / system):
                return storage.storage_id
        return STORAGE_INTERNAL

    # ------------------------------------------------------------------
    # 목록 조회
    # ------------------------------------------------------------------
    def rows(self, collection_id, **query):
        """Gamelist 한 페이지. 정렬/필터/검색/페이징은 전부 SQL이 처리한다."""
        return self.open(collection_id).query_rows(**query)

    def row_count(self, collection_id, **query) -> int:
        return self.open(collection_id).count_rows(**query)

    def storage_usage(self, collection_id) -> dict:
        """Storage별 Actual 사용량. Plan 계산의 기준값이 된다(§82)."""
        return self.open(collection_id).storage_usage()
