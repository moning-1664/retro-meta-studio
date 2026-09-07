"""
file_ops.py
============
File Operation Layer - 호출부(import_engine.py, export_engine.py,
exporters/*)가 파일 복사/이동이 필요할 때 바라보는 유일한 모듈.

지금은 엔진이 NativeWorkerEngine(media_copy_worker.py -> native/
MediaCopyWorker.exe) 하나뿐이라 엔진 선택은 사실상 no-op이다. 나중에
두 번째 엔진(예: Robocopy 기반)이 추가되면, 상황/설정에 따라 어떤
엔진을 쓸지 고르는 분기는 이 파일 안에서만 생긴다 - 호출부는 계속
`file_ops.copy_files(...)`만 부르면 되고 어떤 엔진이 실제로 동작했는지
알 필요가 없다.

세 함수의 계약(인자/반환값/타임아웃 시 동작)은 media_copy_worker.py의
동명 함수와 완전히 동일하다 - 여기서는 로직을 추가하지 않는다.
"""

from pathlib import Path

from engines.native_worker_engine import NativeWorkerEngine

_engine = NativeWorkerEngine()


def copy_pairs(pairs: list, timeout_sec: float = 120.0) -> dict:
    return _engine.copy_pairs(pairs, timeout_sec=timeout_sec)


def copy_files(dest_dirs, pairs: list, timeout_sec: float = 180.0) -> dict:
    return _engine.copy_files(dest_dirs, pairs, timeout_sec=timeout_sec)


def copy_finalize_groups(dest_dirs, groups: list, timeout_sec: float = 180.0) -> dict:
    return _engine.copy_finalize_groups(dest_dirs, groups, timeout_sec=timeout_sec)


def delete_files(paths, timeout_sec: float = 180.0) -> dict:
    """파일들을 삭제한다. 복사와 같은 이유로 네이티브 워커에 위임한다.

    copy_finalize_groups는 "그룹의 모든 copy가 성공해야 delete/rename을 실행한다"는
    계약이다. copy가 하나도 없으면 그 조건은 자동으로 참이므로, copies가 빈 그룹
    하나로 순수 삭제를 표현할 수 있다.

    다만 그 반환값은 copy 결과만 담기 때문에(삭제에 대한 항목별 성공 여부가 없다)
    실제로 사라졌는지를 여기서 직접 확인해서 돌려준다.

    반환: {str(path): 성공여부}
    """
    paths = [Path(p) for p in paths]
    if not paths:
        return {}
    copy_finalize_groups([], [{"copies": [], "deletes": paths, "renames": []}], timeout_sec=timeout_sec)
    return {str(p): not p.exists() for p in paths}


def move_files(pairs: list, timeout_sec: float = 300.0) -> dict:
    """(src, dest) 쌍을 이동한다. 볼륨이 달라도 동작한다.

    쌍마다 하나의 그룹으로 만들어 "임시 파일로 복사 -> 원본 삭제 -> 임시 파일을
    최종 이름으로 rename" 순서를 태운다. 복사가 실패하면 그룹 전체가 확정되지 않아
    **원본이 그대로 남는다** - 이동 도중 실패로 파일이 사라지는 사고를 구조적으로 막는다.

    반환: {str(dest): 성공여부}
    """
    pairs = [(Path(s), Path(d)) for s, d in pairs]
    if not pairs:
        return {}
    dest_dirs, groups, tmp_of = [], [], {}
    for src, dest in pairs:
        tmp = dest.with_name(dest.name + ".rmstmp")
        tmp_of[str(dest)] = str(tmp)
        dest_dirs.append(dest.parent)
        groups.append({"copies": [(src, tmp)], "deletes": [src], "renames": [(tmp, dest)]})
    results = copy_finalize_groups(dest_dirs, groups, timeout_sec=timeout_sec)
    # 그룹이 확정되면 tmp는 최종 이름으로 rename되어 사라진다. 복사 성공 + 최종 파일
    # 존재를 둘 다 확인해야 "이동이 끝났다"고 말할 수 있다.
    return {str(dest): bool(results.get(tmp_of[str(dest)])) and dest.exists() for _, dest in pairs}


class MediaCopyBatch:
    """[체감 속도] 여러 ROM의 media copy 쌍을 모아뒀다가 flush()에서 한 번에
    copy_files()를 호출한다 - ROM마다 즉시 copy_files()를 부르면 워커
    프로세스를 그만큼 반복 spawn하게 되어(각 pair는 이미 서로 독립적이라
    한 번의 호출에 몰아 넣어도 실패 격리는 그대로 유지됨), spawn 오버헤드가
    ROM 수에 비례해 누적된다. 호출부(export_engine.py)가 N개 ROM마다,
    그리고 루프 끝에 flush()를 불러준다."""

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
        # [실패 시 재시도 방지] copy_files() 호출 *전에* 버퍼를 비운다 - 만약
        # copy_files()가 예외를 던지면(예: worker/fallback 둘 다 실패), 이
        # pair들을 들고 있는 채로 남겨두면 다음 flush()가 실패한 pair를 또
        # 끌고 가서 배치가 무한히 자라거나 같은 실패를 반복 보고하게 된다.
        # 호출자가 예외를 못 받으면 그 배치는 조용히 유실되므로, 반드시
        # try/except로 감싸서 실패를 기록해야 한다.
        dest_dirs, pairs = self.dest_dirs, self.pairs
        self.dest_dirs, self.pairs = [], []
        kwargs = {} if timeout_sec is None else {"timeout_sec": timeout_sec}
        return copy_files(dest_dirs, pairs, **kwargs)
