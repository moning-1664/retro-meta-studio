"""
media_copy_worker.py
=====================
Media 파일 복사(+관련 파일시스템 mutation)를 별도 네이티브 프로세스
(native/MediaCopyWorker.exe)에 위임한다.

배경: 패키징된(PyInstaller/Nuitka) RetroMetadataManager 프로세스가 자기
스레드에서 직접 shutil.copy2/CopyFileW로 대량 파일을 쓰면, AhnLab이 행동
기반 탐지(Ransom/MDP.Event.M1875)로 프로세스를 강제 종료한다 - 별도
브랜치의 copybench/ 진단 도구로 재현/확정됨(copybench/INCIDENT_T015_
pyinstaller.md 참고).

[v2] 처음엔 "CopyFileW만" 위임하고 mkdir/기존파일삭제/rename은 Python
(부모 프로세스)이 직접 했다. 그런데 실제 RetroMetadataManager 패키징
EXE + 실제 ES-DE Local(14,705개 media)로 검증했더니, 그렇게 해도 부모
프로세스 자신이 ROM마다 반복하는 mkdir/삭제/rename 자체가 M1875에
걸려 부모가 강제 종료됐다(2026-09-04 18:05:37 - headless_export.exe,
AhnLab 이벤트 로그로 확인). 그래서 이제 "복사 -> (전부 성공 시) 기존
파일 삭제 + rename까지"의 전체 lifecycle을 워커에 위임한다
(copy_finalize_groups) - 부모 프로세스는 "무엇을 할지 계획만 세워서
job으로 넘기는" 역할만 하고, 실제 파일시스템 mutation(mkdir/copy/
delete/rename)은 전부 워커 프로세스 안에서만 일어난다.

세 개의 공개 함수:
- copy_pairs(pairs): 단순 (src, dest) 목록을 독립적으로 복사만 한다
  (서로 연관 없음 - 하나 실패해도 다른 pair에 영향 없음).
- copy_files(dest_dirs, pairs): mkdir(들) + 단순 복사(삭제/rename 없음).
  ROM 복사, exporters/*의 "그냥 덮어쓰기" 스타일 media 복사가 이 형태다
  - copy_finalize_groups()의 얇은 래퍼.
- copy_finalize_groups(dest_dirs, groups): media type 단위의 원자적
  그룹(복사 -> 전부 성공하면 기존 파일 삭제 + rename)을 위임한다.
  import_engine.py의 _copy_media_to_masterdb()가 쓰는 게 이쪽이다.
  dest_dirs는 단일 Path 또는 여러 디렉터리의 list - Local 쪽 media
  구조(예: es-de 스타일 downloaded_media/<system>/<mediatype>/)는 media
  type마다 목적지 폴더가 달라서, 한 번의 워커 호출로 여러 디렉터리를
  한꺼번에 만들어야 하는 경우가 있다.

셋 다 워커 프로세스 자체가 실패(바이너리 없음/크래시/타임아웃/손상된
출력)하면 예외 없이 in-process fallback으로 전환한다 - 호출자는 항상
결과를 받는다고 신뢰할 수 있다.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

# [주의] config.BASE_DIR을 그대로 쓰면 안 된다 - config.BASE_DIR은 config.json을
# "실행 파일 옆의 영구적인 위치"에 두기 위해 일부러 sys.executable의 부모
# 디렉터리를 가리킨다. 반면 PyInstaller --onefile로 번들한 --add-binary
# 파일(MediaCopyWorker.exe)은 매 실행마다 sys._MEIPASS(임시 자기추출 폴더)에
# 풀린다 - onefile 실행 파일 자신이 있는 폴더가 아니다. 이 둘을 헷갈리면
# 워커를 못 찾는다.
if getattr(sys, "frozen", False):
    _meipass = getattr(sys, "_MEIPASS", None)
    _RUNTIME_BASE = Path(_meipass) if _meipass else Path(sys.executable).resolve().parent
else:
    _RUNTIME_BASE = Path(__file__).resolve().parent

WORKER_PATH = _RUNTIME_BASE / "native" / "MediaCopyWorker.exe"

_VALID_STATUSES = ("OK", "ERR")


def worker_available() -> bool:
    return WORKER_PATH.exists()


# ---------------------------------------------------------------------------
# 공유 파싱 로직 - copy_pairs()/copy_finalize_groups() 둘 다 워커 stdout을
# 같은 신뢰 규칙으로 해석해야 하므로 한 곳에 모은다.
# ---------------------------------------------------------------------------

def _parse_worker_output(stdout: str, idx_to_key: dict, returncode: int) -> dict:
    """"OK <index>"/"ERR <index> <code>" 줄을 파싱해서 {key: 성공여부}를
    만든다. idx_to_key: job에 쓴 C 명령의 index -> 그 pair를 식별하는 키
    (보통 str(tmp_or_dest_path)).

    [정책 - 두 종류의 실패를 다르게 다룬다]
    - "워커 프로세스 자체"가 실패한 신호(returncode>=2, 또는 returncode==0
      인데 파싱 결과에 실패가 섞여있는 계약 위반)는 RuntimeError를 던져서
      호출자가 전체를 in-process fallback으로 돌리게 한다.
    - "OK"/"ERR" 외의 status, 파싱 불가능한 라인, 같은 index의 중복 보고는
      전부 "이 pair에 대한 결과를 못 받았다"로 취급한다(딕셔너리에서 아예
      빠짐) - 손상된 출력을 실제 복사 실패로 오인하지 않기 위함. 호출자가
      비어있는 key들을 missing으로 모아 별도 처리해야 한다.
    - 워커가 정상적으로 살아서 특정 pair를 "ERR"로 명시적으로 보고한
      경우(예: ERROR_FILE_NOT_FOUND)는 그대로 False로 반환한다 - 재시도
      안 함(다시 시도해도 똑같이 실패할 뿐이므로).
    """
    if returncode >= 2:
        raise RuntimeError(f"worker process failure (returncode={returncode})")

    results: dict = {}
    seen_indices: set = set()
    malformed_indices: set = set()
    for line in stdout.splitlines():
        parts = line.split(" ", 2)
        if len(parts) < 2:
            continue
        status, idx_str = parts[0], parts[1]
        if status not in _VALID_STATUSES:
            continue
        try:
            idx = int(idx_str)
        except ValueError:
            continue
        if idx not in idx_to_key:
            continue
        if idx in malformed_indices:
            continue
        if idx in seen_indices:
            # 같은 index가 두 번 이상 보고됨 - 어느 쪽도 믿지 않는다.
            malformed_indices.add(idx)
            results.pop(idx_to_key[idx], None)
            seen_indices.discard(idx)
            continue
        seen_indices.add(idx)
        results[idx_to_key[idx]] = (status == "OK")

    if returncode == 0 and not all(results.values()):
        # 워커 계약: returncode==0은 ERR가 하나도 없었다는 뜻. 그런데도
        # False가 섞여 있으면 출력 자체를 신뢰할 수 없다.
        raise RuntimeError("worker returncode=0 but parsed output reports a failed copy")

    return results


# ---------------------------------------------------------------------------
# copy_pairs - 단순 독립 (src, dest) 복사
# ---------------------------------------------------------------------------

def copy_pairs(pairs: list, timeout_sec: float = 120.0) -> dict:
    """(src, dest) 목록을 복사하고 {str(dest): 성공여부}를 돌려준다. 각
    pair는 서로 독립적이다(하나가 실패해도 다른 pair의 결과에 영향 없음).

    어떤 이유로든 워커 경로가 신뢰할 수 없으면(바이너리 없음/타임아웃/
    손상된 출력 등) in-process shutil.copy2로 폴백한다 - 호출자는 이
    함수가 모든 pair에 대해 결과를 채워서 돌려준다고 신뢰할 수 있다.
    """
    if not pairs:
        return {}

    if not worker_available():
        return _copy_pairs_fallback(pairs)

    try:
        return _copy_pairs_via_worker(pairs, timeout_sec)
    except Exception:
        return _copy_pairs_fallback(pairs)


def _copy_pairs_via_worker(pairs: list, timeout_sec: float) -> dict:
    # 각 pair를 자기 자신만의 group(G)으로 감싼다 - pair끼리 서로 독립이어야
    # 하므로, 하나가 실패해도 워커가 "그룹 실패"로 다른 pair의 tmp를
    # 건드리면 안 된다(copy_finalize_groups처럼 여러 pair가 한 그룹으로
    # 묶여 함께 성공/실패해야 하는 경우와는 다른 계약).
    job_lines = []
    idx_to_key: dict = {}
    for i, (src, dest) in enumerate(pairs):
        job_lines.append("G\t_")
        job_lines.append(f"C\t{i}\t{src}\t{dest}")
        idx_to_key[i] = str(dest)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".job", delete=False, encoding="utf-8", newline="\n"
    ) as f:
        f.write("\n".join(job_lines) + "\n")
        job_path = Path(f.name)

    try:
        result = subprocess.run(
            [str(WORKER_PATH), str(job_path)],
            capture_output=True, text=True, timeout=timeout_sec,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    finally:
        try:
            job_path.unlink()
        except OSError:
            pass

    results = _parse_worker_output(result.stdout, idx_to_key, result.returncode)

    missing = [(src, dest) for i, (src, dest) in enumerate(pairs) if str(dest) not in results]
    if missing:
        results.update(_copy_pairs_fallback(missing))
    return results


def _copy_pairs_fallback(pairs: list) -> dict:
    import shutil

    results: dict = {}
    for src, dest in pairs:
        try:
            shutil.copy2(src, dest)
            results[str(dest)] = True
        except Exception:
            results[str(dest)] = False
    return results


# ---------------------------------------------------------------------------
# copy_files - "mkdir(들) + 단순 복사만, 삭제/rename 없음"인 호출부를 위한
# 얇은 래퍼. ROM 복사(export_engine.py)와 exporters/*의 "덮어쓰기만 하는"
# media 복사가 전부 이 형태다 - 애초에 삭제/rename 단계가 없었으므로
# copy_finalize_groups()의 그룹 원자성이 딱히 필요 없고, 그냥 mkdir을
# 부모 프로세스가 아니라 워커가 하게만 만들면 된다.
# ---------------------------------------------------------------------------

def copy_files(dest_dirs, pairs: list, timeout_sec: float = 180.0) -> dict:
    """dest_dirs(단일 경로 또는 리스트)를 mkdir한 뒤 pairs를 복사한다.
    각 pair는 서로 완전히 독립적이다(copy_pairs와 동일한 실패 격리).

    [버그 수정] 이 pair들을 전부 "그룹 하나"로 묶어서 보내면 안 된다 -
    copy_finalize_groups()의 그룹은 원자적이라, 그룹 안에 실패한 copy가
    하나라도 있으면 "이번에 성공했던 tmp들"까지 전부 정리(삭제)한다.
    여기서는 각 pair의 dest가 이미 최종 이름이라 "성공한 pair가 삭제되는"
    사고로 직결된다(실측 회귀: 파일 3개 중 1개만 존재하지 않는 소스여도
    성공한 나머지 2개까지 사라졌었음). pair마다 자기 자신만의(원소 1개)
    그룹으로 감싸서, 한 pair의 실패가 다른 pair에 아무 영향도 없게 한다
    (copy_pairs()가 이미 쓰는 것과 동일한 기법).

    반환: {str(dest): 성공여부}.
    """
    if not pairs:
        return {}
    groups = [{"copies": [pair], "deletes": [], "renames": []} for pair in pairs]
    return copy_finalize_groups(dest_dirs, groups, timeout_sec=timeout_sec)


# ---------------------------------------------------------------------------
# copy_finalize_groups - "복사 -> 전부 성공하면 기존파일 삭제+rename" 원자적
# 그룹. import_engine.py의 _copy_media_to_masterdb()가 media type 하나당
# 그룹 하나를 만들어 넘긴다.
# ---------------------------------------------------------------------------

def _normalize_dest_dirs(dest_dirs) -> list:
    """단일 Path/str 또는 리스트를 전부 Path 리스트로 정규화한다."""
    if isinstance(dest_dirs, (str, Path)):
        return [Path(dest_dirs)]
    return [Path(d) for d in dest_dirs]


def copy_finalize_groups(dest_dirs, groups: list, timeout_sec: float = 180.0) -> dict:
    """dest_dirs(단일 경로 또는 경로 리스트)를 전부 mkdir(parents=True)한
    뒤, groups의 각 그룹을 처리한다.

    groups: [{"copies": [(src, tmp), ...], "deletes": [path, ...],
              "renames": [(tmp, final), ...]}, ...]

    각 그룹은 원자적으로 다뤄진다: 그 그룹의 모든 copies가 성공해야만
    deletes(기존 파일 정리)와 renames(tmp -> final)가 실행된다. 하나라도
    실패하면 그 그룹은 아무것도 확정하지 않고, 이번에 새로 만든 tmp
    파일만 정리한다(기존 파일은 그대로 유지).

    반환: {str(tmp_path): 성공여부} - copies에 대한 결과만 돌려준다.
    호출자는 그룹의 모든 tmp가 True인지로 "이 그룹이 확정됐는가(=final
    경로들이 실제로 존재한다)"를 판단하면 된다 - delete/rename 자체는
    이 함수(또는 워커)가 이미 실행했으므로 호출자가 따로 할 일은 없다.

    워커 경로가 신뢰할 수 없으면(바이너리 없음/타임아웃/손상된 출력)
    in-process fallback으로 동일한 lifecycle(mkdir/copy/조건부 delete+
    rename)을 그대로 재현한다.
    """
    if not groups:
        return {}

    dest_dirs = _normalize_dest_dirs(dest_dirs)

    if not worker_available():
        return _copy_finalize_groups_fallback(dest_dirs, groups)

    try:
        return _copy_finalize_groups_via_worker(dest_dirs, groups, timeout_sec)
    except Exception:
        return _copy_finalize_groups_fallback(dest_dirs, groups)


def _copy_finalize_groups_via_worker(dest_dirs: list, groups: list, timeout_sec: float) -> dict:
    lines = [f"M\t{d}" for d in dest_dirs]
    idx_to_key: dict = {}
    idx = 0
    for group in groups:
        lines.append("G\t_")
        for src, tmp in group["copies"]:
            lines.append(f"C\t{idx}\t{src}\t{tmp}")
            idx_to_key[idx] = str(tmp)
            idx += 1
        for path in group["deletes"]:
            lines.append(f"X\t{path}")
        for tmp, final in group["renames"]:
            lines.append(f"R\t{tmp}\t{final}")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".job", delete=False, encoding="utf-8", newline="\n"
    ) as f:
        f.write("\n".join(lines) + "\n")
        job_path = Path(f.name)

    try:
        result = subprocess.run(
            [str(WORKER_PATH), str(job_path)],
            capture_output=True, text=True, timeout=timeout_sec,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    finally:
        try:
            job_path.unlink()
        except OSError:
            pass

    results = _parse_worker_output(result.stdout, idx_to_key, result.returncode)

    # 결과를 못 받은 index가 있으면, 그게 속한 그룹 "전체"를 in-process로
    # 다시 처리한다(pair 하나만 따로 재시도하지 않음 - "그룹 확정 여부"는
    # 항상 그 그룹의 모든 copy를 함께 봐야 하므로, 절반만 아는 상태로
    # delete/rename을 재현하면 원자성이 깨질 수 있다. 워커가 이미 그
    # 그룹을 확정지었더라도 fallback이 다시 처리하는 건 멱등적이라 안전함
    # - 같은 파일을 다시 복사/삭제/rename할 뿐).
    missing_keys = {key for key in idx_to_key.values() if key not in results}
    if missing_keys:
        affected_groups = []
        seen_group_ids = set()
        for group in groups:
            for _src, tmp in group["copies"]:
                if str(tmp) in missing_keys and id(group) not in seen_group_ids:
                    affected_groups.append(group)
                    seen_group_ids.add(id(group))
                    break
        results.update(_copy_finalize_groups_fallback(dest_dirs, affected_groups))

    return results


def _copy_finalize_groups_fallback(dest_dirs: list, groups: list) -> dict:
    import shutil

    for d in dest_dirs:
        d.mkdir(parents=True, exist_ok=True)
    results: dict = {}
    for group in groups:
        created_tmp = []
        all_ok = True
        for src, tmp in group["copies"]:
            try:
                shutil.copy2(src, tmp)
                results[str(tmp)] = True
                created_tmp.append(tmp)
            except Exception:
                results[str(tmp)] = False
                all_ok = False

        if all_ok:
            for path in group["deletes"]:
                try:
                    Path(path).unlink()
                except OSError:
                    pass
            for tmp, final in group["renames"]:
                try:
                    Path(tmp).replace(final)
                except OSError:
                    pass
        else:
            for tmp in created_tmp:
                try:
                    Path(tmp).unlink()
                except OSError:
                    pass
    return results
