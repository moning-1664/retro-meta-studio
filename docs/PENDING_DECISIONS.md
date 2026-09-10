# 나중에 사용자에게 물어볼 것

이 파일은 작업 중 판단이 필요했지만 사용자 확인 없이 진행하기보다 recommend만 실행하고
미룬 항목을 모아둔다. 각 항목은 결정되면 지우고 `memory.md`에 결론을 남긴다.

## 2026-09-09 — Archive Revision 정책 Phase D 착수 여부

**배경**: `docs/ARCHIVE_REVISION_POLICY.md`의 Phase A(+일부 C)는 커밋 `b9b92eb`로
구현됐다(계보 추적, Preferred Revision, 무제한 보존 기본값). 남은 Phase D는
**VALUE/ABSENT/CLEARED 구분**과 **field-level BestEffort Import**인데, 이건
메타데이터 편집 UI(저장/충돌 표시 화면)까지 고쳐야 하는 별도 작업이다.

**recommend**: 지금 바로 착수하지 않는다. 이유:
1. 현재 앱이 정상 동작하는 상태에서 UI 편집 흐름을 건드리는 것은 사용자가 실제로
   그 화면을 쓸 때 회귀 위험이 있다 - 다른 Phase처럼 "필요성이 확인된 뒤" 진행하는 게
   안전하다.
2. `docs/TEST_MATRIX.md` §12의 ARCHIVE-002~004도 아직 TC로 정리되지 않아, Phase D를
   시작하면 검증 하네스부터 새로 만들어야 한다(작지 않은 선행 작업).

**다음에 물어볼 것**: Phase D(VALUE/ABSENT/CLEARED + field-level Import)를 언제
진행할지, 아니면 스펙에서 실제로 필요해질 때까지 미룰지.

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
