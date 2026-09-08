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

**Phase 5(Match)까지 완료 + main에 push됨.** Phase 6(Compare Mode)이 다음 - `compare_engine.py`
일반화, Match 엔진의 티어 판정을 Compare 좌우 매칭에 재사용할 예정.

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
