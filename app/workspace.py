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
from app.model.collection import STORAGE_INTERNAL
from app.store.cache import CacheStore
from app.store.registry import CHANGE_SCAN_UPDATED, MAX_OPEN_COLLECTIONS, RegistryStore
from app.scan.scanner import scan_collection
from storage.local import LocalStorageProvider

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
    def create_collection(self, name, frontend, root_path, **kwargs):
        """경로를 훑어 System을 찾아내고 Internal Storage에 배치한 Collection을 만든다.

        External Storage는 만들지 않는다 - 사용자가 나중에 "Add External Storage"로
        추가한다(스펙 §9).
        """
        adapter = get_adapter(frontend)
        provider = LocalStorageProvider.for_path(root_path)
        detection = adapter.detect(provider, root_path)
        if not detection.matched:
            raise WorkspaceError(f"{adapter.display_name} 구조를 찾을 수 없습니다: {detection.message}")

        collection = self.registry.create_collection(name, frontend, root_path, **kwargs)
        for system in detection.systems:
            self.registry.upsert_system(collection.id, system, STORAGE_INTERNAL)
        return self.registry.get_collection(collection.id)

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
        return LocalStorageProvider.for_path(collection.root_path)

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
        known = {s.system for s in collection.systems}
        for system in result["systems"]:
            if system not in known:
                self.registry.upsert_system(collection_id, system, STORAGE_INTERNAL)

        # 다른 인스턴스가 이 Collection을 열어두고 있다면 캐시를 다시 읽어야 한다(§9.3).
        self.registry.append_change(CHANGE_SCAN_UPDATED, collection_id,
                                    {"scanned": result["scanned"], "roms": result["roms"]})
        return result

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
