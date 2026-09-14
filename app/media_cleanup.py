"""
app/media_cleanup.py
=====================
System 전체에서 고른 media type만 지운다(예: Video만, 또는 Cover+Screenshot만) -
사용자 결정: System 우클릭 메뉴의 "System 전체 미디어 정리".

ROM과 Metadata, 고르지 않은 media type은 건드리지 않는다.

**파일을 지운 뒤에는 그 System을 다시 스캔한다.** media 테이블(has_media 플래그,
system_stats의 media_count/bytes, Dashboard의 Metadata Health)을 여기서 손으로
하나씩 고치는 대신, 이미 그 계산을 전부 하는 스캐너를 다시 돌려 디스크의 실제
상태로 맞춘다 - 손으로 맞추면 어딘가 하나는 놓치기 쉽다(system_ops.py의 System
삭제와 같은 태도).
"""

from __future__ import annotations

import file_ops


def media_type_counts(cache, system) -> dict[str, dict]:
    """이 System의 media type별 개수·용량 - 정리 대화상자의 체크박스 옆 숫자."""
    return cache.media_type_counts(system)


def cleanup_media(cache, provider, workspace, collection_id, system, media_types) -> dict:
    """선택한 media type의 파일을 지우고 그 System을 다시 스캔한다.

    일부 파일이 삭제에 실패해도 나머지는 계속 지운다(부분 성공을 허용한다) - 하나가
    잠겨 있다고 나머지 수백 개를 못 지우면 정리 도구로 쓸 수 없다.

    반환: {"removed": 지운 파일 수, "failed": [경로, ...]}
    """
    paths = [p for p in cache.media_paths(system, media_types) if provider.exists(p)]
    failed: list[str] = []
    if paths:
        results = file_ops.delete_files(paths)
        failed = [str(p) for p in paths if not results.get(str(p))]
    workspace.scan(collection_id, force=True, systems=[system])
    return {"removed": len(paths) - len(failed), "failed": failed}
