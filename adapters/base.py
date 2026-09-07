"""
adapters/base.py
=================
Frontend Adapter 인터페이스.

이전 프로젝트는 읽기(`importers/`)와 쓰기(`exporters/`)를 별도 패키지로 나눠
두었다. 같은 Frontend의 파일 형식을 아는 지식이 두 곳에 흩어져 있었고, 그래서
"읽을 때는 보존하는데 쓸 때는 버리는" 필드가 생기기 쉬웠다. 여기서는 하나의
Adapter가 그 Frontend의 읽기와 쓰기를 모두 책임진다.

## 계약 1 — bulk만 노출한다

`read_index`/`write_index`는 **System 단위 일괄 처리**다. ROM 하나짜리 읽기/쓰기
메서드를 두지 않는다.

이전 코드는 ROM마다 gamelist.xml을 다시 열어 파싱했고, ROM이 1,000개인 시스템은
같은 파일을 최대 2,000번 통째로 여는 O(n^2)가 됐다. 캐시와 flush로 고쳤지만
그건 인터페이스가 낱개 접근을 허용했기 때문에 생긴 문제였다. 낱개 API를 아예
제공하지 않으면 같은 실수를 구조적으로 할 수 없다.

## 계약 2 — 모르는 필드를 버리지 않는다

`to_common()`은 반드시 `(fields, frontend_raw)` 쌍을 돌려준다. 공통 모델로 옮길 수
없는 값은 전부 `frontend_raw`에 남기고, `from_common()`이 그것을 되살린다.
ES-DE -> 공통 모델 -> Pegasus -> 공통 모델 -> ES-DE 왕복에서 원래 있던 정보가
사라지면 안 된다(스펙 §50-51). 이 계약을 지키지 않는 Adapter는 통과시키지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Detection:
    """이 경로가 이 Frontend인지에 대한 판정. 확신이 없으면 confidence를 낮게 준다."""

    confidence: float
    systems: tuple[str, ...] = ()
    message: str = ""

    @property
    def matched(self) -> bool:
        return self.confidence > 0


@dataclass(frozen=True)
class Layout:
    """한 System이 디스크에서 어디에 놓이는지. Adapter가 Collection 설정으로부터 계산한다."""

    system: str
    rom_dir: str | None = None
    metadata_file: str | None = None
    media_dir: str | None = None


@dataclass
class MediaFile:
    media_type: str
    path: str
    size: int = 0
    mtime_ns: int = 0


@dataclass
class GameEntry:
    """Adapter가 읽어들인 게임 하나.

    fields: 공통 메타데이터(name/desc/genre/developer/publisher/releasedate/region/
            players/rating).
    frontend_raw: 공통 모델로 표현할 수 없어 원본 그대로 보관하는 값들(계약 2).
    """

    filename: str
    fields: dict = field(default_factory=dict)
    frontend_raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterAction:
    """Frontend 고유 기능. 예: ES-DE의 custom systems XML 생성(스펙 §22).

    Storage 같은 일반 기능으로 만들지 않고 해당 Adapter의 기능으로 둔다.
    """

    id: str
    label: str


class FrontendAdapter:
    id: str = "base"
    display_name: str = "Base"
    #: 이 Frontend가 다루는 media 종류
    media_types: tuple[str, ...] = ()

    # ------------------------------------------------------------------
    # 구조 파악
    # ------------------------------------------------------------------
    def detect(self, provider, root_path) -> Detection:
        raise NotImplementedError

    def list_systems(self, provider, collection) -> list[str]:
        raise NotImplementedError

    def layout(self, collection, system) -> Layout:
        """System의 실제 경로를 계산한다.

        Collection의 System은 각자 Storage에 속하고(§8) Storage마다 root_path가
        다르므로, 경로 계산은 반드시 이 메서드를 통해야 한다. 스캐너가 ES-DE의
        `gamelists/<system>/gamelist.xml` 같은 규칙을 직접 알면 안 된다.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 읽기 (bulk)
    # ------------------------------------------------------------------
    def read_index(self, provider, layout) -> dict[str, GameEntry]:
        """System 전체의 메타데이터를 한 번에 읽는다. 키는 ROM 파일명."""
        raise NotImplementedError

    def read_media_index(self, provider, layout, media_types=None) -> dict[str, list[MediaFile]]:
        """System 전체의 media를 한 번에 인덱싱한다. 키는 ROM stem.

        media_types를 주면 그 타입의 폴더만 실제로 열거한다 - 비디오처럼 무거운
        타입을 나중 단계로 미루기 위한 것이다.
        """
        raise NotImplementedError

    def list_roms(self, provider, layout) -> list[str]:
        raise NotImplementedError

    def media_dirs(self, layout, media_types=None) -> list[str]:
        """이 System의 media가 실제로 놓이는 디렉터리들.

        스캐너가 변경 감지를 위해 훑어야 할 대상을 알려주는 용도다. 폴더 이름 규칙은
        Frontend마다 다르므로 스캐너가 직접 알면 안 된다.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 쓰기 (bulk)
    # ------------------------------------------------------------------
    def write_index(self, layout, entries) -> None:
        """System 전체의 메타데이터를 한 번에 쓴다.

        entries에 없는 기존 항목을 지우지 않는다 - Export가 기존 데이터를 조용히
        삭제하면 안 된다(스펙 §70).
        """
        raise NotImplementedError

    def media_pairs(self, layout, filename, media) -> list[tuple[str, str]]:
        """media를 이 Frontend의 규칙에 맞는 목적지로 매핑한 (src, dest) 목록.

        실제 복사는 하지 않는다 - Plan이 이 목록으로 용량을 계산하고, Apply가
        FileOperationEngine에 넘긴다.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    def extras(self) -> list[AdapterAction]:
        return []


_ADAPTERS: dict[str, FrontendAdapter] = {}


def register(adapter: FrontendAdapter):
    _ADAPTERS[adapter.id] = adapter
    return adapter


def get_adapter(frontend_id) -> FrontendAdapter:
    try:
        return _ADAPTERS[frontend_id]
    except KeyError:
        raise KeyError(f"지원하지 않는 Frontend입니다: {frontend_id}") from None


def available() -> list[FrontendAdapter]:
    return list(_ADAPTERS.values())
