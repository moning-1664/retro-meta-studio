"""
engines/base.py
================
파일 복사 엔진이 구현해야 하는 최소 인터페이스(계약).

file_ops.py(File Operation Layer)는 이 3개 메서드만 알면 되고, 어떤
엔진이 실제로 mkdir/copy/delete/rename을 수행하는지는 몰라야 한다.
지금은 NativeWorkerEngine 하나뿐이지만, 나중에 RobocopyEngine을
추가할 때도 이 3개만 구현하면 file_ops.py를 건드리지 않고 끼워넣을 수
있다 - 단, syntactic하게 같은 메서드 시그니처를 갖는 것만으로는
부족하다. 아래에 적힌 semantic 계약(특히 copy_finalize_groups의
group 원자성과, 함수마다 반환 dict의 키가 무엇을 가리키는지)까지
동일하게 지켜야 file_ops가 엔진을 바꿔치기해도 호출부의 관찰 가능한
동작이 그대로 유지된다.

세 메서드 모두 공통으로 지켜야 하는 것:
- 백엔드(워커 프로세스 등)가 실패해도(바이너리 없음, 크래시, 타임아웃,
  손상된 출력) 예외를 던지지 않는다 - 그 pair/group만 실패로 표시하고
  나머지는 정상 처리하거나, 필요하면 in-process fallback으로 대체한다.
  호출자는 항상 완전한 결과 dict를 받는다고 신뢰할 수 있어야 한다.
- pairs/groups에 있는 항목들은 서로 독립적이다 - 한 항목의 실패가
  다른 항목에 영향을 주면 안 된다(copy_finalize_groups의 group *내부*
  원자성은 예외 - 아래 참고).
"""

from pathlib import Path


class CopyEngine:
    def copy_pairs(self, pairs: "list[tuple[Path, Path]]", timeout_sec: float) -> "dict[str, bool]":
        """(src, dest) 쌍을 서로 완전히 독립적으로 복사한다. mkdir은
        하지 않는다 - dest의 부모 디렉터리가 이미 존재한다고 가정한다.

        반환: {str(dest): 성공여부} - pairs에 있던 모든 dest가 키로
        존재해야 한다.
        """
        raise NotImplementedError

    def copy_files(self, dest_dirs: "Path | list[Path]", pairs: "list[tuple[Path, Path]]", timeout_sec: float) -> "dict[str, bool]":
        """dest_dirs를 전부 mkdir한 뒤 pairs를 복사한다 - 삭제/rename은
        없다(단순 덮어쓰기). 각 pair는 서로 완전히 독립적이다.

        dest_dirs: 단일 Path 또는 Path 리스트. pairs의 dest들이 여러
        디렉터리에 걸쳐 있을 수 있다(예: media type마다 다른 폴더) -
        파일이 하나도 그 폴더로 안 가더라도, dest_dirs에 넣은 디렉터리는
        전부 생성되어야 한다.

        반환: {str(dest): 성공여부} - pairs에 있던 모든 dest가 키로
        존재해야 한다.
        """
        raise NotImplementedError

    def copy_finalize_groups(self, dest_dirs: "Path | list[Path]", groups: "list[dict]", timeout_sec: float) -> "dict[str, bool]":
        """dest_dirs를 전부 mkdir한 뒤, 각 group을 원자적으로 처리한다:
        group 안의 모든 copy가 성공해야만 그 group의 delete/rename이
        실행된다. 하나라도 실패하면 그 group 전체가 미확정 상태로
        남는다 - 성공했던 copy까지 포함해서 rename되지 않고, delete
        대상이었던 기존 파일도 그대로 남는다. group들은 서로 독립적이다
        (한 group의 실패/성공이 다른 group에 영향을 주지 않는다).

        각 group은 다음 형태의 dict:
            {
                "copies": list[tuple[Path, Path]],   # (src, tmp_dest)
                "deletes": list[Path],                # copies 전부 성공할 때만 삭제될 기존 파일들
                "renames": list[tuple[Path, Path]],   # copies 전부 성공할 때만 실행될 (tmp_dest, final_dest)
            }

        반환: {str(tmp_dest): 성공여부} - 모든 group의 "copies"에 있던
        tmp_dest가 키로 존재해야 한다. [주의] copy_pairs/copy_files와
        달리 최종(rename 후) 경로가 아니라 copies의 목적지(보통 .tmp
        경로)가 키다 - group이 확정되지 않아도(rename이 실행되지
        않아도) 그 copy 자체의 성공 여부는 이 키로 알 수 있어야 한다.
        """
        raise NotImplementedError

    def delete_paths(self, paths, timeout_sec: float) -> "dict[str, bool]":
        """파일들을 삭제한다. 항목끼리 독립적이다.

        반환: {str(path): 성공여부} - paths의 모든 경로가 키로 존재해야 한다.
        """
        raise NotImplementedError

    def move_pairs(self, pairs: "list[tuple[Path, Path]]", timeout_sec: float) -> "dict[str, bool]":
        """(src, dest)를 이동한다. 볼륨이 달라도 동작해야 한다.

        **실패 시 원본이 남아야 한다.** 이동 도중 실패로 파일이 사라지는 것은
        허용되지 않는다 - 복사를 먼저 끝내고 원본을 지우는 순서를 지켜야 한다.

        반환: {str(dest): 성공여부} - pairs의 모든 dest가 키로 존재해야 한다.
        """
        raise NotImplementedError
