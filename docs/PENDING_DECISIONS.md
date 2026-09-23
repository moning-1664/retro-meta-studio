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

## 2026-09-10 — Settings 화면 (신규 기능, UI/기능 모두 미확정)

레이아웃 재검토에서 Navigator 좌측 하단에 톱니바퀴 아이콘을 두기로 했지만,
**그 뒤에 열릴 화면은 아직 아무것도 정해지지 않았다.** 코드를 뒤져봐도 지금
앱에는 "설정 화면"이라 부를 만한 게 없다 - `app.js`에 settings 관련 코드가
없고, 저장되는 상태는 Collection별 UI 상태(컬럼 폭, 정렬, 보기 모드,
`saveUiState`)뿐이며 앱 전역 설정(테마·언어·확인창 여부 등)을 다루는 코드는
Python 쪽에도 없다.

원래 스펙(§26-28)은 "새로 만들지 말고 실제 존재하는 설정을 조사해 정리하라"는
전제였는데, 조사 결과 정리할 실제 설정이 거의 없다 - 그래서 Settings는
**신규 구현**으로 남겨두고, 화면/기능이 확정되기 전까지는 톱니바퀴를 눌러도
빈 화면(또는 자리표시자)만 나온다.

Navigator 하단 고정 영역(App Title + 톱니바퀴)은 만들었다 - 누르면 "아직
준비 중" 안내만 뜬다.

**다음에 물어볼 것**: General/Appearance/Frontend 등 카테고리에 실제로 무엇을
넣을지 - 예를 들어 확인창(destructive operation confirm) on/off, 기본
List/Card 모드, Preview 기본 상태 같은 것부터 시작할지, 아니면 다른 우선순위가
있는지.

## 해결됨 — Archive ↔ Collection 버튼 위치 (2026-09-10)

GameList Overview로 옮기는 안은 "Overview=상태 표시 전용" 원칙과 부딪혀서
보류했었는데, 대신 **Detail 패널 상단의 새 빈 공간(.detail-topspace)**으로
옮기는 것으로 해결됐다(사용자 지시) - 그 자리는 애초에 액션 버튼을 위한
자리라 원칙과 부딪히지 않는다. Collection 탭에선 "Archive에 수집", Archive
탭에선 "Collection으로 보내기"가 나온다. `renderDetailTopSpace()` 참고.
