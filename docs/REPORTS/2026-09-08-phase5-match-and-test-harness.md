# Phase 5 (Match) + 검증 하네스 도입 — 결과와 확정된 결정

**요약.** 요청대로 먼저 이전 프로젝트(RetroGameManager)의 자체 검증 방식이 이 구조에
쓸 수 있는지 검토하고 도입한 뒤, Phase 5(Match)를 구현했다. 도입 과정에서 이미 있던
버그 2건이 드러나 함께 고쳤다. 현재 **파이썬 196개 + Playwright GUI 28개 전부 통과**한다.

선택이 필요했던 3건은 §4에 있고 **2026-09-08 사용자 확정**됐다 - 임계값만 60으로 바뀌었고
나머지 둘은 현행 유지다.

---

## 1. 테스트 하네스 — 무엇이 쓸 수 있었고 무엇은 아니었나

| 이전 프로젝트 자산 | 재사용 여부 | 처리 |
|---|---|---|
| `tests/`의 fixture 빌더(`make_esde_local` 등) | **방식만** | 구조가 달라 코드는 못 쓰지만, "실제 Frontend 레이아웃을 흉내낸 트리를 미리 만들어 두고 테스트가 공유한다"는 방식이 정확히 필요했다. `tests/fixtures.py`로 도입 |
| `tests/test_api_wiring.py` + `tests_ui/api-wiring.spec.js` | **거의 그대로** | 가장 값어치가 컸다. 합쳐서 `tests/test_wiring.py` 하나로 |
| `playwright.config.js` + mock 폴백 구조 | **구조만** | 설정값은 리눅스 샌드박스 전용이라 이 PC에서 한 줄도 안 돌았다. 다시 씀 |
| `tests_ui/*.spec.js` 11개 | **아니오** | 폐기된 MasterDB/GameListSet/ArchiveDB 개념을 전제한 화면 테스트라 이식 가치가 없다. 현재 UI 기준으로 새로 작성 |
| `tests/test_media_copy_worker.py`, `test_file_ops.py` | 이미 가져와 있음 | 파일 엔진 쪽은 Phase 0에서 넘어온 그대로 유지 |

### 1-1. 도입하면서 바꾼 것

**fixture를 테스트 모듈 밖으로.** 이전 프로젝트는 빌더가 `test_api.py` 안에 있어서,
그걸 쓰려고 import하면 남의 테스트까지 딸려 실행됐다(그 파일 주석이 불편을 그대로
기록해 뒀다). 이 저장소도 이미 `from tests.test_es_de_adapter import build_esde_tree`로
같은 길을 가고 있었다. `tests/fixtures.py`로 분리하고, 4개 파일에 복사돼 있던
`wait_idle`/`wait_job`/`scan`도 합쳤다.

**규모를 지정할 수 있는 fixture를 더했다.** `GOLDEN_VALIDATION.md`가 남긴 교훈("파일이
수백 개뿐인 데이터로는 실제로 문제가 터지는 임계치 근방을 지나가 보지 못한다")을
`build_scaled_esde_tree(systems, per_system, variant)` 형태로 옮겼다. 지역판/리비전/확장자
변종을 만들 수 있어 Match 테스트가 여기에 기대고 있다.

**3단 배선 검증을 Python 하나로.** `app.js → api-client.js → bridge/api.py`의 이름이
어긋나면 "버튼은 있는데 아무 일도 안 일어나는" 상태가 된다. 이전 프로젝트는 이걸 두
파일로 나눠 봤고 앞쪽은 Playwright 러너를 통해서만 돌았는데, 브라우저가 전혀 필요 없는
검사였다. 합치면서 **인자 개수(arity)**와 **목업 커버리지**까지 보게 했다.

### 1-2. 도입하자마자 나온 결과

목업 커버리지 검사가 **8개 호출이 목업에 아예 없다**는 것을 즉시 잡아냈다 —
Collection 생성/이름변경/제거, External Storage 추가/제거, System 이동, Plan 엔트리 제거.
목업에 없으면 `{ok:false}`로 떨어지므로, 그 화면들은 **GUI 테스트를 붙여도 오류 경로만
지나갔을 것**이다. 목업을 `ok(true)`로 때우지 않고 배열을 실제로 바꾸는 형태로 채워서
"이름을 바꾸면 탭 제목도 바뀐다"까지 확인할 수 있게 했다.

### 1-3. 환경 변경 (알려둘 것)

이 PC에 **Node.js가 설치돼 있지 않아** Playwright를 돌릴 수 없었다. winget으로 Node LTS
v24.19.0을 설치하고 `npm install` + `npx playwright install chromium`을 마쳤다. 지금은
`npx playwright test` 한 줄로 GUI 테스트 28개가 돈다(약 10초).

---

## 2. 도입 과정에서 드러난 버그 2건

### 2-1. Archive에서 고친 Metadata가 화면에 안 보였다

`archive_detail()`이 표시용 `fields`를 "가장 최근에 갱신된 출처"에서 뽑았는데, Archive
직접 편집은 출처가 아니라 `__archive__`라는 별도 기록이다. 정작 Archive → Collection으로
내보낼 때는 `_resolve_fields()`가 그 편집본을 쓰고 있어서, **화면에는 원본이 보이는데
실제로 나가는 값은 편집본**인 상태였다. 기존 테스트가 이미 이 버그를 잡고 있었는데 실패한
채로 남아 있었다(세션 시작 시점 176개 중 1개 실패).

### 2-2. 지역판이 하나의 ROM Identity로 합쳐지고 있었다 (§46 위반)

`app/store/archive.py`의 문서는 "같은 게임의 Japan/USA/Korea판은 서로 다른 ROM
Identity"라고 적어 뒀지만, `ensure_rom_identity()`가 `filename_norm`(괄호 안 정보를
통째로 버림)으로 Identity를 찾아 정반대로 동작했다. 실측으로 확인:

```
두 Collection에서 각각 3개씩 Ingest
  기대: 6개 (USA 3 + Europe 3)
  실제: 3개 — 나중에 들어온 쪽의 파일명/크기가 사라짐
```

Archive → Collection이 **엉뚱한 지역판 파일을 가져올 수 있는** 상태였다. Match는 "서로
다른 Identity를 사람이 이어준다"가 전제이므로, 이걸 고치지 않으면 Phase 5 자체가 성립하지
않는다. `rom_key`(괄호 보존)를 Identity 키로 쓰도록 고쳤다(migration 3).

---

## 3. Phase 5 — Match

### 티어

| 티어 | 판정 | 자동 |
|---|---|---|
| Exact | 해시 일치, 또는 (정규화 파일명 + 크기) 일치 | **O** (후보가 하나일 때만) |
| Normalized | 정규화 파일명/제목은 같지만 크기가 다르거나 모름 | X |
| Metadata | 제목은 안 닮았는데 개발사/연도가 겹침 | X |
| Heuristic | `similar_rom` 점수 ≥ 60 | X |

- **파일명만으로는 절대 Exact가 되지 않는다**(§47). 크기를 모르는 metadata-only 항목은
  Normalized로 내려간다.
- 해시가 서로 **다르면** 이름이 같아도 후보에서 뺀다.
- Exact 후보가 둘 이상이면 자동으로 고르지 않는다(§88 — 모호하면 사람이 정한다).

### 성능

행마다 부르는 뱃지 계산(`quick_candidates`)과 사용자가 눌렀을 때만 도는 전수 비교
(`deep_candidates`)를 나눴다. `similar_rom.py`가 세워둔 "자동 실행 안 함, 사용자가 요청한
스코프에서만 O(n) 비교" 원칙을 그대로 지킨다.

### 확정한 선택을 기억한다

`match_links` 테이블(migration 4). 키를 `rom_uid`로 잡지 **않았다** — cache의
`replace_system()`이 System 단위로 DELETE 후 재삽입하므로 AUTOINCREMENT 값이 재스캔마다
바뀐다. `(collection_id, system, filename)`이 안정적인 키다. `archive_ingest()`는 링크가
있으면 새 Identity를 만들지 않고 그쪽에 붙는다.

### UI

Gamelist 행에 `[n]` 뱃지 → 누르면 스펙 §49의 화면 그대로. 확정해도 파일과 Metadata는
건드리지 않고 "같은 것"이라는 사실만 남는다. 값을 실제로 가져오는 것은 여전히
Archive → Collection이다.

---

## 4. 확인이 필요했던 결정 3건 — **2026-09-08 사용자 확정**

### ① Heuristic 임계값 → **60점으로 확정**

처음에는 55로 두었다("후보를 보여줄 뿐 자동 반영이 없으니 놓치는 쪽을 줄이자"). 사용자가
`similar_rom.py`의 기본값 60과 맞추는 쪽을 택했다 - 두 곳이 서로 다른 기준으로 "닮았다"를
판정하면 유사롬 목록과 Match 후보가 어긋나 보이는 이유를 설명할 수 없기 때문이다.
`engine.HEURISTIC_THRESHOLD = 60.0`.

### ② Normalized를 자동에 넣지 않은 것 → **현행 유지로 확정**

"정규화 파일명이 같고 크기만 다르다"는 상당히 강한 신호라 자동으로 붙이자는 선택도
가능하다. 다만 그게 정확히 **지역판/리비전이 갈리는 지점**이라, 자동으로 붙이면 USA판
메타데이터가 Europe판에 조용히 들어간다. §49를 문자 그대로 지키는 쪽(=후보로만 제시)을
택했다.

### ③ Match 확정이 Metadata를 가져오지는 않는다 → **현행 유지로 확정**

지금은 "같은 것"이라는 사실만 기록하고, 값을 가져오려면 Archive → Collection을 따로
실행해야 한다(§40의 "Archive는 Canonical Source가 아니다"를 따른 것). Apply Match 직후에
"바로 가져올까요?"를 묻는 흐름도 검토했으나, Match와 값 반영이 한 동작으로 붙으면
되돌리기가 애매해져 지금 형태를 유지하기로 했다.

---

## 5. 다음

Phase 6(Compare Mode) — `compare_engine.py` 일반화. Match의 티어 판정을 Compare의 좌우
매칭에 그대로 쓸 수 있으므로 이번 엔진이 그쪽 기반이 된다.
