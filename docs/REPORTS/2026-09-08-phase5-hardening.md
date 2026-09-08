# Phase 5 Hardening — 외부 리뷰 대응

**요약.** Phase 5(Match)에 대한 외부 리뷰의 지적 3건(P1 1건, P2 2건)과 성능 지적 1건을
반영했다. 그 과정에서 리뷰가 짚은 문제의 **더 나쁜 사례** 두 개를 추가로 발견해 함께
고쳤다 — 하나는 사용자가 본 근거와 기록되는 근거가 달라지는 것, 다른 하나는 Heuristic
티어가 사실상 도달 불가능한 죽은 코드였다는 것이다.

파이썬 211개(신규 15개), Playwright 29개(신규 1개) 전부 통과.

---

## 1. [P1] Apply Match가 근거 없는 링크를 티어까지 위장해 저장하고 있었다

리뷰 지적: 후보가 아닌 Identity도 `tier=heuristic, score=0`으로 저장된다.

**실제로는 더 나빴다.** `apply_match()`는 확정할 때 `classify()`를 다시 불렀는데,
`classify()`는 앞쪽 두 티어(Exact/Normalized)만 판정한다. 따라서:

```
사용자가 Heuristic 후보(78%)를 골라 Apply
        ↓
apply_match가 classify() 재호출 → None
        ↓
tier=heuristic, score=0.0 으로 기록
```

즉 **제대로 고른 Metadata/Heuristic 후보 전부가 "근거 없음"과 똑같은 모습으로 기록**되고
있었다. 점수가 가장 중요한 티어에서 점수가 거짓말을 한 셈이다.

### 고친 방식

- 확정할 때 **후보 목록을 다시 만들어 그 안에 있는지 확인**하고, 있으면 그 후보가 가진
  티어/점수를 **그대로** 기록한다. 사용자가 보고 고른 근거와 저장되는 근거가 같아진다.
- 후보에 없으면 **거절한다**. Match Link는 Ingest / Archive→Collection / Compare가 "같은
  ROM"이라고 믿고 쓰는 관계 데이터이므로, 근거 없는 연결이 섞이면 나중에 그 링크가
  어디서 왔는지 데이터만 보고 설명할 수 없다.
- 정말 강제로 이어야 하면 `manual=True`를 명시해야 하고, 그때는 `TIER_MANUAL`로 남는다.
  엔진은 이 값을 **절대 반환하지 않는다** — 판정 결과와 사람의 단언을 데이터에서 구분한다.
  지금 UI에는 강제 연결 경로가 없다. Compare(Phase 6)처럼 사용자가 좌우를 직접 지목하는
  화면이 생길 때 쓰라고 열어 둔 것이다.

---

## 2. [P2] Metadata / Heuristic 티어를 사후에 끼워 맞추고 있었다

리뷰 지적: `breakdown["title"] < 20`으로 티어를 나누는 것은 임의적이다. 맞다.

이제 두 판정을 **각각의 함수로 분리**했다.

| 티어 | 판정 근거 | 함수 |
|---|---|---|
| Metadata | 구조화된 필드의 **동일성** — 개발사와 출시일이 함께 일치(배급사까지 같으면 가산) | `_metadata_match()` |
| Heuristic | 문자열 **유사도** | `_heuristic_match()` |

개발사만, 혹은 연도만 같은 것은 근거로 인정하지 않는다 — 같은 회사가 같은 해에 낸 게임은
얼마든지 있어서 후보 목록이 쓸모없어진다. 빈 값끼리는 "같다"로 치지 않는다.

또한 모든 티어가 **왜 이 티어인지 근거 문구(`evidence`)를 함께 돌려준다**. 후보 목록에
`정규화 파일명 일치 · 크기 다름`, `개발사 일치 · 출시일 일치`처럼 표시되어, 점수만 보고
판단해야 했던 문제를 없앴다.

---

## 3. [P2에서 파생] 임계값 60이 Heuristic 티어를 죽은 코드로 만들고 있었다

티어를 분리하고 Golden Test를 넣자마자 드러났다. `similar_rom`의 100점 만점은

```
title 35 + filename 15 + developer 15 + year 15 + screenshot 20
```

인데, **Match 경로는 스크린샷 해시를 아예 계산하지 않는다.** 게다가 Archive Identity에
개발사/출시일이 없으면 만점이 **50점**이다. 여기에 100점 척도용 임계값 60을 대면:

```
"Metal Gear Solid 2"  vs  "Metal Gear Solid 2 Substance"
  → 39.13 / 100  → 후보 아님
```

같은 프랜차이즈의 명백한 후보조차 올라오지 못한다. 실측해 보니 개발사나 연도 중 하나가
맞아떨어져도 최대 54점이라, **제목이 90% 이상 닮지 않는 한 Heuristic 티어는 도달
불가능**했다.

### 고친 방식 — 사용자가 정한 "60"의 의미는 지키면서 척도만 맞춤

점수를 **이번에 실제로 비교할 수 있었던 근거 기준으로 환산**한다. 양쪽 모두 값이 있는
항목의 배점만 더해 만점을 구하고 그 비율을 쓴다.

```
raw 39.13 / attainable 50 → 78.2%  → Heuristic 후보
```

이러면 60은 "가용 근거의 60%가 일치"라는 뜻이 되어, 모든 근거가 갖춰졌을 때의
`similar_rom` 60과 같은 의미가 된다 — 사용자가 "similar_rom과 통일" 취지로 60을 고른
결정을 그대로 지킨다. 근거가 너무 적을 때 환산이 과대평가되는 것은
`MIN_ATTAINABLE_EVIDENCE = 50`(제목+파일명)으로 막았다.

> **확인 요청**: 이 환산은 리뷰 대응 중 발견한 것이라 사전 상의 없이 넣었다. 60이라는
> 숫자는 그대로지만 **재는 척도가 바뀌었다**. 원래대로 raw 점수에 60을 대고 싶다면
> Heuristic 티어를 사실상 포기하는 것과 같다는 점만 알아두면 된다.

---

## 4. [성능] `quick_candidates`가 이름과 달리 전수 순회하고 있었다

리뷰 지적대로였다. 주석에는 "인덱스로 바로 찾히는 것만"이라 적어 두고 실제로는
`identities_in_system()`으로 그 System의 Identity를 전부 받아 파이썬에서 돌았다.
Gamelist 뱃지는 화면에 보이는 행마다 이걸 부르므로 (보이는 행 수 × System Identity 수)의
비교가 된다.

`ArchiveStore.identities_matching()`을 추가해 세 인덱스
(`ix_rom_identities_lookup`, `ix_games_title`, `ix_rom_identities_sha`)로 SQL이 먼저
거르게 했다. 보통 0~수 건만 돌아온다. Heuristic은 이름이 어긋난 뒤에 보는 것이라 이
질의로는 못 찾으므로, 전수 순회는 사용자가 Match 버튼을 눌렀을 때만 도는 deep 경로에만
남겨 두었다.

---

## 5. [정책 명시] 한쪽만 SHA256을 아는 경우

리뷰가 "버그는 아니고 문서화가 필요한 부분"으로 짚었다. 동의한다. `classify()`
docstring에 명시했다: 해시로 확정할 수 없으므로 (정규화 파일명 + 크기) 규칙으로
내려가며, 그 조합을 Exact의 2차 증거로 인정하는 것은 ARCHITECTURE의 해시 정책("전량
사전 해싱 금지, `(size, 정규화 파일명)`이 1차 판정")을 따른 **의도된 결정**이다.

---

## 6. Golden Test 고정

리뷰가 요청한 케이스를 `tests/test_match.py::GoldenMatchCases`로 전부 박아 두었다.
필드 하나 차이로 티어가 갈리는 케이스를 규모 생성기의 부산물로 얻으면 테스트가 무엇을
검증하는지 읽을 수 없으므로, 항목을 하나씩 지정하는 `build_custom_esde_tree()`를
fixture에 추가했다.

| 케이스 | 기대 |
|---|---|
| 해시 일치 | Exact |
| 파일명 + 크기 일치 | Exact |
| 이름·크기 같지만 해시 다름 | **후보 아님** |
| 지역판(이름 같고 크기 다름) | Normalized |
| 크기 모름(metadata-only) | Normalized (Exact 불가) |
| 개발사 + 출시일 일치 | Metadata |
| 개발사만 일치 | 후보 아님 |
| 빈 필드끼리 | 후보 아님 |
| 이름이 닮음 | Heuristic |
| 무관한 제목 | 후보 아님 |
| Exact 후보 2개 | **자동 매칭 금지** |
| manual 티어 | 자동 매칭 대상 아님 |

---

## 7. 남겨 둔 것

**`match_links`의 키가 파일명이라 rename에 끊긴다.** 리뷰 지적이 맞다.
`(collection_id, system, filename)`은 안정적이지만 사용자가 ROM을 rename하면 링크가
끊어진다. 다만 이걸 고치려면 Cache에 안정적인 rom key를 심어야 하고, 그건 Phase 5에서
이미 두 번 건드린 스키마를 또 흔드는 일이다. 리뷰의 권고대로 **Phase 6 이후**로 미룬다.

---

## 8. Phase 6 방향 정정 (중요)

기존 문서에 "Match 엔진의 `classify()`를 Compare의 좌우 매칭에 그대로 쓸 수 있다"고
적어 두었는데, **그대로 쓰면 안 된다.** 리뷰 지적이 맞다.

```
현재 classify(source, identity)
    source   = Collection의 cache row에서 만든 dict
    identity = Archive의 rom_identity 행

Compare가 필요한 것
    Collection A의 row  ↔  Collection B의 row
```

두 입력이 우연히 비슷한 모양일 뿐, 계약이 "Collection ↔ Archive"로 박혀 있다. 이대로
Compare를 얹으면 Phase 6에서 Match 코드를 다시 뜯게 된다.

올바른 방향은 판정 로직을 **한 단계 일반화**하는 것이다.

```
        MatchSubject (system / filename / title / size / sha256 / fields)
                 ↑                      ↑
        Archive Identity          Collection Row
                 └── classify(subject, subject) ──┘
```

`source_of_row()`가 이미 절반을 하고 있으므로, Archive 쪽에도 같은 shape을 만드는 어댑터를
두고 `classify()`가 subject ↔ subject를 받게 바꾸면 된다. Phase 6은 이 일반화부터 하고
Compare를 얹는다.
