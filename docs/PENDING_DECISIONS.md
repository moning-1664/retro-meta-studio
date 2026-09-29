# 나중에 사용자에게 물어볼 것

이 파일은 작업 중 판단이 필요했지만 사용자 확인 없이 진행하기보다 recommend만 실행하고
미룬 항목을 모아둔다. 각 항목은 결정되면 지우고 `memory.md`에 결론을 남긴다.

## 해결됨 — Archive Revision Phase D (2026-09-23 상태 확인)

`docs/ARCHIVE_REVISION_POLICY.md`의 VALUE/ABSENT/CLEARED 동작과 field-level
BestEffort는 현재 구현되어 있다. 출처 Revision의 빈 값은 ABSENT로 보고, Archive
직접 편집에서 키가 있는 빈 값은 CLEARED로 보존한다. Preferred의 값이 비어 있으면
다른 Revision의 값으로 보완하며, Archive 직접 편집은 그 결과 위에 적용된다.

현재 검증은 `tests/test_archive_revision_policy.py`와 `tests/test_archive_media.py`에
있다. revision별 media tombstone과 Archive projection도 이 검증 범위에 포함한다.
테스트 매트릭스의 미검증 항목은 정식 TC 추적이 없다는 뜻으로 유지하되, 구현 자체가
미착수라고 기록하지 않는다.

## 2026-09-09 — Phase 8 (MTP Provider) 재평가

`docs/ARCHITECTURE.md` §7에 "필요성 재평가 후 착수"로 남아 있는 선택 항목. 안정성
작업(Phase 7.9~7.13)이 이번에 일단락됐으니, MTP(모바일/휴대용 기기 직결) 지원이
실제로 필요한 사용 시나리오인지 사용자에게 확인이 필요하다. 필요 없다면 스펙에서
아예 빼는 것도 고려할 만하다(문서에 계속 "미결" 항목으로 남는 것 자체가 다음
세션의 혼란 요인).

## 해결됨 — Settings 화면 (2026-09-29 상태 확인)

현재 Settings에는 Archive 폴더·형식, Scraper, 언어, Emulator 등 실제 설정이
있다. Archive는 폴더를 설정한 뒤에만 사용하며 폴더 구조를 읽고 형식을 제안한다.
기존의 "설정 화면 미구현" 설명은 현재 코드와 달라 제거했다.

## 해결됨 — Archive ↔ Collection 버튼 위치 (2026-09-10)

Collection의 Archive 보내기는 HERO 아이콘에서 현재 선택 범위를 Plan에 담는다.
Archive의 Collection 보내기는 Detail 패널 상단에서 대상 Collection을 고른 뒤
그 Collection의 Plan에 담는다. 둘 다 Apply 전에는 실제 데이터를 변경하지 않는다.
