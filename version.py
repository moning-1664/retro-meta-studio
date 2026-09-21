"""
version.py
==========
Retro Metadata Manager 버전 정보 (Semantic Versioning: MAJOR.MINOR.PATCH).

- 0.x.y: 초기 개발 단계. 1.0.0 전까지는 API/데이터 스키마가 언제든 바뀔 수 있음.
- MAJOR: 1.0.0 도달 시 "완전한 최초 정식 버전"을 의미. 이후 MAJOR 증가는 호환성이
         깨지는 큰 변경(예: DB 스키마 마이그레이션이 필요한 변경, 대규모 UX 개편)에만 사용.
- MINOR: 새로운 기능 추가(예: 신규 Frontend 지원, 새 GUI 화면) - 기존 기능/데이터와 호환.
- PATCH: 버그 수정, 내부 리팩토링 등 기능 변화 없는 수정.

버전을 올릴 때는 CHANGELOG.md에도 동일한 버전으로 항목을 추가한다.
"""

__version__ = "0.4.1.6"


def version_tuple():
    return tuple(int(x) for x in __version__.split("."))
