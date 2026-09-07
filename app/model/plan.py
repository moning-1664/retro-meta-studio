"""
app/model/plan.py
==================
Plan - 실제 파일을 바꾸기 전에 계산해두는 변경 집합.

**Plan은 세션 한정이다(결정 D2).** 메모리에만 존재하고 앱을 다시 켜면 사라진다.
그래서 DB 테이블이 없고, Plan과 실제 파일 상태가 어긋난 채로 되살아나는 위험도 없다.

**Plan에 들어가는 것은 저장 용량이 변하는 작업뿐이다(결정 D1).** 텍스트 메타데이터
편집은 저장 즉시 파일에 기록되고 Plan을 거치지 않는다. 덕분에 Plan의 의미가 화면의
`Actual -> Plan` 용량 표시와 정확히 일치한다.

용량 재계산은 O(1)이다. 엔트리를 넣고 뺄 때마다 Storage별 누적 델타를 갱신할 뿐,
Collection 전체를 다시 훑지 않는다. 수천 개를 한 번에 붙여넣는 시나리오(스펙 §88
Scenario 6)에서 이 차이가 체감 속도를 좌우한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

OP_ADD = "add"                        # 다른 Collection/Archive에서 가져오기
OP_DELETE = "delete"                  # 이 Collection에서 제거
OP_STORAGE_CHANGE = "storage_change"  # System을 다른 Storage로 이동

#: Gamelist Status 영역에 쓰는 기호(스펙 §24). 작고 명확하게만 표시하고
#: 제목이나 설명 전체를 색칠하지 않는다.
MARKS = {OP_ADD: "+", OP_DELETE: "-", OP_STORAGE_CHANGE: "△"}


@dataclass
class PlanEntry:
    op: str
    system: str
    filename: str = ""
    rom_uid: int | None = None
    #: add일 때 원본 정보 {collection_id, rom_path, rom_size, media:[...], fields, frontend_raw}
    source: dict | None = None
    storage_from: str | None = None
    storage_to: str | None = None
    #: 논리적 크기(사용자에게 보여줄 값)
    estimated_bytes: int = 0
    #: Storage별 실제 물리 증감 {storage_id: ±bytes}. 대상에 이미 같은 파일이 있으면 0이다.
    physical_delta: dict = field(default_factory=dict)
    #: 아직 디스크에 없는(add) 항목을 미리 편집했을 때의 메타데이터(위험요소 R7)
    payload: dict | None = None
    status: str = "pending"
    error: str | None = None

    @property
    def key(self) -> str:
        if self.op == OP_STORAGE_CHANGE:
            return f"{self.op}|{self.system}"
        return f"{self.op}|{self.system}|{self.filename}"

    @property
    def mark(self) -> str:
        return MARKS.get(self.op, "△")


class Plan:
    def __init__(self, collection_id):
        self.collection_id = collection_id
        self._entries: dict[str, PlanEntry] = {}
        self._delta: dict[str, int] = {}

    # ------------------------------------------------------------------
    def add(self, entry: PlanEntry) -> PlanEntry:
        """같은 대상에 대한 엔트리가 이미 있으면 교체한다(중복 누적 방지)."""
        existing = self._entries.get(entry.key)
        if existing is not None:
            self._apply_delta(existing.physical_delta, sign=-1)
        self._entries[entry.key] = entry
        self._apply_delta(entry.physical_delta, sign=1)
        return entry

    def remove(self, key) -> bool:
        entry = self._entries.pop(key, None)
        if entry is None:
            return False
        self._apply_delta(entry.physical_delta, sign=-1)
        return True

    def clear(self):
        self._entries.clear()
        self._delta.clear()

    def _apply_delta(self, delta, sign):
        for storage_id, value in (delta or {}).items():
            self._delta[storage_id] = self._delta.get(storage_id, 0) + sign * value
            if self._delta[storage_id] == 0:
                del self._delta[storage_id]

    # ------------------------------------------------------------------
    @property
    def entries(self) -> list[PlanEntry]:
        return list(self._entries.values())

    def __len__(self):
        return len(self._entries)

    def get(self, key) -> PlanEntry | None:
        return self._entries.get(key)

    def delta(self) -> dict[str, int]:
        """Storage별 누적 증감. Actual에 더하면 Plan 예상 사용량이 된다(스펙 §82)."""
        return dict(self._delta)

    def marks(self) -> dict[str, str]:
        """(system, filename) -> 기호. Gamelist가 행마다 조회한다.

        System 단위 이동은 그 System의 모든 항목에 △로 나타난다 - 개별 행에도
        변화가 예정되어 있다는 사실이 보여야 한다.
        """
        result = {}
        moved_systems = set()
        for entry in self._entries.values():
            if entry.op == OP_STORAGE_CHANGE:
                moved_systems.add(entry.system)
            else:
                result[f"{entry.system}|{entry.filename}"] = entry.mark
        return {"rows": result, "systems": sorted(moved_systems)}

    def summary(self) -> dict:
        added = [e for e in self._entries.values() if e.op == OP_ADD]
        deleted = [e for e in self._entries.values() if e.op == OP_DELETE]
        moved = [e for e in self._entries.values() if e.op == OP_STORAGE_CHANGE]
        return {
            "total": len(self._entries),
            "added": len(added), "deleted": len(deleted), "moved": len(moved),
            "addedBytes": sum(e.estimated_bytes for e in added),
            "deletedBytes": sum(e.estimated_bytes for e in deleted),
            "delta": self.delta(),
        }
