# Test Report — 2026-09-08 (Phase 7.11 QA Audit)

대상 커밋 시작점: `df600a2` (Phase 7.10 안정성 보강 직후)

---

## 1. Audit 결과 — 새로 찾은 결함 4건

Phase 7.10에서 "승인한 것은 그 시점의 그 파일"이라는 규칙을 넣었지만, **그 규칙이
모든 경로를 덮지 못했다.** 규칙을 넣는 것과 규칙이 빠짐없이 적용되는 것은 다르다.

### ① 승인이 파일 단위가 아니라 항목 단위였다 (P0, 데이터 손실)

`entry.resolution`은 항목당 하나인데 충돌은 파일마다 생긴다. **커버 하나에
"덮어쓰기"를 누르면 그 항목 전체가 덮어쓰기 모드가 됐다.** 그 사이 목적지에 나타난
ROM은 사용자가 본 적도 없는데 덮어써졌다.

재현: `ApprovalIsPerFileTests.test_a_rom_that_appeared_later_is_not_overwritten`

### ② 승인 없이 건너뛰면서 "완료"라고 보고했다 (P0, 잘못된 연결)

충돌 승인이 없으면 그 파일은 조용히 복사에서 빠졌다. 그런데 **gamelist는 그대로
쓰고 항목을 APPLIED로 표시**했다. 결과적으로 메타데이터가 남의 ROM을 가리키고,
사용자는 자기 게임이 복사됐다고 믿는다. (I-05 / I-06 위반)

재현: `TargetAppearingAfterThePlanTests.test_the_entry_does_not_claim_success`

### ③ 원본 media에 snapshot 검증이 없었다 (P1)

ROM은 Phase 7.10에서 막았지만 media는 `exists()`만 봤다. Plan 이후 커버가 다른
그림으로 바뀌면 그 그림이 조용히 복사됐다.

재현: `SourceMediaSnapshotTests.test_a_replaced_cover_is_detected`

### ④ 테스트 자체의 결함 두 가지

- **Adapter 싱글턴 오염** — 인스턴스 속성으로 monkeypatch하고 치우지 않아,
  클래스 레벨로 패치하는 `test_plan_recovery`를 가려 **거짓 PASS**를 만들었다.
- **fixture flakiness** — 같은 크기 파일을 같은 clock tick에 만들어
  `classify_destination`이 서로 다른 파일을 "이미 같은 파일"로 판정했다. 실행할
  때마다 결과가 달랐다. `touch()`가 파일마다 다른 mtime을 찍도록 고쳤다.

---

## 2. 수정 내용

| 파일 | 변경 |
|---|---|
| `app/plan/builder.py` | `add_destinations()` / `approved_targets()` / `unapproved_overwrites()` — 승인 범위를 **파일 단위**로 정의하고 Validate·Apply가 같은 목록을 본다 |
| `app/plan/applier.py` | `_plan_copies()`가 `blocked` 반환. 승인 없는 대상이 하나라도 있으면 **그 항목은 아무것도 하지 않고** FAILED |
| `app/plan/validator.py` | 원본 media snapshot 검증, `unapproved_overwrites()` 사전 차단 |

정책 확정: 원본 media가 **없어진 것**은 빼고 진행(D3), **바뀐 것**은 멈춘다.

---

## 3. 테스트 실행 결과

```
Python (unit + integration + data-safety) : 468 passed, 1 skipped
  ├─ 신규 test_approval_scope             :   8
  ├─ 신규 test_provider_regression        :  27
  ├─ 신규 test_convert_integration (추가) :   2
  └─ 기존 (7.10 포함)                     : 431
Playwright (GUI, 목업 모드)               :  62 passed
```

전체 스위트를 **4회 연속** 돌려 순서 의존/flakiness가 없음을 확인했다.

## 4. 실제 ES-DE 데이터 검증

```
gamelist 27개 / 게임 1,558개 / 값 14,282개
  태그가 달라진 파일   0
  값이 달라진 필드     0
  원본 무결성          sha256 전후 동일 (983b07c55aacac06)
```

원본은 읽기 전용. 모든 쓰기는 임시 폴더의 복사본에서 일어났다.

## 5. Release Gate

| 항목 | 상태 |
|---|---|
| P0-01 승인 없는 target overwrite | **PASS** |
| P0-02 overwrite 후 원본 복구 | **PASS** |
| P0-03 partial scan 캐시 삭제 | **PASS** |
| P0-04 source/target 변경 감지 | **PASS** |
| P0-05 실패 후 filesystem/metadata 모순 | **PASS** |
| ES-DE round trip | PASS |
| Metadata preservation | PASS |
| Target/Source/Media/Delete stale detection | PASS |
| Overwrite rollback | PASS |
| Storage classification | PASS |
| Phase 8 Provider regression | PASS |
| Media replacement (GUI drag) | **NOT TESTED** |
| Archive merge 충돌 규칙 | **NOT TESTED** (정책 미확정) |
| Collection → Collection 붙여넣기 workflow | **NOT TESTED** |
| Plan drag / clipboard / Execute (실제 GUI) | **NOT TESTED** |
| External filesystem refresh | **NOT TESTED** |
| Cancel safety | **NOT TESTED** |
| Restart recovery | **NOT TESTED** |

## 6. Known Limitations

1. **같은 tick 안의 제자리 덮어쓰기는 감지 불가.** mtime도 file id도 바뀌지 않는다.
   해싱 없이는 원리적으로 불가능하며, SHA256 전면 도입은 4GB ISO 수천 개에 쓸 수 없다.
   `test_the_known_limit_is_written_down`에 테스트로 기록.
2. **덮어쓰기 중 디스크 사용량이 일시적으로 2배.** 백업을 작업 끝까지 유지하는 정책의
   대가다.
3. **media 링크 쓰기 실패는 되돌리지 않는다**(PARTIAL). 되돌리면 새로 복사한 ROM이
   사라지기 때문이다.
4. **Playwright 62개는 목업 API 위에서 돈다.** "GUI 성공 메시지 = 실제 파일 결과"는
   아직 검증되지 않았다.

## 7. Phase 8 진행 가능 여부

**P0 5개는 모두 PASS. Provider 전환에 회귀 없음(4개 Adapter × 왕복 검증).**

다만 지시서의 Release Gate 중 GUI/E2E 계열 7개 항목이 NOT TESTED다. 이들은 전부
**실제 filesystem에 닿는 E2E 하네스가 없어서** 못 한 것이고, 목업 위의 Playwright로는
대체할 수 없다. Phase 8을 "안정화 완료"로 표시하려면 그 하네스가 먼저 필요하다.

## 8. 사용자가 직접 확인해야 할 Manual TC

자동화 하네스가 생기기 전까지 다음은 손으로 봐야 한다.

1. Collection A → B로 ROM 10개 drag → Plan → Execute → **실제 폴더에서** ROM/커버/
   gamelist 확인 → 앱 재시작 후 다시 확인
2. Ctrl+C / Ctrl+V 붙여넣기에서 Similar 항목(같은 게임 다른 지역)이 **자동 병합되지
   않고** 확인을 묻는지
3. 덮어쓰기 확인 창에서 **Cancel**을 눌렀을 때 파일이 하나도 안 바뀌는지
4. Media를 drag해서 교체 → 저장 → 재시작 후에도 유지되는지
5. 앱 두 개를 동시에 켜고 A→B 작업 시 클립보드/Plan이 서로 섞이지 않는지
6. 탐색기로 ROM을 추가/삭제/이름변경한 뒤 Refresh 했을 때 목록이 실제와 맞는지
