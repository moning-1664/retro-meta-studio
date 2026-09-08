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
    #: ROM이 Collection root 밖에 있을 때 그 폴더에 붙이는 Storage id.
    ROM_STORAGE_ID = "roms"

    def create_collection(self, name, frontend, root_path, *, rom_path=None,
                          media_path=None, **kwargs):
        """경로를 훑어 System을 찾아내고 Collection을 만든다.

        `root_path`는 **메타데이터가 있는 곳**이다(ES-DE라면 `gamelists/`가 있는 폴더).

        `rom_path`를 따로 주면 ROM은 그쪽에서 찾는다. ES-DE는 원래 메타데이터와 ROM을
        떼어 놓는 Frontend이고(안드로이드의 외장 SD가 그 경우다), 사용자의 실제 배치도
        그렇다. 하나만 받으면 **ROM만 있거나 메타데이터만 있는 Collection**밖에 만들 수
        없다.

        ROM 폴더는 별도 Storage로 붙인다 - 용량이 다른 디스크에 쌓이므로 그렇게 해야
        내장/외장 표시가 실제와 맞는다(§9).

        `media_path`는 media가 또 다른 곳에 있을 때만 준다. 대개는 root 밑이다.
        """
        adapter = get_adapter(frontend)
        detection = adapter.detect(storage.for_path(root_path), root_path)

        rom_root = str(rom_path).strip() if rom_path else ""
        rom_systems = ()
        if rom_root and not self._same_path(rom_root, root_path):
            rom_systems = self._systems_under(adapter, frontend, rom_root)

        systems = sorted(set(detection.systems) | set(rom_systems))
        if not systems:
            raise WorkspaceError(
                f"{adapter.display_name} 구조를 찾을 수 없습니다: {detection.message}")

        collection = self.registry.create_collection(name, frontend, root_path, **kwargs)
        if rom_systems:
            self.registry.add_storage(collection.id, self.ROM_STORAGE_ID, kind="external",
                                      label="ROM", root_path=rom_root)
        for system in systems:
            # ROM이 그 폴더에 실제로 있는 System만 그쪽으로 보낸다. 메타데이터만 있는
            # System을 ROM Storage에 붙이면 있지도 않은 곳을 가리키게 된다.
            storage_id = self.ROM_STORAGE_ID if system in rom_systems else STORAGE_INTERNAL
            self.registry.upsert_system(
                collection.id, system, storage_id,
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
