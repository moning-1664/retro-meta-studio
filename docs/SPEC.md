# RetroMeta Studio — Product & Architecture Design Specification

- Version: 0.1
- Status: Design Baseline
- 이 문서는 제품 요구사항의 원본이다. 구현 판단과 아키텍처 결정은
  [`ARCHITECTURE.md`](ARCHITECTURE.md)에 있고, 그 문서의 §8 "확정된 결정"(D1–D5)이
  이 스펙과 충돌하는 부분의 최종 판단이다.
- UI 참고 예제: [`ui-reference.png`](ui-reference.png)

---

## 1. 목적

여러 Retro Game Frontend(ES-DE, Pegasus, EmulationStation 계열, LaunchBox, 기타
Adapter 추가 가능)의 게임 목록·메타데이터·ROM·Media를 하나의 작업 공간에서 관리하고
변환하는 데스크톱 애플리케이션.

핵심 개념은 기존 "MasterDB" 중심 구조를 폐기하고 넷을 명확히 분리하는 것이다.

| 개념 | 역할 |
|---|---|
| Collection | 실제 Frontend Collection을 표현하고 작업하는 논리적 게임 라이브러리 |
| Archive | 여러 Collection에서 수집한 Metadata/ROM Identity 정보 보관소 |
| Cache | 파일 시스템을 빠르게 다시 열기 위한 Scan 결과 및 상태 정보 |
| Plan | 실제 파일을 바꾸지 않고 추가/삭제/이동/변환 결과를 미리 계산한 변경 집합 |

파일 시스템에 대한 복사·삭제·이동·생성은 FileOperationEngine 계층을 통해 수행한다.

---

## 2. 핵심 설계 원칙

### 2.1 Collection이 기본 작업 단위다
"Local" / "MasterDB" 구조를 쓰지 않는다. 사용자는 하나 이상의 Collection을 열 수 있고
각 Collection은 하나의 Frontend 환경을 나타낸다(예: Master Library, Android ES-DE,
Windows ES-DE, Android Pegasus, Windows LaunchBox).

Collection은 "Master"라는 특수 타입을 갖지 않는다. 필요하면 이름을 'Master Library'로
지어 대규모 원본으로 쓸 수 있을 뿐이다.

### 2.2 동시에 Open 가능한 Collection은 최대 10개
영구 저장 가능한 Collection 수 제한이 아니라 동시에 화면에 띄울 수 있는 수 제한이다.
Collection을 닫으면 UI 상태만 제거하고 Cache와 실제 파일은 유지한다. 다시 열면 Cache로
빠르게 화면을 구성한 뒤 실제 파일 시스템을 검증한다.

---

## 3. 전체 시스템 구조

```
Collections · Archive · Cache
        → Game Model → (Edit / Compare / Match)
        → Plan → (Import / Export / Convert) → Preview → Apply
        → FileOperationEngine → File System
```

---

## 4. Collection

Collection은 특정 Frontend 환경의 게임 라이브러리를 논리적으로 표현한다.

```
Collection
├─ ID (이름과 독립적인 안정적 UUID)
├─ Name
├─ Frontend
├─ Platform / Target
├─ OS
├─ Architecture
├─ Root Path
├─ Systems
├─ Game Membership
├─ Frontend-specific Data
└─ Cache Reference
```

이름 변경은 ID에 영향을 주지 않는다.

---

## 5. Frontend / Target / OS / Architecture는 별도 저장

`Frontend != Platform != OS != Architecture`. 하나의 값으로 묶지 않는다.

예: Frontend=ES-DE, Target=Android, OS=Android, Architecture=ARM64.

정보가 없으면 임의로 추측하지 않고 **Unknown** 상태를 쓴다.

---

## 6~8. System 구조와 Storage

Collection 내부에는 여러 System(PS1, PS2, PSP, NDS, GBA, SNES …)이 있고 각 System은
자신의 저장 위치를 가진다.

Storage는 애플리케이션의 독립적 최상위 Entity로 만들지 않는다. Collection 내부의
System에 저장 위치를 종속시킨다.

**하나의 System은 Collection 안에서 반드시 하나의 Storage Location만 갖는다.**

허용: `PS2 → External`, `NDS → Internal`
금지: `PS2의 일부는 Internal, 일부는 External`

이 제약이 UI와 용량 계산을 단순하게 만들고, 같은 System이 양쪽에 중복 표시되는 문제를
막는다.

---

## 9~11. Internal / External

Collection 생성 시 Internal/External이 둘 다 존재할 필요는 없다. 사용자가 Internal에서
우클릭 → **Add External Storage**를 선택하면 External이 생성되고 실제 경로 등을 추가로
입력할 수 있다.

System은 UI에서 Internal ↔ External로 Drag & Drop 할 수 있다. Drag 시점에는 Plan
상태로만 들어가고 실제 파일은 이동하지 않는다. Apply/확정 시 실제 이동 또는 필요한
Copy/Delete가 실행된다.

Internal과 External은 서로 다른 Collection이 아니다. 사용자는 하나의 Collection으로 본다.

---

## 12~13. 왼쪽 Navigation

왼쪽 Navigation은 현재 상단 Tab에서 선택한 Collection만 표시한다. 다른 Collection을
중복 표시하지 않는다. 상단 Tab을 바꾸면 Navigation 전체가 해당 Collection 구조로 교체된다.

최상단에는 항상 **ALL**을 제공하며, 선택 시 Internal + External의 모든 System 게임을
가운데 Gamelist에 표시한다.

---

## 14~18. Collection Tab과 Header

상단에 동시에 Open된 Collection을 Tab으로 표시한다(최대 10개). 닫으면 Tab은 사라지지만
Cache와 저장된 Collection은 유지된다.

Collection Header는 평상시 2줄 정도의 compact 형태만 표시한다.

```
[ES-DE]  Android ES-DE                           [Android] [ARM64]
         1,284 Games · INT 31.2→27.5 GB · EXT 421.4→434.6 GB      [⌄]
```

우측 아래 Expansion 버튼을 누르면 Header가 확장되어 상세 정보(Frontend/Target/OS/
Architecture/Root Path/Systems/Games/Media, Internal·External 각각의 Capacity/Actual/
Plan/Free, `[Rescan] [Frontend Settings] [ES-DE XML]`)를 보여준다. 기존 Gamelist 공간을
최대한 침해하지 않는 Overlay/Expandable Panel 형태를 우선 고려한다.

Header의 Frontend/Target 아이콘으로 값을 바꿀 수 있다는 원안은 **변경되었다**: Header에서
직접 Frontend를 바꾸지 않는다. 실제 형식 변환은 별도 Convert 메뉴가 담당한다.
(ARCHITECTURE.md 참고)

---

## 19~21. 용량 표시

Storage 정보를 별도의 큰 Panel로 배치하지 않는다. 평상시 Header에 compact하게 표시하고,
Plan이 있으면 `Actual → Plan` 형태로 보여준다.

```
INT 31.2 → 27.5 GB
EXT 421.4 → 434.6 GB
```

Capacity는 실제 물리 저장 위치별로 계산한다. Plan 사용량이 Capacity를 초과하면 즉시
오류 상태로 표시한다(`OVER CAPACITY +23.5 GB`).

System별 용량은 항상 표시하지 않는다. 왼쪽 System 우클릭 → **Health**에서 Games /
ROM Size / Media Size / Missing ROM / Missing Media / Orphan Media / Storage / Actual /
Plan / Available을 보여준다.

---

## 22. ES-DE Custom XML

Internal/External 구조에 따른 XML 생성은 일반 Storage 기능으로 만들지 않는다. ES-DE
Frontend Adapter의 기능으로 취급하며, Header Expansion의 `[ES-DE XML]`로 실행한다.
다른 Frontend가 유사 기능을 요구하면 해당 Adapter가 담당한다.

---

## 23~24. Gamelist

Collection의 중심 UI는 Gamelist다. 기존 프로젝트의 구조와 UI를 최대한 유지하고, 이번
설계 변경 때문에 데이터 표현 방식을 불필요하게 단순화하지 않는다.

기본 구성: Selection / Title / System / Status / Description.

게임별 Size나 Storage Location은 기본 컬럼으로 표시하지 않는다. Storage Location은 왼쪽
Navigation의 System 그룹으로 표현된다.

Status는 Plan 상태를 매우 작게 표시한다.

| 기호 | 의미 | 색 |
|---|---|---|
| `+` | 추가 | Blue |
| `-` | 삭제 | Red |
| `△` | 변경 또는 충돌 | Yellow |

정상 항목은 강조하지 않는다. **게임 제목이나 Description 전체를 색칠하지 않는다.**

---

## 25~33. Plan

Plan은 단순한 "복사 예정 목록"이 아니라 Collection에 적용될 전체 변경 집합이다:
Add / Delete / Move / Copy / Import / Export / Convert / Storage Location Change /
Metadata Change / Media Change.

**Auto Plan** 토글(`[✓] Auto`)을 제공한다. 켜져 있으면 Copy/Paste, Drag & Drop, Delete,
Import, Export, Convert가 가능한 경우 자동으로 Plan에 들어가고 실제 파일 작업을 즉시
실행하지 않는다.

- Copy/Paste: Collection A에서 Ctrl+C → Collection B에서 Ctrl+V → Plan. Gamelist에 Blue `+`.
- Drag & Drop: Internal의 PS2를 External로 Drag → `EXTERNAL / PS2 [+]`. 파일은 그대로.
- Delete: Plan으로 들어가고 Red `-` 표시. Plan 용량도 즉시 재계산.

UI에서는 Actual과 Plan을 항상 구분한다. Plan이 없으면 Actual만 표시할 수 있다.

Plan 확정 시 처리 순서:

```
Plan → Validation → Capacity Check → Conflict Check → Source Check → Target Check
     → Actual File Operation
```

확정 버튼을 누르기 전까지 실제 파일은 변경하지 않는다.

Auto Plan을 끄려고 하면 경고한다("이후 Copy/Move/Delete 등이 실제 파일에 즉시 적용될 수
있습니다"). OFF 상태에서 실제 삭제/복사를 실행할 때는 별도 확인 대화상자를 표시한다.

Plan 생성 이후에도 파일 시스템은 외부에서 바뀔 수 있으므로 Apply 직전에 Source Exists /
Target Exists / File Size / File Modification Time / Capacity / Conflict를 다시 검증한다.
상태가 다르면 알리고 중지하거나 재계산한다.

---

## 34~36. Metadata / Media / ROM UI

기존 프로젝트의 Metadata UI를 그대로 유지한다. 새로운 Property Grid 형태로 단순화하지
않는다. 필드 구성·순서·Description의 세로 배치·관련 객체·편집 방식·UI 컴포넌트를 유지하며,
특히 **Description은 충분한 세로 공간을 가진 편집 영역**으로 유지한다.

Metadata 필드는 기본적으로 즉시 편집 가능한 상태를 유지한다. 별도의 복잡한 Edit Dialog를
거치지 않는다. 단 **UI Editable과 File System Write는 분리**한다.

오른쪽 Detail 영역에는 기존의 `[Metadata] [Media] [ROM]` 탭 구조를 유지한다. 기존 Media
객체와 유형(Cover, Marquee, Miximage, 3D Box, Backcover, Fanart, Screenshot, Titlescreen,
Video, Wheel …)을 제거하거나 단순화하지 않는다.

---

## 37~44. Archive

Archive는 MasterDB의 대체 개념이 **아니다**. Metadata 및 Game/ROM Identity의 저장소이며
**실제 Media 파일 저장소가 아니다**. 여러 Collection에서 수집한 정보를 보관하고 출처를
기록한다.

```
Archive Record
├─ Game ID
├─ ROM Identity
├─ Source Collection ID   ← 이름이 아니라 안정적인 ID
├─ Metadata
├─ Revision
└─ Updated At
```

Revision은 무한히 증가하지 않게 한다. 기본적으로 `Collection × ROM`별 최신 상태를
유지하고, **내용이 변경된 경우에만** 새 Revision을 만든다(Content Hash 또는 동등한 Diff
판단). History Retention 정책(None / Latest 1 / Latest 5 / 30 Days / Unlimited)을 지원할
수 있도록 설계하며 기본은 제한된 History를 권장한다.

**Archive에서 수정한 데이터는 자동으로 Collection에 반영하지 않는다.** 반영하려면 명시적
Copy/Paste 또는 Import를 수행한다. 이 시점에서 Plan이 활성화되어 있으면 미리 계산할 수 있다.

Collection → Archive로 보낼 때 Source Collection ID를 기록한다. 동일 데이터가 이미 있으면
중복 저장하지 않고 내용이 바뀐 경우에만 새 Revision을 만든다.

Archive도 별도의 복잡한 UI로 만들지 않는다. 일반 Collection과 마찬가지로 Gamelist를
출력하고, 게임 선택 시 기존 Metadata/Media/ROM Detail UI를 사용한다.

Archive에서 게임을 선택하면 그 데이터의 Source Collection들을 확인하고 각 Source의
Metadata를 비교할 수 있어야 한다.

---

## 45~49. Matching

Import / Archive / Collection 간 데이터 연결에는 Match Engine을 쓴다. 우선순위:

1. Exact ROM Identity
2. Strong filename / normalized title
3. Strong metadata match
4. Heuristic match
5. No match

**Game Identity와 ROM Identity를 분리한다.** 동일 Game이 여러 ROM(Japan/USA/Korea)을 가질
수 있으므로 하나의 ID로 취급하지 않는다.

Exact ROM Identity가 확인되면 자동 매칭한다(Hash, Size, System, Disc information,
Filename, ROM identity metadata 등 활용). **단순 Filename만으로 Exact Match를 확정해서는
안 된다.**

휴리스틱 조건만 만족하는 후보는 **자동 반영하지 않는다.** Gamelist에 작은 Match 버튼을
표시하고(예: `Final Fantasy X   [3]`), 누르면 후보 목록을 보여준다.

```
Possible Matches
Source: Final Fantasy X
Candidates
○ Final Fantasy X (Japan)   94%
○ Final Fantasy X (USA)     91%
○ Final Fantasy X (Korea)   87%
[Cancel] [Apply Match]
```

사용자가 직접 선택해야 한다. 점수는 추천 순서와 참고 정보로만 쓰고 자동 Merge하지 않는다.

---

## 50~51. Frontend-specific Data 보존 / Round-trip

Frontend 간 변환에서 정보 손실을 방지한다.

```
Game
├─ Identity
├─ Metadata
├─ ROM
├─ Media
└─ FrontendData { ES-DE, Pegasus, LaunchBox, … }
```

Frontend가 지원하지 않는 필드를 발견했다고 조용히 삭제해서는 안 된다.

`ES-DE → Common → Pegasus → Common → ES-DE` 왕복에서 원래 존재했던 정보를 가능한 한
보존해야 한다. Target Frontend가 표현할 수 없는 정보도 내부 모델 또는 Frontend-specific
data를 통해 보존해야 한다.

---

## 52~53. Import / Export / Convert

| 기능 | 의미 |
|---|---|
| Import | 외부 Source의 정보를 현재 Collection에 합친다 (Source → Match → Target Collection) |
| Export | 현재 Collection을 특정 Target 환경에 출력한다 |
| Convert | 현재 Collection의 Frontend 표현을 다른 Frontend 표현으로 변환한다. 원본 Collection을 기본적으로 보존한다 |

Plan은 별도의 독립 작업 종류라기보다 **작업 실행 방식**이다. Plan OFF면 실제 실행, Plan ON이면
예상 결과만 생성한다. Import/Export/Convert/Delete/Drag/Copy·Paste 모두에 적용된다.

---

## 54~59. Compare

Compare는 반드시 유지한다. 별도의 완전히 다른 화면이 아니라 **기존 Gamelist의 Compare
Mode**로 구현한다.

상단 Collection Tab 우클릭 → **Compare**로 기준을 지정하고, 다른 Collection Tab 우클릭 →
**Compare with Master**를 선택한다.

```
COMPARE   Master ↔ Android ES-DE
[All] [Same] [Only A] [Only B] [Conflict] [Media]
```

상태 체계는 동일하게 재사용한다: Same / Only A / Only B / Conflict, 기호는 `+`(Blue),
`-`(Red), `△`(Yellow).

Compare 상태에서 게임을 선택하면 오른쪽 Detail에서 두 Collection의 정보를 비교할 수 있어야
한다. 기존 Metadata/Media/ROM UI를 버리지 않는다. 차이가 있는 값은 비교 상태를 명확히
표현한다.

Compare Mode에는 명확한 종료 기능(`[Exit Compare]`)을 제공한다.

---

## 60~66. Cache

Collection을 매번 Full Scan하지 않는다. Directory Scan 결과를 Cache로 저장한다.

```
db/
├─ archive.db
├─ collections.db
└─ cache/<collection-id>.db
```

실제 ROM/Media 파일을 Cache DB에 복제하지 않는다. 파일 시스템 상태를 빠르게 재구성하기
위한 정보만 보관한다.

```
Filesystem → Scanner → Cache → Collection Model → UI
```

**Cache가 Collection 자체를 대체해서는 안 된다. 실제 파일 시스템이 Source of Physical
Truth다.**

처음 열 때는 `Directory → Full Scan → Cache 생성 → 표시`, 다시 열 때는
`Load Cache → UI 즉시 표시 → Incremental Validation Scan → Changed Files Update`가 기본
동작이다.

최소한 Path / Size / Modified Time을 저장해 변경 여부를 판단하고, 변경된 파일만 다시
처리한다.

외부(탐색기 등)에서 변경될 수 있으므로 가능하면 File System Watcher를 쓰고, Watcher가
모든 변경을 보장하지 못하는 환경에 대비해 Collection 재활성화 또는 주기적 Validation Scan을
사용할 수 있다.

Cache가 손상되거나 버전이 맞지 않으면 Full Scan으로 복구할 수 있어야 한다.

---

## 67~71. FileOperationEngine

실제 파일 작업은 기존 FileOperationEngine 추상화 계층을 유지한다. UI 및 Business Logic은
실제 파일 작업 구현을 직접 호출하지 않는다.

```
UI → Plan / Operation Engine → FileOperationEngine → Native Worker / Fallback → Filesystem
```

담당 작업: mkdir, copy, delete, rename, move 및 필요한 파일 시스템 작업.

Plan을 Apply하면 Plan/Capacity/Conflict Validation 후 실제 작업을 수행한다. 실패 항목이
있으면 전체 결과를 사용자에게 표시한다.

**Export / Convert가 기존 Media를 자동 삭제하지 않는다.** 기존 Media는 보존하고, 불필요한
Media 제거는 별도 Cleanup 기능(Orphan / Unused / Duplicate / Invalid Media)으로 처리하며
Cleanup도 가능하면 Plan을 거친다.

Copy(원본 유지)와 Move(원본 제거)를 명확히 구분한다. Export에서 원본 Collection을 기본적으로
삭제하지 않는다.

---

## 72~78. UI 전체 구성

```
+------------------------------------------------------------------------+
| Application Header                                                     |
+------------------------------------------------------------------------+
| Collection Tabs                                                        |
+----------------+------------------------------------------+------------+
|                | Collection Header                        |            |
| Navigation     | Gamelist                                 | Detail     |
| Systems        |                                          | Metadata   |
|                |                                          | Media      |
|                |                                          | ROM        |
+----------------+------------------------------------------+------------+
| Status / Plan / Storage / Actions                                      |
+------------------------------------------------------------------------+
```

하단에는 별도의 대형 Storage Panel을 만들지 않는다.

```
Selected 3 | +12.4 GB | -3.2 GB | Actual 452.6 GB | Plan 461.8 GB
                                  [Import] [Export] [Convert] [Apply]
```

정보는 세 단계로 분리한다: Collection 정보(Header) / System 정보(우클릭 Health) /
Game 정보(오른쪽 Detail).

Context Menu:
- Collection Tab: Open, Rename, Compare, Close
- System: Open, Health, Change Storage, Add External Storage, Rename
- External Storage: Rename, Settings, Remove, Health
- Game: Open, Copy, Delete, Compare, Match, Plan

---

## 79. 데이터 모델 기본 구조

```
Collection { id, name, frontend, target, os, architecture, root_path, systems[] }
System     { id, name, storage_location, root_path, games[] }
Game       { id, identity, metadata, media[], roms[], frontend_data{} }
ROM        { id, identity, path, size, hash, disc_info, metadata }
ArchiveRecord { game_id, rom_id, source_collection_id, metadata, revision, content_hash }
Plan       { source, target, entries[], status }
PlanEntry  { operation, source, target, game_id, rom_id, storage_change,
             estimated_size, status }
Cache      { collection_id, root_path, scan_version, last_scan, filesystem_entries[] }
```

---

## 80~84. Collection과 Physical File

Logical Collection Membership과 Physical File Location을 분리한다. 하나의 ROM이 여러
Collection에서 참조될 수 있으므로 Collection membership을 물리적 파일의 소유권과 동일하게
취급하지 않는다.

동일 Media가 여러 Collection에서 참조될 때 중복 물리 용량을 이중 계산하지 않는다. Logical
Collection Size와 Physical Storage Usage를 구분한다.

```
Plan Usage = Actual Usage + Added Bytes - Deleted Bytes
           + Moved Bytes between physical locations
           + Newly required Media - Removed Media
```

동일 물리 파일의 단순 참조 변경은 실제 물리 용량을 증가시키지 않는다.

Internal → External 이동은 `Internal Actual - X`, `External Actual + X`로 계산하며 Plan
상태에서는 실제 파일을 아직 옮기지 않는다.

Frontend Conversion도 Plan 상태에서는 Target Collection/Metadata/Media/Paths만 계산하고
실제 파일을 만들지 않는다.

---

## 85~87. Error Handling과 UX 원칙

모호한 상황에서 자동으로 결정하지 않는다: Metadata Conflict, Heuristic Match, Insufficient
Capacity, Missing Source, Duplicate Target, Unsupported Frontend Field 등은 사용자에게 명확히
표시한다.

| 상황 | 처리 |
|---|---|
| High Confidence | 자동 처리 |
| Low Confidence | 사용자 확인 |
| Destructive Operation | Plan 또는 확인 |
| Conflict | 사용자 선택 |

휴리스틱 매칭은 자동 처리하지 않는다.

RetroMeta Studio는 "파일을 직접 조작하는 관리자"보다 **"현재 Collection의 상태를 안전하게
구성하고, 변경 결과를 미리 확인한 뒤 적용하는 관리 도구"**로 설계한다. 사용자가 항상
`현재 상태 → 예상 상태 → 확정` 흐름을 이해할 수 있어야 한다.

---

## 88. 핵심 사용자 시나리오

1. **Collection 열기** — Open → Load Cache → Display UI → Background Scan → Update changed items
2. **System 선택** — Click PS2 → Gamelist = PS2 only
3. **전체 보기** — Click ALL → Gamelist = All Systems
4. **Internal → External** — Drag PS2 → External → Auto Plan → Blue `[+]` → Actual/Plan 재계산 → Apply → 실제 이동
5. **게임 삭제** — Delete → Auto Plan → Red `[-]` → Plan Usage 감소 → Apply → 실제 삭제
6. **Master → Android Collection** — Select Games → Ctrl+C → Android Collection → Ctrl+V → Auto Plan → Blue `[+]` → Capacity Check → Apply
7. **Archive 수정** — Archive → Select Game → Edit Metadata → Save Archive (기존 Collection은 변경되지 않음)
8. **Archive → Collection** — Archive → Copy → Collection → Paste → Plan → Apply
9. **Heuristic Match** — Exact Match 실패 → 후보 발견 → Gamelist에 Match 버튼 → 사용자 클릭 → 후보 목록 → 선택 → Apply Match
10. **Compare** — Master Tab 우클릭 Compare → Android Tab 우클릭 Compare with Master → Compare Gamelist → Same/Only A/Only B/Conflict → 게임 선택 → Detail 비교

---

## 89. 구현 우선순위

| Phase | 범위 |
|---|---|
| 1 | Core Model — Collection, System, Game, ROM, Frontend, Target, Storage Location |
| 2 | Collection UI — Tabs, Header, System Navigation, ALL/Internal/External, Gamelist, 기존 Detail |
| 3 | Cache — Collection Cache, Load Cache, Incremental Scan, Filesystem Validation |
| 4 | Plan — Model, Auto Plan, Add/Delete/Move/Copy·Paste/Drag&Drop, Actual·Plan 계산, Apply |
| 5 | Archive — Source Tracking, Revision, Archive Gamelist, Archive Edit, Collection Import |
| 6 | Match — Exact, Normalized, Heuristic Candidate, User Selection |
| 7 | Compare — Compare Selection, Compare Gamelist, Metadata/Media Compare |
| 8 | Frontend Adapters — ES-DE, Pegasus, LaunchBox, EmulationStation; Frontend-specific data 보존과 Round-trip 검증 |

> 실제 구현 순서는 `ARCHITECTURE.md` §7의 Phase 0~8을 따른다(위험도 높은 항목을 앞으로 당김).

---

## 90. 필수 테스트 시나리오

구현 완료 전에 반드시 통과해야 한다.

**Collection**
- ES-DE Collection 열기 / 닫기 / Cache로 재오픈
- 10개 동시 Open / 11번째 Open 처리
- Collection Rename

**Storage**
- Internal 생성 / External 생성
- System Internal → External / External → Internal
- Storage Capacity 계산 / Plan Capacity 초과 / System Health

**Plan**
- Game Copy / Paste / Delete / Drag, System Drag
- Add / Delete / Move
- Actual·Plan 계산 / Apply / Apply 직전 파일 변경 / Apply 실패

**Archive**
- Collection → Archive / Archive Edit / Archive → Collection
- Archive Revision / Source Tracking

**Matching**
- Exact ROM Match / Filename Match / Region 차이 / Localization 차이
- Heuristic Candidate / User Candidate Selection

**Compare**
- Collection A vs B / Same / Only A / Only B
- Metadata Conflict / Media Conflict / Compare 종료

**Frontend**
- ES-DE → Pegasus / Pegasus → ES-DE
- Frontend-specific data 보존 / Unsupported field 보존 / Round-trip

**ES-DE Android**
- Internal / External System 구성 / External path 설정
- custom_settings XML 생성 / XML 재생성 / ROM과 Media 경로 검증

---

## 91. 기존 코드에 대한 기본 원칙

검증된 기존 동작을 무조건 새 구조에 맞춰 재작성하지 않는다. 다음은 재사용을 우선한다.

Metadata UI, Media UI, ROM UI, Gamelist UI, FileOperationEngine, Native MediaCopyWorker,
기존 Frontend Adapter, 기존 Media Model, 기존 scraper infrastructure.

새 아키텍처는 기존 기능을 대체하기 위한 것이 아니라 상위의 Collection / Archive / Plan
구조를 재정의하기 위한 것이다.

---

## 92. 명시적으로 금지하는 설계

- MasterDB를 다시 Canonical Source로 만드는 것 / Archive를 새 MasterDB로 취급하는 것
- Collection을 Storage별로 분리(Android Internal Collection, Android External Collection 등)
- System을 Internal/External 양쪽에 동시에 저장
- Heuristic 자동 Merge
- Export 시 기존 Media 자동 삭제 (Cleanup과 Export를 분리)
- Frontend-specific Data 삭제
- Collection 재오픈 시 항상 Full Scan
- Plan을 단순 Copy Queue로 구현

---

## 93. 최종 UX 개념

```
                    COLLECTION TABS
        [Master] [Android ES-DE] [Windows ES-DE]

┌──────────────┬─────────────────────────────────────┬───────────────┐
│ SYSTEMS      │ COLLECTION HEADER                   │               │
│ ALL          │ [ES-DE] Android ES-DE    [Android]  │               │
│              │ 1,284 Games INT 31.2→27.5G          │               │
│ INTERNAL     │ EXT 421.4→434.6G             [⌄]    │ METADATA      │
│ ├ PS1        ├─────────────────────────────────────┤               │
│ ├ NDS        │ Search                              │ MEDIA         │
│ └ GBA        ├─────────────────────────────────────┤               │
│              │ GAMELIST                            │ ROM           │
│ EXTERNAL     │ Game A                         [+]  │               │
│ ├ PS2        │ Game B                         [-]  │               │
│ ├ PSP        │ Game C                         [△]  │               │
│ └ GC         │                                     │               │
├──────────────┴─────────────────────────────────────┴───────────────┤
│ Selected 3 │ Actual 452.6G │ Plan 461.8G │ [Import][Export][Apply] │
└────────────────────────────────────────────────────────────────────┘
```

역할 분리: LEFT=System 탐색, CENTER=Game List/Compare, RIGHT=기존 Metadata/Media/ROM,
HEADER=Collection/Frontend/Target/Capacity, BOTTOM=Actual/Plan/Operations, TAB=여러
Collection 동시 작업.

---

## 94. 최종 정의

| 용어 | 정의 |
|---|---|
| Collection | 논리적인 게임 라이브러리 |
| System | Collection 내부의 게임 플랫폼 단위 |
| Storage Location | System이 사용하는 물리적 저장 위치(Internal / External 등) |
| Game | 게임의 논리적 Identity |
| ROM | 실제 ROM Identity 및 파일 |
| Archive | Metadata / Identity의 보관 및 Source History |
| Cache | Filesystem Scan 결과의 빠른 재사용 |
| Plan | 실제 변경 전의 가상 변경 집합 |
| FileOperationEngine | 실제 파일 시스템 변경의 최종 실행 계층 |

전체 사용자 흐름:

```
Open Collection → Load Cache → Browse / Edit
  → Compare / Import / Export / Convert → Auto Plan
  → Actual ↔ Plan 확인 → User Confirmation → Apply
  → FileOperationEngine → Filesystem → Cache Update
```

이 설계에서 가장 중요한 원칙은 **"Collection을 작업의 중심에 두되, Archive를 Canonical
DB로 만들지 않고, Plan을 통해 실제 파일 변경과 사용자 의도를 분리하는 것"**이다.
