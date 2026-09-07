"""
app/model/collection.py
========================
Collection / Storage / System 모델.

핵심 규칙 두 가지가 여기서 타입으로 표현된다.

- **Frontend != Target != OS != Architecture** (스펙 §5). 네 값을 하나로 묶지
  않는다. 모르는 값은 추측하지 않고 `None`(= Unknown)으로 둔다.
- **하나의 System은 정확히 하나의 Storage에 속한다** (스펙 §8). `SystemEntry`가
  `storage_id`를 단일 값으로 갖기 때문에 "PS2의 일부는 Internal, 일부는 External"
  같은 상태는 표현 자체가 불가능하다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

STORAGE_INTERNAL = "internal"

FRONTENDS = ("es-de", "pegasus", "launchbox", "emulationstation")
TARGETS = ("windows", "android", "linux")
ARCHITECTURES = ("x64", "arm64", "arm32")


@dataclass
class StorageLocation:
    """Collection 안의 물리 저장 위치. 앱 최상위 Entity가 아니다(스펙 §7)."""

    storage_id: str
    kind: str  # "internal" | "external"
    label: str
    root_path: str
    # 물리 볼륨 식별자. 서로 다른 Collection이 같은 디스크를 쓸 때 용량을 두 번
    # 더하지 않기 위한 키(스펙 §81).
    volume_key: str | None = None
    # 마지막으로 관측한 총 용량. None이면 Unknown - MTP나 일부 네트워크 공유처럼
    # 용량을 못 읽는 저장소는 Capacity Check를 건너뛴다(스펙 §5, §20).
    capacity_bytes: int | None = None

    @property
    def is_external(self) -> bool:
        return self.kind != STORAGE_INTERNAL


@dataclass
class SystemEntry:
    """Collection 안의 하나의 게임 플랫폼. 반드시 하나의 Storage에 속한다."""

    system: str
    storage_id: str
    rom_path: str | None = None
    media_path: str | None = None
    metadata_path: str | None = None


@dataclass
class Collection:
    """하나의 Frontend 환경을 나타내는 논리적 게임 라이브러리.

    "Master" 같은 특수 타입은 없다(스펙 §2.1). 사용자가 이름을 'Master Library'로
    지어서 대규모 원본으로 쓸 수는 있지만 앱은 그것을 특별 취급하지 않는다.
    """

    id: str
    name: str
    frontend: str
    root_path: str
    target: str | None = None
    os: str | None = None
    arch: str | None = None
    storages: list[StorageLocation] = field(default_factory=list)
    systems: list[SystemEntry] = field(default_factory=list)
    ui_state: dict = field(default_factory=dict)

    def storage(self, storage_id: str) -> StorageLocation | None:
        return next((s for s in self.storages if s.storage_id == storage_id), None)

    def storage_of_system(self, system: str) -> StorageLocation | None:
        entry = next((s for s in self.systems if s.system == system), None)
        return self.storage(entry.storage_id) if entry else None

    def systems_in(self, storage_id: str) -> list[SystemEntry]:
        return [s for s in self.systems if s.storage_id == storage_id]
