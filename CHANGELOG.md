## v0.4.1.5

**시스템 사이드바/상세패널 아이콘 리워크**

- 사이드바 System 목록과 상세 패널의 시스템 아이콘을 `hashColor` 기반 단색
  사각형에서 시스템별 전용 아이콘으로 교체. 3단 우선순위 자산 체계 신설:
  `system-icons-raster.js`(전용 라이트/다크 PNG, 58개 시스템) →
  `system-icons.js`(전용 currentColor SVG) → `icons.js`(범용 카테고리 폴백).
- `systemIcon()`/`systemSquareIcon()`을 `normalizeSystemName()`과 연결하고
  `renderSystemIcon()` 하나로 lookup 로직 통합 - 별칭(SFC/PS1 등)이 전용
  아이콘을 건너뛰고 generic 폴백으로 새던 문제, 상세패널이 전용 SVG 티어를
  건너뛰던 버그를 함께 수정.
- 신규 Playwright 회귀 테스트(`tests_ui/system-icon-resolution.spec.js`) 14개 추가.

**[0.4.1.x GUI 개선 5/5 — 위험도: 높음] F2 파일명 변경**

이 버전이 0.4.1.x 시리즈에서 유일하게 **실제 파일시스템을 조작**하는 변경이다
(ROM 실물 파일 + media 폴더를 실제로 rename/move). 아래 나머지 항목(#5, #7)은
사용자 요청으로 이번 시리즈에서 제외하고 다음에 별도 진행한다.

- ArchiveDB에서 게임 하나를 선택하고 **F2**를 누르면 새 파일명을 입력하는 모달이
  뜬다. 확인하면 ROM 실물 파일과 그 게임의 media 폴더(`media/<system>/<rom_stem>/`)를
  새 이름으로 함께 이동하고, media 딕셔너리에 저장된 경로 문자열도 새 경로로 갱신한다.
  **대상 파일명이 이미 존재하면(디스크/DB 어느 쪽이든) 아무 것도 바꾸지 않고 그대로
  취소**된다 (부분 적용으로 인한 데이터 불일치를 막기 위해 rename 전에 전부 검사).
- Ctrl+C/Ctrl+V(ArchiveDB, metadata+media 복사)는 이미 이전부터 구현되어 있던 걸
  확인만 함 - 요청하신 "media + 메타데이터 복사(default 기준)"와 정확히 일치.

**⚠️ 배포 전 권장 사항**: 실제 파일을 옮기는 기능이므로, 반영 후 실사용 전에
Windows에서 MasterDB 백업을 한 번 뜨고 F2로 파일명 변경을 실제 데이터로 테스트해
보길 권장한다. 이 sandbox에서는 자동화 테스트(백엔드 유닛 테스트 + Playwright
mock 모드)로만 검증했고, 실제 pywebview/Windows 환경에서는 검증되지 않았다.

## v0.4.1.4

**[0.4.1.x GUI 개선 4/5 — 위험도: 중간] 유사롬 묶어보기 + Favorite**

- 게임 리스트 상단에 "유사롬 묶기" 토글 추가 (특정 system 선택 시에만 노출).
  켜면 유사롬 그룹의 대표 1개만 남기고 나머지는 숨기며, 대표에 `+N` 뱃지 표시.
  결과 모달에서 대표를 수동으로 바꾸면 즉시 반영.
- `start_find_similar_roms()`가 그룹을 새로 만든 직후 대표를 **자동으로** 지정하도록
  변경: favorite → default 버전 metadata 필드 채움 개수 → description 길이 → media
  총 용량 순, 전부 동률이면 romKey 사전순. 수동 지정(별표 클릭)은 그대로 언제든 덮어쓸 수 있음.
- **Favorite 필드 신규**: SQLite 스키마에 이미 예약만 되어 있던 `favorites` 테이블에
  실제 read/write 메서드 추가 (JSON DB에는 저장하지 않는 native-only 플래그 - ROM이
  실제로 삭제되지 않는 한 `rom_id`가 안정적으로 유지되므로 JSON 저장을 반복해도 사라지지
  않음). 게임 리스트/Preview에 별 아이콘(클릭 또는 Space 키로 토글), "즐겨찾기만 보기"
  필터, **Delete 삭제 시 즐겨찾기 항목은 자동으로 제외**(제외 개수를 토스트로 안내).

⚠️ **디버깅 메모(다음 세션 참고)**: 이 버전을 원래 구현 순서(6→8→9)에서 위험도 순서
(3→4→8+9→6)로 재배치하는 과정에서, unit8/9의 테스트 2개(`test_auto_pick_similar_
representative_*`)가 호출하는 `_wait_job()` 헬퍼가 원래 unit6(F2, 0.4.1.5)의 커밋에서
같이 정의됐었다는 게 뒤늦게 드러났다. 그 상태로 두면 헬퍼가 없어 테스트가 조용히
**Python 세그폴트**를 내는(백그라운드 job 스레드가 끝나기도 전에 `tearDown()`이
Api를 close하면서 발생하는 것으로 추정) 문제가 있어, `_wait_job()` 정의를 이 버전의
`tests/test_api.py`로 옮겨왔다. **커밋을 재배치/cherry-pick 할 때는 테스트 헬퍼처럼
"코드 본문 diff에는 안 보이지만 다른 커밋에 정의가 있는" 암묵적 의존성을 놓치기 쉬우니
주의할 것** - 각 버전 경계에서 반드시 전체 테스트 스위트를 돌려서 "조용한 실패"가
없는지 확인해야 한다(이번엔 `Ran 107 tests`처럼 숫자가 안 맞거나, 최악의 경우처럼
프로세스 자체가 죽는 형태로 드러났다).

## v0.4.1.3

**[0.4.1.x GUI 개선 3/5 — 위험도: 중간] Settings 체계화 + Playwright UI 테스트 도입**

- Settings를 General/GameListSet/Metadata/Media/ArchiveDB/Interface/Advanced 7개
  카테고리로 재구성. 실제로 동작하는 설정만 조작 가능하게 두고, 백엔드 로직이 없는
  항목(Scan Interval, Title Normalization, Media Naming, Cache/Debug/Performance 등)은
  "Coming soon" 비활성 표시로 명확히 구분.
- 신규로 실제 동작하는 설정: Startup Page, Confirmations(끄면 삭제 등 위험 작업이
  확인창 없이 즉시 실행됨), Logging(브릿지 호출을 콘솔에 기록), 기본 목록 보기
  (List/Preview). `config.py`의 `ui.*`에 필드 추가, `api.py`에 `save_ui_settings()` 신규.
- Export/Import 기본값 체크박스를 MetaData/Media(세부 7종)/Rom 그룹 레이아웃으로
  통일 (이후 드래그앤드롭 전송 모달에서도 같은 레이아웃을 재사용할 예정).
- **Playwright 기반 UI 회귀 테스트 도입** (`npm run test:ui`). `api-client.js`가
  pywebview 없을 때 자동 전환되는 내장 mock 모드를 이용해, 실제 pywebview/Windows
  없이도 headless Chromium으로 클릭/키보드 이벤트를 검증한다. 이 버전 시점 기준
  16개 테스트로 사이드바/대시보드/Settings를 커버.

## v0.4.1.2

**[0.4.1.x GUI 개선 2/5 — 위험도: 중간] GameListSet 목표 용량 대시보드**

- Dashboard에 GameListSet(구 Local)별 목표 용량 현황 패널 추가: 사용량 게이지,
  목표/여유 용량 텍스트, 슬라이더+직접입력(GB)으로 목표 조절.
- 상단 SOURCE 바의 GameListSet 카드에도 목표가 설정된 경우 소형 사용량 게이지 표시.
- `api.py`: 기존에 스키마에는 있었지만 GUI에서 설정할 방법이 없던
  `target_capacity_bytes` 필드를 실제로 쓰게 하는 `set_local_target_capacity()` 신규
  추가 (기존 필드 재활용이라 스키마 변경 없음, `config.json`에 값 하나만 기록됨).

## v0.4.1.1

**[0.4.1.x GUI 개선 1/5 — 위험도: 낮음] 프로그레스 바 스타일 + 사이드바 재구성**

이번 0.4.1.x 시리즈는 "기존 gui 개선"을 목적으로 한 사용자 요청 9개 항목을 위험도
낮은 것부터 순서대로 별도 버전에 나눠 반영한다 (자세한 전체 계획은 HANDOFF.md
"12. [0.4.1.x] GUI 개선 - 위험도 단계별 롤아웃" 참고). 이 버전은 **데이터를 전혀
건드리지 않는(렌더링/라벨만 바뀌는) 항목만** 포함한다.

- 백그라운드 작업(Refresh List/Export/Import 등) 진행률 바를 `[||||||][      ] (55%)`
  형태의 브라켓 스타일로 교체 (기존 채움 막대 → 텍스트 기반 바 + 아래 현재 항목명).
- 사이드바 순서/라벨 변경: Dashboard → **ArchiveDB**(구 MasterDB) → **GameListSet**
  (구 Local). **GUI 표시 라벨만 바뀌었고, 내부 view key(`masterdb`/`local-*`)와
  `import_engine.py`/`export_engine.py`/`api.py`의 함수명은 전부 그대로**(리스크 최소화
  원칙 - HANDOFF.md 6절의 MasterDB 고정 기준 원칙과 충돌 없음).
- Settings 톱니바퀴 아이콘을 상단 브랜드 영역에서 사이드바 맨 아래로 이동.

## v0.4.1.0

**v0.5 SQLite 마이그레이션 8~11단계 완료 + Compare 화면 신규 + 실사용 버그 다수 수정**
(Claude.ai → Claude Code 이관 후 첫 릴리즈)

- **GameListSet 기반 다지기**: `game_list_set_roms` 멤버십을 SQLite에 실제로 저장(매번
  파일시스템 재스캔 대신), `target_capacity_bytes` 필드 추가.
- **Import/Export native SQLite write 전환**: `import_local_to_masterdb`가 JSON과
  나란히 SQLite에도 직접 write. 커밋을 배치 처리하도록 최적화해서 대량 Import
  성능이 기존 대비 크게 개선됨(실측: 1,000롬 기준 SQLite 오버헤드가 사실상 0으로 수렴).
- **Compare 화면 신규**: GameListSet 대 GameListSet, 또는 MasterDB 대 GameListSet의
  ROM 목록을 좌우 독립 리스트로 비교. 각 행은 FILE/TITLE/DESCRIPTION을 한 줄로 표시,
  GameList 스타일 헤더, 하단 COPY 버튼으로 선택 항목을 반대쪽에 복사.
- **유사롬(Comparable ROM) SQLite 이전 + 대표 지정 UI**: `similar_groups` 테이블로
  이전(기존 JSON 방식은 그룹에 고정 ID가 없어 대표 지정이 불가능했음), 결과 모달에서
  별표로 대표 지정/해제 가능.
- **버그 수정**:
  - Media(드래그앤드롭) 저장 후 Title이 다른 게임 값으로 덮어써지던 문제 수정.
  - SQLite WAL 모드 미적용으로 인한 심각한 Import 성능 저하(수십 배) 수정.
  - Local GameList에서 ES-DE alias 시스템(예: msx/msx1)이 같은 게임을 중복 행으로
    보여주던 문제 수정 - 실제 ROM/media 존재 여부를 반영해 정확히 병합, media 타입이
    두 폴더에 나뉘어 있어도 합집합으로 병합.
  - 백업(zip) 생성이 SQLite WAL 사이드카 파일 때문에 Windows에서 실패하던 문제 수정.

## v0.4.0.22

- Local GameList cache를 실제 Local scan 결과의 독립 snapshot으로 보존하도록 수정.
- Local → MasterDB → Local 전환 시 Local GameList가 0개로 변하는 문제 수정.
- Local cache의 비정상 빈 placeholder를 유효한 cache로 취급하지 않도록 보호.
- ES-DE metadata-only 항목도 media index를 생성하도록 수정하여 ROM이 없어도 Cover/Media를 사용할 수 있도록 개선.
- ES-DE Local scan 진행률을 metadata/game entry 전체 기준으로 표시.

## v0.4.0.21
- ES-DE Local may be registered without a ROM path; gamelists/downloaded_media are sufficient to show metadata-only entries as Missing ROM.
- ES-DE system discovery now unions gamelists, downloaded_media, and optional ROM directories.
- Local scan summary now records Missing ROM and metadata counts from the same gamelist-based source used by GameList.
- MasterDB -> Local version import/export keeps the newest imported metadata version as `default_version_id` (latest wins).
- ROM filename normalization now treats Roman numerals I..XXX as their Arabic 1..30 equivalents for matching, while preserving sequel/part identity.
- Normal-click after multi-selection immediately clears the visual multi-selection state; Ctrl/Meta-click remains the toggle mechanism.
- ES-DE Local setup UI places the required ES-DE metadata/media root above an optional ROM path.
- Media layout remains no-scroll with a 68/32 Cover/right stack and natural image sizing.

## v0.4.0.20
- Media 탭을 무스크롤 68/32 레이아웃으로 재구성(Cover + Marquee/MixImage/Wheel, Screenshot 전체폭).
- List/Preview 현재 커서 highlight를 상세 패널 자동숨김과 분리하여 항상 유지.
- 다중 선택 후 일반 클릭은 전체 다중 선택을 해제하고 클릭한 게임을 단일 선택.
- MasterDB -> Local 매칭에 system-scoped 보수적 파일명 정규화 추가(언어/CD/버전/release 태그 무시, 부제 후방 fallback, 편/숫자 정보 보존).
- 정규화 매칭이 여러 MasterDB 항목으로 모호하면 자동 매칭하지 않도록 안전장치 추가.

## v0.4.0.19

- Game list multi-selection: Ctrl+A selects all currently filtered games.
- Clicking an already-selected game with a normal mouse click toggles that item off.
- List-view selected/multi-selected styling now uses the same accent highlight language as Preview cards instead of red danger styling.
- Media layout corrected: compact fixed-height Cover tile, Marquee/MixImage stacked on the right, large full-width Screenshot, smaller Wheel below.
- Cover media now uses contain/auto sizing so portrait artwork does not stretch the composition.

## v0.4.0.18

- Restore native Windows title bar for reliable minimize/maximize/restore/close/resize.
- Fix Local→MasterDB media synchronization so missing individual media types are copied even when metadata is duplicate.
- Add Media/ROM selection dialog for MasterDB→Local Export/Import; defaults are configurable in Settings.
- Rebuild Media layout: Cover left, Marquee/MixImage right, large full-width Screenshot, smaller Wheel.
- Fix font scaling to remain layout-stable.
# v0.4.0.17

- Local → MasterDB metadata Export now copies MasterDB media when the DB entry has no media, even when the metadata version is already a duplicate.
- MasterDB → Local Import/Export now supplements missing Local media instead of depending on metadata changes.
- Representative metadata Cover now resolves lightweight media markers through the per-media image API instead of rendering `media://available` as an image URL.
- Frameless Windows controls now use native Win32 HWND operations for minimize/maximize/restore/close, native drag, and native edge/corner resize.
- Font scaling no longer uses CSS `zoom`; typography is scaled independently so layout geometry and resize hit zones remain stable.
- Screenshot media preview enlarged to the same visual class as the other major media panels.

# v0.4.0.16

- Frameless window controls repaired: current pywebview geometry properties, resize bridge wrapper, native drag region, minimize/maximize/restore/close, edge/corner resize.
- Preview keyboard navigation now forwards ArrowLeft/ArrowRight as well as vertical keys.
- Local/MasterDB detail media uses lightweight availability + per-image bridge loading to avoid oversized base64 payloads; media paths accept both ES-DE root and downloaded_media root and stem matching is case-insensitive.
- Media panel redesigned: Cover spans left two rows, Marquee/MixImage right, Screenshot/Wheel below.
- Import from MasterDB has fixed MasterDB source/current Local target and asks only for confirmation; imports metadata + media only.
- Mutation refresh invalidates detail/media caches so delete/export/import results appear immediately.

## 0.4.0.15
- Frameless title controls overlaid at the top-right without consuming layout space.
- Restored frameless window resize via edge/corner hit zones.
- Unified Local/MasterDB source-card format: `NAME - N Roms(XG)`.
- Fixed preview card geometry and removed conflicting dynamic grid rules.
- Fixed preview keyboard navigation to use actual rendered grid columns.
- Restored visible selected-row highlight in List mode.
- Fixed Media overview key mapping for Marquees/Covers/Screenshots/Miximages/Wheel/Videos.
- Added MasterDB ROM size to source-card statistics.

# Retro Metadata Manager Changelog

## 0.4.0.11
- Local 화면 전환 시 불필요한 전체 재스캔 방지
- runtime scan index를 설정 파일에서 분리하여 10,000 ROM 환경의 config I/O 폭증 방지
- gamelist XML metadata index 재사용 및 media index 구조 변경 감지 최적화
- Local/MasterDB DEL 키 전역 처리 및 삭제 후 캐시 즉시 갱신
- Dashboard Local scan 결과 캐시 재사용

# Changelog

## 0.4.0.10
- Local Refresh incremental scan/index optimization.
- System-filtered Local Export to MasterDB; already registered ROMs skipped before processing.
- Local/MasterDB navigation state reflected in top cards and MasterDB ROM count refreshed.
- Local Dashboard uses cached scan data.
- Similar ROM threshold moved to General Settings with a single 0-100% slider.
- Delete key deletes selected Local ROM + metadata/media, and MasterDB ROM + stored media.


이 프로젝트는 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.
`0.x.y` 동안은 초기 개발 단계로, MINOR 버전 변경에도 호환성이 깨질 수 있습니다.
`1.0.0`부터 "완전한 최초 정식 버전"으로 취급합니다.

## [0.4.0.9] - Local 초기화/Refresh/삭제 흐름 수정

### Fixed
- MasterDB 미설정 상태의 실제 pywebview 실행 시 시작 직후 MasterDB 경로 선택 대화상자를 자동 표시.
- Local 추가 직후 새 Local을 자동 선택하고 초기 스캔을 백그라운드로 실행하여 0 ROMs 상태로 남지 않도록 수정.
- Local 화면 전환 시 매번 전체 파일 스캔하던 동작 제거. 마지막 성공 스캔 결과를 캐시하여 Local <-> MasterDB 전환을 즉시 처리.
- Refresh List 진행률을 시스템 수(1/4 등)가 아닌 실제 처리 중인 게임 파일명 + 파일 수로 표시.
- Local Delete 완료 후 불필요한 전체 Refresh List 재실행 제거. 삭제 결과를 현재 목록에 즉시 반영.

## [Unreleased]

### Fixed
- `build.bat`/`run.bat`에 포함된 한글 텍스트가 Windows cmd.exe에서 코드페이지 문제로
  깨져 명령어 자체가 조각나 실행되던 문제(`echo`가 `'ho'`로 잘리는 등) → 배치파일 내용을
  전부 영문(ASCII)으로 재작성 + CRLF 줄바꿈으로 통일하여 인코딩 이슈 원천 차단.

## [Unreleased] - 웹 GUI 전환 진행 중 (Claude Code로 이관)

### Added
- `api.py`: pywebview용 Api 브릿지 클래스. Local CRUD, 스캔, Import/Export, Version 관리,
  Media 업로드(base64), 백업/복원, 설정 저장 등 현재 확정된 GUI 기능 전체를 기존 백엔드에 연결.
- `main_gui.py`: pywebview 진입점 (신규 웹 GUI, 기존 Tkinter main.py는 그대로 보존).
- `db.update_single_media`: media 타입 하나만 부분 갱신하는 헬퍼 (GUI 드래그앤드롭용).
- `config.export_options.force_overwrite` 옵션 + `export_engine.py` 연동 (충돌 시
  확인 없이 무조건 덮어쓰기).
- `tests/test_api.py`: api.py 통합 테스트 11개 (한글 인코딩 왕복 검증 포함).
- `HANDOFF.md`: Claude Code 세션 이관용 인수인계 문서.

### Fixed
- `backup_engine.py`: `from config import BACKUP_DIR` 방식이라 테스트에서 경로를
  재할당해도 반영 안 되던 문제 -> `import config as cfgmod` 방식으로 변경.

### In Progress
- `gui_web/` (실제 HTML/CSS/JS 프론트엔드)는 아직 미작성. `RetroMetadataManagerMockup.jsx`
  (React 프로토타입)를 참고해 vanilla JS로 이식하는 작업이 다음 단계.

## [Unreleased] - gui_web 실사용 피드백 반영 (Midnight Arcade 디자인 적용)

### Changed
- 컬러 테마를 "Midnight Arcade" 팔레트로 교체 (보라 계열 accent #8B5CF6),
  배경 그라디언트 + 스캔라인 텍스처 + focus-ring 추가.
- 상단 Local/MasterDB 카드바 제거 (실수로 죽은 코드처럼 남아있던 것 확인 후,
  사용자 확인 하에 제거 확정) - 사이드바가 그 역할을 흡수.
- 사이드바에 GAME SYSTEMS 목록 추가 (리스트 화면에서만 노출), Settings는
  하단 nav 항목 대신 로고 옆 톱니바퀴 아이콘으로 진입 + 이전 화면 기억 후 복귀.
- Metadata/Media/Settings 패널의 타이포그래피를 게임리스트 수준으로 통일
  (`--fs-eyebrow`~`--fs-title` 5단계 CSS 변수 신설), 상세 패널 폭도 340px->320px로 축소.
- Dashboard 통계 테이블 좌우 여백 타이트하게 조정.
- Local 사이드바 항목에 Frontend/ROM수(축약 표기)/용량을 한 줄로 표시.

### Fixed
- 상세 패널에서 게임을 바꿀 때마다 Metadata/Media 탭과 Media 타입(Covers/Screenshots 등)
  선택이 초기화되던 문제 -> 이제 게임을 바꿔도 마지막 선택이 유지됨.
- 시스템 이름 표기 규칙 확정: ROM 디렉토리 이름 기준, ES-DE 표준(소문자 축약형)과
  다르면 표준으로 교정 (예: SNES -> snes, PSX -> psx). `normalizeSystemName()` 신설.
- `pick_folder()`에 pywebview/WebView2 조합에서 네이티브 폴더 선택창이 떠 있는 동안
  화면이 빈 화면처럼 보이는 알려진 렌더링 이슈에 대한 완화 조치 추가 (확정적 재현/해결
  여부는 실사용 재확인 필요).

## [0.4.0.8] - 유사롬(Comparable ROM) 알고리즘

"중복 ROM" 명칭을 "유사롬"으로 변경하고, 점수제 기반 판별 알고리즘을 신규 구현.

### Added
- `similar_rom.py` 신규: 5개 기준 점수제 (제목 유사도 35점, 스크린샷 SHA256 완전일치
  20점, 파일명 유사도 15점, 개발사 유사도 15점, 출시년도 일치 15점, 합계 100점,
  기본 임계값 60점). Python 표준 라이브러리 difflib만 사용 (외부 의존성 없음).
  Union-Find로 서로 연결된 ROM들을 그룹핑.
- **시스템 선택 후 수동 실행**: "유사롬 찾기" 버튼은 MasterDB 뷰에서 특정 시스템이
  선택된 상태에서만 노출 (전체 시스템 한꺼번에 O(n²) 비교하면 느리므로 의도적으로
  스코프 제한). 결과는 MasterDB에 저장되어 재계산 없이 "결과 보기"로 다시 조회 가능.
- Settings에 "유사롬 설정" 섹션 신규 - 5개 항목 배점 + 임계값을 직접 조정 가능.
- 게임 리스트 상태 필터의 "Duplicate ROM"을 "유사롬 (Comparable ROM)"으로 명칭 변경.
- 백그라운드 job(진행률 표시) 기반으로 실행 (`start_find_similar_roms`).

### Tests
- BT 총 **79개** (기존 74 + 신규 5: 설정 저장/기본값, 유사 타이틀 그룹핑, 결과 영속성,
  시스템이 다르면 절대 안 섞이는지 검증)

## [0.4.0.7] - Preview 모드 대량 게임(683개+) 출력 깨짐 수정

### Fixed
- **[BUG FIX] 게임이 많을 때(예: 683개) Preview(카드형) 모드 출력이 깨지던 문제**:
  원인은 카드가 렌더링되는 즉시 전부 동시에 썸네일 API를 호출해서 브릿지가
  과부하 걸렸던 것으로 확인. `IntersectionObserver`로 실제 스크롤해서 화면(또는
  근처 200px)에 들어올 때만 낱개로 지연 로딩하도록 전면 교체.
  - Observer의 `root`를 실수로 존재하지 않는 요소로 잘못 지정했던 것도 같이 발견/수정
    (고쳤으면 사실상 항상 브라우저 뷰포트 기준으로 동작해서 스크롤 컨테이너 내부
    가시성을 제대로 못 잡았을 뻔한 문제).
- `#preview-grid`의 `height:100%`를 이 프로젝트에서 반복적으로 문제였던 패턴이라
  더 견고한 `flex:1; min-height:0;` 체인으로 미리 교체.

### Tests
- BT 총 74개 (프론트엔드 전용 변경이라 백엔드 테스트 수 변화 없음, 전체 재확인 완료)

## [0.4.0.6] - ROM만 있고 metadata 없는 항목 표시

### Added
- **[신규] gamelist.xml에 항목이 없는 ROM(고아 ROM)도 목록에 표시**: 지금까지는
  scan_local()이 gamelist.xml 기준으로만 열거해서 "ROM은 있는데 metadata가 아예 없는"
  경우가 목록에서 빠졌었음. 이제 그런 항목도 함께 표시하고 `noMetadata: true` 플래그를
  전달, GUI에서 파일명을 빨간색으로 강조 표시 (List/Preview 모드 둘 다).

### Changed
- `test_delete_local_games_metadata_only_keeps_rom` 테스트를 새 동작에 맞게 갱신
  (metadata만 삭제해도 이제 항목 자체가 사라지지 않고 "고아 ROM"으로 계속 표시됨 -
  더 정확한 동작).

### Tests
- BT 총 **74개** (기존 72 + 신규 2)

## [0.4.0.5] - 게임 삭제 기능 + 추가 버그 수정

### Fixed
- **[BUG FIX] `_remove_es_style_entry`가 ES-DE에서 media 파일을 조용히 못 지우던 문제**:
  CleanUp 버그와 같은 종류의 실수 - `es_media_root()`를 안 거쳐서 잘못된 경로를 찾다보니
  media_dir.exists()가 항상 False가 되어 아무 것도 안 지워지고 있었음. Orphan Cleanup과
  이번에 추가한 게임 삭제 기능 둘 다에 영향. 회귀 테스트로 검증.

### Added
- **게임 삭제 기능**: Local 뷰에서는 metadata/ROM 파일을 개별 선택해서 삭제 가능,
  MasterDB 뷰에서는 metadata만 삭제 가능(ROM 실물 삭제는 추후 추가 예정) - 사용자
  확정: "Master에서 삭제하면 Master에서만, Local에서 삭제하면 Local에서만".
  - `api.delete_local_games()` / `api.delete_masterdb_games()` 신규
  - 다중선택: Ctrl+Click(개별 토글), Ctrl+Shift+Click(범위 선택)
  - 상단 "삭제 시," + metadata/Rom 체크박스 (Rom은 MasterDB 뷰에서 비활성)
  - Delete 키로 실행, 실행 전 확인 대화상자 필수
- List/Preview 모드 둘 다 다중선택 지원, 선택된 행/카드는 빨간 아웃라인으로 표시.

### Tests
- BT 총 **72개** (기존 65 + 신규 7: 삭제 기능 metadata-only/rom-only/both/다중선택,
  MasterDB 삭제가 Local에 영향 안 주는지 등)

## [0.4.0.4] - Dashboard 개편 / Detail 패널 재구성 / 키보드 버그 수정

### Fixed
- **[BUG FIX] Dashboard의 Local 통계 부정확 문제**: 시스템명 근사매칭 대신 scan_local()의
  정확한 결과를 직접 사용하도록 재작성. 같은 시스템(snes 등)을 쓰는 Local이 여러 개여도
  더 이상 통계가 섞이지 않음 (회귀 테스트로 검증).
- **[BUG FIX] 키보드 방향키/PageUp·Down/Home/End 미동작**: `#list-scroll`에 `tabIndex`만
  주고 실제 `.focus()` 호출이 없어 키 이벤트가 전혀 안 잡히던 문제 - 포커스에 의존하지
  않는 전역 키 이벤트로 이전 (입력창에 타이핑 중일 땐 방해하지 않도록 처리).

### Changed
- **Dashboard 전면 개편**: Health 요약 한 줄(LOCAL 등록수/SERVER 경로) 복원, 지표
  3개 -> 6개(전체 ROM 개수/크기, 전체 metadata 개수, 전체 media 크기, Missing ROM,
  Missing Media), 시스템별 가로 막대그래프 신규(눈금 최대 20GB 고정, 시스템별 고정
  색상, 전체 크기 텍스트 병기), 시스템별 통계 테이블에 색상 라벨 점 + ROM/Media 크기 컬럼 추가.
- **MasterDB scope의 Missing ROM 판정 변경**: 이제 MasterDB가 ROM 실물도 저장하므로,
  "실물 파일이 저장되어 있는지" 기준으로 재정의 (기존엔 metadata 완성도 기준이었음).
- **Detail 패널 Metadata 탭 재구성**: 하단 중복 Cover 박스 제거 (상단 identity 카드에
  이미 있음). 레이아웃을 상단고정(대표이미지+Title)/Description(가변, flex:1)/
  하단고정(필드그리드+Version관리) 구조로 바꿔서, 생긴 여유 공간을 Description이
  우선적으로 채우도록 함.

### Added
- `api.get_health_info()` 신규.
- BT 4개 추가 (Dashboard 정확도, MasterDB Missing ROM 재정의, 6개 지표 존재, Health 정보)

### Tests
- BT 총 **64개**

## [0.4.0.3] - 진행률 바 / Export 모드 선택 UI 연결

0.4.0.2에서 준비한 백엔드 job 시스템·3모드 Export를 실제 화면에 연결했다.

### Added
- `#job-progress` 진행률 바 UI: Refresh List/CleanUp/Prune Data/Export 4개 작업
  전부 공용으로 사용 (`runJobWithProgress()` 헬퍼가 폴링 처리).
- Export to MasterDB 클릭 시 3가지 모드(MetaData/Roms/MetaData+Roms) 선택 목록 표시,
  ROM이 포함된 모드는 확인창에서 필요 용량/여유 공간을 미리 보여주고, 용량 부족 시
  확인창 단계에서부터 바로 알림 (실행 자체가 시작되지 않음).

### Changed
- 버전 0.4.0.1 -> 0.4.0.2 -> 0.4.0.3 (요청하신 대로 소수점 넷째 자리로 천천히 증가)

## [0.4.0.2] - CleanUp 심각 버그 수정 + MasterDB ROM 저장 기반 + 진행률 인프라

### Fixed
- **[심각] CleanUp이 ROM 파일까지 삭제할 수 있던 버그**: `reset_metadata()`가
  `es_media_root()`를 거치지 않고 media_path를 그대로 순회해서, ROM 폴더가
  metadata_path 루트 밑에 같이 있는 흔한 ES-DE 구조에서 ROM까지 삭제될 위험이 있었음.
  실제로 버그를 재현하는 회귀 테스트 작성 후 수정 확인함.

### Added
- **MasterDB ROM 저장 기반**: `db.rom_storage_path()`/`rom_is_stored()` 신규 (스키마
  마이그레이션 없이 파일 존재 여부로 판단). MasterDB가 이제 metadata뿐 아니라 ROM
  실물 파일도 저장할 수 있음 (NAS 백업/중복 정리 목적).
- **Export 3가지 모드**: `start_export_local_to_masterdb(local_id, mode)` -
  "metadata" | "roms" | "metadata_roms". ROM 복사는 이미 저장된 것은 건너뜀.
- **Export 전 디스크 용량 사전 확인**: `disk_utils.py` 신규, `check_export_disk_space()`.
  용량 부족 시 복사를 아예 시작하지 않고 바로 실패 반환.
- **백그라운드 진행률(Job) 시스템**: `_run_job()`/`get_job_progress()` 신규.
  Refresh List/CleanUp/Prune Data/Export 전부 `start_*` 메서드로 스레드 실행 후
  폴링으로 진행률 확인 가능 (`start_reset_metadata`, `start_orphan_cleanup`,
  `start_scan_local`, `start_export_local_to_masterdb`).
- `pick_folder(title=...)`: 폴더 선택 대화상자에 목적을 알리는 문구 시도 (pywebview
  버전에 따라 지원 여부 다를 수 있어 여러 방식 순차 시도 후 안전 폴백).

### Tests
- BT 총 **60개** (기존 50 + 신규 10: CleanUp 버그 재현/수정 검증, Job 시스템,
  3모드 Export, 디스크 용량 부족 시나리오 등)

### 진행 중 (다음 배치에서 이어감)
- 프론트엔드(JS) 쪽 진행률 바 UI, Export 모드 선택 화면, 디스크 부족 에러 표시는
  아직 안 만들었음 (백엔드 API만 준비됨)
- Dashboard 개편(Health/막대그래프/7개 지표), Detail 패널 재구성, GameList 삭제
  기능, 유사롬 알고리즘, 레이아웃 저장/복원 등은 미착수

## [0.4.0.1] - 실사용 버그 대량 수정

v0.4.0을 실제로 실행해본 결과 나온 심각한 버그들을 수정했다.

### Fixed
- **pywebviewready 타이밍 버그**: DOMContentLoaded 시점에 곧바로 init()을 돌려서, 실제
  pywebview 브릿지가 준비되기 전에 목업 데이터로 폴백하던 문제 (더미 Local, 잘못된
  MasterDB 상태로 보이던 근본 원인으로 추정). pywebviewready 이벤트를 기다리도록 수정.
- **MasterDB 최초 설정 화면 부재**: `setMasterdbPath()`가 어디서도 호출되지 않아 최초
  실행 시 MasterDB를 설정할 방법이 아예 없었음. 미설정 시 GameList 영역에 온보딩 화면
  ("+ MasterDB 추가") 신규 구현.
- **GameList가 창 크기를 못 채우던 문제**: `height:100%` 체인이 조상 어딘가 깨지기
  쉬운 방식이라, 더 견고한 `flex:1` 체인으로 전면 교체.
- **Settings가 화면 최하단에 출력되던 문제**: `renderAll()`에서 `#list-area`(filter-bar/
  list-body/detail-panel을 감싸는 래퍼) 자체를 숨기지 않아서, 리스트 화면이 아닐 때도
  flex:1 공간을 계속 차지하며 Settings/Dashboard를 밀어내던 게 원인. `#list-area`도
  같이 토글하도록 수정.
- **[핵심] GameList가 ROM 매칭된 항목만 보여주던 버그**: `importers/base.py`에
  `list_gamelist_entries()` 신규 함수로 gamelist.xml 전체를 ROM 존재 여부와 무관하게
  열거하도록 하고(ES-DE/EmulationStation), `api.py`의 `scan_local()`을 전면 재작성해서
  5단계 상태 분류(Normal/Partial/Missing ROM/Missing Media/Duplicate ROM, video 제외
  media 기준)를 구현. Pegasus/LaunchBox는 아직 미지원 - 기존 방식으로 안전하게 폴백.
  - 이 재작성 과정에서 `importer.list_roms()`가 dict가 아니라 `Path` 객체 리스트를
    반환한다는 걸 놓치고 `r["filename"]`으로 잘못 접근해 예외가 조용히 삼켜지며
    `romMatched`가 항상 False로 나오던 실제 버그도 같이 발견/수정함 (테스트 작성 중 발견).
- **Local 화면에서 게임 클릭 시 "게임을 찾을 수 없습니다" 버그**: Local 화면에서도
  MasterDB 전용 조회 함수(`get_game_detail`)를 그대로 썼던 게 원인. `get_local_game_detail()`
  신규 추가 - Import 없이도 Local 파일을 직접 읽는 읽기전용 조회 경로 (예전 Tkinter
  버전의 "Local 상세는 Import 없이도 조회 가능" 원칙 복원). Detail 패널도 읽기전용일 때
  저장/버전관리 UI를 숨기고 안내 문구를 표시하도록 처리.
- **Preview(그리드) 모드에서 Local 뷰의 커버가 안 보이던 문제**: `scan_local` 응답에
  `hasCover` 필드가 없었고, 있었더라도 지연로딩이 MasterDB 전용 API만 호출했음.
  `hasCover` 추가 + `get_local_cover_thumbnail()` 신규 추가로 Local/MasterDB 각각
  맞는 API를 호출하도록 수정.

### Added (테스트)
- `tests/test_api.py`에 9개 신규 테스트 추가 (Missing ROM 열거, 5단계 상태 분류,
  Local 내 중복 판별, Local 읽기전용 상세조회, 다이지쇼 폴백 경로 검증 등)
- BT 총 **49개** (기존 40 + 신규 9)

### Known issues (다음에 확인 필요)
- "GameList가 목업과 달리 흰색 테마로 고정되어 보인다"는 리포트는 정적 분석으로
  명확한 원인을 못 찾음 (게임리스트 카드 자체는 원래부터 항상 밝게 유지하도록 의도된
  디자인 - 앱 전체가 밝게 나오는 건지, 카드만 그런 건지 스크린샷으로 재확인 필요)

## [0.4.0] - 웹 GUI(gui_web/) 완성 - 1차 실사용 가능 버전

이 버전부터 웹 기반 GUI(`main_gui.py` + `gui_web/`)가 기존 Tkinter GUI(`main.py`)를 대체하는
주력 인터페이스가 된다. Tkinter 버전은 계속 보존되지만 더 이상 개발하지 않는다.

### Added
- `api.py`: pywebview Api 브릿지 완성. Local CRUD/스캔/Import/Export, Version 관리,
  Media 6종(Covers/Screenshots/Miximages/Marquees/Wheel/Videos) 업로드, 백업/복원,
  설정 저장, Region/Rating/중복 ROM 표시, 버전 조회(`get_version`) 등 전체 연결.
- `gui_web/`: 순수 HTML/CSS/JS 프론트엔드 (Tailwind 등 외부 의존성 없음).
  - Midnight Arcade 컬러 테마, SOURCE 바(Local/MasterDB 카드), 사이드바 GAME SYSTEMS 목록
  - 게임 리스트: Region/Rating 컬럼, 컬럼 드래그 리사이즈, 키보드 네비게이션(방향키/PageUp·Down/Home·End/Enter)
  - Detail 패널: identity 요약 카드, 5초 자동숨김 + Pin 고정, Media 드래그앤드롭 업로드,
    Version 복제/기본값/삭제/Ver Diff
  - Preview(그리드) 모드: 커버 썸네일 지연 로딩(`get_cover_thumbnail`)
  - Font-scale: Shift+마우스 휠로 전체 화면 75~150% 확대/축소 (CSS zoom 기반)
  - Settings: 언어/테마/저장주기/Export 옵션(강제 덮어쓰기 포함)/백업·복원
- `tests/test_api.py`: 20개 (한글 인코딩 왕복, 중복 ROM, Marquees/Videos, 썸네일 지연로딩,
  버전 조회 등 포함)

### Fixed
- `db.update_single_media`: media 타입 하나만 부분 갱신하는 헬퍼 신설 (드래그앤드롭용)
- `config.export_options.force_overwrite` 옵션 추가 + `export_engine.py` 연동
- `backup_engine.py`: 모듈 import 시점에 경로가 고정되던 문제 수정 (테스트 격리성)
- Frontend 표시 라벨("ES-DE" 등)과 백엔드 내부 키("es-de" 등) 매핑 (`GUI_FRONTEND_TO_INTERNAL`)
- 영상 미디어를 base64로 통째로 인코딩하지 않도록 처리 (용량 문제 방지)

### Changed
- 버전을 0.3.0 -> 0.4.0으로 (신규 GUI라는 큰 기능 추가이므로 MINOR 버전업)
- 사이드바의 버전 표시가 하드코딩 문자열 대신 `api.get_version()`으로 실제 `version.py`
  값을 가져오도록 변경 (두 곳이 따로 놀며 어긋나는 것 방지)

### Known limitations (다음 버전에서 다룰 것)
- 다이지쇼(Daijishō) Import/Export는 여전히 미구현 (실제 폴더 구조 확보 전까지 보류하기로 확정)
- Core 설정 / ScreenScraper 연동 / RetroArch Export / CSV / 버전 일괄정리는 백엔드엔
  있지만 현재 gui_web 화면에는 노출되지 않음 (필요 시 해당 화면 추가 후 연결)
- pywebview 자체가 개발 sandbox에 설치 불가능해서, 실제 창 렌더링/클릭/드래그는
  100% 사용자 환경(Windows)에서만 최종 확인 가능함

## [0.3.0] - 2026-08-26 (기능 버그 대량 수정 + GUI 디자인 리팩토링)

### Fixed (실제 사용 중 발견된 기능 버그)
- **커서가 안 보이던 문제.** 모든 Entry/Text 위젯에 `insertbackground`(커서 색상)가 지정되어
  있지 않아, 배경색과 겹쳐 커서 자체가 보이지 않았을 가능성이 높음 — "입력해도 반응 없다가
  화살표 키를 눌러야 갱신된다"는 반복 제보의 실제 원인으로 추정. 전체 Entry/Text에 명시 적용.
- **Local 화면에서 MasterDB Import 없이는 metadata/media를 전혀 보여주지 않던 문제.**
  이제 Local 자체 파일(gamelist.xml 등)에서 직접 읽어 읽기 전용으로 표시.
- **Media 탭이 실제 이미지를 렌더링하지 않고 파일 개수/이름 텍스트만 보여주던 문제.**
  `gui/image_utils.py` 신설(Pillow 우선, 없으면 내장 PhotoImage 폴백)로 실제 썸네일 표시.
- **Media 탭에서 다른 게임으로 이동(목록 재선택)이 막히던 문제.** 클로저 상태 관리가
  꼬여있던 이전 구현을 전면 재작성.
- **목록(Local/MasterDB)에서 Description이 여러 줄로 표시되어 행이 깨지던 문제.**
  `utils.single_line()` 추가, 개행 문자를 공백으로 치환 + 길이 제한.
- **Dashboard 테이블 컬럼이 헤더와 어긋나 보이던 문제.** `anchor` 미지정이 원인
  (텍스트 컬럼은 좌측, 숫자/용량 컬럼은 우측 정렬로 통일).
- 상단 Local 카드에 ROM 경로 정보 표시 추가.

### Changed (UX)
- Metadata 필드 순서를 Title → Description → (짧은 필드 2열 그리드) 순으로 변경,
  그리드 옆 여백에 대표 Screenshot 미리보기 추가.

### Changed (GUI 디자인 전면 리팩토링 — Minimal & Modern SaaS)
- 컬러 팔레트를 Stripe/Vercel/Linear 느낌의 다크모드 톤으로 교체
  (배경 #0F172A, 카드 #1E293B, 포인트 #6366F1, 보더 #334155).
- Typography 위계 정립(H1/H2/H3/Body/Caption)으로 제목과 본문 구분 명확화.
- **rounded-xl 카드**: Tkinter엔 border-radius가 없어 Canvas로 직접 둥근 사각형을 그리는
  `RoundedCard` 컴포넌트 신설, 상단 Local/MasterDB 카드·Dashboard 요약 카드에 적용.
- **버튼 Hover 애니메이션**: 색상 보간(lerp) 방식의 `animate_hover` 헬퍼 신설,
  Nav/상단 버튼/Dashboard·Settings 탭 버튼에 적용.
- 색상은 전부 `gui/style.py`의 토큰을 통해서만 참조하도록 되어 있어(하드코딩 없음),
  팔레트 교체가 앱 전체에 자동 반영됨.

### Added
- `requirements.txt`에 Pillow 추가 (Media 이미지 미리보기용).

## [0.2.2] - 2026-08-26 (디자인 개선 — 참조 샘플 코드 반영)

### Changed (UX/비주얼 폴리시)
- 이전 프로젝트의 참고 샘플 코드 스타일을 반영해 Nav/상단바를 개선:
  - Nav에 이모지 아이콘 + 섹션 라벨(LOCAL/SERVER) 추가로 구조 명확화
  - 선택된 메뉴 항목을 꽉 찬 accent 블록 대신 은은한 배경(PANEL3) + accent 글자색으로 표시
  - 상단바에 앱 타이틀("🎮 RETRO METADATA MANAGER" + 버전) 브랜딩 박스 추가
  - 카드/버튼 테두리를 2px → 1px로 얇게 (더 정돈된 느낌)
  - Local/MasterDB 카드 제목과 주요 액션 버튼에 아이콘 추가
  - Local 상태(정상/경고/오류/미설정)를 Nav의 Local 목록에서도 ●▲✕○ 아이콘으로 즉시 확인 가능

## [0.2.1] - 2026-08-26 (실제 Windows 실행 피드백 반영)

### Fixed (심각 — 실제 사용 불가 수준의 버그들)
- **ES-DE media 경로 구조 오인식.** 실제 ES-DE는 `<루트>/gamelists/`와
  `<루트>/downloaded_media/`가 같은 폴더 밑에 있는데, 코드는 media 경로 자체가
  downloaded_media 폴더인 것처럼 잘못 가정해 별도 입력을 요구했음. 이제 media_path는
  metadata_path와 동일한 "루트"를 가리키고, 내부적으로 downloaded_media/를 붙여 찾는다.
  (`importers/base.py`, `importers/es_de.py`, `importers/emulationstation.py`,
  `exporters/base.py`)
- **Local 등록 대화창: Metadata/Media 경로를 하나로 통합.** 모든 지원 Frontend가
  metadata와 media를 같은 루트에 두는 구조라서, 별도 필드가 불필요했을 뿐 아니라
  "Metadata만 입력하면 스캔오류인데 등록은 되어버리고", "둘 다 입력하면 등록 버튼이
  안 눌리는" 등 여러 연쇄 버그의 원인이었다. 필드 하나로 합치고 프론트엔드별 안내
  문구를 추가.
- Local 등록 대화창 크기가 작아 등록 버튼이 화면 밖으로 밀려나 보이지 않던 문제
  → 창 크기 확대 + 리사이즈 가능하도록 변경.
- **Settings 하단 버튼([취소][설정저장][기본값복원])이 메뉴를 클릭할 때마다
  한 줄씩 계속 쌓이던 버그.** 버튼 행이 매번 다시 생성되면서도 이전 것이 제거되지
  않고 있었음 → 버튼 행을 한 번만 생성하도록 구조 변경.
- **상단 Local/MasterDB 카드를 클릭해도 반응 없던 문제.** 카드 안의 텍스트(Label)에는
  클릭 이벤트가 연결되어 있지 않아, 사실상 카드의 여백 부분만 클릭해야 작동했음 →
  카드 내 모든 자식 위젯에 재귀적으로 클릭 이벤트를 연결하도록 수정.

### Added / Changed (UX 개선)
- Nav 패널의 "Local" 항목 아래에 등록된 Local 목록과 "+ Local 추가" 버튼을 바로 노출
  (상단 카드 대신 Nav에서 바로 선택/추가 가능).
- Nav 패널에 현재 보고 있는 화면(Local/MasterDB/Dashboard/Settings, 그리고 어떤 Local인지)을
  강조 표시.
- 카드 여백, Treeview 행 높이/헤더 여백을 소폭 확대해 가독성 개선.

## [0.2.0] - 2026-08-26

**스키마 변경(media 재구조화)이 포함되어 MINOR 버전을 올림.**

### Changed (중요 설계 변경)
- **media를 Version별 관리 → ROM 레벨 단일 관리로 전환.** 기존에는 metadata Version마다
  media를 따로 저장했으나, 이제 ROM 하나당 media는 단 1세트만 존재한다
  (`rom_entry["media"]`, 어떤 Version을 보든 동일한 이미지 표시). 저장 용량 절약 +
  사용자가 채택한 이미지가 재Import마다 바뀌지 않도록 하기 위한 의도적 설계.
  일반 Import는 media가 이미 있으면 덮어쓰지 않고(`overwrite=False`), 스크랩 적용처럼
  사용자의 명시적 행동에서만 교체(`overwrite=True`)한다.

### Fixed (매우 중요 - 데이터 유실 가능성)
- **`new_version_id()` 밀리초 충돌로 인한 Version 데이터 유실 버그.** 같은 밀리초 안에
  여러 Version이 연속 생성되면(Import 배치 처리 등) ID가 겹쳐 이전 Version의 데이터가
  통째로 덮어써지는 심각한 문제가 있었음. nanosecond 단위 모노토닉 카운터로 완전히 해결.
- Version 정렬 기준을 `created_at`(밀리초 정밀도, 동점 가능) 대신 `version_id`
  (충돌 없는 모노토닉 값)로 변경.

### Added
- **버전 일괄 정리** (Settings > Metadata 설정): Default에 없는 필드를 non-default
  버전들 중 최신 값으로 채운 뒤 non-default 버전을 모두 삭제. 2단계 확인 절차.
- **Ver Diff 대화창**: Version 2개를 나란히 비교/편집/삭제. 삭제 시 해당 버전에만
  있던 정보를 남는 버전으로 자동 이전.
- **CSV Export/Import**: 모든 ROM x 모든 Version을 CSV로 내보내고, upsert 방식으로
  재반영(add 신규 + 기존 version_id는 강제 덮어쓰기). media는 CSV 대상에서 제외.
- **백업 개선**: `backup/` 폴더(실행 파일 기준)에 날짜/시각 postfix로 자동 저장,
  목록에서 선택해 복원.

## [0.1.2] - 2026-08-26

### Fixed (예외 케이스 검토 중 발견)
- **[안전] 심각: 빈 경로가 현재 작업 디렉토리로 해석되던 문제.** `pathlib.Path("")`는
  `.exists()`가 `True`를 반환하며 cwd로 취급된다. Local 경로가 설정되지 않은 상태로
  스캔/Import/Export는 물론 특히 **파일을 삭제하는 Reset Metadata/Orphan Cleanup까지
  실행될 경우 엉뚱한 위치의 파일이 지워질 수 있는 위험**이 있었음.
  `config.validate_local_paths()`를 신설해 모든 파일시스템 진입점
  (`scan_local`, `detect_local_structure`, `reset_metadata`, `orphan_cleanup`)에서
  가장 먼저 검증하도록 수정. 위험한 삭제 작업은 경고창보다 경로 검증을 먼저 수행하도록 순서도 변경.
- MasterDB 미설정 시 상단 카드가 다른 카드와 시각적으로 구분 없이 표시되던 문제
  → 회색 배경/텍스트로 명확히 비활성 표시 (설계서 §5, §6)
- MasterDB 미설정 + Export to Local, Local 미설정 + Export to MasterDB 시나리오에
  누락되어 있던 방어 코드 보강 (기존에도 일부는 가드되어 있었으나 진입 경로별로 점검)

## [0.1.1] - 2026-08-26

### Fixed
- **RetroArch Playlist(.lpl) 크로스 플랫폼 경로 버그**: `path` 필드를 `pathlib.Path`로
  만들어 `str()` 변환하던 방식이, Windows에서 실행 시 안드로이드 스타일 경로
  (`/storage/emulated/0/...`)를 입력해도 강제로 `\`로 바꿔버리는 문제가 있었음.
  이제 "CRC32 계산용 로컬 경로"와 "playlist에 기록될 대상 경로(문자열, forward-slash 고정)"를
  분리했고, 대상 경로는 폴더 선택 대화창이 아닌 텍스트 입력으로 받아
  이 PC에 존재하지 않는 다른 기기의 경로도 지정할 수 있도록 수정.

## [0.1.0] - 2026-08-26 (초기 개발 버전)

### Added
- Core: config/db/utils 모듈, MasterDB JSON 스키마, Version(시간순) 관리
- Import: ES-DE / EmulationStation / Pegasus / LaunchBox 구조 감지·스캔·metadata 파싱
- Export: 4개 Frontend로 metadata/media 쓰기, 충돌 처리(OK/Skip/Replace All/Skip All),
  한글화 중복 옵션, RetroArch Playlist(.lpl) Export
- GUI 스켈레톤: 3단 레이아웃(Local/MasterDB/Dashboard/Settings), Local 등록, Metadata/Media Detail
- Core 설정, ScreenScraper 연동(단건/일괄), Dashboard(크기 기준 그래프), Settings 화면
- Reset Metadata / Orphan Cleanup, 중복 ROM 필터

### Fixed (자체 QA에서 발견)
- MasterDB 미설정 상태에서 설정 대화창을 취소하면 화면이 빈 채로 멈추던 문제
- Local 게임 목록의 Title/Description/Genre가 항상 빈 값으로 표시되던 문제
- 목록 헤더 클릭 정렬이 오름차순 고정이고 방향 토글이 안 되던 문제 (MasterDB는 정렬 자체가 미연결)
- Ctrl+Z(Undo)가 Entry 필드에서 동작하지 않던 문제 (수동 Undo/Redo 스택 구현)
- Ctrl+S 저장 단축키 미구현
- 종료 시/주기적 설정 자동 저장 미구현
- 목록에 Scrollbar가 없어 창 축소 시 스크롤이 어려웠던 문제
- Local의 시스템 폴더명이 Pegasus 등에서 ES-DE 표준과 다를 경우 Import/Export가
  올바르게 매칭되지 않던 문제 (`system_name_map` 추가)

### Known Limitations
- 다이지쇼(Daijisho) Import/Export는 실제 폴더 구조 미확인으로 미구현 (`NotImplementedError`)
- LaunchBox media 매칭은 ROM stem 기준만 지원 (제목 기반 폴백은 부분 구현)
- MasterDB 기준 "시스템 전체 스크랩"은 이름 검색 전용으로 제한 (해시 매칭은 Local 화면에서만 가능)
- 실제 tkinter 렌더링은 Windows 환경에서 미검증 (샌드박스 네트워크 제한으로 tkinter 설치 불가).
  `MANUAL_GUI_TEST_CHECKLIST.md` 참고하여 최초 실행 시 확인 필요.

## 0.4.0.12
- Local/MasterDB 상단 카드 선택 상태를 tuple 기반으로 통일
- MasterDB 카드에 Metadata 개수 표시
- Dashboard 진입 시 Local 전체 스캔을 동기 실행하지 않도록 변경
- Local metadata 직접 편집/저장 지원
- Local ROM Treeview에서 Delete 직접 바인딩
- Local 재진입 시 runtime scan cache 재사용
- Local Export는 버튼 클릭 시점의 Game System 선택 상태를 기준으로 대상 결정

## 0.4.0.12 (Web GUI correction)
- Game System 필터가 선택된 상태에서는 해당 시스템만 Local → MasterDB Export
- 전체 시스템 선택 상태에서만 전체 Export
- MasterDB 화면의 Export 버튼을 Export to Local로 변경
- Local metadata 직접 편집/저장 API 연결
- Delete 대상 기본값 및 MasterDB ROM/metadata 삭제 처리 개선
- Dashboard fast 통계 경로 및 Local scan 결과 캐시 개선


## 0.4.0.14

### GUI / UX
- Native WebView title banner 제거 및 frameless custom titlebar 추가 (minimize/maximize/close).
- Local SOURCE 카드 표시를 `LOCALn - N Roms(X.XG)` 형식으로 통일.
- Preview 카드 크기를 결과 개수와 무관하게 고정(기존 대비 약 20% 축소).
- Preview 키보드 탐색을 실제 2D grid 상하좌우 이동으로 수정.
- List 선택 상태를 더 강하게 표시.
- Metadata > Media를 Marquees/Cover/Screenshot → MixImage/Wheel 순으로 한 화면에 표시.
- Local 하단에 `Import from MasterDB` 추가.
- Export/Import/Delete 후 전체 재스캔 없이 현재 화면/Navigation/상단 통계를 즉시 동기화.

## 0.4.0.13
- Local 재진입 버그 수정: Local 목록 캐시를 실제 상태 객체에 초기화하고 Dashboard/Settings 경유 화면 전환에서도 재사용
- 게임 선택 시 전체 GameList 재렌더링 제거 및 상세 정보 캐시 추가
- Preview 685+ 카드의 이미지 지연 로딩 안정화 및 초기 카드 렌더링 개선
- Delete 키가 다중 선택뿐 아니라 단일 선택 게임에도 동작하도록 수정
- Local/MasterDB 삭제 후 즉시 목록/네비게이션 상태 갱신
- Local metadata 편집 저장 및 상세 정보 cache 무효화 개선
- Local Dashboard 최초 진입에서 전체 filesystem scan을 하지 않도록 fast 경로 수정
- MasterDB metadata count를 실제 version/metadata 존재 기준으로 계산
- Settings에서 세부 유사도 점수 UI 제거하고 일반 설정의 임계값만 유지

## v0.4.0.23 — Metadata-only Export + Preview Performance
- Fixed Local -> MasterDB metadata export for ES-DE installations with no physical ROM files.
- `scan_local()` now returns `metadata_entries` separately from `rom_list`; ROM-backed entries are not imported twice.
- Metadata-only entries participate in target system/selection filtering and version matching.
- Local Preview thumbnails now reuse the last scan's media index instead of rescanning media directories for every card.
- Preview thumbnails are resized to a compact 256px WebP representation and kept in a small LRU cache; detail media remains full-resolution.
- Reduced eager Preview thumbnail loading from 32 serial bridge calls to 12 cards in batches of 6.
- Added regression test for metadata-only ES-DE Import.
- Test suite: 89 passed.

## v0.4.0.28
- Alias-system media merge now ignores stale paths and preserves valid media from all merged Local systems.
- Local media drag/drop and URL import now persist directly to the Local frontend media tree.
- Local metadata save now also commits pending media instead of returning before media persistence.
- List rows now expose `data-rom-key`, fixing selected-row highlight tracking after keyboard/mouse selection.
- Diagnostic logging is quiet by default for high-volume scan/render/media-read events; actionable save/selection/error diagnostics remain.
