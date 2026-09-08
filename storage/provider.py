"""
storage/provider.py
====================
물리 저장소 접근 추상화.

**이 계층의 존재 이유는 MTP다.** 드라이브 문자와 UNC(SMB)는 지금 코드가 그대로
쓸 수 있지만, MTP로 연결한 안드로이드 기기는 경로가 없어서 `open()`도 Native
Worker도 동작하지 않는다. 읽기를 전부 이 인터페이스로 통과시켜 두면, 나중에
MtpProvider 하나를 추가하는 것으로 끝난다 - 그렇게 해두지 않으면 앱 전체에 흩어진
`Path.stat()` / `os.scandir()` 호출을 나중에 다 찾아내야 한다.

## 무엇이 여기를 지나고 무엇이 CopyEngine을 지나는가

- **ROM/media 같은 덩어리 전송은 FileOperationEngine(`file_ops.py`)** 이 한다. 별도
  프로세스에 맡기는 이유는 백신의 행동 기반 탐지 때문이고, 그건 대량 파일 작업에만
  해당한다.
- **gamelist.xml 같은 "문서" 하나를 읽고 쓰는 것은 여기(`read_bytes`/`write_bytes`)** 다.
  Adapter가 `ET.parse(path)`로 직접 열면 경로 없는 저장소에서는 손도 못 댄다 -
  MTP를 붙일 수 있는 유일한 길이 이 두 메서드다.

경계는 크기가 아니라 **누가 그 바이트의 의미를 아는가**로 나뉜다. 내용을 파싱해서
고쳐 쓰는 쪽(Adapter)은 Provider를, 그대로 옮기기만 하는 쪽(Plan/Apply)은 Engine을
쓴다.

용량을 못 읽는 저장소는 예외를 던지지 않고 `VolumeInfo(capacity=None)`을
돌려준다. 스펙 §5가 Unknown을 허용하므로 상위 계층은 Capacity Check를 건너뛰면
된다 - 이 규칙 덕분에 SMB/MTP가 특별 분기 없이 흡수된다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stat:
    size: int
    mtime_ns: int
    is_dir: bool
    # 물리 파일 동일성 판정용. 서로 다른 Collection이 같은 파일을 가리킬 때 용량을
    # 두 번 더하지 않기 위해 쓴다(§81). 알 수 없으면 None.
    file_id: str | None = None


@dataclass(frozen=True)
class DirEntry:
    name: str
    path: str
    is_dir: bool
    size: int = 0
    mtime_ns: int = 0


@dataclass(frozen=True)
class VolumeInfo:
    """capacity/free가 None이면 Unknown - Capacity Check를 건너뛴다."""

    volume_key: str | None
    capacity_bytes: int | None
    free_bytes: int | None


class StorageProvider:
    """읽기 전용 접근 인터페이스. 구현체는 storage/local.py 등을 참고."""

    id: str = "base"
    #: File System Watcher를 신뢰할 수 있는가. False면 주기적 Validation Scan으로
    #: 대체한다(SMB/MTP).
    supports_watch: bool = False

    def exists(self, path) -> bool:
        raise NotImplementedError

    def stat(self, path) -> Stat | None:
        """없거나 접근할 수 없으면 None. 예외를 던지지 않는다."""
        raise NotImplementedError

    def scandir(self, path) -> list[DirEntry]:
        """없거나 접근할 수 없으면 빈 목록. 예외를 던지지 않는다."""
        raise NotImplementedError

    def volume_info(self, path) -> VolumeInfo:
        raise NotImplementedError

    def copy_engine(self):
        """이 저장소에 실제로 쓰기를 수행할 CopyEngine."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 문서 파일 내용 (gamelist.xml, metadata.pegasus.txt ...)
    # ------------------------------------------------------------------
    def read_bytes(self, path) -> "bytes | None":
        """파일 전체를 읽는다. 없거나 못 읽으면 None - 예외를 던지지 않는다.

        **ROM이나 media에 쓰라고 만든 것이 아니다.** 통째로 메모리에 올리므로
        Adapter가 파싱해야 하는 메타데이터 파일에만 쓴다.
        """
        raise NotImplementedError

    def write_bytes(self, path, data: bytes) -> bool:
        """부모 디렉터리까지 만들고 파일 전체를 쓴다. 성공 여부를 돌려준다.

        **부분 쓰기를 남기지 않아야 한다.** 도중에 실패해서 반쯤 쓰인 gamelist가
        남으면 그 System의 메타데이터를 통째로 잃는다 - 임시 파일에 쓰고 자리를
        바꾸는 식으로 구현한다.
        """
        raise NotImplementedError
