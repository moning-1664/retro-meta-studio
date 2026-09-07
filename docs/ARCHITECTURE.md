# RetroMeta Studio — Feasibility 검토 및 아키텍처 설계

- 대상 스펙: Product & Architecture Design Specification v0.1
- 이 문서의 상태: 설계 baseline 제안 (구현 착수 전 합의용)
- 기준 코드: RetroGameManager `fix/ahnlab-mass-file-access` 스냅샷

---

## 0. 결론 요약

스펙 전체는 **구현 가능**하다. 기술적으로 불가능한 항목은 없고, 조건부/후순위로 미뤄야 하는
항목이 하나(MTP 접근) 있다.

| 구분 | 항목 |
|---|---|
| 그대로 재사용 | FileOperationEngine, Native Worker, Job Queue, Gamelist/Detail UI, Compare 로직, 유사 ROM 스코어링 |
| 개조 후 재사용 | Scanner(→영속 Cache), Importer/Exporter(→Frontend Adapter), SQLite 저장소 패턴 |
| 신규 구현 | Collection/Storage 모델, Plan 엔진, Archive, Match 티어, ES-DE custom XML, 가상 스크롤 |
| 폐기 | `db.py`(MasterDB), `gui/`(tkinter 레거시 2,900줄), `import_engine.py`/`export_engine.py`의 오케스트레이션 |

가장 주의할 점 세 가지:

1. **Round-trip 보존(스펙 §50–51)은 현재 코드가 구조적으로 못 한다.** 지금 importer는
   알려진 태그만 뽑아 dict로 만들고 나머지는 버린다. 어댑터 계층을 새로 만들 때 원본
   보존을 인터페이스에 못 박아야 하며, 나중에 얹을 수 없는 종류의 요구사항이다.
2. **MTP는 경로 기반 파일 접근이 불가능하다.** 드라이브 문자와 UNC(SMB)는 기존 Native
   Worker가 그대로 동작하지만, MTP는 Windows Shell API를 쓰는 별도 백엔드가 필요하고
   File Watcher와 여유 용량 조회가 원천적으로 안 된다. 그래서 `StorageProvider` 추상화를
   **처음부터** 넣어두고 구현은 Phase 후반으로 미룬다.
3. **`api.py` 3,400줄 모놀리스를 그대로 승계하면 안 된다.** 브릿지는 얇게 두고 로직은
   `app/`으로 내린다. 단, 그 안의 Job Queue(약 350줄)는 실제 크래시를 겪으며 다듬어진
   코드라 통째로 살린다.

---

## 1. 재사용 자산 맵 (파일 단위)

### 1.1 그대로 가져가는 것

| 파일 | 근거 |
|---|---|
| `engines/base.py`, `engines/native_worker_engine.py` | 스펙 §67이 명시적으로 유지를 요구. 계약(원자성/실패격리)이 문서화되어 있음 |
| `media_copy_worker.py`, `native/media_copy_worker.c` | AhnLab M1875 회피가 실측 검증된 자산(`GOLDEN_VALIDATION.md`) |
| `file_ops.py` + `MediaCopyBatch` | 배치 flush로 워커 spawn 비용을 억제하는 구조 |
| `api.py`의 Job Queue (`_run_heavy_job`, `_start_phased_media_job`, 취소/직렬화) | Scan 중 크래시 대응으로 만들어진 부분. 재작성하면 같은 버그를 다시 겪는다 |
| `gui_web/` 전체 (app.js 4,011줄 + style.css 974줄) | 스펙 §34/§36/§75가 유지를 요구. Detail 패널·모달·토스트·드래그선택·시스템 아이콘 모두 재사용 |
| `similar_rom.py` | Match 엔진의 휴리스틱 스코어링 + SHA256 |
| `compare_engine.py` | Compare 매칭 인덱스 로직 |
| `disk_utils.py`, `utils.py`, `scraper/`, `csv_engine.py`, `backup_engine.py` | 부가 기능, 손댈 이유 없음 |

### 1.2 개조해서 재사용

| 파일 | 개조 내용 |
|---|---|
| `importers/scan.py` | 증분 판정 로직(디렉터리 mtime 3종 시그니처)은 그대로. 결과를 **런타임 dict가 아니라 Cache DB에 영속화**. ES-DE 경로 하드코딩(`gamelists/`, `downloaded_media/`)을 어댑터로 이동 |
| `importers/*`, `exporters/*` | 하나의 `FrontendAdapter`로 통합. bulk read/write만 노출. 미지원 필드 원본 보존 추가 |
| `database/sqlite_db.py` | 커넥션/배치/트랜잭션 패턴은 재사용, **스키마는 전면 교체** |
| `cleanup_engine.py` | Plan을 경유하도록 변경(스펙 §70) |
| `export_engine.py` / `import_engine.py` | 오케스트레이션은 폐기. 내부의 충돌 처리·미디어 배칭·매칭 루프는 Plan Applier로 이식 |

### 1.3 폐기

- `db.py` — MasterDB 스키마. 스펙 §92가 부활을 금지.
- `gui/` 전체 (tkinter) — 유지비만 발생. **삭제 권장.**
- `main_gui.py`, `headless_export*.py` — MasterDB 전제 진입점.

---

## 2. 계층 구조

```
gui_web/  (UI)
    │  pywebview bridge (얇게)
bridge/   api.py — 입출력 변환 + jobs.py(기존 Job Queue)
    │
app/      Collection · Plan · Archive · Match · Compare · Scan  ← 모든 비즈니스 로직
    │
adapters/ FrontendAdapter (ES-DE / Pegasus / LaunchBox / EmulationStation)
    │
storage/  StorageProvider (Local / UNC / [MTP])   ← 물리 접근 추상화
    │
engines/  CopyEngine (NativeWorker / [MTP Shell] / [Robocopy])
    │
          File System
```

핵심 규칙: **UI와 app/은 경로를 직접 열지 않는다.** 읽기는 `StorageProvider`, 쓰기는
`FileOperationEngine`만 통과한다. 이 규칙 하나가 MTP·adb 백엔드를 나중에 끼워 넣을 수
있게 만드는 유일한 장치다.

### 2.1 디렉터리 구조 제안

```
app/
├── model/          collection.py  game.py  plan.py  identity.py     (dataclass, 순수)
├── store/          registry.py  cache.py  archive.py  migrations.py (SQLite)
├── scan/           scanner.py  watcher.py
├── plan/           builder.py  capacity.py  validator.py  applier.py
├── match/          engine.py
├── compare/        engine.py
└── ops/            import_op.py  export_op.py  convert_op.py  cleanup_op.py
adapters/           base.py  es_de.py  pegasus.py  launchbox.py  emulationstation.py
storage/            provider.py  local.py  (mtp.py)
bridge/             api.py  jobs.py
engines/  file_ops.py  media_copy_worker.py  native/   ← 기존 유지
gui_web/                                               ← 기존 유지 + 확장
```

---

## 3. 데이터 저장 설계

DB를 셋으로 나눈다. 스펙 §61의 배치를 따르되 역할 경계를 강제한다.

```
db/
├── registry.db            Collection 등록 · Storage · System 배치 · Plan
├── archive.db             Metadata / Identity / Revision
└── cache/<collection-id>.db   Scan 결과 (언제든 버리고 재생성 가능)
```

**Cache는 언제나 파기 가능해야 한다.** 손상/버전 불일치 시 Full Scan으로 복구(§66).
반대로 registry/archive는 사용자 자산이므로 마이그레이션 대상이다. 기존 프로젝트는
스키마 마이그레이션 프레임워크가 없어서 "기존 DB를 고치려면 새로 만들어야 한다"는
주석이 코드에 남아 있다(`database/sqlite_db.py`). 이번에는 `PRAGMA user_version`
기반 마이그레이션을 **1일차부터** 넣는다.

### 3.1 registry.db

```sql
collections(
  id TEXT PRIMARY KEY,          -- UUID. 이름 변경과 무관 (§4.1, §38)
  name TEXT NOT NULL,
  frontend TEXT NOT NULL,
  target TEXT, os TEXT, arch TEXT,   -- NULL = Unknown (§5). 추측하지 않는다
  root_path TEXT,
  ui_state_json TEXT,           -- 탭 순서, 마지막 선택 system
  created_at TEXT, updated_at TEXT
);

collection_storages(
  collection_id TEXT, storage_id TEXT,        -- 'internal' | 'ext-1' ...
  kind TEXT, label TEXT, root_path TEXT,
  volume_key TEXT,              -- 물리 볼륨 식별자 (용량 중복계산 방지 §81)
  capacity_bytes INTEGER,       -- 마지막 관측치. NULL = Unknown
  PRIMARY KEY(collection_id, storage_id)
);

collection_systems(
  collection_id TEXT, system TEXT,
  storage_id TEXT NOT NULL,     -- ★ 여기 한 컬럼이 스펙 §8을 구조적으로 강제한다
  rom_path TEXT, media_path TEXT, metadata_path TEXT,
  PRIMARY KEY(collection_id, system)
);
```

`storage_id`를 System 행에 **단일 컬럼**으로 두면 "하나의 System은 하나의 Storage"(§8)가
검증 로직 없이 스키마로 보장된다. 스펙 §92의 금지 사항(System을 양쪽에 동시 저장)도
표현 자체가 불가능해진다.

### 3.2 cache/&lt;collection-id&gt;.db

```sql
scan_meta(key, value);           -- scan_version, adapter_version, last_scan
dir_sig(path PRIMARY KEY, mtime_ns, ctime_ns, kind);   -- 증분 판정 (기존 scan.py 방식)

roms(
  rom_uid INTEGER PRIMARY KEY,
  system, filename, rel_path, storage_id,
  size INTEGER, mtime_ns INTEGER,
  sha256 TEXT,                   -- lazy. NULL 허용
  volume_file_id TEXT,           -- 물리 동일성 판정 (§80–81)
  UNIQUE(system, filename)
);
metadata(rom_uid PRIMARY KEY, fields_json, frontend_raw_json, content_hash);
media(rom_uid, media_type, rel_path, size, mtime_ns, PRIMARY KEY(rom_uid, media_type));

-- 리스트 전용 비정규화 테이블: 정렬/필터/페이지를 전부 SQL로 처리
list_rows(rom_uid PRIMARY KEY, system, title, title_norm,
          has_metadata INT, has_media INT, size INT, favorite INT);
CREATE INDEX ix_rows_sort ON list_rows(system, title_norm);
```

`frontend_raw_json`이 스펙 §50–51(Round-trip 손실 방지)의 저장소다. 어댑터가 공통 모델로
변환하면서 **버리게 되는 원본 필드를 여기에 통째로 남긴다.**

`list_rows`가 성능 설계의 핵심이다. 게임 목록을 JS 메모리에 전부 올리지 않고 SQL
`ORDER BY / LIMIT`으로 화면에 보이는 만큼만 가져온다. 지금 규모(5,000~10,000)에서도
이득이고, 나중에 규모가 커져도 UI를 다시 쓸 필요가 없다.

### 3.3 archive.db

```sql
games(game_id TEXT PRIMARY KEY, title_norm TEXT);          -- 논리 Game (§46)
rom_identities(
  rom_identity_id TEXT PRIMARY KEY, game_id TEXT,
  system, filename_norm, size INTEGER, sha256 TEXT, region TEXT, disc_info TEXT
);
archive_records(
  record_id INTEGER PRIMARY KEY,
  rom_identity_id TEXT, source_collection_id TEXT,          -- ID로 추적 (§38)
  revision INTEGER, content_hash TEXT,
  fields_json TEXT, frontend_raw_json TEXT, updated_at TEXT,
  UNIQUE(rom_identity_id, source_collection_id, revision)
);
archive_media(rom_identity_id, media_type, source_collection_id, rel_path);  -- 참조만 (§37)
```

Revision 증가 조건은 `content_hash` 변경 시에만(§39). 같은 내용 재Import는 행을 만들지
않는다. Retention 정책(None / Latest 1 / Latest 5 / 30 Days / Unlimited)은 `archive_records`에
대한 정리 쿼리로 구현하며 기본값은 **Latest 5**를 권장한다.

---

## 4. 핵심 인터페이스

### 4.1 StorageProvider — MTP 확장 지점

```python
class StorageProvider:
    def stat(self, path) -> Stat | None: ...
    def scandir(self, path) -> Iterable[Entry]: ...
    def volume_info(self, path) -> VolumeInfo: ...   # capacity/free/volume_key, Unknown 허용
    def supports_watch(self) -> bool: ...
    def copy_engine(self) -> CopyEngine: ...
```

| Provider | 대상 | 용량 조회 | Watcher | 복사 |
|---|---|---|---|---|
| `LocalProvider` | 드라이브 문자, SD/USB | O | O | Native Worker |
| `UncProvider` | `\\device\share` (SMB) | 대체로 O, 실패 시 Unknown | X → 주기적 Validation Scan | Native Worker |
| `MtpProvider` (후순위) | 폰 USB 직결 | Shell API로 제한적 | X | Shell 복사, 느림 |

스펙 §5가 Unknown 상태를 허용하므로, 용량을 못 읽는 저장소는 "Unknown"으로 표시하고
Capacity Check(§20)를 건너뛰면 된다 — 이 설계 덕분에 SMB/MTP가 예외 처리 없이 흡수된다.

### 4.2 FrontendAdapter

```python
class FrontendAdapter:
    id: str; display_name: str
    def detect(self, root) -> Detection            # 신뢰도 + 감지된 systems/paths
    def layout(self, collection, system) -> Layout # rom/media/metadata 경로 규칙
    def read_index(self, layout) -> dict[str, RawEntry]        # bulk only
    def read_media_index(self, layout, types) -> dict[str, list]
    def to_common(self, raw) -> tuple[Fields, FrontendRaw]     # 미지원 필드 보존
    def from_common(self, fields, frontend_raw) -> RawEntry
    def write_index(self, layout, entries) -> None             # bulk only
    def extras(self) -> list[AdapterAction]        # 예: ES-DE custom systems XML
```

**bulk만 노출하는 것이 의도적인 제약이다.** 기존 코드는 ROM 하나마다 gamelist.xml을
다시 열어 파싱하다가 1,000 ROM에서 최대 2,000회 재파싱하는 O(n²)를 겪었고, 캐시+flush로
고쳤다. 그 교훈을 인터페이스에 못 박아서 같은 실수를 구조적으로 막는다.

### 4.3 Plan

```python
@dataclass
class PlanEntry:
    op: Literal["add","delete","move","copy","convert","metadata","media","storage_change"]
    source: Ref | None; target: Ref | None
    rom_identity_id: str | None
    storage_from: str | None; storage_to: str | None
    estimated_bytes: int          # 논리 크기
    physical_delta: dict[str,int] # {storage_id: ±bytes} — 이미 존재하는 물리 파일은 0
    status: Literal["pending","invalid","applied","failed"]
```

`physical_delta`를 엔트리 생성 시점에 확정해 두면 용량 재계산이 O(1) 누적합이 된다.
Plan 항목을 추가/삭제할 때마다 Collection 전체를 다시 훑지 않는다 — 수천 개 항목을
Ctrl+V 하는 시나리오(§88 Scenario 6)에서 체감 속도를 좌우한다.

Apply 파이프라인(§31, §33):

```
Plan → Validate(소스 존재/크기/mtime 재확인) → Capacity Check → Conflict Check
     → FileOperationEngine 실행 → Cache 갱신 → 실패 항목 보고
```

Plan 생성 시점의 `(size, mtime_ns)`를 엔트리에 박아두고 Apply 직전에 대조한다. 다르면
그 항목만 `invalid`로 표시하고 사용자에게 재계산을 제안한다.

---

## 5. 성능 설계 (우선순위 1)

| 문제 | 결정 |
|---|---|
| Collection 열기 지연 | Cache DB 로드 → UI 즉시 표시 → 백그라운드 증분 검증(§63). 기존 scan.py의 3종 시그니처(ROM 디렉터리 mtime / gamelist mtime / media 폴더 mtime)를 그대로 사용해 stat 폭주를 막는다 |
| 목록 렌더링 | 가상 스크롤 + `list_rows` SQL 페이징. 정렬/필터/검색도 SQL에서 처리 |
| 썸네일 | 기존 IntersectionObserver 지연 로딩 유지 + **디스크 썸네일 캐시 추가**(현재는 매번 재인코딩). 10,000개 규모에서 체감 차이가 큼 |
| 파일 복사 | 기존 `MediaCopyBatch` 배칭 유지. Plan Apply는 배치 단위로 워커에 위임 |
| 용량 계산 | Plan 엔트리별 `physical_delta` 누적. 전체 재계산 금지 |
| 해시 | 전량 사전 해싱 금지(400GB = 수 시간). Exact Match는 `(size, 정규화 파일명)` 1차 → 충돌하거나 사용자가 요구할 때만 SHA256. 기존 백그라운드 해시 워커 재사용 |
| 10개 동시 Open | Collection당 Cache DB 커넥션 1개. 데이터는 DB에 두고 JS에는 현재 탭의 화면 분량만 유지 |
| Progress 표시 | 최근에 고친 원칙 유지 — 디스크 flush가 끝나야 100%. 표시 진행률이 실제 완료보다 앞서지 않게 한다 |

---

## 6. 위험 요소

| # | 위험 | 영향 | 완화 |
|---|---|---|---|
| R1 | **Round-trip 보존이 현재 importer 구조로는 불가** | ES-DE↔Pegasus 왕복 시 필드 유실 (§51 위반) | 어댑터 인터페이스에 `frontend_raw` 보존 강제. Phase 1에 포함(나중에 못 얹음) |
| R2 | MTP 경로 접근 불가 | Android 직결 시나리오 동작 안 함 | `StorageProvider` 추상화 선반영, 구현은 Phase 후반. 1·2(드라이브/SMB) 우선 |
| R3 | SMB에서 여유 용량·Watcher 불안정 | Capacity Check 오작동 | Unknown 상태 허용 + 주기적 Validation Scan 폴백 |
| R4 | 물리 파일 동일성 판정 | 용량 이중 계산 (§81) | NTFS `volume_file_id` 우선, 실패 시 정규화 경로 비교 |
| R5 | `api.py` 모놀리스 승계 | 새 구조가 다시 진흙탕 | 브릿지는 얇게. Job Queue만 `bridge/jobs.py`로 분리 이식 |
| R6 | 스키마 마이그레이션 부재 | 사용자 자산 유실 | `user_version` 마이그레이션을 1일차 도입. Cache는 파기·재생성으로 처리 |
| R7 | Auto Plan과 즉시 편집 UI의 충돌 | 아래 §8 참조 | 미결정 — 확인 필요 |

---

## 7. 구현 단계

스펙 §89의 Phase를 유지하되, **R1(보존)과 스키마를 앞으로 당긴다.**

| Phase | 범위 | 비고 |
|---|---|---|
| 0 | 저장소 골격: registry/cache/archive 스키마 + 마이그레이션, `StorageProvider`, `FrontendAdapter` 인터페이스, 레거시 정리(`db.py`/`gui/` 제거) | 여기서 R1·R6를 처리 |
| 1 | Core Model + ES-DE 어댑터 실동작 + Cache 스캔 | 실제 Collection 하나가 열리는 것까지 |
| 2 | Collection UI: 탭 / 헤더(compact·확장) / ALL·INTERNAL·EXTERNAL 내비 / 가상 스크롤 Gamelist / 기존 Detail 패널 연결 | gui_web 재사용 구간 |
| 3 | Plan: 모델·Auto Plan·용량 계산·Validate·Apply. Copy/Paste, Delete, Drag&Drop, System 이동 | Apply는 기존 FileOperationEngine |
| 4 | Archive: Source Tracking, Revision, Archive Gamelist, Archive→Collection | |
| 5 | Match: Exact → Normalized → Heuristic 후보 UI (자동 병합 금지 §49) | `similar_rom.py` 활용 |
| 6 | Compare Mode | `compare_engine.py` 일반화 |
| 7 | 나머지 어댑터(Pegasus/LaunchBox/ES) + Round-trip 검증 + ES-DE custom systems XML | |
| 8 | MTP Provider (선택) | 필요성 재평가 후 착수 |

Phase 2까지가 "새 구조가 실제로 굴러가는지" 판가름하는 구간이다. 여기서 기존 UI 재사용이
예상대로 되는지 먼저 확인하고 Phase 3(Plan)에 들어가는 것을 권한다.

---

## 8. 확인이 필요한 결정

1. **Metadata 편집과 Plan의 관계.** 스펙 §25는 Metadata Change를 Plan에 포함시키고,
   §35는 기존처럼 즉시 편집 가능한 UI를 요구한다. Auto Plan이 켜져 있을 때 필드를 고치면
   (a) Plan 항목으로 쌓였다가 Apply에서 파일에 반영, (b) 기존처럼 Save 시 즉시 파일 기록 —
   둘 중 무엇인가? (a)가 스펙 철학에 맞지만 편집 반응성이 떨어진다.
2. **Plan의 영속성.** 앱을 껐다 켜면 Plan이 남아 있어야 하나? (남기는 쪽을 권장 — registry.db에 저장)
3. **Archive→Collection의 Media 처리.** Archive는 Media 파일을 보관하지 않으므로(§37) 붙여넣기
   시 원본 Collection 경로에서 복사해야 한다. 원본 Collection이 닫혀 있거나 외장 디스크가
   분리된 경우의 동작은?
4. **기존 RetroGameManager 자산 이관.** 기존 MasterDB(JSON/SQLite)의 메타데이터를
   Archive로 가져오는 마이그레이션이 필요한가, 아니면 Collection을 다시 스캔해서 채우면 되나?
