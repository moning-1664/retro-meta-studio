# Phase 6 Post-Hardening — 외부 리뷰 대응

**요약.** Phase 6 리뷰의 백로그(P0 1건, P1 4건, P2 2건)를 처리했다. P1의 "Compare에서
변경 작업이 실행되지 않는지 확인"은 **확인해 보니 실제로 실행됐다** — 가장 중요한 수정이다.

파이썬 236개(신규 7개), Playwright 41개(신규 5개) 전부 통과.

---

## P0 — `Same`의 의미를 고정했다

리뷰 지적대로 **`Same`은 "ROM 파일이 같다"는 뜻이 아니다.** 정의를 세 곳에 못박았다.

| 상태 | 정의 |
|---|---|
| `Same` | 양쪽에 대응 항목이 있고 **비교 대상 Metadata가 동일** |
| `Conflict` | 양쪽에 대응 항목이 있고 **비교 대상 Metadata가 상이** |
| `Only A` / `Only B` | 한쪽에만 존재 |

- **엔진**: `app/compare/engine.py` docstring.
- **UI**: 필터 버튼 툴팁에 그대로 적었다 — Same은 *"양쪽에 있고 비교 대상 Metadata가 같음
  (ROM 파일이 같다는 뜻은 아님 - 크기는 상세에서 확인)"*.
- **테스트**: `CompareContractTests`가 "같은 이름 + 다른 크기 + 같은 Metadata → Same"을
  박아 둔다. 누군가 Compare를 "ROM identity 비교"로 바꾸면 여기서 깨진다.

Pairing 정책(같은 파일명이면 크기/해시가 달라도 짝)은 리뷰 판단대로 **유지**했다.

---

## P1 — Compare가 read-only가 아니었다 (실제 버그)

"확인해야 한다"는 항목이었는데, 확인해 보니 **세 갈래로 변경이 가능했다.**

### ① Ctrl+V — 실제로 붙여넣기가 실행됐다

`bindEvents()`의 단축키는 `if (!S.activeId) return;`만 보고 Compare 여부를 보지 않았다.
`pasteIntoActive()`는 **선택 항목이 없어도 동작**하므로 비교 화면에서 Ctrl+V를 누르면
클립보드 내용이 활성 Collection의 Plan에 들어가고, **Auto Plan이 꺼져 있으면 `applyPlan()`이
이어져 실제 파일까지 움직였다.**

### ② Ctrl+S — 저장 경로로 들어갔다

Compare 상세도 `S.detailState.tab === "metadata"`라서 저장 조건을 통과했다.
`state.romUid`가 없어 백엔드에서 실패로 끝나긴 했지만, 비교 화면에서 쓰기 경로를 타는 것
자체가 잘못이다.

### ③ 내비 드래그 — System 이동이 가능했다

Compare 중에도 System 행이 `draggable`이었고 Storage 헤더가 드롭을 받았다.
`moveSystemToStorage()` → `planStorageChange()`, Auto Plan이 꺼져 있으면 즉시 적용.
`Add External Storage` 버튼과 Storage 우클릭 메뉴(제거 포함)도 살아 있었다.

### 고친 방식 — 화면에서 지우는 것과 문 앞에서 막는 것을 **둘 다** 했다

버튼만 숨기면 단축키와 드래그가 남고, 함수만 막으면 사용자는 눌리는 버튼이 왜 아무 일도
안 하는지 모른다.

- `blockedInCompare(what)` 헬퍼를 만들어 변경 함수 6개(`copySelection` / `pasteIntoActive` /
  `deleteSelection` / `handleSaveDetail` / `moveSystemToStorage` / `openAddStorage`) 입구에서
  막고 **왜 안 되는지 토스트로 알린다**.
- 상태바는 Compare 중 Copy/Paste/Delete/Apply를 아예 그리지 않고 `읽기 전용` 배지만 둔다.
  (Paste와 Apply는 선택이 없어도 눌리는 버튼이라 남겨두면 그대로 변경이 일어난다.)
- 내비는 Compare 중 `draggable`을 붙이지 않고, 드롭·컨텍스트 메뉴·Add Storage를 뺀다.
- Ctrl+S는 `isCompare()`를 함께 본다.

> **설계 메모**: 처음엔 단축키를 통째로 `return`시켰는데, 그러면 아무 반응이 없어 "키가
> 안 먹네"로 보인다. 지금은 단축키를 삼키지 않고 각 함수가 막으면서 안내를 낸다.

---

## P1 — Compare Detail에 크기 차이 표시

값 비교표 **위에** 파일명/크기 표를 따로 두었다. 같은 이름인데 크기가 다르면 다른 덤프일
수 있다는 것이 값 하나하나보다 먼저 알아야 할 정보이기 때문이다. 크기는 Cache에 이미 있어
파일을 다시 읽지 않는다. SHA-256 비교는 리뷰 판단대로 **이번 작업에서 제외**했다.

---

## P1 — 스냅샷 상태를 화면에 밝혔다

`start_compare` 시각을 `takenAt`으로 함께 돌려주고, 비교 막대에 `Snapshot HH:MM:SS`와
`[Refresh]`를 넣었다. Refresh는 `start_compare()`를 다시 부르는 것뿐이다 — 리뷰 권고대로
자동 갱신은 하지 않는다.

---

## P1 — 테스트 추가

| 테스트 | 고정하는 것 |
|---|---|
| `test_same_means_metadata_is_identical_not_the_rom` | 같은 이름 + 다른 크기 + 같은 Metadata → Same |
| `test_metadata_media_and_size_differ_independently` | Metadata/Media/크기는 **독립적인 신호** |
| `test_media_difference_alone_never_becomes_a_conflict` | Media만 달라도 Conflict가 아니다 |
| `test_state_reports_when_the_snapshot_was_taken` | `takenAt` 제공 |
| `test_the_snapshot_does_not_change_underneath_the_user` | 비교 중 원본이 바뀌어도 결과 고정 |
| `test_starting_again_picks_up_the_change` / `test_exit_then_start_...` | 다시 시작하면 최신 반영 |

GUI 쪽도 read-only 보장(상태바/Ctrl+V/드래그), 스냅샷·Refresh, 크기 표시를 spec으로 박았다.

---

## P2 — 성능: 측정하고 나서 고쳤다

리뷰 권고대로 **먼저 쟀다**(4개 System에 고르게 분산, 파이썬 3.12).

| 규모 | 현실적(1차에서 전부 짝지어짐) | 최악(이름을 하나도 공유 안 함) |
|---|---|---|
| 1,000 × 1,000 | 0.00s | 0.30s |
| 5,000 × 5,000 | 0.03s | **7.32s** |

현실적인 경로는 문제가 없었지만 최악의 경우 7.3초는 눈에 띄는 정지다. `classify()`가
Exact/Normalized를 주는 조건이 "정규화 파일명 / 정규화 제목 / 해시가 같음" 셋뿐이므로,
그 세 키로 후보를 먼저 좁혔다(Phase 5에서 Archive 후보 검색을 인덱스로 좁힌 것과 같은 방향).

| 규모 | 현실적 | 최악 |
|---|---|---|
| 1,000 × 1,000 | 0.007s | 0.025s |
| 5,000 × 5,000 | 0.029s | **0.121s** (60배 개선) |

결과 자체는 그대로다(`test_compare.py` 25개 전부 통과) — 후보 밖의 항목은 애초에
Exact/Normalized가 될 수 없기 때문이다.

---

## 남겨 둔 것

- **Compare Row key의 구조화** (`"system|filename"` → 구조체). 리뷰 판단대로 우선순위
  매우 낮음 — Windows 파일명에 `|`가 못 들어가므로 지금은 실질적 버그가 아니다.
  다른 플랫폼까지 공통 모델로 넓힐 때 함께 본다.
- **SHA-256 Compare**. filesystem I/O 비용 때문에 후순위. 필요해지면 사용자가 요청한
  항목만 lazy 계산하는 방향으로 검토한다.
- **`match_links`가 파일명 rename에 끊기는 문제** (Phase 5에서 이월). 여전히 Phase 7 이후.
