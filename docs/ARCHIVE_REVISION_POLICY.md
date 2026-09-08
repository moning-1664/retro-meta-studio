# Archive Revision Policy

## 1. 목적

Archive는 Collection의 단순 백업 저장소가 아니다.

Archive는 동일한 Game에 대해 서로 다른 Metadata 및 Media 상태를 **Revision**으로 보존하고, Collection에서 현재 사용 중인 데이터가 변경되거나 삭제되더라도 과거의 의미 있는 상태를 유지하기 위한 **historical version store**이다.

Archive의 핵심 목적은 다음과 같다.

- 동일 Game의 서로 다른 Metadata 상태를 보존한다.
- 서로 다른 Media 상태를 보존한다.
- 사용자가 수정한 Metadata/Media의 이전 상태를 보존한다.
- Collection에서 삭제된 데이터도 Archive에서는 유지할 수 있다.
- 여러 Revision 중 사용자가 선호하는 Revision을 지정할 수 있다.
- Archive → Collection Import 시 여러 Revision을 활용하여 최대한 완전한 Metadata/Media를 복원한다.
- 동일한 상태가 반복 Export되는 경우 불필요한 Revision을 생성하지 않는다.

---

# 2. 핵심 개념

## 2.1 Game Identity

Archive의 최상위 단위는 `Game`이다.

하나의 Game Identity 아래에 여러 Revision이 존재할 수 있다.

```text
Game Identity
│
├── Revision 1
├── Revision 2
├── Revision 3
└── Revision 4
```

Game Identity와 Revision은 서로 다른 개념이다.

- **Game Identity**: 동일 게임이라는 사실
- **Revision**: 해당 게임의 특정 시점의 Metadata/Media 상태

Revision의 수는 Export 횟수와 동일하지 않다.

---

# 3. Revision의 기본 원칙

## 3.1 Revision은 의미 있는 상태의 Snapshot이다

Revision은 특정 시점의 Metadata/Media 상태를 표현하는 불변(immutable) Snapshot이다.

Revision이 생성된 이후 해당 Revision의 내용을 직접 수정하지 않는다.

사용자가 기존 Revision을 수정할 경우 기존 Revision을 변경하는 것이 아니라 새로운 Revision을 생성한다.

```text
R1
 │
 └─ User Edit
      ↓
     R2
```

이를 통해 이전 상태를 항상 복원할 수 있다.

---

# 4. 동일 데이터의 중복 Revision 방지

동일한 Metadata/Media 상태를 반복해서 Export하더라도 새로운 Revision을 생성하지 않는다.

예:

```text
Export #1 → R1
Export #2 → R1
Export #3 → R1
```

Export #2와 #3에서 새로운 Revision을 만들지 않는다.

이를 위해 Revision은 내용 기반 fingerprint를 가진다.

권장 개념:

```text
metadata_fingerprint
media_fingerprint
revision_fingerprint
```

또는 이에 준하는 동등한 내용 식별자를 사용한다.

## 4.1 Revision 생성 규칙

```text
새로운 상태
   │
   ├─ 기존 Revision과 동일
   │      └─ 기존 Revision 재사용
   │
   └─ 기존 Revision과 다름
          └─ 새로운 Revision 생성
```

따라서 Revision 개수는 Export 횟수가 아니라 **서로 다른 상태의 개수**에 의해 증가한다.

---

# 5. Metadata Revision

동일 Game에 대해 서로 다른 Metadata가 Export되면 각각 별도의 Revision으로 보존한다.

예:

```text
Revision 1
title       = Game A
developer   = ABC
description = Description A

Revision 2
title       = Game A
developer   = ABC
description = Description B
```

두 상태가 다르므로 각각 독립적인 Revision이다.

Metadata 전체를 하나로 병합하여 기존 Revision을 덮어쓰지 않는다.

---

# 6. Media Revision

Media 역시 Metadata와 동일한 원칙을 적용한다.

서로 다른 Media 상태는 별도의 Revision으로 보존한다.

예:

```text
Revision 1
cover       = cover_a.png
screenshot  = screenshot_a.png

Revision 2
cover       = cover_b.png
screenshot  = screenshot_a.png
```

Revision 1과 Revision 2는 서로 다른 상태이므로 모두 보존한다.

Media를 무조건 하나의 최신 상태로 덮어쓰지 않는다.

---

# 7. Metadata와 Media의 관계

Metadata와 Media는 서로 독립적인 정보이지만 Revision에서는 하나의 상태로 함께 표현될 수 있다.

따라서 Revision은 다음과 같이 구성될 수 있다.

```text
Revision
├── Metadata
└── Media
```

다만 Metadata의 변경과 Media의 변경이 반드시 동일한 원인으로 발생한다고 가정하지 않는다.

구현에서는 Metadata와 Media 각각의 fingerprint를 유지하는 것이 권장된다.

```text
metadata_fingerprint
media_fingerprint
```

이를 통해 어느 부분이 변경되었는지 판단할 수 있다.

---

# 8. Preferred Revision

사용자는 특정 Revision을 해당 Game의 **Preferred Revision**으로 지정할 수 있다.

Preferred Revision은 Archive에서 사용자가 명시적으로 선택한 최우선 Revision이다.

```text
Game
│
├── R1
├── R2 ★ Preferred
└── R3
```

Preferred 설정은 Revision의 내용 자체를 변경하지 않는다.

권장 모델:

```text
Game
├── revisions
└── preferred_revision_id
```

즉, Preferred는 Revision의 본질적인 속성이라기보다 **Game이 현재 어떤 Revision을 선호하는지를 나타내는 선택 상태**로 관리하는 것을 권장한다.

---

# 9. Revision 우선순위

Revision을 선택해야 하는 경우 다음 우선순위를 사용한다.

```text
1. Preferred Revision
2. Latest Revision
3. Older Revision
```

단, 이 우선순위는 **전체 Revision을 하나만 선택한다는 의미가 아니다.**

Archive → Collection Import에서는 가능한 경우 **field-level / media-level BestEffort resolution**을 수행한다.

---

# 10. BestEffort Import

Archive → Collection Import에서는 Preferred Revision을 우선 사용한다.

그러나 Preferred Revision에 특정 정보가 없고 다른 Revision에 해당 정보가 존재하는 경우, 다른 Revision의 정보를 fallback으로 사용할 수 있다.

예:

```text
Preferred R2
title       = Game A
developer   = ABC
description = 없음

Latest R5
title       = Game A
developer   = 없음
description = Description B
```

Import 결과:

```text
title       ← R2
developer   ← R2
description ← R5
```

즉, Revision 전체를 하나 선택하는 것이 아니라 **각 Metadata field 및 Media 항목별로 최선의 정보를 구성**한다.

---

# 11. 값의 상태

BestEffort fallback을 올바르게 수행하기 위해 단순한 `NULL` 또는 값의 존재 여부만으로는 충분하지 않다.

최소한 다음 세 가지 상태를 구분해야 한다.

```text
VALUE
ABSENT
CLEARED
```

## 11.1 VALUE

해당 field에 실제 값이 존재한다.

```text
developer = VALUE("Nintendo")
```

BestEffort Import 시 해당 값을 사용할 수 있다.

---

## 11.2 ABSENT

해당 Revision에서는 해당 field에 대한 정보가 존재하지 않는다.

예:

```text
developer = ABSENT
```

이 경우 다른 Revision에 유효한 값이 있다면 fallback할 수 있다.

---

## 11.3 CLEARED

사용자가 명시적으로 해당 값을 삭제했다.

예:

```text
developer = CLEARED
```

이는 단순히 값이 없는 것과 다르다.

사용자가 의도적으로 삭제한 것이므로 BestEffort fallback으로 이전 Revision의 값을 다시 복원해서는 안 된다.

예:

```text
R1:
developer = "Nintendo"

R2:
developer = CLEARED
```

Import 결과:

```text
developer = 없음
```

R1의 `"Nintendo"`를 자동으로 부활시키지 않는다.

---

# 12. Media의 상태

Media도 동일한 개념을 적용할 수 있다.

```text
PRESENT
ABSENT
CLEARED
```

예:

```text
R1:
cover = cover_a.png

R2:
cover = CLEARED
```

이 경우 R2를 우선하여 Import하면 R1의 cover를 자동으로 복원하지 않는다.

반대로:

```text
R2:
cover = ABSENT
```

이라면 다른 Revision에 유효한 cover가 존재하는 경우 fallback할 수 있다.

---

# 13. 사용자 수정

사용자가 Detail 화면에서 Revision을 선택하고 데이터를 수정할 수 있다.

중요한 원칙:

> 사용자가 선택한 Revision 자체를 수정하지 않는다.

예:

```text
R1
 │
 └─ Detail에서 수정
       ↓
      R2
```

R1은 원본 상태로 유지되고 R2가 수정된 새로운 Revision이 된다.

---

# 14. Detail 화면의 기본 Revision

Detail 화면을 열었을 때는 기본적으로 현재 우선순위가 가장 높은 Revision을 표시한다.

우선순위:

```text
Preferred
   ↓
Latest
   ↓
Older
```

사용자는 필요하면 Revision 목록에서 다른 Revision을 직접 선택할 수 있다.

```text
Game A

★ R5  Preferred
  R4  Latest
  R3
  R2
  R1
```

Revision을 선택하면 해당 Revision의 원본 상태를 확인할 수 있다.

---

# 15. Revision 수정의 범위

사용자가 Revision을 선택하여 수정하면 수정 결과는 선택한 Revision의 후속 Revision으로 생성된다.

예:

```text
R3
 │
 └─ User Edit
       ↓
      R6
```

다른 Revision은 변경되지 않는다.

```text
R1  unchanged
R2  unchanged
R3  unchanged
R6  modified version of R3
```

이를 통해 Revision 간 독립성을 유지한다.

---

# 16. Parent Revision

Revision 간 관계를 추적하기 위해 `parent_revision_id`를 사용하는 것을 권장한다.

예:

```text
R1
│
└── R2
     │
     └── R3
```

예를 들어:

```text
R1 = 최초 Export
R2 = 사용자가 R1을 수정
R3 = 사용자가 R2를 수정
```

이라면:

```text
R2.parent_revision_id = R1
R3.parent_revision_id = R2
```

를 가진다.

단, Parent는 Revision의 데이터 동일성을 판단하기 위한 identity가 아니다.

Fingerprint가 Revision의 내용 동일성을 판단하고, Parent는 변경 계보(provenance)를 설명하기 위한 정보이다.

---

# 17. Revision Metadata

Revision에는 최소한 다음과 같은 정보를 저장하는 것을 권장한다.

```text
Revision
├── revision_id
├── game_id
├── created_at
├── created_by
├── source
├── parent_revision_id
├── metadata_fingerprint
├── media_fingerprint
└── revision_fingerprint
```

## 17.1 created_by

Revision이 생성된 원인을 표현한다.

예:

```text
export
user_edit
import
```

실제 구현에서 필요한 범위에 맞춰 enum을 정의한다.

---

## 17.2 source

Revision의 원천을 추적할 수 있어야 한다.

예:

```text
Collection A
Collection B
User
```

Source는 가능한 경우 provenance 정보로 보존한다.

---

# 18. Export Event와 Revision의 구분

Export 횟수와 Revision 횟수는 서로 다른 개념이다.

예:

```text
Export #1 → R1
Export #2 → R1
Export #3 → R2
Export #4 → R2
```

이 경우 Revision은 2개지만 Export는 4회 발생했다.

따라서 향후 Export 이력을 상세하게 관리할 필요가 생긴다면 다음처럼 별도 Event 모델을 둘 수 있다.

```text
Game
│
├── Revisions
│    ├── R1
│    └── R2
│
└── Events
     ├── Export #1 → R1
     ├── Export #2 → R1
     ├── Export #3 → R2
     └── Export #4 → R2
```

다만 초기 구현에서는 Export Event를 반드시 구현할 필요는 없다.

Revision과 Export Event를 혼합하여 Revision 수를 Export 횟수에 종속시키지 않는 것이 핵심이다.

---

# 19. Archive → Collection Import

Archive → Collection Import는 다음 우선순위를 사용한다.

```text
Preferred Revision
        ↓
Latest Revision
        ↓
Older Revisions
```

그러나 최종 결과는 field-level / media-level BestEffort로 구성한다.

## 19.1 Metadata 예

```text
Preferred R3
├── title       = Game A
├── developer   = ABC
└── description = ABSENT

Latest R5
├── title       = Game A
├── developer   = ABSENT
└── description = Description B
```

Import:

```text
title       = Game A       ← R3
developer   = ABC          ← R3
description = Description B ← R5
```

---

# 20. Media Import

Media도 동일한 방식으로 처리한다.

예:

```text
Preferred R3
├── cover
└── screenshot = ABSENT

Latest R5
├── cover
└── screenshot
```

Import:

```text
cover       ← R3
screenshot  ← R5
```

Preferred Revision에 없는 Media를 다른 Revision에서 보완할 수 있다.

단, `CLEARED` 상태는 fallback을 차단한다.

---

# 21. 충돌 처리

서로 다른 Revision에 서로 다른 값이 존재하는 것은 오류가 아니다.

예:

```text
R1:
genre = RPG

R2:
genre = Adventure
```

두 Revision을 하나의 값으로 자동 병합하지 않는다.

각 Revision은 독립적으로 보존한다.

사용자가 Preferred Revision을 지정하면 Import 시 Preferred 값이 우선된다.

Preferred가 없다면 Latest가 우선된다.

---

# 22. Collection에서 삭제된 데이터

Collection에서 Game 또는 특정 Metadata/Media가 삭제되더라도 Archive의 Revision은 자동으로 삭제하지 않는다.

예:

```text
Collection
   ↓ delete
Game A
```

이후에도:

```text
Archive
└── Game A
    ├── R1
    ├── R2
    └── R3
```

를 유지할 수 있다.

Archive는 Collection의 현재 상태를 자동으로 반영하여 과거 Revision을 삭제하는 저장소가 아니다.

---

# 23. Revision 삭제 정책

## 23.1 기본 정책

Revision은 자동으로 삭제하지 않는 것을 기본 정책으로 한다.

이유:

- Archive의 목적이 historical preservation이기 때문이다.
- 사용자가 Collection에서 데이터를 삭제한 경우에도 복구 가능해야 한다.
- 오래된 Revision이 현재 Preferred/Latest에서 사용되지 않더라도 historical value가 있을 수 있다.
- 자동 삭제는 사용자의 의도와 무관하게 데이터 보존성을 감소시킨다.

---

# 24. 사용자 주도 Archive 정리

Revision 수가 지나치게 증가하는 경우 사용자가 명시적으로 Archive를 정리할 수 있도록 한다.

향후 지원 가능한 기능:

```text
Delete Revision
Delete Duplicate Revisions
Keep Preferred
Keep Latest
Delete Older Revisions
Delete Revisions Before Date
```

자동 정리 기능을 추가하는 경우에도 사용자에게 명확한 범위와 결과를 보여줘야 한다.

---

# 25. Duplicate Revision 정리

Fingerprint가 동일한 Revision은 논리적으로 동일한 상태다.

예:

```text
R1 → fingerprint A
R2 → fingerprint B
R3 → fingerprint A
R4 → fingerprint C
R5 → fingerprint A
```

실질적으로 서로 다른 상태는:

```text
A
B
C
```

세 가지다.

따라서 향후 `Delete Duplicate Revisions` 기능을 제공할 수 있다.

단, 다음 Revision은 삭제 대상에서 제외해야 한다.

- Preferred Revision
- 다른 Revision의 parent로 참조되는 Revision
- 필요한 provenance를 보존하기 위해 유지해야 하는 Revision

정확한 삭제 조건은 구현 시 별도 정책으로 확정한다.

---

# 26. 자동 보존 개수 제한

기본적으로 `Keep Latest N`과 같은 자동 개수 제한을 적용하지 않는다.

예를 들어 기본값으로:

```text
최신 10개만 유지
```

와 같은 정책을 사용하지 않는다.

Revision의 개수 자체보다 Revision의 의미와 데이터 보존성이 더 중요하기 때문이다.

필요한 경우 사용자가 직접 보존 정책을 실행하도록 한다.

---

# 27. Revision 삭제 시 안전 규칙

Revision을 삭제하는 작업은 일반 파일 삭제와 동일하게 데이터 안전성을 고려해야 한다.

최소한 다음을 보장해야 한다.

1. Preferred Revision은 확인 없이 삭제하지 않는다.
2. 현재 Import 대상이 되는 Revision을 삭제할 경우 사용자에게 결과를 명확히 보여준다.
3. Revision 삭제로 인해 BestEffort fallback 결과가 변경될 수 있음을 고려한다.
4. 삭제 후 Game Identity 자체가 의도하지 않게 사라지지 않아야 한다.
5. 삭제 작업 실패 시 Archive가 부분적으로 손상되지 않아야 한다.

---

# 28. Revision과 Collection의 관계

Collection은 현재 사용자가 사용하는 working state이고 Archive는 historical state이다.

```text
Collection
    │
    │ Export
    ↓
Archive Revision
```

Archive → Collection:

```text
Archive Revisions
        │
        │ BestEffort Import
        ↓
Collection
```

Archive가 Collection의 자동 Sync 대상이라는 의미는 아니다.

Export와 Import는 명시적인 사용자 작업으로 취급한다.

---

# 29. Archive의 핵심 불변식

다음 불변식을 유지한다.

### Invariant 1 — Revision 불변성

생성된 Revision의 내용은 직접 변경하지 않는다.

### Invariant 2 — 동일 상태 중복 방지

동일한 Metadata/Media 상태에 대해 불필요한 중복 Revision을 생성하지 않는다.

### Invariant 3 — History 보존

Collection의 삭제나 변경이 기존 Archive Revision을 자동으로 삭제하지 않는다.

### Invariant 4 — Preferred 우선

Preferred Revision은 Import 및 기본 Detail 표시에서 최우선이다.

### Invariant 5 — Latest fallback

Preferred가 없거나 특정 정보가 없는 경우 Latest를 차선으로 사용한다.

### Invariant 6 — Field-level fallback

Import는 가능하면 Revision 전체가 아니라 field/media 단위로 BestEffort 구성한다.

### Invariant 7 — Explicit delete 보존

사용자가 명시적으로 삭제한 값(`CLEARED`)은 이전 Revision의 값으로 자동 부활시키지 않는다.

### Invariant 8 — Similarity는 permission이 아니다

Game Identity를 heuristic하게 판단하는 경우에도 유사성 판단만으로 자동 merge 또는 Revision 삭제를 수행하지 않는다.

---

# 30. 예시: 전체 Revision History

다음과 같은 상황을 가정한다.

```text
Export A
    ↓
R1

Export B
    ↓
R2
```

R1과 R2의 Metadata가 다르므로 별도의 Revision이다.

이후 사용자가 R2를 Preferred로 지정한다.

```text
Game A
├── R1
└── R2 ★ Preferred
```

사용자가 Detail에서 R1을 선택하여 description을 수정한다.

```text
Game A
├── R1
├── R2 ★ Preferred
└── R3
```

R3의 parent는 R1이다.

이후 R3가 현재 최신 Revision이 된다.

```text
Preferred = R2
Latest    = R3
```

Archive → Collection Import 시:

```text
Priority:
R2 → R3 → older revisions
```

각 field에 대해 BestEffort resolution을 수행한다.

---

# 31. 예시: CLEARED 처리

```text
R1
developer = Nintendo
genre     = Action
```

사용자가 R1을 기반으로 수정:

```text
R2
developer = CLEARED
genre     = Action
```

Import 시:

```text
developer → 없음
genre     → Action
```

R1의 `developer = Nintendo`를 복원하지 않는다.

이것은 단순히 R2에 developer가 없는 것과 다르다.

---

# 32. 예시: ABSENT 처리

```text
R1
developer = Nintendo
description = Description A

R2
developer = ABSENT
description = Description B
```

Import:

```text
developer   ← R1
description ← R2
```

R2의 developer가 ABSENT이므로 이전 Revision의 값을 fallback할 수 있다.

---

# 33. 예시: Preferred와 Latest

```text
R1
title = Game A

R2 ★ Preferred
title = Game A
developer = ABC

R3 Latest
title = Game A
description = New Description
```

Import:

```text
title       ← R2
developer   ← R2
description ← R3
```

따라서 Preferred와 Latest 중 하나를 통째로 선택하는 방식이 아니라 field-level resolution을 수행한다.

---

# 34. UI 권장 방향

Archive Game을 열었을 때 Revision 목록을 명확하게 보여준다.

예:

```text
Game A

Revision History
────────────────────────────
★ R5   Preferred    2026-09-08
  R4   Latest        2026-09-07
  R3                 2026-09-05
  R2                 2026-09-01
  R1                 2026-08-20
```

가능한 UI 기능:

```text
View
Edit
Set as Preferred
Compare
Import
Delete
```

Revision을 선택하면 해당 Revision의 Metadata/Media를 Detail에서 확인할 수 있다.

---

# 35. Compare 기능

향후 Revision Compare를 제공할 수 있다.

예:

```text
R2 vs R5

Metadata
────────────────────────
Title        same
Developer    R2: ABC
             R5: XYZ

Description  R2: ...
             R5: ...

Media
────────────────────────
Cover        different
Screenshot   R2 only
Marquee      R5 only
```

Compare는 자동 merge가 아니라 **사용자가 어떤 Revision을 Preferred로 선택할지 판단하기 위한 도구**로 사용한다.

---

# 36. 자동 Merge 금지 원칙

Archive Revision 간 차이를 발견했다고 해서 자동으로 하나의 Revision으로 병합하지 않는다.

예:

```text
R1 developer = ABC
R2 developer = XYZ
```

이는 충돌이며, 시스템이 임의로:

```text
developer = ABC
```

또는:

```text
developer = XYZ
```

로 원본 Revision을 변경해서는 안 된다.

원본 Revision은 그대로 유지하고 Preferred/Latest 및 BestEffort Import 정책을 통해 결과를 결정한다.

---

# 37. 향후 구현 우선순위

Archive Revision 기능 구현 시 다음 순서를 권장한다.

### Phase A — Data Model

- Game Identity
- Revision
- revision_id
- game_id
- created_at
- created_by
- parent_revision_id
- metadata_fingerprint
- media_fingerprint
- revision_fingerprint
- preferred_revision_id

### Phase B — Revision Creation

- Export 시 fingerprint 비교
- 동일 상태 중복 Revision 방지
- 변경 상태의 새로운 Revision 생성
- User Edit 시 새로운 Revision 생성

### Phase C — Revision Selection

- Preferred 관리
- Latest 계산
- Revision 목록
- Detail Revision 선택

### Phase D — BestEffort Import

- VALUE / ABSENT / CLEARED
- Metadata field-level fallback
- Media-level fallback
- Preferred → Latest → Older 순서

### Phase E — Revision Management

- Compare
- Delete
- Duplicate cleanup
- 보존 정책

---

# 38. 현재 단계에서 확정하지 않아도 되는 항목

다음 항목은 Revision 기본 모델이 완성된 이후 별도 설계로 확정할 수 있다.

- Export Event의 상세 모델
- Revision 삭제 시 parent 관계 처리
- Revision branch/merge visualization
- 자동 보존 기간
- 자동 보존 개수
- Revision 압축
- Binary Media deduplication
- Archive 전체 용량 관리
- Revision Compare UI의 상세 UX

이 항목들은 기본 Revision 모델을 변경하지 않는 범위에서 추후 추가할 수 있도록 설계한다.

---

# 39. 최종 정책 요약

Retro Meta Studio의 Archive Revision 정책은 다음과 같다.

```text
Archive
│
└── Game Identity
     │
     ├── R1
     ├── R2
     ├── R3 ★ Preferred
     └── R4   Latest
```

### Revision

- Revision은 immutable snapshot이다.
- 동일한 상태는 fingerprint로 중복 생성하지 않는다.
- Metadata가 다르면 Revision을 분리한다.
- Media가 다르면 Revision을 분리한다.
- 사용자가 수정하면 새로운 Revision을 만든다.
- 기존 Revision은 변경하지 않는다.

### Priority

```text
Preferred
   ↓
Latest
   ↓
Older
```

### Import

- Archive → Collection은 BestEffort 방식이다.
- Revision 전체가 아니라 field/media 단위로 fallback한다.
- `VALUE`는 사용한다.
- `ABSENT`는 다음 Revision으로 fallback할 수 있다.
- `CLEARED`는 fallback을 차단한다.

### Preservation

- Collection 삭제가 Archive Revision을 삭제하지 않는다.
- Revision은 기본적으로 자동 삭제하지 않는다.
- 사용자가 명시적으로 Archive를 정리할 수 있다.
- 동일 fingerprint Revision은 향후 사용자 주도로 정리할 수 있다.

### User Control

- 사용자가 Preferred Revision을 지정할 수 있다.
- 사용자가 원하는 Revision을 Detail에서 직접 선택할 수 있다.
- 선택한 Revision에서 수정하면 새로운 Revision이 생성된다.
- Revision 간 충돌은 원본을 삭제하거나 자동 병합하지 않는다.

---

# 40. 설계의 핵심 원칙

> **Archive는 "최신 데이터 하나를 보관하는 곳"이 아니라 "동일 Game의 의미 있는 상태들을 안전하게 보존하고, 사용자가 그중 원하는 상태를 선택할 수 있는 Revision History"이다.**

따라서 Archive의 기본 전략은:

```text
Preserve first
     ↓
Deduplicate identical states
     ↓
Never overwrite history
     ↓
User chooses Preferred
     ↓
Import with field-level BestEffort
```

이다.
