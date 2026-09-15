"""
storage/mtp.py
===============
MTP(안드로이드 기기)용 StorageProvider - **gamelist.xml 같은 문서 전용**이다(사용자 결정).

`storage/provider.py` 머리말이 예고한 그 Provider다. 경계도 거기 적힌 그대로다:

- 문서 하나를 읽고 쓰는 것(`read_bytes`/`write_bytes`)은 여기가 한다.
- ROM/media 덩어리 전송은 하지 않는다 - `copy_engine()`은 이유를 붙여 거절한다.
  MTP는 부분 쓰기도, 원자적 교체도 없어서 대량 전송을 여기에 얹으면 실패했을 때
  무엇이 남았는지 알 수 없는 상태가 된다. 그건 ADB(나중 단계)의 몫이다.

## 경로

`mtp://<기기키>/<스토리지>/<그 아래 경로>` 형태다.

    mtp://R58N30ABCDE/Internal shared storage/ES-DE/gamelists/ps2/gamelist.xml

기기키는 WPD의 기기 ID(`\\\\?\\usb#vid_04e8&...`)가 아니라 **일련번호**다 - 원래 ID는
경로에 쓸 수 없는 문자가 섞여 있고, USB를 다시 꽂으면 바뀔 수 있다.

**구분자를 가리지 않고 받는다.** 앱 곳곳이 경로를 `Path()`에 태우는데, 그러면
`mtp://a/b`가 `mtp:\\a\\b`로 뭉개진다(슬래시가 하나로 줄고 역슬래시로 바뀐다).
경로를 만들 때는 늘 `mtp://`로 쓰되, 읽을 때는 그 변형까지 같은 것으로 본다.

## COM은 밖에 둔다

실제 WPD COM 호출은 `storage/mtp_wpd.py`가 한다. 여기서는 `MtpBackend` 인터페이스만
알고, 테스트는 메모리 트리로 만든 가짜 backend를 끼운다 - 기기 없이도 이 파일의
동작(경로 해석, 안전한 쓰기, 캐시)을 전부 검증하기 위해서다.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from storage.provider import DirEntry, Stat, StorageProvider, VolumeInfo

SCHEME = "mtp://"
#: `Path()`를 거치며 뭉개진 형태(`mtp:\a\b`, `mtp:/a/b`)까지 같은 경로로 본다.
_SCHEME_RE = re.compile(r"^mtp:[\\/]{1,2}", re.IGNORECASE)


class MtpError(Exception):
    """기기 연결/전송 실패. 호출부는 이 메시지를 그대로 사용자에게 보여줘도 된다."""


@dataclass(frozen=True)
class MtpObject:
    """기기 위의 객체 하나. `object_id`는 세션 안에서만 유효하다(다시 꽂으면 바뀐다)."""

    object_id: str
    name: str
    is_dir: bool
    size: int = 0
    mtime_ns: int = 0


@dataclass(frozen=True)
class MtpDeviceInfo:
    key: str          # 일련번호(경로에 쓰는 값)
    name: str         # 사용자에게 보여줄 이름
    device_id: str    # WPD 내부 ID


class MtpBackend:
    """COM이 해줘야 하는 일의 전부. 구현은 storage/mtp_wpd.py, 테스트는 가짜 구현."""

    def devices(self) -> list[MtpDeviceInfo]:
        raise NotImplementedError

    def children(self, device_key: str, object_id: str | None) -> list[MtpObject]:
        """`object_id`가 None이면 기기의 스토리지 목록(내장/SD)."""
        raise NotImplementedError

    def read(self, device_key: str, object_id: str) -> bytes:
        raise NotImplementedError

    def create(self, device_key: str, parent_id: str, name: str, data: bytes) -> str:
        """새 파일 객체를 만들고 그 object_id를 돌려준다. 같은 이름이 있으면 안 된다."""
        raise NotImplementedError

    def create_folder(self, device_key: str, parent_id: str, name: str) -> str:
        raise NotImplementedError

    def delete(self, device_key: str, object_id: str) -> None:
        raise NotImplementedError

    def storage_info(self, device_key: str, object_id: str) -> tuple[int | None, int | None]:
        """(전체 용량, 여유 공간). 모르면 (None, None)."""
        return (None, None)


# ----------------------------------------------------------------------
# 경로
# ----------------------------------------------------------------------
def is_mtp_path(path) -> bool:
    return bool(_SCHEME_RE.match(str(path or "")))


def split_path(path) -> tuple[str, list[str]]:
    """`mtp://키/a/b` -> ("키", ["a", "b"]). MTP 경로가 아니면 MtpError."""
    text = str(path or "")
    if not is_mtp_path(text):
        raise MtpError(f"MTP 경로가 아닙니다: {text}")
    rest = _SCHEME_RE.sub("", text).replace("\\", "/")
    parts = [p for p in rest.split("/") if p]
    if not parts:
        raise MtpError(f"기기를 알 수 없는 MTP 경로입니다: {text}")
    return parts[0], parts[1:]


def join_path(device_key: str, segments) -> str:
    """항상 `mtp://` 형태로 만든다 - 뭉개진 형태는 읽을 때만 받아준다."""
    parts = [str(s).strip("/\\") for s in segments if str(s).strip("/\\")]
    return SCHEME + "/".join([device_key, *parts])


# ----------------------------------------------------------------------
# Provider
# ----------------------------------------------------------------------
class MtpProvider(StorageProvider):
    id = "mtp"
    #: 기기는 파일 변경 알림을 주지 않는다 - 주기적으로 다시 읽는 수밖에 없다.
    supports_watch = False

    def __init__(self, backend: MtpBackend):
        self._backend = backend
        # 경로 -> 객체. 스캔이 같은 폴더를 반복해서 물어보는데, MTP는 한 번 물어보는
        # 값이 비싸다(객체마다 속성 조회가 따로 간다). 쓰기/삭제한 자리만 지운다.
        self._cache: dict[str, MtpObject | None] = {}
        self._lock = threading.RLock()

    # --- 내부 -----------------------------------------------------------
    @staticmethod
    def _key(device_key, segments) -> str:
        return join_path(device_key, segments).lower()

    def _resolve(self, path) -> MtpObject | None:
        """경로가 가리키는 객체. 없으면 None. 기기가 없으면 None(예외를 던지지 않는다)."""
        device_key, segments = split_path(path)
        with self._lock:
            cache_key = self._key(device_key, segments)
            if cache_key in self._cache:
                return self._cache[cache_key]

            found: MtpObject | None = None
            parent_id: str | None = None
            try:
                for index, name in enumerate(segments):
                    children = self._backend.children(device_key, parent_id)
                    match = next((c for c in children if c.name.lower() == name.lower()), None)
                    if match is None:
                        found = None
                        break
                    # 중간 단계도 같이 캐시해 둔다 - 다음 경로가 대부분 이 길을 다시 지난다.
                    self._cache[self._key(device_key, segments[:index + 1])] = match
                    found, parent_id = match, match.object_id
            except MtpError:
                return None
            self._cache[cache_key] = found
            return found

    def _forget(self, path) -> None:
        device_key, segments = split_path(path)
        with self._lock:
            self._cache.pop(self._key(device_key, segments), None)

    def _parent_id(self, device_key, segments) -> str | None:
        """부모 폴더의 object_id. 루트(스토리지 목록) 바로 아래면 None."""
        if not segments:
            return None
        parent = self._resolve(join_path(device_key, segments))
        return parent.object_id if parent else None

    # --- StorageProvider ------------------------------------------------
    def exists(self, path) -> bool:
        return self._resolve(path) is not None

    def stat(self, path) -> Stat | None:
        obj = self._resolve(path)
        if obj is None:
            return None
        # file_id는 없다 - 세션마다 object_id가 바뀌므로 동일성 판정에 쓸 수 없다.
        return Stat(size=obj.size, mtime_ns=obj.mtime_ns, is_dir=obj.is_dir, file_id=None)

    def scandir(self, path) -> list[DirEntry]:
        device_key, segments = split_path(path)
        try:
            if segments:
                obj = self._resolve(path)
                if obj is None or not obj.is_dir:
                    return []
                children = self._backend.children(device_key, obj.object_id)
            else:
                children = self._backend.children(device_key, None)   # 스토리지 목록
        except MtpError:
            return []

        entries = []
        with self._lock:
            for child in children:
                self._cache[self._key(device_key, [*segments, child.name])] = child
                entries.append(DirEntry(
                    name=child.name, path=join_path(device_key, [*segments, child.name]),
                    is_dir=child.is_dir, size=child.size, mtime_ns=child.mtime_ns))
        return entries

    def volume_info(self, path) -> VolumeInfo:
        """스토리지(첫 번째 segment)의 용량. 못 읽으면 Unknown - 스펙 §5가 허용한다."""
        device_key, segments = split_path(path)
        if not segments:
            return VolumeInfo(volume_key=device_key, capacity_bytes=None, free_bytes=None)
        storage = self._resolve(join_path(device_key, segments[:1]))
        capacity = free = None
        if storage is not None:
            try:
                capacity, free = self._backend.storage_info(device_key, storage.object_id)
            except MtpError:
                capacity = free = None
        return VolumeInfo(volume_key=f"{device_key}/{segments[0]}",
                          capacity_bytes=capacity, free_bytes=free)

    def copy_engine(self):
        raise MtpError(
            "MTP 기기에는 파일을 복사할 수 없습니다 - Metadata(gamelist)만 읽고 씁니다. "
            "ROM/Media를 옮기려면 ADB 연결이 필요합니다.")

    # --- 문서 읽기/쓰기 --------------------------------------------------
    def read_bytes(self, path) -> bytes | None:
        obj = self._resolve(path)
        if obj is None or obj.is_dir:
            return None
        device_key, _ = split_path(path)
        try:
            return self._backend.read(device_key, obj.object_id)
        except MtpError:
            return None

    def write_bytes(self, path, data: bytes) -> bool:
        """**반쯤 쓰인 파일을 남기지 않는다**(Provider 계약).

        MTP에는 덮어쓰기가 없다 - 지우고 새로 만드는 수밖에 없다. 그래서 지우기 전에
        원본을 메모리에 들고 있다가, 새로 만들기가 실패하면 원본을 되돌린다. 이걸 안
        하면 연결이 한 번 끊기는 것으로 그 System의 gamelist가 통째로 사라진다.
        """
        device_key, segments = split_path(path)
        if not segments:
            return False
        name = segments[-1]
        try:
            parent_id = self._ensure_dirs(device_key, segments[:-1])
        except MtpError:
            return False

        existing = self._resolve(path)
        backup = None
        if existing is not None:
            try:
                backup = self._backend.read(device_key, existing.object_id)
                self._backend.delete(device_key, existing.object_id)
            except MtpError:
                return False
            self._forget(path)

        try:
            self._backend.create(device_key, parent_id, name, data)
        except MtpError:
            if backup is not None:
                # 되살리기까지 실패하면 더 할 수 있는 것이 없다 - 예외로 알린다.
                try:
                    self._backend.create(device_key, parent_id, name, backup)
                except MtpError as e:
                    raise MtpError(
                        f"{name}을 쓰지 못했고 원본도 되돌리지 못했습니다. 기기에서 확인해주세요: {e}"
                    ) from e
            return False
        finally:
            self._forget(path)
        return True

    def _ensure_dirs(self, device_key, segments) -> str | None:
        """없는 중간 폴더를 만들며 내려간다. 부모의 object_id를 돌려준다."""
        parent_id: str | None = None
        for index, name in enumerate(segments):
            here = join_path(device_key, segments[:index + 1])
            obj = self._resolve(here)
            if obj is None:
                if parent_id is None and index == 0:
                    # 스토리지(내장/SD)는 우리가 만들 수 없다.
                    raise MtpError(f"기기에 없는 스토리지입니다: {name}")
                new_id = self._backend.create_folder(device_key, parent_id, name)
                obj = MtpObject(object_id=new_id, name=name, is_dir=True)
                with self._lock:
                    self._cache[self._key(device_key, segments[:index + 1])] = obj
            elif not obj.is_dir:
                raise MtpError(f"폴더가 아닙니다: {here}")
            parent_id = obj.object_id
        return parent_id

    # --- 기기 목록 ------------------------------------------------------
    def devices(self) -> list[MtpDeviceInfo]:
        return self._backend.devices()

    def forget_all(self) -> None:
        """연결이 끊겼을 때. object_id는 세션 밖에서 유효하지 않다."""
        with self._lock:
            self._cache.clear()


# ----------------------------------------------------------------------
# 프로세스 단위 인스턴스 - COM 세션과 경로 캐시를 공유한다.
# ----------------------------------------------------------------------
_instance: MtpProvider | None = None
_instance_lock = threading.RLock()


def provider() -> MtpProvider:
    """`storage.for_path()`가 쓰는 공용 Provider. 처음 부를 때 COM backend를 만든다."""
    global _instance
    with _instance_lock:
        if _instance is None:
            from storage.mtp_wpd import WpdBackend
            _instance = MtpProvider(WpdBackend())
        return _instance


def set_provider(instance: MtpProvider | None) -> None:
    """테스트가 가짜 backend를 끼울 때 쓴다."""
    global _instance
    with _instance_lock:
        _instance = instance
