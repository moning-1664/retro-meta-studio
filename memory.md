# RetroMeta Studio — AI Handoff / Memory

이 파일은 세션이 바뀌거나 다른 AI가 이어받을 때 맥락을 빠르게 복원하기 위한 기록이다.
**Phase가 끝날 때마다 맨 아래에 새 항목을 추가한다** (날짜순, 과거 항목은 고치지 않는다).
자세한 변경 근거/대안 비교는 `docs/REPORTS/<날짜>-<주제>.md`에 남기고, 여기서는 그 리포트로
링크하며 다음 사람이 알아야 할 결론만 요약한다.

## 프로젝트 개요

- Windows 데스크톱 앱. 여러 Frontend(ES-DE, Pegasus, LaunchBox, EmulationStation, 다이지쇼)의
  ROM/Metadata/Media를 관리한다.
- [RetroGameManager](https://github.com/moning-1664/RetroGameManager)에서 코드를 가져와
  구조를 다시 짠 프로젝트. 그 프로젝트의 MasterDB 중심 구조를 폐기하고
  **Collection / Archive / Cache / Plan** 4분할 구조로 바꿨다 - 자세한 설계 근거는
  `docs/SPEC.md`(원 설계서), `docs/ARCHITECTURE.md`(구현 아키텍처, Phase 표는 §7).
- GUI: Python backend(`bridge/api.py`) + pywebview + vanilla JS(`gui_web/`).
- Repo: `git@github.com:moning-1664/retro-meta-studio.git`, 기본 브랜치 `main`에 직접 커밋.

## 작업 규칙 (2026-09-08 확정)

- **Phase가 끝나면 그 자리에서 `git push origin main`까지 한다.** 로컬에만 커밋해 두고
  넘어가지 않는다.
- **Phase가 끝나면 이 파일(`memory.md`) 맨 아래에 항목을 추가하고 그것도 push한다.**
  다른 AI가 git log만 보고도 "무엇을 왜 그렇게 했는지"를 알 수 있어야 하므로, 커밋 메시지에
  적은 이유를 반복하기보다 **결론 + 다음 사람이 실수하기 쉬운 지점**을 적는다.
- 검증 방법(파이썬 unittest + Playwright)은 `README.md`의 "테스트" 절, 하네스 설계 배경은
  `docs/REPORTS/2026-09-08-phase5-match-and-test-harness.md` §1 참고.

## 현재 상태 (2026-09-08 기준)

**Phase 7.4까지 완료, main에 push됨.** Adapter 4종, Match, Compare, Convert, Plan,
Archive가 동작하고, Apply 성능과 Match 링크의 rename 취약성도 닫혔다.

지켜야 할 성질 여섯:
- **Compare는 읽기 전용이다.** 새 변경 동작에는 `blockedInCompare()`를 넣을 것.
- **Adapter는 모르는 필드를 버리지 않는다.** 단 경로처럼 위치에 매인 값은
  `strip_location_raw()`로, 다른 Frontend의 값은 `raw_is_mine()`으로 걸러낸다.
- **`to_common()`은 `tag_raw()`로 출처를 남긴다.**
- **Adapter 쓰기는 System 단위 bulk다.** ROM 하나씩 쓰는 형태로 되돌리지 말 것.
- **Adapter가 포맷 지식을 독점한다.** `supported_fields`/`media_types`를 서비스 쪽에
  하드코딩하지 말 것.
- **호출을 묶는 것과 실패를 묶는 것은 별개다.** Apply는 복사를 25개씩 묶어 부르지만,
  실패와 되돌리기의 단위는 항목 그대로다.

**성능 기준선**(회귀 판단용): 400게임 Apply 1.20s, 1,000게임+media 12.36s,
5,000게임+media 61.34s.

남은 것: Compare Row key 구조화(Phase 6에서 이월, 우선순위 낮음), Phase 8(MTP, 선택).
의도적으로 남긴 한계: 다른 볼륨으로 파일을 옮기면 Match 링크가 끊긴다(해시가 필요한데
비용 때문에 보류), SHA-256 비교.

(이 절은 최신 상태를 담으므로 계속 갱신한다. 아래 날짜별 항목은 그 시점의 기록이므로
고치지 않는다.)

---

## Phase 5 — Match, 그리고 검증 하네스 도입 (2026-09-08, Claude Code)

**요청 배경**: 사용자가 "이전 프로젝트(RetroGameManager)에서 자체 테스트 파일/GUI 테스트를
미리 만들어 검증했다"며 그 방식을 이 프로젝트에도 도입 검토 후 적용해 달라고 요청. 상세
비교표와 근거는 `docs/REPORTS/2026-09-08-phase5-match-and-test-harness.md` §1 참고 - 요지는:

- fixture 빌더 **방식만** 재사용(`tests/fixtures.py`로 분리, 테스트 모듈에서 fixture를
  import하던 예전 방식은 "import하면 남의 테스트까지 실행됨" 문제가 있어 가져오지 않음).
- `test_api_wiring.py` + `api-wiring.spec.js`(3단 배선 이름 검사)는 **거의 그대로** 가치가
  있어서 `tests/test_wiring.py` 하나로 합침(Playwright 없이 Python만으로 돌게 함) +
  인자 개수·목업 커버리지 검사 추가.
- `tests_ui/*.spec.js` 11개는 폐기된 MasterDB 개념 전제라 이식 안 함. 현재 UI 기준 새로 씀.
- **이 PC에 Node.js가 없어서** Playwright를 아예 못 돌리던 상태였음 → winget으로
  Node LTS v24.19.0 설치 + `npx playwright install chromium` 완료. 다음 세션에서 Node가
  다시 없다면(다른 머신/재설치 등) 같은 조치 필요.

**목업 커버리지 검사가 도입 즉시 실제 버그를 찾음**: Collection 생성/이름변경/제거,
External Storage 추가/제거, System 이동 등 8개 호출이 `api-client.js`의 mock 객체에
없었다. 목업에 없으면 `{ok:false}`로 떨어져서, 그 화면들은 GUI 테스트를 붙여도 오류
경로만 지나갔을 것 - 목업을 `ok(true)`로 때우지 않고 실제로 배열 상태를 바꾸게 고쳤다.

**하네스 도입 과정에서 드러난 기존 버그 2건(둘 다 수정 완료)**:
1. `archive_detail()`이 Archive 직접 편집(`__archive__` 출처)을 안 보고 "최근 출처"만 봐서,
   화면에는 원본이 보이는데 실제 반영값은 편집본인 불일치가 있었음(`app/archive/service.py`).
2. **§46(Game/ROM Identity 분리) 위반**: `ensure_rom_identity()`가 `filename_norm`(괄호 정보
   버림)으로 Identity를 찾아서 `"Game (USA)"`와 `"Game (Europe)"`이 같은 ROM으로 합쳐지고
   있었다. `rom_key`(괄호 보존) 컬럼을 migration 3으로 추가해 고침 - **다음 사람이 알아야
   할 것**: Archive의 ROM Identity 매칭 키는 `filename_norm`이 아니라 `rom_key`다.
   `filename_norm`은 여전히 존재하지만 이제 Match 엔진의 "느슨한 후보 찾기" 용도로만 쓴다.

**Phase 5 본체 (`app/match/engine.py`, `app/match/service.py`)**:
- 티어: Exact(해시 일치 또는 정규화 파일명+크기 일치) → Normalized(이름만 같음) →
  Metadata(개발사/연도 겹침) → Heuristic(`similar_rom.py` 점수 기반, 임계값 60 - 아래 참고).
- **자동으로 붙는 것은 Exact 하나뿐**, 그것도 후보가 정확히 하나일 때만(`auto_match()`).
  파일명만으로는 Exact가 되지 않는다(§47) - 크기나 해시 확증이 필요.
- 확정한 Match는 `match_links` 테이블(migration 4)에 `(collection_id, system, filename)`을
  키로 저장한다 - **`rom_uid`를 키로 쓰지 않은 이유**: cache의 `replace_system()`이 System
  단위로 DELETE 후 재삽입해서 `rom_uid`(AUTOINCREMENT)가 재스캔마다 바뀌기 때문. 다음에
  Match 관련 코드를 만질 때 rom_uid를 영속 키로 쓰지 않도록 주의.
- UI: Gamelist 행에 `[n]` 뱃지 → 클릭 시 §49 사양 그대로의 "Possible Matches" 모달
  (Source / 후보 티어·점수 / Cancel / Apply Match). Apply해도 파일/Metadata는 안 건드리고
  "같은 것"이라는 링크만 남긴다 - 값을 실제로 가져오려면 Archive → Collection을 따로 실행.

**사용자 확정 결정 3건** (`docs/REPORTS/2026-09-08-phase5-match-and-test-harness.md` §4):
1. Heuristic 임계값 = **60**(similar_rom.py 기본값과 통일 - 두 곳이 다른 기준을 쓰면
   "유사롬 목록엔 뜨는데 Match 후보엔 없다"를 설명할 수 없어서).
2. Normalized 티어는 **자동 적용 안 함**(지역판/리비전이 갈리는 지점이라 자동 반영 위험).
3. Apply Match는 **링크만 기록**, 값 반영은 Archive → Collection을 별도 실행(§40 준수).

**검증**: `python -m unittest discover -s tests` → 196개 전체 통과(신규 15개, Match 관련).
`npx playwright test` → 28개 전체 통과(신규 7개, `tests_ui/match.spec.js`).

**커밋**: `b004896`(Archive 편집 버그 수정) → `3471edd`(하네스 도입) → `9764acc`(Phase 5 본체,
rom_key 수정 포함) → `7319ec6`(문서) → `6b5030b`(임계값 60 확정) → `2007c8f`(리포트 정리).
전부 `origin/main`에 push 완료(`7153555..2007c8f`).

**다음 세션에서 볼 것**: `docs/ARCHITECTURE.md` §7 Phase 표, Phase 6(Compare Mode)은
`compare_engine.py`를 일반화하는 작업 - Match 엔진(`app/match/engine.py`)의 `classify()`를
Compare의 좌우 매칭에 재사용할 수 있을지부터 확인할 것.

---

## Phase 5 Hardening — 외부 리뷰 대응 (2026-09-08, Claude Code)

다른 AI의 Phase 5 리뷰(P1 1건, P2 2건 + 성능/문서 지적)를 반영했다. 상세는
`docs/REPORTS/2026-09-08-phase5-hardening.md`. **다음 사람이 반드시 알아야 할 것만** 추린다.

### 계약이 바뀐 것 (코드를 만질 때 주의)

- **`engine.classify()`는 이제 `(tier, score, evidence)` 3-튜플을 반환한다.** evidence는
  "왜 이 티어인지"를 사용자에게 보여주는 문구 리스트다. 후보 dict에도 `evidence` 키가 있다.
- **`_heuristic()` 함수는 없어졌다.** `_metadata_match()`(구조화 필드의 *동일성*)와
  `_heuristic_match()`(문자열 *유사도*)로 나뉘었다. 예전에는 `breakdown["title"] < 20`으로
  두 티어를 사후에 갈랐는데 임의적이라는 지적을 받아 각각의 판정 함수로 분리했다.
- **`TIER_MANUAL`이 생겼다. 엔진은 이 값을 절대 반환하지 않는다** -
  `service.apply_match(..., manual=True)`로만 기록된다. 엔진 판정과 사람의 단언을
  데이터에서 구분하기 위한 것이니, 엔진 쪽에서 이 티어를 반환하게 만들지 말 것.
- **`apply_match()`는 후보 목록에 없는 Identity를 거절한다.** 강제로 이으려면 `manual=True`.
  UI에는 아직 강제 연결 경로가 없고, Compare(Phase 6)처럼 사용자가 좌우를 직접 지목하는
  화면이 생길 때 쓰라고 열어 둔 것이다.

### 왜 그렇게 고쳤는지 (같은 실수를 반복하지 않기 위해)

1. **확정할 때 classify()를 다시 부르면 안 된다.** classify()는 앞쪽 두 티어만 판정하므로,
   재호출하면 사용자가 제대로 고른 Metadata/Heuristic 후보가 전부 "heuristic / 0.0점"으로
   기록된다 - 근거 없는 강제 링크와 구별이 안 되는 상태였다. 지금은 후보 목록에 있던
   티어/점수를 **그대로** 기록한다.
2. **Heuristic 점수는 "가용 근거" 기준으로 환산해서 잰다.** similar_rom의 100점에는
   스크린샷 해시 20점이 들어 있는데 Match 경로는 그걸 계산하지 않고, Archive Identity에
   개발사/출시일이 없으면 만점이 50점이다. 환산 없이 임계값 60을 대면 Heuristic 티어는
   도달 불가능한 죽은 코드가 된다(실측: "Metal Gear Solid 2" vs "...Substance" = 39.13점).
   **임계값 60이라는 숫자는 사용자가 정한 그대로 두되 척도만 맞춘 것**이니, 60을 건드릴
   때는 이 환산(`MIN_ATTAINABLE_EVIDENCE` 포함)을 함께 봐야 한다.
3. **`quick_candidates()`는 `identities_matching()`(인덱스 질의)을 쓴다.** 예전엔 주석과
   달리 `identities_in_system()`으로 전수 순회했다. Gamelist 뱃지가 화면의 행마다 부르는
   경로이므로 여기에 전수 순회를 되돌려 놓지 말 것. Heuristic은 이름이 어긋난 뒤에 보는
   것이라 인덱스로 못 찾으므로, 전수 순회는 deep 경로에만 남아 있다.

### Phase 6 방향 — 기존 안내를 정정했다

이전 항목 마지막에 "Match 엔진의 `classify()`를 Compare 좌우 매칭에 재사용"이라고 적었는데
**그대로 쓰면 안 된다.** `classify()`의 계약은 "Collection의 cache row ↔ Archive의
rom_identity"로 박혀 있고, Compare가 필요한 것은 "Collection A row ↔ Collection B row"다.
두 입력이 우연히 비슷한 모양일 뿐이라, 이대로 얹으면 Phase 6에서 Match를 다시 뜯게 된다.

→ **판정 로직을 `MatchSubject ↔ MatchSubject`로 한 단계 일반화한 뒤 Compare를 얹을 것.**
`source_of_row()`가 이미 절반을 하고 있으니, Archive 쪽에도 같은 shape을 만드는 어댑터를
두면 된다. (`docs/REPORTS/2026-09-08-phase5-hardening.md` §8)

### 남겨 둔 것 (의도적으로 안 고침)

`match_links`의 키가 `(collection_id, system, filename)`이라 **사용자가 ROM을 rename하면
링크가 끊긴다.** 리뷰도 이걸 짚었지만, 고치려면 Cache에 안정적인 rom key를 심어야 하고
Phase 5에서 이미 두 번 건드린 스키마를 또 흔드는 일이라 **Phase 6 이후**로 미뤘다.

### 관측된 이상 (미해결, 재현 안 됨)

전체 파이썬 스위트를 `git add`와 같은 명령줄에서 돌렸을 때 **1건이 실패한 적이 한 번
있다.** 이후 8회 연속 재현되지 않았고, 출력이 잘려 실패한 테스트 이름을 확보하지 못했다.
추정으로 단정하지 않고 기록만 남긴다 - 같은 증상을 다시 보면 `-v`로 이름부터 확보할 것.

**검증**: 파이썬 211개(신규 15), Playwright 29개(신규 1) 전부 통과. 커밋 `65d4f7d`,
`origin/main`에 push 완료.

---

## Phase 6 — Compare Mode (2026-09-08, Claude Code)

스펙 §54-59. 상세는 `docs/REPORTS/2026-09-08-phase6-compare.md`.

### 착수 전에 한 일 — 판정 계약을 한 단계 올렸다

직전 항목에서 예고한 그대로 했다. `classify()`는 이제 **`MatchSubject ↔ MatchSubject`**를
받는 대칭 함수다.

- `engine.subject(...)` — 중립 형태를 만든다. `system/filename/title/size/sha256/fields/ref`.
- `engine.subject_of_row(row)` — Collection cache row → subject.
- `engine.subject_of_identity(identity, fields)` — Archive rom_identity → subject.
  (개발사/출시일은 Identity가 아니라 Record에 있으므로 `fields`를 따로 받는다.)
- `classify()` / `_metadata_match()` / `_heuristic_match()` 셋 다 `(a, b)` 대칭.
- `source_of_row`는 **별칭으로 남아 있다** - Archive Match 경로를 건드리지 않으려고.

**주의**: 엔진은 `ref` 값을 들여다보지 않는다. 호출자가 `rom_uid`든 `rom_identity_id`든
넣어 두고 나중에 자기가 해석하는 칸이다. 여기에 엔진 로직을 붙이지 말 것.

### Compare가 Match와 **다른 점** (여기가 제일 헷갈린다)

판정 함수는 공유하지만 **짝짓기 규칙은 일부러 다르다.**

| | Match (Archive) | Compare |
|---|---|---|
| 묻는 것 | "이 둘이 같은 ROM인가" | "두 목록을 어떻게 줄 세우나" |
| 같은 이름 + 다른 크기 | Normalized 후보(자동 아님) | **짝으로 본다** |

Match의 Exact 기준(크기/해시 확증)을 Compare에 그대로 쓰면 같은 이름의 다른 덤프가
"양쪽에 각각 있음"으로 갈라져 보인다 - **그 차이를 보려고 Compare를 여는 것인데도.**
그래서 Compare는 1차로 정확한 파일명(크기/해시 무관), 2차로 `classify()`가 Exact/Normalized로
인정하면서 그런 상대가 **유일할 때만** 짝짓는다. 둘 이상이면 각자 "한쪽에만 있음"으로
남긴다(§88). 나중에 "Compare도 Match랑 같은 기준을 쓰자"고 통일하려 들면 이 화면이
망가지니 주의.

### 상태 체계

`same` / `conflict`(△) / `only_a`(−) / `only_b`(+). **Media 차이는 상태를 바꾸지 않고**
`mediaDiff`로 따로 두어 `[Media]` 필터로 본다 - Media만 다른 것을 Conflict라 부르면
"Metadata가 충돌한다"는 뜻이 흐려진다. Conflict 판정 필드는 게임을 서술하는 9개뿐이고
`favorite`/`playcount` 같은 사람이 관리하는 값은 넣지 않는다(넣으면 온통 Conflict가 된다).

### 다음 사람이 실수하기 쉬운 지점

- **Compare 행의 키는 `romUid`가 아니라 `"<system>|<filename>"`이다.** 한쪽에만 있는 행은
  `romUid`가 아예 없고, `romUid`는 재스캔마다 바뀐다(Phase 5에서 확인한 것과 같은 이유).
- **비교 결과는 `start_compare` 때 한 번 계산해 `Api._compare`에 들고 있는다.** 필터를
  누를 때마다 다시 훑도록 바꾸지 말 것 - 느린 것도 문제지만, 그 사이 스캔이 끼면 필터마다
  다른 스냅샷을 보게 된다. Plan과 같이 **세션 한정**이라 앱을 끄면 사라진다.
- **`CacheStore.all_entries()`를 새로 만들었다.** Compare처럼 전량이 필요할 때 쓴다.
  행마다 `get_row()`를 부르면 한 건에 질의가 세 번이라 (좌 N + 우 M)번이 된다.
- UI는 별도 화면이 아니다. `#filter-bar`가 비교 막대로 바뀌고 목록/상세는 같은 자리를
  쓴다(`isCompare()`로 분기). `loadMatchCounts()`는 Compare에서 건너뛴다 - Compare 행에는
  단일 `romUid`가 없다.

**검증**: 파이썬 229개(신규 18), Playwright 36개(신규 7) 전부 통과. 커밋 `fe487bc`,
`origin/main`에 push 완료.

**다음**: Phase 7 — 나머지 Frontend Adapter(Pegasus / LaunchBox / EmulationStation) +
Round-trip 검증 + ES-DE custom systems XML. Round-trip 검증에는 이번 Compare를 그대로
쓸 만하다 - "ES-DE에서 읽어 Pegasus로 쓰고 다시 읽었을 때 필드가 그대로인가"는 결국
두 Collection을 맞대는 일이다.

---

## Phase 6 Hardening — 외부 리뷰 대응 (2026-09-08, Claude Code)

리뷰 백로그(P0 1건, P1 4건, P2 2건) 처리. 상세는
`docs/REPORTS/2026-09-08-phase6-hardening.md`. **다음 사람이 반드시 알아야 할 것만** 추린다.

### 가장 중요 — Compare는 **읽기 전용**이다. 이 성질을 깨뜨리지 말 것

리뷰는 "확인해 보라"는 항목으로 올렸는데, 확인해 보니 실제로 세 갈래로 변경이 가능했다.

1. **Ctrl+V가 붙여넣기를 실행했다.** 단축키 핸들러가 `S.activeId`만 보고 Compare 여부를
   안 봤고, `pasteIntoActive()`는 **선택 항목이 없어도 동작한다** - Auto Plan이 꺼져
   있으면 `applyPlan()`까지 이어져 실제 파일이 움직였다.
2. **Ctrl+S가 저장 경로를 탔다.** Compare 상세도 `S.detailState.tab === "metadata"`라서
   저장 조건을 통과했다.
3. **내비 드래그로 System 이동이 가능했다.** `Add External Storage`와 Storage 우클릭
   메뉴(제거 포함)도 살아 있었다.

**지금의 방어 구조 (둘 다 필요하다)**:
- `blockedInCompare(what)` — 변경 함수 6개(`copySelection`/`pasteIntoActive`/
  `deleteSelection`/`handleSaveDetail`/`moveSystemToStorage`/`openAddStorage`) **입구**에서
  막고 안내 토스트를 낸다.
- 화면에서도 지운다 — 상태바는 Compare 중 Copy/Paste/Delete/Apply를 그리지 않고
  `읽기 전용` 배지만 두고, 내비는 `draggable`을 붙이지 않는다.

**새 변경 동작을 추가할 때는 그 함수 입구에도 `blockedInCompare()`를 넣을 것.** 버튼을
숨기는 것만으로는 부족하다 - 단축키와 드래그처럼 버튼을 거치지 않는 길이 있다.
반대로 단축키를 통째로 `return`시키는 방식도 쓰지 말 것 - 아무 반응이 없으면 사용자는
"키가 안 먹네"로 여긴다(그렇게 만들었다가 되돌렸다).

### `Same`의 의미 — "ROM 파일이 같다"가 아니다

`Same` = 양쪽에 대응 항목이 있고 **비교 대상 Metadata가 동일**. 크기가 달라도 Same일 수
있고, 그 차이는 상세의 Size 줄에서 본다. 이 정의는 엔진 docstring / 필터 버튼 툴팁 /
`CompareContractTests` 세 곳에 박아 뒀다 - Compare를 "ROM identity 비교"로 바꾸려 들면
테스트가 깨진다. Pairing 정책(같은 파일명이면 크기/해시가 달라도 짝)은 그대로 유지다.

**Metadata / Media / 크기는 서로 독립적인 신호다.** 하나로 뭉뚱그리지 말 것.

### 스냅샷

`start_compare`가 `takenAt`을 함께 돌려주고 비교 막대가 `Snapshot HH:MM:SS`와
`[Refresh]`를 보여준다. Refresh는 `start_compare()`를 다시 부르는 것뿐이고, **자동 갱신은
하지 않는다**(필터마다 결과가 달라지면 안 되므로).

### 성능 — 재고 나서 고쳤다

`_pair()`의 2차 탐색이 O(N×M)이라는 지적에, 먼저 측정했다.

| 5,000 × 5,000 | 인덱스 전 | 인덱스 후 |
|---|---|---|
| 현실적(1차에서 전부 짝지어짐) | 0.03s | 0.029s |
| 최악(이름을 하나도 공유 안 함) | **7.32s** | **0.121s** |

`classify()`가 Exact/Normalized를 주는 조건이 "정규화 파일명 / 정규화 제목 / 해시가 같음"
셋뿐이므로 그 세 키로 후보를 먼저 좁혔다(Phase 5의 Archive 후보 인덱스와 같은 방향).
**후보 밖 항목은 애초에 Exact/Normalized가 될 수 없으므로 결과는 동일하다** - 이 등가성이
깨지지 않게, 나중에 `classify()`에 새 판정 근거를 추가한다면 이 인덱스 키도 함께 늘려야
한다.

### 남겨 둔 것 (의도적)

- Compare Row key의 구조화(`"system|filename"` → 구조체). Windows 파일명에 `|`가 못
  들어가므로 지금은 실질적 버그가 아니다. 다른 플랫폼까지 넓힐 때 함께.
- SHA-256 Compare. filesystem I/O 비용 때문에 후순위 - 필요하면 사용자가 요청한 항목만
  lazy 계산하는 방향.
- `match_links`가 파일명 rename에 끊기는 문제(Phase 5에서 이월). 여전히 Phase 7 이후.

**검증**: 파이썬 236개(신규 7), Playwright 41개(신규 5) 전부 통과. 커밋 `4a70552`,
`origin/main`에 push 완료.

---

## Phase 7 — 나머지 Frontend Adapter와 Round-trip 검증 (2026-09-08, Claude Code)

Pegasus / LaunchBox / EmulationStation Adapter 추가(총 4종) + Frontend 간 왕복 검증
+ ES-DE custom systems XML(§22). 상세는 `docs/REPORTS/2026-09-08-phase7-adapters.md`.

### Adapter 인터페이스는 바꾸지 않았다

Phase 1의 두 계약(bulk만 노출 / 모르는 필드를 `frontend_raw`에 보존)이 그대로
작동해서, `adapters/base.py`를 한 줄도 고치지 않고 세 종류를 얹었다. **새 Adapter를
추가할 때도 이 계약을 먼저 읽을 것.** 낱개 read/write 메서드를 추가하지 말 것 -
그걸 허용하면 이전 프로젝트의 O(n²)가 되살아난다.

새 Adapter는 `app/workspace.py` 상단에 import를 추가해야 등록된다(`register()`가
모듈 import 시점에 돈다).

### Frontend별 함정 — 여기가 이 Phase의 알맹이다

- **Pegasus**: `metadata.pegasus.txt`는 **들여쓴 줄이 앞 키의 값으로 이어진다**
  (주로 `description`). 그리고 이전 프로젝트 writer가 블록을 아는 필드만으로 다시
  만들어 사용자 키(`sort-by`, `x-favorite`)를 날렸다 - 지금은 모든 줄을 **순서까지**
  보존한다. 파일 헤더(`collection:`/`shortname:`/`launch:`)도 유지한다.
- **LaunchBox**: **media 파일명이 ROM이 아니라 게임 제목을 따른다.** `FFX.iso`의 커버가
  `Final Fantasy X.jpg`다. ROM stem으로만 인덱싱하면 커버를 하나도 못 찾으므로,
  플랫폼 XML의 `<Title>`로 "제목 → stem" 대응표를 만들어 되돌린다. `<ApplicationPath>`는
  상대/절대가 섞여 있어 **원본 그대로 보존**한다(재조립하면 사용자 경로가 깨진다).
- **EmulationStation(원조)**: **gamelist.xml이 media 경로를 직접 들고 있다**
  (`<image>`/`<video>`/`<marquee>`). 배포판마다 위치가 달라 폴더 규칙을 가정하면
  media를 통째로 놓친다. 이 Adapter만 media 인덱스를 gamelist가 가리키는 경로에서
  만든다. `detect()`도 `downloaded_media`가 함께 있으면 ES-DE일 수 있으므로 확신을
  0.9 → 0.5로 낮춰 사용자가 고르게 한다.

### Round-trip의 정의 (헷갈리기 쉬움)

| 왕복 | 지켜야 하는 것 |
|---|---|
| 같은 Frontend 제자리 | 공통 필드 **+ `frontend_raw`** |
| Frontend 간(ES-DE → Pegasus → ES-DE) | **공통 필드만** |

두 번째에서 `frontend_raw`가 따라가지 않는 것은 **결함이 아니라 정의다** - ES-DE의
`<playcount>`를 Pegasus 블록에 적을 수는 없다. "왕복인데 값이 없어졌다"고 판단해
frontend_raw를 Frontend 사이로 옮기려 들지 말 것. Pegasus 왕복에서 `region`이 빠지는
것도 포맷에 그 키가 없어서이며, 테스트가 `skip=("region",)`으로 명시해 둔다.

### 남겨 둔 연결 하나 (중요, 아직 미완)

**`EmulationStationAdapter.write_media_links()`가 Plan Apply 경로에 연결되지 않았다.**
원조 ES는 gamelist가 가리키는 경로만 보므로, media를 복사한 뒤 이걸 부르지 않으면
**파일은 복사됐는데 화면에는 안 나온다.** Adapter에는 구현돼 있고 테스트도 있지만
`app/plan/applier.py`가 아직 호출하지 않는다. EmulationStation Collection으로 media를
내보내는 경로를 만들 때 반드시 함께 연결할 것.

### ES-DE Custom Systems XML (§22)

`AdapterAction`으로 노출 → 헤더 확장의 `[ES-DE XML 생성]`. Storage 같은 일반 기능으로
올리지 않았다(ES-DE의 사정이다). **Collection root 안의 System은 적지 않는다** - ES-DE가
스스로 찾고, 전부 적으면 사용자가 손본 설정을 덮어쓴다. 확장자/실행 명령도 비워 둔다.

UI 연결 시 주의: `openTab()`은 `ensureDetail()`을 거치지 않고 `openCollection` 응답을
그대로 쓴다. Frontend별로 달라지는 것을 탭 열기에서 불러오려면 `openTab()`에도 직접
넣어야 한다(이번에 `loadAdapterActions()`가 여기서 빠져 GUI 테스트가 잡았다).

**검증**: 파이썬 276개(신규 40), Playwright 45개(신규 4) 전부 통과. 커밋 `b1b5475`,
`origin/main`에 push 완료.

**다음 후보**: Phase 8(MTP)은 스펙에서도 "필요성 재평가 후"인 선택 항목이다. 그보다
① `write_media_links()`의 Apply 연결, ② Adapter 간 변환 UI(§349 Import: Source → Match
→ Target), ③ 이월분(`match_links` rename 취약성 / Compare Row key 구조화 / SHA-256 비교)
쪽이 먼저다.

---

## Phase 7.1 — EmulationStation media 링크를 Plan/Apply에 연결 (2026-09-08, Claude Code)

Phase 7이 남긴 구멍을 닫았다. 상세는 `docs/REPORTS/2026-09-08-phase7.1-es-media-links.md`.

### 계약이 늘었다 (Adapter를 만질 때 주의)

`FrontendAdapter`에 셋이 추가됐다. **전부 기본 no-op**이라 폴더 규칙으로 media를 찾는
Adapter(ES-DE / Pegasus / LaunchBox)는 아무 영향이 없다.

- `build_media_links(layout, filename, media) -> [(media_type, dest)]` — **계산만 한다.**
  파일도 메타데이터도 건드리지 않는다. Plan 단계에서 불러도 안전해야 한다.
- `write_media_links(layout, links_by_filename)` — **System 단위 bulk.** ROM 하나씩
  받는 형태로 되돌리지 말 것(Phase 7에서 그렇게 만들었다가 이번에 고쳤다). 게임 1,000개면
  gamelist.xml을 1,000번 다시 쓰게 되어 계약 1이 막으려던 O(n²)가 재현된다.
- `strip_location_raw(frontend_raw)` — **다른 위치로 옮겨 적을 때 따라가면 안 되는 원본
  값**을 걷어낸다. 아래 참고.

`EmulationStationAdapter.media_pairs()`는 `build_media_links()` 위에 세워져 있다.
**둘을 따로 계산하도록 되돌리지 말 것** - 복사되는 곳과 gamelist에 적히는 곳이 갈라지면
"파일은 있는데 화면엔 안 나온다"가 된다.

### 찾은 버그 — `frontend_raw`의 경로가 다른 Collection으로 샜다

계약 2("모르는 필드를 버리지 않는다")로 보존되는 값 중에 **그 자리에서만 참인 것**이 있다.
원조 ES의 `<thumbnail>`/`<video>`는 경로라서, 게임을 다른 Collection으로 복사하면
`write_index()`가 source의 경로를 target gamelist에 그대로 적는다.

`strip_location_raw()`로 갈랐다 — 계약 2는 유지하되 위치에 매인 값은 새 위치로
따라가지 않는다. **같은 Collection 안에서 다시 쓸 때는 호출하지 않으므로 제자리 보존은
그대로다.** `_apply_add`(= 다른 Collection에서 온 항목을 적는 경로)에서만 부른다.

### 테스트가 우연히 통과했던 일 — 방법으로 남겨둘 것

통합 테스트 11개가 한 번에 전부 통과하길래 **수정을 임시로 되돌려 확인**했더니 2개만
실패했다. 핵심 테스트가 수정 없이도 통과하고 있었다 - fixture의 source와 target을 둘 다
우리 layout 규칙으로 만들어서 source의 상대 경로가 target에서도 우연히 해석된 탓이다.

fixture를 **RetroPie 스타일**(`downloaded_images/<system>/<stem>.png`)로 바꾸자 수정
없이는 6개가 실패한다. **ES 관련 fixture를 손댈 때 source의 media 배치를 우리 규칙과
같게 만들지 말 것** - 그 순간 이 테스트들이 아무것도 검증하지 않게 된다.

새 기능에 테스트를 붙였는데 처음부터 전부 통과하면, 한 번은 수정을 되돌려 실제로
실패하는지 확인하는 것이 좋다.

### 실패 처리 정책

- media 복사 실패 → **링크 단계에 도달하지 않는다**(파일이 자리를 잡은 뒤 메타데이터).
- 링크 기록 실패 → 그 System의 항목을 **PARTIAL로 내리고 Plan에 남긴다.** 파일은
  복사됐는데 Frontend가 못 찾는 상태를 성공으로 처리하면 사용자는 원인을 알 수 없다.
- 복사되지 않은 media는 링크로 적지 않는다(존재하는 dest만).

### 알려진 잔여 문제 (아직 안 고침)

**`write_index()`가 ADD 항목마다 호출된다.** `_apply_add`가 항목 하나씩
`adapter.write_index(layout, [entry])`를 부르므로, media 링크에서 고친 것과 같은 O(n²)가
메타데이터 쪽에 남아 있다. 함께 고치지 않은 이유는 **실패 처리의 단위가 바뀌기
때문**이다 - 지금은 항목 하나가 실패하면 그 항목의 파일만 되돌리는데, bulk로 묶으면 그
경계가 사라진다. 되돌리기 정책을 먼저 정해야 하는 별도 작업이다.

**검증**: 파이썬 292개(신규 16), Playwright 45개 전부 통과. 커밋 `db9b023`,
`origin/main`에 push 완료.

**다음**: Phase 7.2(Adapter 간 변환 UI) → 7.3(Match/Compare 이월분: `match_links` rename,
Compare Row key) → Phase 8(MTP, 선택).

---

## Phase 7.2 — Adapter 간 변환(Convert)과 손실 미리보기 (2026-09-08, Claude Code)

스펙 §53. 상세는 `docs/REPORTS/2026-09-08-phase7.2-convert.md`.

### Convert에는 새 실행 경로가 없다 — 이 점을 유지할 것

```
source cache row ──(공통 모델)──> builder.plan_add ──> Plan ──> Apply
                                                                └─ target Adapter가 자기 포맷으로 쓴다
```

**붙여넣기(`paste`)와 같은 `builder.plan_add`를 쓴다.** 목적지 충돌 판정, 용량 계산,
원본이 사라진 항목 건너뛰기가 전부 거기 이미 있다. Convert 전용 복사 코드를 새로 만들지
말 것 - 그 순간 두 경로의 충돌/용량 규칙이 갈라진다.

Plan 계약도 그대로다: **Plan 단계에서는 아무 파일도 안 바뀌고**, 원본 Collection은 읽기만
한다(§53 "원본 보존"). 테스트가 둘 다 고정하고 있다.

### 새로 만든 건 미리보기뿐 — 세는 규칙이 핵심

`app/convert/service.py::preview()`. 신경 쓴 것 셋:

- **값이 비어 있으면 세지 않는다.** `region` 태그가 있어도 값이 빈 문자열이면 잃을 것이
  없다. 겁주는 숫자를 만들지 않기 위함이다.
- **어느 필드인지 이름까지 준다**(`unsupportedFieldNames`). 숫자만으로는 사용자가 무엇을
  잃는지 알 수 없다.
- **필드와 media는 별개의 축이다.** EmulationStation은 공통 필드 9개를 전부 담아
  `unsupportedFields`가 0이지만 `3dboxes`는 여전히 못 받는다. **두 숫자를 하나로
  합치지 말 것** - 테스트가 이 구분을 고정한다.

### Adapter 계약에 `supported_fields`가 늘었다

각 Adapter가 **자기 포맷이 담을 수 있는 공통 필드**를 선언한다(기본 = 9개 전부,
Pegasus만 `region` 제외 - `metadata.pegasus.txt`에 그 키가 없다).

**이 값을 Convert 서비스에 하드코딩하지 말 것.** 그러면 Adapter를 추가할 때마다 서비스를
함께 고쳐야 하고, "Adapter가 포맷 지식을 독점한다"는 원칙이 깨진다. 새 Adapter를 만들 때
자기 포맷이 못 담는 공통 필드가 있으면 여기서 빼면 된다.

### UI 메모

탭 우클릭 → `Convert` → 대상 선택 → 미리보기 → `Plan에 올리기`. 대상 목록에 자기 자신은
없고, Plan에 올린 뒤 **대상 Collection 탭으로 데려간다** - 그러지 않으면 사용자는 아무 일도
안 일어난 것처럼 느낀다. 토스트가 "Apply를 눌러야 실제로 반영됩니다"를 명시한다.

서비스의 `preview()`/`plan_convert()`는 이미 `systems=` 인자를 받는다(부분 변환). UI에는
아직 노출하지 않았다 - 전체 변환이 기본 시나리오라 그것부터 붙였다.

### 우선순위가 올라간 잔여 문제

Phase 7.1에서 적어 둔 **`_apply_add`의 항목별 `write_index()` 호출(O(n²))**이 그대로다.
Convert가 **대량 항목을 한 번에 Plan에 올리는 경로**를 만들었으므로 이 문제가 실제로
드러나기 쉬워졌다 - 1,000개를 변환해 Apply하면 gamelist.xml을 1,000번 다시 쓴다.
다음에 다룰 후보로 우선순위가 올라갔다. 고칠 때는 **되돌리기 정책을 먼저 정해야 한다**
(지금은 항목 하나가 실패하면 그 항목의 파일만 되돌린다).

**검증**: 파이썬 305개(신규 13), Playwright 51개(신규 6) 전부 통과. 커밋 `aca1366`,
`origin/main`에 push 완료.

**다음**: Phase 7.3(이월분: `match_links` rename, Compare Row key 구조화) 또는 위의
`write_index` bulk화. Phase 8(MTP)은 여전히 선택 항목이다.

---

## Phase 7.2 Hardening — 변환의 마지막 10% 검증 (2026-09-08, Claude Code)

리뷰가 지목한 9개 항목 처리. 상세는 `docs/REPORTS/2026-09-08-phase7.2-hardening.md`.

### 실제 버그 — `frontend_raw`가 Frontend 간 Convert를 통째로 깨뜨리고 있었다

`frontend_raw`는 **Frontend마다 모양이 다르다**.

```
ES-DE   : {"tag": "playcount", "text": "17", "attrib": {}}
Pegasus : {"key": "sort-by",   "value": "..."}
```

Convert가 source의 raw를 그대로 실어 보내 target Adapter가 되살리려다
`KeyError: 'key'` → **미지 태그가 하나라도 있으면 Apply가 통째로 실패**했다.

**고친 방식: 값이 자기 출처를 밝힌다.**
- `RAW_FRONTEND_KEY = "_frontend"` — `frontend_raw` 안에 들어가는 출처 표시.
- `adapter.tag_raw(raw)` — `to_common()` 마지막에 붙인다. **새 Adapter를 만들면 여기도
  반드시 부를 것**(`AdapterContractTests`가 검사한다).
- `adapter.raw_is_mine(raw)` — 소비하는 쪽에서 판정.

출처를 **값 안에** 넣었기 때문에 Clipboard 핸드오프 파일이나 Archive DB를 거쳐도 따라간다.
소비처 두 곳(`_apply_add`, `archive/service.py::to_collection`)에서 남의 것이면 버리고
내 것이면 `strip_location_raw()`만 적용한다.

**출처 표시가 없으면 내 것으로 본다.** 예전에 저장된 값에는 표시가 없는데, 없다고 버리면
계약 2를 어기는 쪽이 된다. 이 기본값을 뒤집지 말 것.

### fixture가 현실보다 깨끗하면 테스트가 통과한다

Phase 7.2 테스트가 이 버그를 놓친 이유는 `build_custom_esde_tree()`가 미지 태그를 만들지
않아서다. **Convert/왕복 테스트를 새로 쓸 때는 미지 태그와 media를 실제로 심을 것** -
`tests/test_convert_integration.py::esde_source()`가 그 형태다.

### 확인만 하고 넘어간 것

`cache`의 media 키 이름이 `rel_path`인데 **실제로는 절대 경로**다(`scanner.py`가
`m.path`를 그대로 넣는다). 동작은 정상이고 테스트로 고정했다. 이름을 고치려면 cache
스키마와 clipboard 핸드오프 포맷을 함께 건드려야 해서 미뤘다 - **`rel_path`를 보고
상대 경로라고 가정하지 말 것.**

### 벤치마크 — 앞서 내가 적은 우선순위가 틀렸다 (정정)

Phase 7.1·7.2 항목에 "`write_index()`의 O(n²)가 다음 과제"라고 적었는데, **재 보지 않고
단정한 것이라 틀렸다.**

| | 1,000 게임 | 5,000 게임 |
|---|---|---|
| Convert 미리보기 | 0.04s | 0.22s |
| Convert → Plan | 0.28s | 1.47s |

미리보기/Plan은 문제없다. Apply는 100/200/400게임 = 4.55/9.67/20.50s로 **선형이되
항목당 약 50ms**다(O(n²)가 아니다).

그 50ms를 갈라 보면(200게임 기준 9.79s):

| 복사 호출만 제거 | **1.98s** |
|---|---|
| write_index만 제거 | 7.87s |

**복사가 80%, `write_index`가 20%.** `_apply_add`가 항목마다 `file_ops.copy_files()`를
불러 **Robocopy 프로세스가 매번 새로 뜨는 것**이 진짜 병목이다.

→ 먼저 고칠 것은 **항목별 복사 호출을 묶는 것**이고 `write_index` bulk화는 그 다음이다.
둘 다 "항목마다 vs 묶어서"라는 같은 모양이라, **되돌리기 정책을 한 번 정하면 함께
처리할 수 있다** - 지금은 항목 하나가 실패하면 그 항목의 파일만 되돌리는데, 묶으면 그
경계가 사라진다. "어디까지 되돌릴 것인가"를 정하는 것이 그 작업의 본체다.

**검증**: 파이썬 323개(신규 18), Playwright 51개 전부 통과. 커밋 `5bc9e6f`,
`origin/main`에 push 완료.

---

## Phase 7.3 — Apply의 항목별 호출을 묶는다 (2026-09-08, Claude Code)

Phase 7.2 Hardening의 측정을 근거로 고쳤다. **400게임 Apply 20.50s → 1.20s(17배).**
상세는 `docs/REPORTS/2026-09-08-phase7.3-apply-batching.md`.

### 구조 — `_apply_adds()`의 세 단계

```
준비 : 항목마다 복사할 쌍을 계산만 한다 (파일 안 건드림)
복사 : COPY_BATCH(25)개씩 묶어 file_ops.copy_files()
기록 : System 단위로 adapter.write_index() 한 번
```

**전부 한 번에 묶지 말 것.** 복사는 Apply에서 가장 오래 걸리는 구간이라 통째로 묶으면
그 동안 진행률이 멈춰 사용자는 앱이 죽은 것으로 본다. `COPY_BATCH`를 없애거나 아주
크게 만들면 그 회귀가 난다 - `test_progress_still_moves_during_the_copy`가 막는다.

### 이번 작업의 핵심 구분 — **호출을 묶는 것과 실패를 묶는 것은 별개다**

`copy_files()`가 **목적지별 성공 여부**를 돌려주므로, 호출을 묶어도 어느 항목이
실패했는지 정확히 안다. 그래서 되돌리는 것은 **그 항목이 이번에 새로 만든 파일**뿐이다.

묶었다고 묶음 전체를 실패로 처리하지 말 것. 실제로 그렇게 바꿔 보니 테스트 3개가
실패한다(`test_one_failed_copy_does_not_drag_down_its_batch` 등).

### 되돌리기 정책은 **바꾸지 않았다**

리뷰가 "정책 고정"을 요구했지만, 확인해 보니 이미 `tests/test_plan_recovery.py`에
명시돼 있었다(Phase 3 hardening). 새로 정하지 않고 그대로 지켰다.

| 실패 지점 | 정책 |
|---|---|
| 복사 | 그 항목만 FAILED, 그 항목이 새로 만든 파일만 되돌림 |
| 메타데이터 쓰기 | 복사한 파일을 되돌리고 FAILED (묶음 때문에 대상이 그 System 전체로 늘어남) |
| media 링크 쓰기 | PARTIAL, **파일은 유지** (Phase 7.1에서 정함) |

**media 링크만 정책이 다른 이유**: 메타데이터가 없으면 그 ROM은 gamelist에 없는 유령
파일이 되어 다음 Apply가 충돌로 막힌다 → 되돌리는 게 낫다. media 링크만 없으면 항목은
이미 gamelist에 있고 파일도 유효하다 → 되돌리면 오히려 복사를 다시 해야 한다.

### 실측 (이 숫자를 기준선으로 쓸 것)

| 게임 수 | 이전 | 이후 |
|---|---|---|
| 100 | 4.55s | 0.34s |
| 200 | 9.67s | 0.60s |
| 400 | 20.50s | 1.20s |

호출 횟수(400게임): `copy_files` 400 → 16회, `write_index` 400 → 1회.
media 포함 실제 규모: 1,000게임 12.36s / 5,000게임 61.34s — **남은 시간은 실제 파일
I/O이지 프로세스 기동 몫이 아니다.** 여기서 더 줄이려면 복사 자체를 봐야 한다.

**검증**: 파이썬 331개(신규 8), Playwright 51개 전부 통과. 커밋 `022ef78`,
`origin/main`에 push 완료.

**다음**: 이월분 두 개 — `match_links`가 파일명 rename에 끊기는 문제(Phase 5에서 이월),
Compare Row key 구조화(Phase 6에서 이월, 우선순위 낮음). 그 다음이 Phase 8(MTP, 선택).

---

## Phase 7.4 — Match 링크가 파일 rename에도 살아남게 (2026-09-08, Claude Code)

Phase 5에서 이월된 문제를 닫았다. 상세는
`docs/REPORTS/2026-09-08-phase7.4-match-rename.md`.

### 이월할 때 적었던 이유가 틀렸다

Phase 5에서 "고치려면 Cache에 안정적인 rom key를 심어야 하니 스키마를 또 흔든다"고
미뤘는데, **Cache가 이미 `volume_file_id`(`st_dev:st_ino`)를 들고 있었다.** Windows
실측: rename과 내용 수정에는 유지되고 새로 만든 파일과는 다르다.

### 설계 — 주 키는 그대로, 파일 ID는 보조 수단

`(collection_id, system, filename)`이 여전히 주 키다. 파일 ID를 주 키로 **삼지 말 것**:
네트워크 공유/비NTFS에서는 값이 없고, 다른 볼륨으로 옮기면 바뀐다.

파일 ID는 `match_links`의 열로 저장해 두 가지에만 쓴다.

1. **이름이 같아도 파일 ID가 다르면 남남으로 본다.** rename 뒤 같은 이름의 다른 파일이
   생기면 이름만 보고 옛 링크를 물려주게 된다.
2. **이름으로 못 찾으면 파일 ID로 되찾고, 그 자리에서 `filename`을 고쳐 놓는다**(자가
   복구). 되찾기만 하고 두면 그 뒤로도 매번 파일 ID로 뒤져야 한다.

파일 ID가 없으면(`None`) 예전과 똑같이 이름으로만 찾는다 - 그 환경에서 rename하면
링크가 끊기는 것은 **의도된 그대로**다.

### 계약 변경

`match_service.linked_identity(archive, collection_id, row)` — 예전에는
`(system, filename)`을 받았는데 이제 **cache row를 통째로** 받는다(`volume_file_id`가
필요하다). `archive/service.py::ingest_collection`이 호출부다.

`ArchiveStore.get_match_link(...)`에 `volume_file_id=` 키워드가 붙었다. 안 넘기면
예전처럼 이름으로만 찾는다 - **넘기는 것을 빠뜨리면 rename 복구가 조용히 죽는다.**

### 가장 중요한 테스트

`test_ingest_follows_the_renamed_link` — Match를 확정하는 이유가 "Ingest가 그 Identity에
붙게 하는 것"이므로, 링크가 끊기면 **Archive에 중복 Identity가 생긴다.** 이게 이 기능의
실제 효용이다.

파일 ID 조회를 임시로 꺼 보니 5개가 실패했다(Phase 7.1의 확인 절차를 그대로 따랐다).

### 남은 한계 (의도적)

**다른 볼륨으로 파일을 옮기면 링크가 끊긴다** - 파일 ID가 바뀌기 때문이다. 여기서 더
가려면 해시가 필요한데, 비용 때문에 계속 보류 중인 그 선택지다.

**검증**: 파이썬 341개(신규 10), Playwright 51개 전부 통과. 커밋 `fb88289`,
`origin/main`에 push 완료.

**다음**: Compare Row key 구조화(Phase 6에서 이월, 우선순위 낮음), Phase 8(MTP, 선택).
