"""
file_ops.py
============
File Operation Layer - 파일을 실제로 복사/이동/삭제해야 할 때 바라보는 유일한 모듈.

호출부는 어떤 엔진이 실제로 일하는지 몰라야 한다. 엔진 선택 분기는 이 파일 안에서만
생긴다.

## 엔진이 둘인 이유

부모 프로세스가 직접 대량 파일 작업을 하면 백신의 행동 기반 탐지(AhnLab
`Ransom/MDP.Event.M1875`)에 걸려 강제 종료된다. 그래서 실제 작업은 별도 프로세스에
맡긴다. 그 별도 프로세스로 무엇을 쓸지가 갈린다.

- **RobocopyEngine (기본)** — Windows에 기본 포함된 마이크로소프트 서명 바이너리다.
  서명이 있어서 백신이 문제 삼지 않는다.
- **NativeWorkerEngine** — 우리가 만든 `MediaCopyWorker.exe`. 서명이 없어서 실사용에서
  탐지되는 사례가 보고됐다. `GOLDEN_VALIDATION.md`의 무탐지 실측은 특정 시점의 한
  번일 뿐이고 탐지 규칙은 언제든 바뀐다.

기본값을 Robocopy로 두되 설정으로 바꿀 수 있게 한다. Robocopy를 찾을 수 없는 환경에서는
네이티브 워커로 자동 폴백한다(워커도 없으면 워커 모듈이 in-process fallback을 쓴다).
"""

from pathlib import Path

from engines.native_worker_engine import NativeWorkerEngine
from engines.robocopy_engine import RobocopyEngine, robocopy_available

ENGINE_ROBOCOPY = "robocopy"
ENGINE_WORKER = "worker"
ENGINE_AUTO = "auto"

_engine = None
_engine_name = ENGINE_AUTO


def select_engine(name=ENGINE_AUTO):
    """엔진을 고른다. 앱 시작 시 설정값으로 한 번 부르면 된다."""
    global _engine, _engine_name
    _engine_name = name or ENGINE_AUTO
    if _engine_name == ENGINE_WORKER:
        _engine = NativeWorkerEngine()
    elif _engine_name == ENGINE_ROBOCOPY:
        _engine = RobocopyEngine()
    else:
        _engine = RobocopyEngine() if robocopy_available() else NativeWorkerEngine()
    return _engine


def engine():
    return _engine if _engine is not None else select_engine()


def active_engine_name() -> str:
    """지금 실제로 쓰이는 엔진 이름(설정값이 auto여도 실체를 돌려준다)."""
    return getattr(engine(), "id", ENGINE_WORKER)


def copy_pairs(pairs: list, timeout_sec: float = 120.0) -> dict:
    return engine().copy_pairs(pairs, timeout_sec=timeout_sec)


def copy_files(dest_dirs, pairs: list, timeout_sec: float = 180.0) -> dict:
    return engine().copy_files(dest_dirs, pairs, timeout_sec=timeout_sec)


def copy_finalize_groups(dest_dirs, groups: list, timeout_sec: float = 180.0) -> dict:
    return engine().copy_finalize_groups(dest_dirs, groups, timeout_sec=timeout_sec)


def delete_files(paths, timeout_sec: float = 180.0) -> dict:
    """반환: {str(path): 성공여부}"""
    return engine().delete_paths([Path(p) for p in paths], timeout_sec=timeout_sec)


def move_files(pairs: list, timeout_sec: float = 300.0) -> dict:
    """반환: {str(dest): 성공여부}. 실패해도 원본은 남는다."""
    return engine().move_pairs([(Path(s), Path(d)) for s, d in pairs], timeout_sec=timeout_sec)


class MediaCopyBatch:
    """여러 ROM의 media copy 쌍을 모아뒀다가 flush()에서 한 번에 처리한다.

    ROM마다 즉시 복사를 부르면 그만큼 프로세스를 반복 spawn하게 되어 오버헤드가
    ROM 수에 비례해 누적된다. 각 pair는 이미 서로 독립적이라 한 번에 몰아넣어도
    실패 격리는 그대로 유지된다.
    """

    def __init__(self):
        self.dest_dirs = []
        self.pairs = []

    def add(self, dest_dirs, pairs):
        if isinstance(dest_dirs, (str, Path)):
            dest_dirs = [dest_dirs]
        self.dest_dirs.extend(dest_dirs)
        self.pairs.extend(pairs)

    def __len__(self):
        return len(self.pairs)

    def flush(self, timeout_sec=None):
        if not self.pairs:
            return {}
        # 복사를 부르기 *전에* 버퍼를 비운다. 예외가 나도 같은 pair를 다음 flush가
        # 다시 끌고 가서 배치가 무한히 자라거나 같은 실패를 반복 보고하지 않도록.
        # 호출자는 반드시 try/except로 감싸서 실패를 기록해야 한다.
        dest_dirs, pairs = self.dest_dirs, self.pairs
        self.dest_dirs, self.pairs = [], []
        kwargs = {} if timeout_sec is None else {"timeout_sec": timeout_sec}
        return copy_files(dest_dirs, pairs, **kwargs)
