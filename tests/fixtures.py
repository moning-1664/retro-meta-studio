"""tests/fixtures.py
===================
테스트가 공유하는 Fixture 빌더와 작업 대기 헬퍼.

**왜 별도 모듈인가**: 이전 프로젝트(RetroGameManager)에서는 fixture 빌더가
`tests/test_api.py` 같은 *테스트 모듈* 안에 있었고, 다른 파일이 그걸 import하면
그 파일의 테스트까지 통째로 딸려 들어와 같이 실행됐다(tests/test_api.py:2279의
주석이 그 불편을 그대로 기록하고 있다). 그래서 여기에는 **테스트 케이스를 두지
않는다** - fixture와 헬퍼만 둔다.

크기에 대한 교훈도 하나 가져왔다: `GOLDEN_VALIDATION.md`가 적어둔 대로, 파일이
수백 개뿐인 fixture는 실제로 문제가 터지는 임계치 근방을 지나가 보지 못한다.
그래서 최소 트리(`build_esde_tree`)와 별개로 규모를 지정할 수 있는
`build_scaled_esde_tree()`를 둔다 - Match/성능처럼 "많아야 의미가 생기는" 테스트는
이쪽을 쓴다.
"""

import itertools
import os
import tempfile
from pathlib import Path

from app.model.collection import Collection, StorageLocation, SystemEntry, STORAGE_INTERNAL

# ----------------------------------------------------------------------
# 최소 트리 (대부분의 단위 테스트가 쓰는 것)
# ----------------------------------------------------------------------

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game id="42" source="ScreenScraper">
    <path>./FFX.iso</path>
    <name>Final Fantasy X</name>
    <desc>A role-playing game.</desc>
    <genre>RPG</genre>
    <developer>Square</developer>
    <publisher>Square Enix</publisher>
    <releasedate>20010719T000000</releasedate>
    <players>1</players>
    <rating>0.9</rating>
    <favorite>true</favorite>
    <playcount>17</playcount>
    <lastplayed>20240101T120000</lastplayed>
    <sortname>Final Fantasy 10</sortname>
    <altemulator>PCSX2</altemulator>
  </game>
  <game>
    <path>./MGS2.iso</path>
    <name>Metal Gear Solid 2</name>
  </game>
  <game>
    <path>./MetadataOnly.iso</path>
    <name>ROM 없는 항목</name>
  </game>
  <folder>
    <path>./Extras</path>
    <name>Extras</name>
  </folder>
</gameList>
"""


# ----------------------------------------------------------------------
# 파일 쓰기 - **수정 시각을 파일마다 어긋나게 찍는다**
# ----------------------------------------------------------------------
#
# 이걸 하지 않으면 테스트가 실행할 때마다 다른 결과를 낸다. Windows 시계는 약
# 15.6ms마다 갱신되는데 fixture는 그보다 훨씬 빨리 만들어진다. 그래서 서로 다른 두
# 트리(source와 target)를 잇달아 만들면 **같은 이름·같은 크기의 파일이 같은 수정
# 시각을 갖는 일**이 자주 생긴다.
#
# `classify_destination()`은 "크기와 시각이 정확히 같으면 이미 같은 파일"로 본다.
# 실제 파일에서는 옳은 판정이다(복사 도구가 타임스탬프를 보존하므로). 하지만 fixture가
# 우연히 그 조건을 만들면, 충돌을 기대한 테스트가 어떤 날은 통과하고 어떤 날은
# 실패한다. 흔들리는 쪽은 fixture이므로 fixture에서 고친다.
#
# 시각을 일부러 맞춰야 하는 테스트는 `shutil.copy2()`처럼 명시적으로 그렇게 한다.

_TICK = itertools.count(1)


def write_file(path: Path, data) -> Path:
    """fixture 파일을 쓰고 다른 파일과 겹치지 않는 수정 시각을 찍는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    stamp = path.stat().st_mtime_ns - next(_TICK) * 10 ** 9
    os.utime(path, ns=(stamp, stamp))
    return path


def build_esde_tree(root: Path) -> Path:
    """실제 ES-DE 레이아웃을 흉내낸 최소 트리."""
    (root / "gamelists" / "ps2").mkdir(parents=True)
    write_file(root / "gamelists" / "ps2" / "gamelist.xml", GAMELIST)
    for folder in ("covers", "screenshots", "videos"):
        (root / "downloaded_media" / "ps2" / folder).mkdir(parents=True)
    write_file(root / "downloaded_media" / "ps2" / "covers" / "FFX.png", b"x" * 10)
    write_file(root / "downloaded_media" / "ps2" / "videos" / "FFX.mp4", b"v" * 100)
    (root / "ps2").mkdir()
    write_file(root / "ps2" / "FFX.iso", b"r" * 1000)
    write_file(root / "ps2" / "MGS2.iso", b"r" * 2000)
    # ES-DE가 만들지만 게임 시스템이 아닌 폴더
    (root / "gamelists" / "cleanup").mkdir()
    return root


def make_collection(root) -> Collection:
    return Collection(
        id="col-1", name="Test", frontend="es-de", root_path=str(root),
        storages=[StorageLocation(STORAGE_INTERNAL, STORAGE_INTERNAL, "Internal", str(root))],
        systems=[SystemEntry("ps2", STORAGE_INTERNAL)],
    )


def temp_root(prefix="rms_") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


# ----------------------------------------------------------------------
# 규모를 지정할 수 있는 트리 (Match / 성능 테스트용)
# ----------------------------------------------------------------------

def _xml_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_scaled_esde_tree(root: Path, *, systems=("ps2", "snes"), per_system=50,
                           variant: str = "", with_media=True, rom_bytes=1024) -> Path:
    """게임 수를 지정할 수 있는 ES-DE 트리.

    `variant`는 같은 게임을 "다른 Collection에서 조금 다르게 부르는" 상황을 만든다 -
    Match(Exact/Normalized/Heuristic)를 검증하려면 두 트리가 완전히 같아서도, 완전히
    달라서도 안 되기 때문이다. 값에 따라 파일명/제목이 이렇게 갈린다:

    - ""        : `Game 001 (USA).iso` / "Game 001"            - 기준 트리
    - "region"  : `Game 001 (Europe).iso` / "Game 001"          - 이름은 같고 파일명만 다름
    - "rev"     : `Game 001 (USA) (Rev 1).iso` / "Game 001 (Rev 1)"
    - "ext"     : `Game 001 (USA).zip` / "Game 001"             - 확장자만 다름

    5번째 게임마다는 일부러 제목을 흔들어(`Game 005 II`) Exact/Normalized로는 안 붙고
    Heuristic 후보로만 잡히는 항목을 남긴다 - 자동 병합 금지(§49)를 검증하려면 "애매한
    후보"가 실제로 존재해야 한다.
    """
    suffix = {"": " (USA)", "region": " (Europe)", "rev": " (USA) (Rev 1)", "ext": " (USA)"}[variant]
    ext = ".zip" if variant == "ext" else ".iso"
    # 변종마다 크기를 어긋나게 둔다. 지역판은 실제로 다른 덤프라 바이트 수가 같을
    # 이유가 없고, 크기까지 같으면 Match 엔진이 (정규화 파일명 + 크기)로 Exact를
    # 확정해 버려서 "확증이 없으면 자동으로 붙이지 않는다"를 검증할 수 없다.
    size_offset = {"": 0, "region": 7, "rev": 13, "ext": 3}[variant]

    for system in systems:
        gamelist_dir = root / "gamelists" / system
        gamelist_dir.mkdir(parents=True, exist_ok=True)
        rom_dir = root / system
        rom_dir.mkdir(parents=True, exist_ok=True)
        if with_media:
            for folder in ("covers", "screenshots", "videos"):
                (root / "downloaded_media" / system / folder).mkdir(parents=True, exist_ok=True)

        entries = []
        for i in range(1, per_system + 1):
            base = f"Game {i:03d}"
            title = base if i % 5 else f"{base} II"
            if variant == "rev":
                title = f"{title} (Rev 1)"
            filename = f"{base}{suffix}{ext}"

            write_file(rom_dir / filename, b"r" * (rom_bytes + i + size_offset))
            if with_media:
                stem = Path(filename).stem
                write_file(root / "downloaded_media" / system / "covers" / f"{stem}.png", b"c" * 32)
                if i % 3 == 0:
                    write_file(root / "downloaded_media" / system / "videos" / f"{stem}.mp4", b"v" * 64)

            entries.append(
                f"  <game>\n"
                f"    <path>./{_xml_escape(filename)}</path>\n"
                f"    <name>{_xml_escape(title)}</name>\n"
                f"    <genre>Action</genre>\n"
                f"    <players>1</players>\n"
                f"  </game>"
            )
        write_file(gamelist_dir / "gamelist.xml",
                   '<?xml version="1.0"?>\n<gameList>\n' + "\n".join(entries) + "\n</gameList>\n")
    return root


def build_custom_esde_tree(root: Path, system: str, entries, *, with_media=False) -> Path:
    """항목을 하나씩 지정하는 ES-DE 트리. Match Golden Case용.

    `build_scaled_esde_tree()`는 규모를 만드는 데 쓰고, 이쪽은 "제목은 다른데 개발사와
    출시일이 같다" 같은 **정확한 조합**이 필요할 때 쓴다. 티어 판정은 필드 하나 차이로
    갈리므로, 그런 케이스를 규모 생성기의 부산물로 얻으려 하면 테스트가 무엇을
    검증하는지 읽을 수 없게 된다.

    entries: [{"filename", "title", "size"?, "developer"?, "publisher"?,
               "releasedate"?, "genre"?, "rom"?(False면 물리 파일 없음)}, ...]
    """
    gamelist_dir = root / "gamelists" / system
    gamelist_dir.mkdir(parents=True, exist_ok=True)
    rom_dir = root / system
    rom_dir.mkdir(parents=True, exist_ok=True)
    if with_media:
        (root / "downloaded_media" / system / "covers").mkdir(parents=True, exist_ok=True)

    games = []
    for entry in entries:
        filename = entry["filename"]
        if entry.get("rom", True):
            write_file(rom_dir / filename, b"r" * int(entry.get("size", 1024)))
        parts = [
            "  <game>",
            f"    <path>./{_xml_escape(filename)}</path>",
            f"    <name>{_xml_escape(entry['title'])}</name>",
        ]
        for tag in ("developer", "publisher", "releasedate", "genre"):
            if entry.get(tag):
                parts.append(f"    <{tag}>{_xml_escape(str(entry[tag]))}</{tag}>")
        parts.append("  </game>")
        games.append("\n".join(parts))

    header = '<?xml version="1.0"?>\n<gameList>\n'
    body = "\n".join(games)
    write_file(gamelist_dir / "gamelist.xml", header + body + "\n</gameList>\n")
    return root



# ----------------------------------------------------------------------
# 작업(Job) 대기 헬퍼
# ----------------------------------------------------------------------

def wait_idle(api, timeout=15.0):
    """모든 job이 끝날 때까지 기다린다."""
    if not api.jobs.wait_idle(timeout):
        raise AssertionError("작업이 끝나지 않았습니다.")


def wait_job(api, job_id, timeout=10.0):
    """phased job은 한 단계가 끝나며 다음 단계를 새 job으로 잇는다. 그래서 이 job
    하나가 done이 되어도 체인 전체는 아직 돌고 있을 수 있다 - 전부 끝날 때까지
    기다려야 tearDown이 워커가 쓰고 있는 DB 연결을 닫는 사고가 나지 않는다."""
    import threading
    event = threading.Event()
    for _ in range(int(timeout / 0.02)):
        job = api.jobs.get(job_id)
        if job and job["done"]:
            break
        event.wait(0.02)
    else:
        raise AssertionError("작업이 끝나지 않았습니다.")
    if not api.jobs.wait_idle(timeout):
        raise AssertionError("후속 phase가 끝나지 않았습니다.")
    return api.jobs.get(job_id)


def scan(api, cid, force=False):
    api.start_scan(cid, force)
    wait_idle(api)


# ----------------------------------------------------------------------
# MTP(안드로이드 기기) - 기기 없이 검증하기 위한 가짜 backend
# ----------------------------------------------------------------------
#
# 실제 COM 호출(storage/mtp_wpd.py)만 기기가 필요하고, 그 위(경로 해석·문서 읽기/쓰기·
# Collection 만들기·스캔)는 전부 이 메모리 트리로 검증한다. `app/launch/retroarch.py`가
# `popen`을 주입받아 프로세스 없이 검증되는 것과 같은 방식이다.

class FakeMtpBackend:
    """메모리 트리로 흉내 낸 MTP 기기. `put()`으로 파일을 심는다."""

    def __init__(self, device_key="R58N30ABCDE", device_name="Galaxy Test",
                 storages=("Internal shared storage", "SD card")):
        from storage.mtp import MtpDeviceInfo

        self.device = MtpDeviceInfo(key=device_key, name=device_name,
                                    device_id=r"\\?\usb#vid_04e8#" + device_key)
        self._next_id = 0
        self.tree = {"id": "DEVICE", "name": "", "is_dir": True, "children": {}}
        for name in storages:
            self._add(self.tree, name, is_dir=True)
        #: 호출 횟수 - "스캔이 기기를 몇 번 두드렸는가"를 검증할 때 쓴다.
        self.children_calls = 0
        self.reads = 0
        #: 앞으로 올 create() 중 몇 번을 실패시킬지(쓰기 실패/복구 실패 재현용).
        self.fail_next_creates = 0

    # --- 트리 만들기 ----------------------------------------------------
    def _add(self, parent, name, *, is_dir, data=b""):
        self._next_id += 1
        node = {"id": f"o{self._next_id}", "name": name, "is_dir": is_dir}
        if is_dir:
            node["children"] = {}
        else:
            node["data"] = data
        parent.setdefault("children", {})[name] = node
        return node

    def put(self, path: str, data: bytes):
        """`"Internal shared storage/ES-DE/gamelists/ps2/gamelist.xml"`에 파일을 심는다."""
        parts = [p for p in str(path).replace("\\", "/").split("/") if p]
        node = self.tree
        for name in parts[:-1]:
            node = node.get("children", {}).get(name) or self._add(node, name, is_dir=True)
        return self._add(node, parts[-1], is_dir=False, data=data)

    def mkdir(self, path: str):
        node = self.tree
        for name in [p for p in str(path).replace("\\", "/").split("/") if p]:
            node = node.get("children", {}).get(name) or self._add(node, name, is_dir=True)
        return node

    # --- 조회 -----------------------------------------------------------
    def _find(self, node, object_id):
        if node.get("id") == object_id:
            return node
        for child in node.get("children", {}).values():
            found = self._find(child, object_id)
            if found:
                return found
        return None

    def _node(self, object_id):
        from storage.mtp import MtpError

        node = self._find(self.tree, object_id if object_id is not None else "DEVICE")
        if node is None:
            raise MtpError(f"없는 객체: {object_id}")
        return node

    def _parent_of(self, node, object_id):
        for child in node.get("children", {}).values():
            if child["id"] == object_id:
                return node
            found = self._parent_of(child, object_id)
            if found:
                return found
        return None

    # --- MtpBackend 인터페이스 -------------------------------------------
    def devices(self):
        return [self.device]

    def children(self, device_key, object_id):
        from storage.mtp import MtpObject

        self.children_calls += 1
        node = self._node(object_id)
        return [MtpObject(object_id=c["id"], name=c["name"], is_dir=c["is_dir"],
                          size=len(c.get("data", b"")), mtime_ns=0)
                for c in node.get("children", {}).values()]

    def read(self, device_key, object_id):
        self.reads += 1
        return self._node(object_id)["data"]

    def create(self, device_key, parent_id, name, data):
        from storage.mtp import MtpError

        if self.fail_next_creates > 0:
            self.fail_next_creates -= 1
            raise MtpError("기기 쓰기 실패")
        return self._add(self._node(parent_id), name, is_dir=False, data=data)["id"]

    def create_folder(self, device_key, parent_id, name):
        return self._add(self._node(parent_id), name, is_dir=True)["id"]

    def delete(self, device_key, object_id):
        node = self._node(object_id)
        del self._parent_of(self.tree, object_id)["children"][node["name"]]

    def storage_info(self, device_key, object_id):
        storages = self.tree.get("children", {})
        first = next(iter(storages.values()), None)
        if first is not None and object_id == first["id"]:
            return (64 * 1024 ** 3, 20 * 1024 ** 3)
        return (None, None)


def mtp_gamelist(games) -> bytes:
    """`[(파일명, 제목), ...]` -> gamelist.xml 바이트."""
    entries = "".join(
        f"  <game>\n    <path>./{_xml_escape(filename)}</path>\n"
        f"    <name>{_xml_escape(title)}</name>\n  </game>\n"
        for filename, title in games)
    return f'<?xml version="1.0"?>\n<gameList>\n{entries}</gameList>\n'.encode("utf-8")


def build_mtp_device(*, with_roms=True) -> "FakeMtpBackend":
    """ES-DE가 깔린 안드로이드 기기 흉내.

    Internal shared storage/
      ES-DE/gamelists/{ps2,snes}/gamelist.xml
      ROMs/{ps2,snes}/<ROM 파일>          (with_roms=False면 만들지 않는다)
    """
    backend = FakeMtpBackend()
    root = "Internal shared storage"
    backend.put(f"{root}/ES-DE/gamelists/ps2/gamelist.xml",
                mtp_gamelist([("FFX (U).iso", "Final Fantasy X"), ("MGS2 (E).iso", "Metal Gear Solid 2")]))
    backend.put(f"{root}/ES-DE/gamelists/snes/gamelist.xml",
                mtp_gamelist([("SMW.sfc", "Super Mario World")]))
    backend.mkdir(f"{root}/ES-DE/downloaded_media/ps2/covers")
    # 커버 한 장. 기기에서 그림을 읽어 오는 경로(Provider 경유)를 검증하기 위한 것이다.
    backend.put(f"{root}/ES-DE/downloaded_media/ps2/covers/FFX (U).png", b"c" * 32)
    if with_roms:
        backend.put(f"{root}/ROMs/ps2/FFX (U).iso", b"r" * 2048)
        backend.put(f"{root}/ROMs/ps2/MGS2 (E).iso", b"r" * 1024)
        backend.put(f"{root}/ROMs/snes/SMW.sfc", b"r" * 512)
    return backend


def use_fake_mtp(test_case, backend=None) -> "FakeMtpBackend":
    """가짜 기기를 `storage.for_path()`에 끼운다. 테스트가 끝나면 원래대로 돌린다."""
    from storage.mtp import MtpProvider, set_provider

    backend = backend or build_mtp_device()
    set_provider(MtpProvider(backend))
    test_case.addCleanup(set_provider, None)
    return backend
