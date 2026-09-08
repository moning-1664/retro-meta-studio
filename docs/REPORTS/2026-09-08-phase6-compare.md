# Phase 6 — Compare Mode

**요약.** 스펙 §54-59의 Compare Mode를 구현했다. 착수 전에 리뷰가 지적한 대로 Match의
판정 계약을 `MatchSubject ↔ MatchSubject`로 한 단계 일반화했고, 그 덕분에 Compare가
Match 코드를 뜯지 않고 그대로 얹혔다.

파이썬 229개(신규 18개), Playwright 36개(신규 7개) 전부 통과.

---

## 1. 먼저 한 일 — 판정 계약을 한 단계 올렸다

Phase 5 hardening 리포트 §8에서 예고한 작업이다. 기존 `classify(source, identity)`는

```
source   = Collection cache의 row에서 만든 dict
identity = Archive의 rom_identity 행
```

로 **한쪽이 Archive로 못박혀** 있었다. Compare가 필요한 것은 `Collection A row ↔
Collection B row`이므로, 이대로면 Collection을 Archive인 척 꾸며 넘겨야 한다.

이제 중립 형태 `MatchSubject`를 두고 양쪽을 거기에 맞춘다.

```
              subject(system, filename, title, size, sha256, fields, ref)
                        ↑                              ↑
              subject_of_row()                 subject_of_identity()
              (Collection cache row)           (Archive rom_identity + fields)
                        └────  classify(a, b)  ────┘
```

`classify()` / `_metadata_match()` / `_heuristic_match()` 셋 다 이제 **대칭**이다 -
어느 쪽이 Collection이고 어느 쪽이 Archive인지 알지 못하고, 알 필요도 없다.
`ref`는 엔진이 들여다보지 않는 호출자 몫의 식별자다(`rom_uid`든 `rom_identity_id`든).

기존 이름 `source_of_row`는 별칭으로 남겨 Archive Match 경로를 건드리지 않았다.

---

## 2. 짝짓기 규칙은 Match와 **다르다** (중요)

여기가 이번 Phase에서 가장 조심한 부분이다. 판정 함수는 공유하지만 **쓰는 방식이 다르다.**

| | Match (Archive) | Compare |
|---|---|---|
| 묻는 것 | "이 둘이 같은 ROM인가?" | "이 두 목록을 어떻게 줄 세우나?" |
| 확증 없을 때 | 후보로만 내놓고 사용자가 선택 | 1:1로 짝지어 **차이를 보여준다** |
| 같은 이름 + 다른 크기 | Normalized 후보(자동 아님) | **짝으로 본다** |

마지막 줄이 핵심이다. Match의 Exact 기준(크기/해시 확증)을 Compare에 그대로 쓰면,
같은 이름의 다른 덤프가 "왼쪽에만 있음 + 오른쪽에만 있음"으로 갈라져 보인다. 그런데
사용자가 Compare를 여는 이유가 바로 **그 차이를 보려는 것**이다.

그래서 Compare의 짝짓기는 2단계다.

1. **정확한 파일명** — 같은 System에서 파일명이 완전히 같으면 짝. 크기/해시 무관.
2. **엔진 판정이 유일할 때만** — 남은 것들에 `classify()`를 돌려 Exact/Normalized로
   걸리는 상대를 찾되, **후보가 정확히 하나일 때만** 짝짓는다. 둘 이상이면 각자
   "한쪽에만 있음"으로 남긴다 — 모호하면 자동으로 결정하지 않는다(§88).

---

## 3. 상태 체계

| 상태 | 뜻 | 기호 |
|---|---|---|
| `same` | 양쪽에 있고 Metadata도 같다 | (없음) |
| `conflict` | 양쪽에 있는데 Metadata가 다르다 | `△` 노랑 |
| `only_a` | 기준에만 있다 | `−` 빨강 |
| `only_b` | 상대에만 있다 | `+` 파랑 |

**Media 차이는 상태를 바꾸지 않는다.** `mediaDiff`로 따로 표시하고 `[Media]` 필터로 본다.
Media만 다른 것을 Conflict라고 부르면 "Metadata가 충돌한다"는 뜻이 흐려지고, 스펙도
`[Media]`를 별도 필터로 둔다.

Conflict 판정에 쓰는 필드는 "이 게임은 무엇인가"를 서술하는 9개(`name`/`desc`/`genre`/
`developer`/`publisher`/`releasedate`/`region`/`players`/`rating`)뿐이다. ES-DE의
`favorite`/`playcount`처럼 사람이 관리하는 값까지 넣으면 목록이 온통 Conflict가 된다.

---

## 4. 구현 메모

- **비교 결과는 시작할 때 한 번 계산해 들고 있는다.** 필터를 누를 때마다 두 Collection을
  다시 훑으면 만 단위 목록에서 버튼이 먹통이 되고, 그 사이에 스캔이 끼면 필터마다 다른
  스냅샷을 보게 된다. 최신 상태로 보려면 사용자가 다시 시작하면 된다. Plan과 마찬가지로
  **세션 한정**이다(앱을 끄면 사라진다).
- **`CacheStore.all_entries()`를 새로 두었다.** `query_rows()`는 목록용이라 fields를 빼고
  `get_row()`는 한 건마다 질의를 세 번 한다. Compare는 두 Collection을 통째로 맞대므로
  행마다 `get_row()`를 부르면 (좌 N + 우 M)번의 질의가 된다 — 이제 Collection당 세 번이다.
- **Compare 행의 키는 `romUid`가 아니라 `system|filename`이다.** 좌우 어느 쪽에만 있을 수
  있어서 `romUid`가 없는 행이 존재하고, `romUid`는 재스캔마다 바뀐다(Phase 5에서 확인한
  것과 같은 이유).
- UI는 별도 화면이 아니라 **기존 Gamelist가 비교 모드로 바뀌는 것**이다(§54). 필터 막대만
  비교 막대로 교체되고, 목록/상세 패널은 같은 자리를 쓴다. `[Exit Compare]`로 되돌린다.

---

## 5. 다음

Phase 7 — 나머지 Frontend Adapter(Pegasus / LaunchBox / EmulationStation) + Round-trip 검증
+ ES-DE custom systems XML. `adapters/`의 인터페이스는 Phase 1에서 `frontend_raw` 보존을
강제해 두었으므로(R1), 어댑터를 늘리는 작업 자체는 그 계약을 따르면 된다.

Round-trip 검증에는 이번에 만든 Compare가 그대로 쓸 만하다 — "ES-DE에서 읽어 Pegasus로 쓰고
다시 읽었을 때 필드가 그대로인가"는 결국 두 Collection을 맞대는 일이다.
