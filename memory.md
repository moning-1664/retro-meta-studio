# Retro Metadata Manager — AI Handoff / Memory

## Project
- Project: Retro Metadata Manager
- Current version: 0.4.1.5 (main/version.py). `fix/sqlite-data-safety`(PR #1)의
  버그 수정 10건은 이 merge로 main에 반영됨 - 아래 "SQLite 데이터 안전성 리뷰 대응"
  절 참고.
- GUI: Python backend + pywebview + vanilla JavaScript/CSS Web GUI (`gui_web/`)
- Main GUI entry: `main_gui.py`
- Web frontend: `gui_web/app.js`, `gui_web/style.css`, `gui_web/api-client.js`
- Backend API: `api.py`
- Database: `db.py`
- Local importers: `importers/`
- MasterDB -> Local: `export_engine.py`
- Local -> MasterDB: `import_engine.py`

## Important design goals
- User has roughly 10,000 ROMs and metadata, so performance is critical.
- Avoid full rescans when changing views or refreshing if nothing changed.
- Metadata and media are independent states. Never skip media processing merely because metadata is duplicate/conflicting.
- UI state must survive Dashboard/Settings/MasterDB/Local navigation.

## Major historical bug fixes already implemented

### Local / MasterDB state and navigation
- `S.localGamesCache` is initialized as an object and reused when returning to Local.
- Local should not rescan just because user moves Dashboard -> Local, Settings -> Local, or MasterDB -> Local.
- `renderAll()` handles view visibility; list views are `masterdb` and `local-*`.
- `currentLocalId()` determines current Local from `S.view`.
- `refreshMutationState()` invalidates detail/media caches, reloads Local/MasterDB info, refreshes the current data source, and renders immediately.
- Source/top cards should reflect current source and actual ROM/metadata statistics.

### Performance / incremental scan
- Avoid parsing `gamelist.xml` once per ROM. System-level metadata should be parsed/indexed once.
- Local scan results are cached in memory (`S.localGamesCache`).
- Detail and media image caches exist (`S.detailCache`, `S.mediaImageCache`).
- Refresh should reuse unchanged data where possible, using filesystem signatures (size/mtime where implemented).
- Do not serialize runtime scan cache into persistent config.
- Dashboard should use cached/summarized data instead of triggering a 10,000-ROM full scan.
- Card rendering uses fixed card geometry and lazy/eager thumbnail loading to avoid hundreds of simultaneous bridge calls.

### Export / Import semantics
- Local -> MasterDB is `import_engine.py`.
- MasterDB -> Local is `export_engine.py`.
- Metadata and media must be handled independently.
- If metadata already exists/duplicates, media still must be copied when selected and missing.
- `continue` must not be placed before media synchronization.
- Media selection is configurable through `settings.exportOptions.selected_media_types`.
- Default media types:
  - screenshots
  - 3dboxes
  - covers
  - marquees
  - miximages
  - wheel
- Videos default OFF.
- ROM copying default OFF.
- Export to Local / Import from MasterDB uses a media-selection confirmation dialog.
- Import from MasterDB has a fixed source (MasterDB) and current Local as target; no source selection dialog.

### System-specific export
- If a Game System is selected, export/import should target only that system.
- `selectedSystem === "all"` means all currently relevant systems.
- For Local -> MasterDB, `target_roms` is used to restrict export to the selected system/game list.
- Already-existing MasterDB entries should not cause unnecessary metadata/media work, but missing selected media must still be synchronized.

### Delete / metadata editing
- Local metadata can be edited directly; it is not read-only.
- Delete supports selected game(s) and can delete metadata and/or ROM depending on delete target settings.
- Delete must update GameList, navigation statistics, source cards, and caches without requiring the user to click another system or manual Refresh.
- Detail/media caches must be invalidated after mutation.

## Current UI conventions

### Game list selection
- Card/preview view: selected card uses `preview-card.selected` / accent border.
- List view must use the same accent-based visual language, not the danger/red color.
- Multi-selected rows/cards use `multi-selected` and should be accent-purple themed.
- `Ctrl+Click` toggles individual multi-selection.
- `Ctrl+Shift+Click` selects a range.
- `Ctrl+A` selects all games currently visible after system/search/status filters.
- When multi-selection is active, clicking an already-selected item with a normal mouse click toggles that item off.
- A normal click on an unselected item exits multi-selection and opens detail.

### Keyboard navigation
- Preview/card grid: Left/Right = horizontal one card; Up/Down = one actual rendered row.
- Do not infer column count from arbitrary width if actual rendered positions can be used.
- Global key handler must pass ArrowLeft/ArrowRight/ArrowUp/ArrowDown to `handleListKeyDown()` when not typing.
- List view: Up/Down/Left/Right move one row/item as appropriate.

### Media detail layout
Desired layout:

```text
┌───────────────────┬──────────────────┐
│ COVER             │ Marquee          │
│                   │                  │
│                   ├──────────────────┤
│                   │ MixImage         │
│                   │                  │
└───────────────────┴──────────────────┘
┌──────────────────────────────────────┐
│ SCREENSHOT                            │
│                                      │
│                                      │
│                                      │
│                                      │
└──────────────────────────────────────┘
┌────────────────────┐
│ WHEEL              │
│                    │
└────────────────────┘
```

- Cover should not become excessively tall just because its natural portrait aspect ratio is different.
- Cover is a fixed two-row tile; its image uses `object-fit: contain` and auto width so it does not stretch.
- Marquee is top-right; MixImage is bottom-right.
- Screenshot is full-width and large.
- Wheel is a smaller block below Screenshot.
- Media images are loaded individually where possible to avoid huge combined base64 bridge payloads.
- GUI media keys use exact API names: `Covers`, `Marquees`, `Miximages`, `Screenshots`, `Wheel`, `Videos`.

## Window behavior
- Previous attempts used a custom frameless title bar but native Windows controls/resize were unreliable.
- v0.4.0.18 restored the native Windows title bar deliberately for reliability.
- Do NOT reintroduce a fake frameless title bar unless there is a tested native Win32 implementation.
- Native title bar provides minimize/maximize/restore/close/drag/resize and should remain the default stable behavior.

## Font scaling
- Font scaling uses CSS variable `--font-scale` rather than CSS zoom.
- Layout geometry should not be scaled with the font size.
- Keep fixed controls/grid geometry independent from text scaling.

## MasterDB statistics / source card
- Desired display convention: `LOCAL1 - 724 Roms(5.2G)` and equivalent MasterDB format.
- MasterDB should include ROM count and metadata count consistently; previous bugs showed `685 Meta 685` or Local `724 Roms(0G)` due to inconsistent fields.
- Backend/UI field names must be checked before changing display logic.

## Testing / handoff rules
- Existing test suite historically has 79 tests and should remain green.
- Before claiming a UI fix is complete, inspect the actual JS call path, not only CSS or a helper function.
- For pywebview/window issues, verify the actual runtime backend and API rather than assuming an HTML button is connected.
- For Local-specific bugs, compare Local API/importer paths against MasterDB API paths; MasterDB working does not prove Local works.
- For media bugs, check both the GUI key and backend internal media key/path handling.
- For performance regressions, look for accidental full scans, repeated XML parsing, repeated recursive media discovery, or rendering all 10,000 rows/cards synchronously.

## Version history context
- 0.4.0.9–0.4.0.13: Local caching/state, export/import filtering, delete/edit work, dashboard/local navigation, similar-ROM threshold UI.
- 0.4.0.14–0.4.0.18: card sizing, keyboard navigation, media overview, media transfer selection, native window/titlebar experiments, media lazy loading, metadata image loading, native Windows titlebar fallback.
- 0.4.0.19: current incremental UI improvements: Ctrl+A multi-select, normal-click deselection, list multi-selection highlight aligned with card accent, corrected compact media geometry with large full-width screenshot, cover aspect-ratio protection.


## v0.4.0.20 matching/media rules
- MasterDB -> Local metadata/media matching is exact filename first, then conservative normalized filename **within the same canonical system only**. Never cross systems.
- Normalization removes recognized language tags (K/Kr/Kor/J/Jpn/Jp/E/En/Eng), tagged CD/disc information, version tags (v/ver/version + numeric version), and release tags (r/rel/release + date/number). Standalone sequel/part numbers are preserved.
- Trailing ` - subtitle` segments may be progressively removed only as fallback; fallback is accepted only when exactly one candidate exists in that system. Ambiguous candidates are skipped rather than guessed.
- Local destination metadata/media always uses the Local ROM filename even when the source MasterDB filename differs.
- Media tab should avoid horizontal/vertical scrolling: Cover ~68% left; Marquee/MixImage/Wheel share ~32% right; Screenshot full width below. Labels are overlays.
- Current GameList cursor highlight must remain visible even when the detail flyout auto-hides. Normal click after multi-select clears multi-select and selects only the clicked game; Ctrl-click remains the toggle mechanism.


## v0.4.0.21 additions
- ES-DE can be metadata-only: `rom_path` may be blank. The required path is the ES-DE root containing `gamelists/` and/or `downloaded_media/`.
- ES-DE system enumeration must be the union of `gamelists/*`, `downloaded_media/*`, and optional ROM folders, so metadata with no ROM files is still visible. Such entries are GameList `status="누락"` / Missing ROM.
- `config.validate_local_paths()` and scan validation special-case ES-DE so a blank ROM path is safe; other frontends still require ROM paths.
- Filename matching normalizes standalone Roman numerals I..XXX to Arabic 1..30 (e.g. VII == 7) after decoration removal. This is only for matching keys and must not alter stored filenames/titles.
- MasterDB Version semantics: Local -> MasterDB changed metadata creates a new Version; the newly created Version must become `default_version_id` so `latest` wins on MasterDB -> Local. Identical metadata is skipped.
- GameList normal click while multi-selected must clear both the Set and DOM visual state immediately, then select the clicked game alone. Ctrl/Meta-click toggles individual selection; Ctrl+A selects current filtered list.
- ES-DE Local add dialog: ES-DE root/gamelist/downloaded_media selector is required and shown before the optional ROM selector.

## v0.4.0.22 additions

- Local cache는 scan 완료 snapshot을 독립 배열로 보존해야 하며 MasterDB 전환으로 S.games가 교체되어도 영향을 받지 않아야 한다.
- ES-DE gamelist metadata-only 항목도 media index 대상이며, ROM 존재 여부와 media 존재 여부는 독립적으로 처리한다.


## v0.5 SQLite migration — session fixes (Claude.ai 리뷰, 반영 완료)

이 세션에서 실제 코드에 반영하고 테스트로 검증한 것들. 다른 AI/세션이 이어받을 때 참고:

1. **`database/sqlite_db.py`의 `replace_from_dict()` 재작성**: 예전엔 호출될 때마다
   `roms` 테이블 전체를 DELETE 후 재삽입했다. `roms.rom_id`가 AUTOINCREMENT라 재사용되지
   않고, `favorites`/`similar_group_members`/`game_list_set_roms`가 `rom_id ON DELETE
   CASCADE`이므로, **관련 없는 JSON 저장 한 번마다 그 세 native-only 테이블이 통째로
   비워지던 버그**가 있었다. 지금은 JSON에서 실제로 사라진 rom만 삭제하고,
   나머지는 `legacy_key` 기준 UPSERT로 `rom_id`를 보존한다. `game_list_sets`도 동일하게
   UPSERT로 바뀌었고, 소속(`game_list_set_roms`)은 이제 건드리지 않는다(부모 set이
   실제로 삭제될 때만 cascade로 같이 삭제됨 - 의도된 동작).
2. **`api.py`의 `_save_db()`에 `sync_sqlite` 옵션 추가**: `save_version_fields`,
   `clone_version`, `set_default_version`, `delete_version`, `save_media` 5개 지점은
   이미 타겟 SQLite write를 했으므로 `sync_sqlite=False`로 뒤이은 전체 재구축을 생략한다.
   Import/Export/Cleanup/CSV/배치삭제 등 아직 SQLite에 직접 안 쓰는 경로는
   `sync_sqlite=True`(기본값) 그대로 유지 - 이 경로들이 8단계(Import/Export 전환)에서
   네이티브 write로 바뀌기 전까진 계속 필요함.
3. **`tests/test_native_table_preservation.py` 신규 추가** (4개): rom_id 안정성,
   favorites/GameListSet 소속이 관련 없는 저장으로 사라지지 않는지, 실제 rom 삭제 시엔
   cascade가 정상 동작하는지 검증. `python3 -m unittest tests.test_native_table_preservation`
4. **`import_engine.py` — metadata 없는 소스의 media 유실 버그 수정**: `fields is None`일
   때 media를 읽기도 전에 `continue`하던 걸, media는 항상 읽고 병합하되 metadata/Version만
   건너뛰도록 수정(`has_metadata` 플래그 도입). "metadata와 media는 독립적으로
   동기화한다"는 기존 설계 원칙이 "metadata가 아예 없는 경우"엔 안 지켜지고 있었음.

### ⚠️ 이번에 새로 발견했고 아직 안 고친 것 (리스트업만, 미반영)
- ~~`_copy_media_to_masterdb`의 파일명 충돌~~ **[2026-09-01 갱신] 이 항목은 이후
  세션에서 "media는 ROM당 1세트, 항상 완전 교체" 정책이 최종 확정되면서(바로 아래
  "media 버전 관리 — 최종 확정"/"media 덮어쓰기 정책 — 반영 완료" 절 참고) 의미가
  달라졌다 - 여러 소스가 같은 ROM의 media를 서로 다른 시점에 가져오면 "마지막에
  들어온 것이 이긴다"가 의도된 동작이지, 버그가 아니다. 다만 **완전히 별개의
  진짜 원자성 버그**가 실제로 있었다: 기존엔 새 파일 복사 전에 기존 파일을 먼저
  지웠기 때문에, 소스가 깨져서 복사가 실패하면 기존 파일은 이미 사라졌는데 DB엔
  예전 경로가 남는 문제. `fix/sqlite-data-safety` 브랜치에서 "새 파일을 `.tmp`로
  전부 복사 성공시킨 뒤에만 기존 파일을 지우고 rename"하는 방식으로 수정 완료
  (아래 절 참고).

### Import/Export 명명 규칙 (버그 아님, 확정된 설계 — HANDOFF.md 6절에 상세 정리함)
GUI 라벨은 "지금 보고 있는 화면 기준" 상대 명명(Local 화면=Local이 주어, MasterDB
화면=MasterDB가 주어)이고, 내부 코드(`import_engine.py`/`export_engine.py`)는 항상
MasterDB 고정 기준이라 두 체계가 다르다. 사용자가 직접 확인 후 "둘 다 일관되니 통일
불필요"로 결론 냄 — 다음에 이 주제가 또 나오면 재논의하지 말고 HANDOFF.md 6절을 참고할 것.

### media 버전 관리 — 최종 확정 (2025-08-31 세션): "ROM당 1세트" 원칙 유지, video 예외도 없음
버전별 media 분리는 전체 포기. media는 video 포함 전부 ROM 단위 단일 관리 그대로 간다
(`MODULE_MAP.md` 원칙 그대로 유지). 여러 Local에서 같은 ROM의 media가 다르게 들어오는
문제(선착순 승자 결정 등)는 **아직 미해결 상태로 남아있음** — 이 세션에서 metadata
쪽만 결론이 나고 media 충돌 정책 자체는 다음 세션에서 계속 논의 필요.

### media 덮어쓰기 정책 — 반영 완료 (2025-08-31 세션)
`import_engine.py`의 media 병합 로직을 "기존 파일 있으면 유지"에서 **"항상 새로 들어온
소스로 덮어쓰기"**로 변경. SHA256 등 내용 비교 없이 무조건 덮어씀 — 비교하려면 기존
파일을 읽어야 해서(읽기+해시) 그냥 쓰기보다 I/O가 더 들기 때문에 비교 자체를 안 하기로
결정. 리스트형(screenshots/videos)도 "누적"이 아니라 "새 세트로 완전 교체"이고,
`_delete_existing_media_files()`로 이전 세트의 파일을 지워 고아 파일이 안 남게 함.
- `tests/test_engines.py`의 `TestSharedMediaPolicy`가 원래 "최초 1회만 저장, 이후
  안 건드림"을 검증하던 테스트였는데, 이 정책이 폐기되면서 **새 정책 기준으로 재작성함**
  (경로 문자열이 아니라 실제 파일 바이트 내용을 비교하도록 수정 - 안 그러면 목적지
  파일명이 재사용되는 케이스에서 내용이 바뀌어도 테스트가 통과해버림).
- 미디어를 버전별로 안 가져가기로 확정했으므로(ROM당 1세트 유지), 여러 Local 간 media
  충돌은 이제 전부 "마지막으로 import한 소스가 이긴다"로 단순하게 정리됨.

### metadata "채우기(fill)" 규칙 — 반영 완료 (2025-08-31 세션)
`db.py`에 `get_filled_fields(rom_entry)` 신규 추가: default 버전 기준으로 **빈 필드만**
다른 버전(오래된 순)에서 채운 합성 dict를 반환하는 **읽기 전용** 함수. 저장된 버전
데이터는 절대 안 건드림(쓰기 시점 승격 방식은 채택 안 함 — 여러 write 경로 동기화
필요 문제 때문에 폐기).
- 빈 문자열/공백만 있으면 "비어있음"으로 채움 대상.
- `.`만 들어있으면 "사용자가 의도적으로 비움"으로 보고 채우지도 않고, 다른 필드를
  채우는 소스로도 안 씀.
- tags(리스트)는 빈 리스트만 비어있음으로 취급, sentinel 개념 미적용.
- 적용 지점: `export_engine.py`(Local export 시 실제 파일에 쓰는 값), `api.py`의
  `get_game_detail`(detail 패널에 표시되는 default 버전의 fields만 교체, Ver
  Diff/버전 드롭다운의 나머지 버전들은 원본 그대로 유지).
- **의도적으로 안 바꾼 곳**: `get_default_fields`(원본, 안 채움)는 Dashboard 요약
  통계(`api.py:387`)/시스템별 통계(`api.py:1117`)/유사롬 후보 수집(`api.py:1346`)처럼
  10,000-ROM 규모로 순회하는 곳에 그대로 남겨둠 — 채우기 연산을 거기까지 넣으면
  Dashboard/유사롬 스캔이 매번 O(전체 ROM × 버전수) 연산이 되어 "10,000-ROM 풀스캔
  회피" 원칙과 충돌하기 때문. 신규 함수 필요한 곳만 콕 집어 교체함.
- 테스트: `tests/test_filled_fields.py` 7개 신규 (fallback/공백판정/sentinel/tags/
  export 통합 케이스).
- **알려진 사이드이펙트(아직 안 고침, 리스트업만)**: `get_game_detail`이 이제 default
  버전 자리에 "합성된" fields를 보여주므로, 사용자가 detail 패널에서 필드 하나만
  고쳐도 `save_version_fields`가 합성본 전체를 그대로 저장해버려서 **의도치 않게
  fallback으로 채워진 값이 그 버전에 영구히 승격**될 수 있음. 문제 삼을지는 사용자
  확인 필요.

## 8~11단계 착수 전 확정 사항 (2025-08-31 세션, Claude.ai → Claude Code 이관 직전)

8~11단계 진행 순서: **11(GameListSet 기반 다지기) → 8(Import/Export를 native SQLite write로
전환, 이때 GameListSet 멤버십/유사롬도 같이 native화) → 9(Compare) → 10(유사롬 SQLite
이전 완료 + 대표 지정 UI)**. 이유: 8번에서 JSON 직접수정→전체재구축 패턴을 걷어내는
김에 GameListSet 멤버십/유사롬도 같이 native로 설계해야 두 번 손 안 댐.

착수 전 발견한 문제와 결정:
- **유사롬은 지금 SQLite `similar_groups`/`similar_group_members`/`representative_rom_id`
  테이블과 전혀 연결 안 되어 있고, 실제로는 `self.db["similar_rom_groups"][system]`이라는
  완전히 별개의 JSON 키에 저장되고 있었음(`api.py`의 `start_find_similar_roms`). 게다가
  "유사롬 찾기"를 누를 때마다 재계산+덮어쓰기라 그룹에 고정 ID가 없어서 대표 지정을
  얹을 데가 없었음. → **SQLite `similar_groups` 테이블로 이전하기로 확정.**
- **GameListSet(구 Local) 멤버십(`game_list_set_roms`)에 실제로 값을 써넣는 코드가
  어디에도 없었고**, `target_capacity_bytes`는 스키마에만 있고 `config.py`의
  `new_local_entry()`엔 필드 자체가 없어서 v0.5 1번(용량 관리)도 사실상 미착수 상태였음.
  → **SQLite에 실제로 멤버십을 저장하기로 확정** (매번 파일시스템 재스캔 방식 대신).

**[2026-09-01] 8~11단계 전체 완료.** 순서대로 11(GameListSet 기반 다지기) → 8(Import/
Export native SQLite write, 그 과정에서 발견된 커밋 배치 성능 버그까지 수정) → 9(Compare
화면) → 10(유사롬 SQLite 이전 + 대표 지정 UI)까지 전부 구현/테스트/커밋 완료. 그 사이
사용자가 실사용 중 발견한 버그 3건(Import 성능 30배 저하, Media 저장 시 Title 오염,
Local 화면 msx/msx1 중복 표시)도 같이 조사해서 수정함 - 각각 아래 해당 섹션 참고.
다음 단계(v0.5의 나머지 항목, 또는 새 기능)는 아직 미정 - 사용자와 상의 후 결정할 것.

## 11단계 완료 — GameListSet 기반 다지기 (2026-08-31, Claude Code)

8~11단계 순서(11→8→9→10) 중 11번을 완료했다. 범위는 **저장소 레벨 프리미티브만** —
import/export 엔진에 실제로 배선하는 건 의도적으로 8단계로 미뤘다(엔진을 두 번 안
건드리기 위해, 위 "8~11단계 착수 전 확정 사항" 문단의 결정 그대로).

- **`config.py`의 `new_local_entry()`에 `target_capacity_bytes: None` 필드 추가.**
  이전엔 SQLite 스키마(`game_list_sets.target_capacity_bytes`)에만 있고 config 쪽엔
  필드 자체가 없어서 `database/sqlite_db.py`의 `replace_from_dict()`가 매번 NULL로
  동기화하고 있었음. 기존 config.json(필드 없는 old locals)도 `.get()` 기반이라
  마이그레이션 없이 그대로 호환됨.
- **`database/sqlite_db.py`에 `game_list_set_roms` 멤버십 네이티브 write 헬퍼 5개 추가**:
  `get_gamelistset_members(set_id)`, `add_gamelistset_members(set_id, legacy_keys)`,
  `remove_gamelistset_members(set_id, legacy_keys)`,
  `sync_gamelistset_membership(set_id, legacy_keys)`(scan 결과와 정확히 일치하도록
  add+remove를 한 번에 처리 — 8단계에서 scan/import 지점이 매번 이걸 호출하면 됨),
  `get_gamelistset_ids_for_rom(legacy_key)`(9단계 Compare에서 역방향 조회용으로 미리
  준비). 전부 legacy_key -> rom_id 해석에 실패하면(아직 MasterDB에 없는 ROM) 조용히
  skip한다 — 멤버십은 이미 MasterDB에 존재하는 ROM만 참조할 수 있음.
- **`tests/test_gamelistset_membership.py` 신규 8개**: add/idempotent/unknown-key-skip/
  remove/sync add+remove/sync-to-empty/역방향조회/관련없는 `replace_from_dict` 재저장에도
  멤버십이 살아남는지(`test_native_table_preservation.py`와 동일 계약).
- 전체 테스트 147개(신규 8개 포함) 전부 통과 확인
  (`python -m unittest tests.test_engines tests.test_api tests.test_native_table_preservation
  tests.test_gamelistset_membership tests.test_filled_fields tests.test_database_shadow
  tests.test_sqlite_native_read`).

**다음(8단계) 진행 시 참고**: 이제 `sync_gamelistset_membership()`이 준비되어 있으니,
`import_local_to_masterdb`/`export_masterdb_to_local`가 native write로 바뀔 때 ROM을
읽거나 쓴 직후 `self._sqlite.sync_gamelistset_membership(local_id, touched_legacy_keys)`
(또는 scan 결과 전체 legacy_key 집합)을 호출하도록 배선하면 됨. `add_local`/`delete_local`
쪽에서 `target_capacity_bytes`를 실제로 입력받는 UI는 아직 없음(범위 밖으로 확인, 별도
"용량 관리" 기능이 필요하면 그건 8~11단계와 별개로 다시 논의).

## 8단계 완료 — Import/Export를 native SQLite write로 전환 (2026-08-31, Claude Code)

11단계 다음으로 8단계를 완료했다. 범위는 확정대로 **Import/Export 흐름 + 그 안에서
GameListSet 멤버십 native화**까지만 — 유사롬(`similar_rom_groups`) native 전환은
의도적으로 손 안 댔다(아래 "범위에서 제외한 것" 참고, 10단계 몫으로 남김).

### 변경 내역
- **`import_engine.py`**: `import_local_to_masterdb()`에 옵션 `sqlite_repo` 파라미터 추가.
  넘겨지면 JSON dict 변경(`db["roms"][...]`)과 나란히 `sqlite_repo.ensure_rom()` /
  `insert_version()` / `set_media()`로 SQLite에도 직접 write한다 - 매 Import 후 10,000-ROM
  규모 `replace_from_dict()` 전체 재구축을 생략하기 위함.
  - `_merge_alias_entry()`가 `(target, did_merge)` 튜플을 반환하도록 변경. 레거시
    ES-DE alias 시스템명(`genesis`→`megadrive` 등, `config.ESDE_SYSTEM_ALIASES`) 병합이
    실제로 발생하면 `result["alias_merge_occurred"] = True`가 켜진다 - 이 rom은
    native mirror로 못 따라가는 구조 변경(키 이동/삭제)이 있었다는 신호.
  - Import 실행 끝에 **GameListSet 멤버십 동기화**: 이번 스캔에서 발견되고
    MasterDB에 실제로 존재하는 rom들의 legacy_key를 모아서, `target_roms=None`(전체
    Local Import)이면 `sqlite_repo.sync_gamelistset_membership()`(발견 안 된 rom은
    멤버십에서 제거), `target_roms` 지정(부분 Import)이면 `add_gamelistset_members()`
    (add-only, 건드리지 않은 rom의 기존 멤버십은 보존)를 호출.
- **`export_engine.py`**: `export_masterdb_to_local()`에 옵션 `sqlite_repo` 파라미터 추가.
  Export는 MasterDB 자체엔 안 쓰므로(Local 파일만 씀) rom/version/media native mirror는
  불필요 - 대신 실제로 MasterDB와 매칭된 rom들(conflict-skip이어도 매칭 자체는 됐으면
  포함)을 같은 add/sync 규칙으로 GameListSet 멤버십에 반영.
- **`api.py` 호출부 4곳** 수정 - 전부 `sqlite_repo=self._sqlite` 전달 + `_save_db()`를
  `sync_sqlite=not result.get("alias_merge_occurred", False)`로 호출(별칭 병합이
  없었으면 native mirror만 믿고 전체 재구축 생략, 있었으면 안전하게 전체 재동기화):
  `start_import_local_to_masterdb`, `import_local_to_masterdb`,
  `start_export_local_to_masterdb`(mode="metadata"/"metadata_roms" 분기), `export_to_local`.
  - **[드라이브바이 발견 버그, 같이 고침]** `start_import_local_to_masterdb`와
    `start_export_local_to_masterdb`(job/비동기 버전 둘 다)가 원래 `dbmod.save_db()`를
    **직접** 호출해서 `self._sqlite`를 아예 안 건드리고 있었다 - 즉 비동기 Import 후
    SQLite 프로젝션이 다음 무관한 전체 재동기화 전까지 계속 stale 상태로 남는 버그였음.
    이번에 전부 `self._save_db(sync_sqlite=...)`로 교체해서 고쳤다.
  - **[드라이브바이 발견 버그, 같이 고침]** `copy_masterdb_game_data`(Ctrl+C/Ctrl+V
    MasterDB 내 게임 복제)도 같은 부류로 `dbmod.save_db()` 직접 호출 → SQLite 갱신
    누락이었음. `self._save_db()`(기본 `sync_sqlite=True`, 이 경로는 대량 처리가
    아니라 굳이 native mirror까지 안 붙임)로 교체.
- **`database/sqlite_db.py`**: `add_gamelistset_members()`/`sync_gamelistset_membership()`에
  `_ensure_gamelistset(set_id)` 자가 보정 추가. **테스트 중 실전에서 재현된 버그**:
  `add_local()`은 `config.json`에만 쓰고 `_save_db()`를 절대 안 부르므로, 새로 등록한
  Local을 곧바로 Import하면 `game_list_sets`에 그 set_id 행이 아직 없어서
  `game_list_set_roms` insert가 FK 위반으로 죽었다(`tests.test_api` 전체가 이걸로
  실패했었음). 멤버십 insert 직전에 `INSERT OR IGNORE INTO game_list_sets(set_id, name)`로
  placeholder 행을 만들어두고, 나중에 `replace_from_dict()`가 진짜 name/paths/capacity로
  덮어쓰는(ON CONFLICT DO UPDATE) 방식으로 해결.

### 범위에서 제외한 것 (의도적)
- **유사롬(`similar_rom_groups`) native 전환은 안 함.** `api.py`의 `start_find_similar_roms`가
  여전히 `self.db["similar_rom_groups"][system]` JSON 키에만 저장한다 - 이건 10단계
  ("유사롬 SQLite 이전 완료 + 대표 지정 UI") 몫으로 명시적으로 남겨둠. 8단계 결정문의
  "이때 GameListSet 멤버십/유사롬도 같이 native화" 문구는 설계 방향 예고였을 뿐, 실제
  구현 범위는 사용자가 확정한 단계 제목("Import/Export를 native SQLite write로 전환")
  기준으로 좁혀서 진행했다. 10단계 진행 시 이 결정을 다시 확인할 것.
- **`cleanup_engine.py`/`csv_engine.py`/배치삭제**는 여전히 `sync_sqlite=True`(전체
  재구축) 경로 그대로 유지. "Import/Export" 타이틀 범위 밖으로 판단해 손 안 댐.
- Local 등록 시 `target_capacity_bytes`를 실제로 입력받는 UI는 여전히 없음(11단계 메모
  그대로 - 별도 "용량 관리" 기능 논의 필요).

### 테스트
- `tests/test_native_import_export.py` 신규 8개: native write가 `replace_from_dict()` 없이
  정확한지, 중복 Import가 새 Version을 안 만드는지, GameListSet 멤버십이 전체/부분
  Import·Export 양쪽에서 정확히 add/sync되는지, alias 병합이 flag를 켜는지.
- 전체 155개(기존 147 + 신규 8) 통과 확인:
  `python -m unittest tests.test_engines tests.test_api tests.test_native_table_preservation
  tests.test_gamelistset_membership tests.test_filled_fields tests.test_database_shadow
  tests.test_sqlite_native_read tests.test_native_import_export`

## 9단계 완료 — Compare 화면 (2026-09-01, Claude Code)

### 착수 전 사용자에게 확인받은 사양 (로컬 문서엔 없던 내용)
- 비교 모드: GameListSet(Local) 대 GameListSet, **그리고** MasterDB 대 GameListSet
  둘 다 - 화면에서 두 소스를 각각 드롭다운으로 선택(그 중 하나가 "MasterDB"일 수 있음).
- 비교 내용: **ROM 존재 여부만** (metadata 필드 값 자체를 보여주진 않음), 단 양쪽에
  다 있는데 metadata가 다르면 파일명 뒤에 `[d]` 표시.
- UI: Beyond Compare 스타일 2열 리스트. 파일명 기준 정렬, 같은 롬이면 같은 줄에
  나란히, 한쪽에만 있으면 그 쪽에만 표시. 행 선택 가능, `>`/`<` 버튼으로 반대쪽에 복사.
  파일명 옆에 title/releasedate 같은 간단 정보 표시.

### 구현
- **`compare_engine.py` 신규**: `compare_entries(left, right, system=None)` - 파일명
  정확 일치 우선, 실패 시 `utils.rom_match_keys()`로 정규화 후 **같은 시스템 내에서
  유일 후보일 때만** fallback 매칭(export_engine.py의 `_find_masterdb_rom`과 동일
  알고리즘을 임의 두 entry 목록에 쓸 수 있게 일반화 - 새 매칭 규칙을 발명하지 않고
  기존에 검증된 규칙 재사용). `collect_local_entries()`(Local 실제 metadata 필드까지
  읽음 - scan_local()의 GUI용 요약 dict는 developer/publisher/players가 빠져있어
  이걸 쓰면 진짜 차이가 없는데도 `[d]`가 잘못 뜸), `collect_masterdb_entries()`
  (`get_filled_fields()` 사용, Local Export가 실제로 쓰는 값과 동일 기준),
  `summarize_entry()`(GUI 표시용 + 복사 액션용 정확한 system/filename 포함 - fallback
  매칭 시 좌우 파일명이 다를 수 있어서 표시용 `row.file` 하나만 믿으면 안 됨).
- **`api.py`**: `list_compare_sources()`(MasterDB + 등록된 Local 전체),
  `compare_sources(source_a, source_b, system=None)`, `compare_copy_row(source_a,
  source_b, direction, source_system, source_filename)`. Local<->Local 직접 복사
  경로가 앱에 없으므로(HANDOFF.md §6 아키텍처) `compare_copy_row`는 항상 MasterDB를
  경유한다 - source가 Local이면 먼저 그 rom 하나만 `import_local_to_masterdb`(native
  SQLite write 사용), MasterDB에 실제 반영된 canonical system/filename을 다시 읽어서,
  target이 Local이면 그걸로 `export_masterdb_to_local` 호출.
  **[갱신, UX 리팩터 세션]** 위 문단은 더 이상 사실이 아니다 - `compare_copy_row`의
  양쪽이 다 Local(GameListSet)이면 이제 `export_engine.copy_local_to_local()`로
  ArchiveDB를 아예 거치지 않고 직접 복사한다(importer.read_metadata_fields/read_media
  + exporter.write_metadata_fields/write_media를 그대로 재사용, ArchiveDB JSON은
  안 읽고 안 씀 - ArchiveDB 미설정 상태에서도 동작). 한쪽이라도 ArchiveDB면 위
  문단 그대로(2-hop) 유지. 같이 진행된 관련 변경: `export_masterdb_to_local()`의
  `copy_rom=True`가 이제 대상에 아직 없는 ROM도 MasterDB 엔트리로부터 타겟을
  합성해서 복사하고(예전엔 대상에 이미 물리적으로 있어야만 후보가 됐음),
  Compare의 복사 버튼도 `#job-progress`를 재사용한 indeterminate 진행바를 보여준다.
- **`gui_web/`**: 사이드바 SERVER 섹션에 "Compare" 메뉴 추가, `#compare-view` 신규
  화면(좌/우 소스 드롭다운 + 검색 + 2열 리스트 + 행별 `>`/`<` 복사 버튼). `--list-*`
  CSS 토큰 재사용(GameList 카드와 동일하게 라이트=흰/다크=남색 자동 전환 - 하드코딩
  색상 아님, 처음에 실수로 흰색 하드코딩했다가 바로 고침). `icons.js`에 `chevronRight`
  아이콘 추가(기존엔 `chevronLeft`만 있었음).

### ⚠️ 이 세션에서 새로 발견하고 같이 고친 심각한 성능 버그 (8단계 native write 관련)
**`database/sqlite_db.py`의 `ensure_rom`/`insert_version`/`set_media` 등 native write
메서드가 호출마다 개별 `with self.conn:`으로 커밋하는데, SQLite 기본 설정(journal_mode
=DELETE, synchronous=FULL)에서는 커밋마다 실제 fsync가 강제된다.** import_engine.py의
Import 루프가 rom 하나당 이 메서드를 2~3번 호출하므로, **10,000-ROM Import 시 이
오버헤드만으로 사실상 응답 불가 수준**이었다(실측: 300개 rom x 3커밋 = **221.3초**,
rom당 737.8ms, 10,000개 투영치 **약 7,378초(약 2시간)**). Compare 9단계 테스트 도중
`test_export_metadata_only_mode_does_not_copy_rom` 테스트가 (원래 1초면 끝나던 게)
타임아웃 직전까지 걸리는 걸 보고 발견함.
**수정**: `SQLiteRepository.__init__`에 `PRAGMA journal_mode=WAL` + `PRAGMA
synchronous=NORMAL` 추가(SQLite 공식 권장 조합 - 내구성을 크게 해치지 않으면서 커밋
비용을 대폭 낮춤). 실측: 300 roms x 3커밋 = **221.3초 → 1.78초** (약 **124배** 개선),
10,000-ROM 투영치 약 **59초** 수준으로 떨어짐. 이 PRAGMA는 매번 새 연결마다 적용되므로
기존 DB 파일에도 자동 적용됨(스키마 마이그레이션 불필요, WAL은 SQLite가 알아서 처리).
- **WAL 전환의 부작용도 하나 발견해서 같이 고침**: WAL 모드는 `master.db` 옆에
  `master.db-wal`/`master.db-shm` 사이드카 파일을 만드는데, 기존 `backup_engine.py`의
  `create_backup()`이 `shutil.make_archive`로 MasterDB 디렉토리 전체를 무차별로
  zip에 담다가 `-shm`(공유 메모리 매핑 파일)에서 Windows 한정으로 `[Errno 22]
  Invalid argument`를 내며 실패했다(`test_backup_and_restore` 회귀로 발견).
  `create_backup()`을 `zipfile`로 직접 파일을 골라 담도록 바꾸고 `-wal`/`-shm`은
  제외, `api.py`의 `do_backup()`이 백업 직전에 `PRAGMA wal_checkpoint(TRUNCATE)`로
  커밋된 데이터를 전부 `master.db` 본체에 합쳐두므로 제외해도 데이터 유실이 없다.
  `restore_backup()`도 복원 후 `self._sqlite`를 닫고 새로 열도록 고쳐서, 복원으로
  파일이 통째로 바뀐 뒤에도 기존에 열려 있던(이제 stale한) connection을 계속 쓰는
  일이 없게 했다.
- **더 개선하고 싶다면(안 함, 리스트업만)**: rom 하나당 3번 커밋하는 것 자체를 묶어서
  "Import 배치 전체 1커밋"으로 바꾸면 이론상 몇 배 더 빨라질 수 있음. 지금은 WAL
  전환만으로 "치명적 병목" -> "허용 가능" 수준까지는 해결됐다고 판단해 거기까지는
  안 건드림. 10단계(유사롬 SQLite 이전)에서 유사롬 그룹도 대량 native write를 하게
  되므로, 그때 체감 속도가 여전히 아쉬우면 이 배치 커밋 최적화를 그때 같이 고려할 것.

### 테스트
- `tests/test_compare_engine.py` 신규 12개(순수 매칭/diff 로직 + 실제 scan/DB 통합).
- `tests/test_compare_api.py` 신규 9개(list_compare_sources/compare_sources/
  compare_copy_row 통합 - Local↔Local이 실제로 MasterDB를 경유하는지도 검증).
- 전체 197개(기존 155 + Compare 21 + 이하 조정) 전체 통과 확인 예정 -
  `python -m unittest tests.test_engines tests.test_api tests.test_native_table_preservation
  tests.test_gamelistset_membership tests.test_filled_fields tests.test_database_shadow
  tests.test_sqlite_native_read tests.test_native_import_export tests.test_compare_engine
  tests.test_compare_api`

## 9단계 이후 사용자 실사용 리포트 2건 수정 (2026-09-01, Claude Code)

10단계 시작 전 사용자가 실제 앱에서 재현한 문제 2건. 둘 다 원인 파악 + 수정 완료.

### 1) Import(Local -> Export to MasterDB) 성능 - "기존 대비 30배 이상 느림"
WAL 전환(9단계 메모 참고)만으론 부족했다. **진짜 원인은 rom 하나당 native write
호출(ensure_rom/insert_version/set_media - media 타입 수만큼 각각)이 전부 개별
커밋이었던 것.** WAL이어도 커밋 수 자체가 10,000-ROM 규모에서 수만 건에 달해 여전히
느렸다.
- **수정**: `database/sqlite_db.py`에 `batch()` 컨텍스트매니저 + `_batch_depth`
  카운터 추가. 개별 write 메서드(`ensure_rom`/`insert_version`/`update_version_fields`/
  `set_default_version`/`delete_version`/`set_media`/`delete_rom`/
  `add_gamelistset_members`/`remove_gamelistset_members`/`sync_gamelistset_membership`)를
  전부 `with self.conn:`(호출마다 커밋) 대신 `self._commit()`(batch 밖이면 즉시 커밋,
  batch 안이면 생략)을 쓰도록 리팩터. `import_engine.py`의 `import_local_to_masterdb()`가
  함수 전체를 `sqlite_repo.batch()`로 감싸서(루프를 다시 들여쓰지 않고
  `batch_cm.__enter__()`/`__exit__()`를 처음/끝에 수동 호출 - 이 함수는 항상
  정상적으로 `return result`까지 도달하고 도중에 예외를 밖으로 던지지 않으므로 안전함)
  전체 Import 1회당 커밋이 1건으로 줄었다.
- **실측(1,000 rom, 전부 cover media 포함, 실제 파일 I/O 포함)**: sqlite_repo 없음
  (JSON-only, 8단계 이전과 동등한 베이스라인) 7.95초 vs batch 적용 후 native SQLite
  write 포함 7.73초 - **사실상 동일**(SQLite 오버헤드가 오차범위 안으로 사라짐).
  10,000-ROM 투영치 약 77초. `dbmod.save_db()`(JSON 저장, 10,000 rom)는 0.15초,
  `replace_from_dict()`(전체 재동기화, alias 병합 시에만 탐)도 10,000 rom에
  0.15~0.65초로 문제 없음을 별도 확인.
- **진단 로그 추가**: `api.py`의 `start_import_local_to_masterdb`/
  `import_local_to_masterdb`/`start_export_local_to_masterdb`(metadata 모드)에
  `IMPORT_TIMING` 이벤트 추가 - `engine_seconds`(scan+metadata읽기+media복사+native
  SQLite write 구간) / `save_db_seconds`(JSON 저장 + 필요시 전체 SQLite 재구축 구간)를
  분리 기록. `logs/retro_manager_diagnostic.log`에서 확인 가능(GUI의
  `get_diagnostic_log_path()`로 경로 조회 가능). **다음에 또 느려지면 이 로그부터
  볼 것** - 어느 구간이 범인인지 바로 나옴.
- ⚠️ **사용자 재확인 필요**: 이 수정은 로컬 벤치마크로 검증했고(engine 레벨 - SQLite
  오버헤드가 사실상 0으로 사라짐을 확인), 실제 pywebview 앱에서 "Export to MasterDB"를
  다시 눌러 체감 속도가 정상으로 돌아왔는지는 사용자가 확인해야 한다. 만약 여전히
  느리다면 `IMPORT_TIMING` 로그의 `engine_seconds`/`save_db_seconds` 값을 알려달라고
  요청할 것 - 그러면 다음 병목을 바로 짚을 수 있다.
- "JSON과 SQLite를 동시 처리해서 느린 거면 SQLite만 켜서 테스트해보고 싶다"는 요청은
  받았지만 실행하지 않음 - JSON 저장을 완전히 끄는 건 아직 여러 읽기 경로가
  `self.db`(JSON 파생 in-memory dict)에 의존하고 있어 위험도가 높은 별도 아키텍처
  작업이라 판단(스코프 밖). 대신 위 벤치마크로 "SQLite 자체는 병목이 아니다"를 이미
  수치로 확인했으므로, 이 토글은 불필요해졌다고 판단 - 그래도 여전히 느리다면 그때
  다시 논의.

### 2) Media 탭에서 드래그 후 저장 시 Title이 엉뚱한 값으로 바뀌는 버그
**원인**: `gui_web/app.js`의 `handleSaveDetail()`이 저장할 metadata 필드를 모듈
전역(게임이 바뀌어도 리셋 안 되는) `fieldRefs`(Metadata 탭이 렌더링될 때만 채워지는
DOM `<input>` 참조 모음)에서 직접 읽고 있었다. Media 탭에 머무른 채(자동/수동으로)
다른 게임을 열면 Metadata 탭이 그 사이 한 번도 안 그려지므로 `fieldRefs`가 리셋되지
않고 **이전에 열려 있던 다른 게임의 낡은 title 등이 그대로 남아있다가**, 지금 게임의
Media만 바꾸고 저장을 눌러도 그 낡은 값으로 metadata를 덮어써버렸다. Metadata 탭으로
갔다가 다시 저장하면 그제서야 정상 값으로 고쳐지는 것도 이 때문(Metadata 탭 렌더링이
`fieldRefs`를 현재 게임 값으로 다시 채움).
- **수정**: `handleSaveDetail()`이 `fieldRefs` 대신 `detailState.draftFields`를 쓰도록
  변경. `draftFields`는 게임을 열 때마다(`renderDetailFromResponse`) 새로 만들어지고
  탭 전환 시(`captureMetadataDraft()`)마다 최신 입력값이 반영되므로 게임 간 오염이
  없다. Metadata 탭에 있는 상태로 곧장 저장을 누르는 경우(탭 전환 이벤트가 안 일어난
  경우)를 위해 저장 직전에도 `captureMetadataDraft()`를 한 번 더 호출해 방금 친
  키입력까지 확실히 반영되게 함.
- ⚠️ **실기 검증 필요**: pywebview 환경에서 (1) 게임A Metadata 탭 확인 -> Media
  탭으로 전환 -> 다른 게임B 열기(같은 Local/System 내 클릭) -> B의 Media 탭에서
  이미지 드래그 후 저장 -> B의 Title이 그대로 유지되는지, (2) 원래 리포트하신
  시나리오(드래그 후 저장 -> Title 확인 -> 재저장 불필요한지) 둘 다 사용자가 Windows
  실행 파일에서 직접 확인해야 한다(이 sandbox는 pywebview 자체가 설치 불가 - 계속
  반복되는 근본적 한계, HANDOFF.md 참고).

## 3) Local 화면에서 msx/msx1(alias 시스템)이 같은 게임을 2줄로 보여주는 버그 (2026-09-01)

**근본 원인은 데이터였지 코드 로직 결함이 아니었다** - `E:\Backup\ES-DE_TEST\_ES-DE_ODIN2\gamelists\msx\gamelist.xml`을
사용자가 직접 공유해서 확인한 결과, msx 폴더의 ROM 디렉토리(`roms/msx/`)만 비어있을 뿐
`gamelists/msx/gamelist.xml`엔 실제로 1288줄짜리 진짜 데이터가 있었고, "Hyper Sports 1/2/3"
항목이 `gamelists/msx1/gamelist.xml`과 **글자 하나 안 틀리고 완전히 동일**했다(아마 예전
스크래핑이 msx/msx1 양쪽에 다 기록됨). MasterDB는 이미 정상이었다 - Import가
`config.canonical_system()`으로 msx1→msx를 매핑하고 내용이 같으면 duplicate로 스킵하기
때문(사용자가 직접 MasterDB 확인 후 "정상"이라고 확인). **버그는 Local 자체 GameList
화면(`api.py`의 `scan_local()`)에 있었다** - 이 경로는 raw 시스템 폴더를 그대로 순회할
뿐 canonical 병합을 전혀 안 해서, Import에 이미 있던 같은 로직이 Local 표시 쪽엔 빠져
있었던 것.

**수정 v1**: `api.py`의 `scan_local()`에서 raw_entries를 다 모은 직후, `cfgmod.canonical_system()`
기준으로 (canonical_system, filename) 키가 겹치는 항목들을 하나로 합치는 패스를 추가.
**표시 전용 병합**이다 - `importers.scan.scan_local()`(import/export 엔진이 쓰는 원본
스캔 함수)은 전혀 안 건드렸으므로 실제 Import/Export 동작에는 영향 없음(이미 정상
동작 중이었으므로).

**수정 v2(같은 세션, 사용자 실기 테스트로 즉시 발견)**: v1의 승자 선택 기준(ROM 매칭 ->
metadata 존재 여부)이 **media 존재 여부를 전혀 안 봐서**, 사용자가 공유해준 실제 폴더
(`E:\Backup\ES-DE_TEST\_ES-DE_ODIN2` - roms 폴더 자체가 없는 metadata 백업본이라 둘 다
Missing ROM, `downloaded_media\msx1\`엔 covers 등 실제 media가 있고 `downloaded_media\msx\`엔
media가 하나도 없음)에서 metadata만 보고 알파벳순으로 먼저인 "msx"가 승자가 되어 버려서
**media가 통째로 사라져 보이는 재발**이 있었다. 승자 선택 기준을 "ROM 매칭 여부 ->
**실제 media 존재 여부**(`importer.has_media()`로 가볍게 확인) -> metadata 존재 여부"
순으로 수정. 사용자의 정확한 폴더 구조(ROM 없음, msx1만 media 있음)를 그대로 재현한
테스트(`test_winner_prefers_the_side_with_actual_media_over_metadata_only`)로 검증.
- 파일명이 다르면(진짜 다른 게임이면) 절대 안 합쳐지는지도 테스트로 확인.

**수정 v3(같은 세션, 사용자가 바로 다음 케이스를 미리 지적)**: "승자 하나만 쓰는" 방식은
두 alias 폴더가 **서로 다른 media 타입을 나눠 갖고 있으면**(예: msx엔 covers만, msx1엔
screenshots만) 여전히 한쪽만 반영되는 한계가 있었음(v2 커밋 직후 사용자가 "이런 경우도
있을 것 같다"고 미리 질문). **승자는 표시용 system/filename/metadata 기준으로만 고르고,
media는 그룹 내 모든 alt 위치(승자 아닌 나머지 alias 폴더들)를 전부 읽어서 "승자 쪽에
이미 있는 타입은 유지, 없는 타입만 채우기"로 합집합 병합**하도록 `api.py`의 `scan_local()`
media-읽기 패스를 수정(`media_alt_locations` dict로 승자 entry -> alt system 목록을
전달). covers만 있는 쪽 + 나머지 4종만 있는 쪽을 합쳐 5종 전부(`완료` 상태)가 되는지
테스트(`test_media_split_across_alias_folders_is_unioned`)로 검증.
- 테스트: `tests/test_scan_alias_dedup.py` 총 5개(사용자 실제 데이터 재현 2건 + media
  타입 분산 합집합 1건 포함). 전체 191개(기존 176 + 신규 5 + 10단계 10) 통과.
- 이 기능은 총 3라운드(중복 행 -> 승자가 media 없는 쪽으로 잘못 뽑힘 -> media 타입
  분산)로 실사용 피드백을 받으며 다듬어졌다. 앞으로 이 근처를 또 건드릴 일이 있으면
  "완전 동일한 파일명 gamelist 중복"뿐 아니라 "ROM 없음", "media 타입이 폴더별로
  갈려있음" 케이스까지 항상 같이 고려할 것 - 실사용 ES-DE 백업이 이런 식으로 지저분하게
  섞여 있는 경우가 드물지 않은 것으로 보임.

## 10단계 완료 — 유사롬 SQLite 이전 + 대표 지정 UI (2026-09-01, Claude Code)

8~11단계 마지막 단계. 유사롬(Comparable ROM) 저장을 `self.db["similar_rom_groups"]`
JSON 키에서 이미 스키마엔 있었지만 안 쓰이고 있던 SQLite `similar_groups`/
`similar_group_members` 테이블로 완전히 이전하고, `representative_rom_id` 컬럼
위에 대표 지정 UI를 얹었다.

### 구현
- **`database/sqlite_db.py`**: `save_similar_groups(system, groups)`(해당 system의
  기존 그룹을 지우고 새로 삽입 - 재탐색은 재분석이므로 이전 group_id/대표 지정은
  초기화되는 게 의도된 설계, 멤버 2명 미만인 그룹은 저장 안 함, 존재하지 않는
  legacy_key는 조용히 skip), `get_similar_groups(system)`(group_id/members/
  representative 반환), `set_similar_group_representative(group_id, legacy_key)`
  (legacy_key=None이면 해제, 그 그룹의 멤버가 아니면 실패).
  **score/pairs(유사도 breakdown)는 SQLite에 저장하지 않기로 함** - 스키마에 pairs용
  테이블이 없었고, 그룹 멤버십+대표 지정이라는 핵심 기능과 무관한 일회성 표시 정보라
  판단(스코프 밖 결정, 기록만 해둠). 그 결과 재조회 시 "최고 유사도 점수" 표시는
  빠짐(탐색 직후 1회성 job 결과에만 여전히 존재).
- **`api.py`**: `start_find_similar_roms`가 이제 `self._sqlite.save_similar_groups()`를
  쓰고(`dbmod.save_db()` JSON 직접 호출 안 함 - 이 기능은 JSON 사이드를 아예 안 씀),
  `get_similar_rom_groups`가 `self._sqlite.get_similar_groups()`를 읽어 enrich.
  신규 `set_similar_group_representative(group_id, rom_key)` 추가.
- **`gui_web/`**: 유사롬 결과 모달(`openSimilarRomResults`)의 각 멤버 행에 별(star)
  버튼 추가 - 누르면 대표 지정/해제, 대표인 항목은 강조(굵게+별 하이라이트). 클릭 시
  모달을 통째로 다시 그림(별도 partial re-render 없이 `openSimilarRomResults()` 재호출 -
  그룹 수가 많지 않은 화면이라 단순함 우선).
- **의도적으로 손 안 댄 것**: 대표 지정이 뭔가를 자동으로 하지는 않음(예: 나머지
  멤버 자동 삭제/병합 같은 기능 없음) - "대표 지정 UI"까지가 이번 스코프이고, 그
  대표를 실제로 어떻게 활용할지(예: Compare/Export 시 대표만 쓰기 등)는 다음에
  필요해지면 별도로 설계할 것.

### 테스트
- `tests/test_similar_rom_sqlite.py` 신규 8개(저장소 레벨: 저장/조회/대표 지정·해제/
  비멤버 거부/재탐색 시 초기화/system별 격리).
- `tests/test_api.py`에 신규 2개(`set_similar_group_representative`가 새 Api
  인스턴스에서도 유지되는지, 비멤버 거부가 API 레벨에서도 동작하는지) + 기존 유사롬
  테스트 3개는 무수정으로 계속 통과(반환 형태가 상위호환으로 확장됨 - `pairs` 필드는
  job의 즉시 반환값에는 그대로 남아있고, 저장/재조회 경로에서만 빠짐).
- 전체 189개(기존 179 + 신규 10) 통과.

## Compare 화면 UI 재설계 — 좌우 분리형 (2026-09-01, Claude Code)

9단계에서 만든 Compare 화면(행마다 좌/우 쌍을 나란히 놓고 중앙에 `>`/`<` 버튼)을 사용자
요청으로 완전히 재설계함. 사용자가 ASCII 와이어프레임까지 직접 그려줘서 그대로 구현:

- **좌우 리스트 분리형**: 행마다 있던 중앙 `>`/`<` 버튼 제거. 왼쪽/오른쪽이 완전히
  독립된 스크롤 리스트로 나란히 배치(`.compare-lists` flex, 각각 `.compare-list-panel`).
  같은 파일이 양쪽에 다 있어도 두 리스트에 각각 표시된다(짝을 맞춰 한 줄에 나란히
  놓지 않음) - 매칭된 항목은 `matched` 클래스로 옅은 배경만 줘서 구분.
- **한 줄 통합 출력**: 각 행이 FILE / TITLE / DESCRIPTION 3컬럼을 grid로 한 줄에 표시
  (`compare_engine.py`의 `summarize_entry()`에 `desc` 필드 추가 - 기존엔 title/releasedate만
  있었음).
- **GameList 스타일 헤더**: 사용자가 "리스트는 Gamelist처럼 head별로 구분되어야 한다"고
  추가 요청 - 각 리스트 패널 상단에 sticky `FILE/TITLE/DESCRIPTION` 헤더 행 추가
  (`.compare-list-header`/`.compare-header-cell`, GameList의 `.grid-header-cell`과 같은
  토큰/스타일 재사용).
- **하단 복사 버튼**: 행별 버튼 대신 화면 하단 중앙에 `COPY >`/`< COPY` 버튼 2개만
  배치. 각 리스트에서 행을 클릭하면 그 쪽의 "선택"이 되고(다시 클릭하면 해제),
  `COPY >`는 왼쪽 선택 항목을 오른쪽으로, `< COPY`는 오른쪽 선택 항목을 왼쪽으로
  복사(기존 `compare_copy_row` API 그대로 재사용 - 백엔드는 안 건드림, JS 렌더링만
  전면 수정).
- 상태: `S.compare.selectedFile`(공용 1개) -> `selectedLeft`/`selectedRight`(양쪽
  독립)로 변경.
- 백엔드(`compare_engine.py`/`api.py`)는 `desc` 필드 추가 말고는 무수정 - 기존
  `compare_sources()`가 반환하는 `{left, right, matched, diff}` 행 배열을 JS에서
  좌/우 두 배열로 나눠 그리는 것뿐이라 서버 쪽 로직 변경 필요 없었음. 기존 backend
  테스트 21개(compare_engine 12 + compare_api 9) 전부 무수정으로 계속 통과.

## v0.4.0.24 planned/implemented UI and system rules
- ES-DE `msx1` and `msx` use canonical MasterDB system `msx`; raw Local system remains available for frontend routing/UI.
- `CLEANUP` is an ES-DE housekeeping directory and must be excluded from scan, navigation, Dashboard, import/export, and management.
- Metadata detail header: remove search button and PINNED text badge; retain actual pin icon control. Show Game System between filename and Metadata/Media tabs.
- Metadata description/fields must survive switching Metadata <-> Media without saving first; maintain an in-memory draft while the detail panel is open.
- Media tiles accept local image files and browser-dragged image URLs; URL images are downloaded by the Python bridge and saved as MasterDB media.
- GameList top bar no longer contains `+ Local`; search area can use the freed space.
- Navigation Game Systems use distinct per-system representative glyphs instead of one generic gamepad icon.

## SQLite 데이터 안전성 리뷰 대응 (2026-09-01, Claude Code, 브랜치 `fix/sqlite-data-safety`)

**다른 AI가 v0.4.1.0(당시 최신 main)까지의 SQLite 마이그레이션 작업을 리뷰했고,
그 결과를 사용자가 그대로 붙여넣어 전달했다. 리뷰가 지적한 항목을 하나씩 코드에서
직접 확인(grep+재현)한 뒤, 실제로 맞는 것만 순서대로 고쳤다.** 이 절은 그 리뷰의
각 항목이 실제로 맞았는지, 어떻게 고쳤는지, 커밋이 어디 있는지를 기록한다. 이
브랜치는 `main`(8f9dd77 = v0.4.1.0)에서 새로 판 것이고 **이 글을 쓰는 시점까지
아직 push 안 됨** - GUI 개선 작업을 하던 다른 브랜치(`claude/retrogamanager-
github-review-vngai9`)와는 무관한 별도 브랜치다 (이유: 리뷰 대상이 기능 버그라
"main에서 작업하는 게 맞다"고 사용자가 명시적으로 정함).

### 리뷰 항목별 실제 검증 결과와 조치

| 우선순위 | 항목 | 리뷰 주장 검증 | 조치 |
|---|---|---|---|
| P0 | Import의 SQLite batch transaction이 수동 `__enter__`/`__exit__` | **정확함** (grep으로 즉시 확인) | `with`로 전환. 예외 시 `_batch_depth`가 원복 안 되면 **프로세스 재시작 전까지 모든 SQLite 쓰기가 영구히 안 됨**을 재현 테스트로 증명 후 수정 |
| P0 | Media 복사가 원자적이지 않음 (기존 삭제 후 복사) | 리뷰가 든 "다른 Local 간 충돌" 예시는 **부정확**(media는 ROM 단위 dest_dir라 실제로 안 겹침) - 하지만 **"삭제 후 복사 실패 시 파일 유실"이라는 진짜 원자성 문제는 실재** | `.tmp` staging + 성공 확인 후 rename으로 수정. 부수적으로 글롭 패턴이 `.tmp` 파일 자체를 삭제하는 버그도 하나 더 발견/수정 |
| P0 | Background job이 직렬화 안 됨 | **정확함** - `_run_job`이 잠금 전혀 없이 스레드만 띄움 | `mutates_db=True` 옵션 추가, Import/Export/유사롬 탐색이 전체 구간 `_db_lock` 보유하도록 수정. `delete_masterdb_games()`도 같이 잠금 |
| P0/P1 | Compare COPY가 실패해도 항상 성공 반환 | **정확함** - `export_masterdb_to_local()` 반환값을 아예 버림 | 반환값 검사 후 실패 사유별 에러 메시지 반환, 성공 시 `{"exported": N}` |
| P1 | SimilarGroup `representative_rom_id`에 FK 없음 | **정확함** | `ON DELETE SET NULL` FK 추가 (신규 DB부터 적용 - 기존 master.db는 마이그레이션 안 됨, 이 프로젝트가 아직 스키마 마이그레이션 프레임워크가 없는 v0.x라는 전제와 동일선상) |
| P1 | Compare가 msx/msx1 alias 처리 안 함 | **정확함** | `collect_local_entries`가 `canonical_system()`으로 변환한 값을 매칭용 `system`에 쓰고, raw 값은 `raw_system`으로 별도 보존(compare_copy_row가 Import 호출 시 필요) |
| P1 | Compare exact-match가 O(N²) | **정확함** | `(system, filename) -> [index]` dict로 O(1) 조회. 4000×2000 스케일 테스트 0.05초 |
| P1 | Backup과 mutation job 동시 실행 | **이미 해결되어 있었음** - `do_backup`/`restore_backup`은 원래도 `_db_lock`을 잡고 있었고, 위 job 직렬화 수정으로 자동으로 상호 배제됨 | 새 코드 없이 회귀 테스트만 추가해서 확정 |

### 검증 방법론 (다음에 비슷한 외부 리뷰를 받으면 참고)
리뷰 내용을 그대로 믿고 고치지 않았다 - **각 항목을 grep/코드 읽기로 먼저
재현/확인**한 뒤에만 손댔다. 그 결과 리뷰의 세부 근거 하나(media 충돌의 구체적
메커니즘)는 실제로 부정확했지만, 결론("원자성 문제가 있다")은 다른 이유로
맞았다 - 이런 경우 리뷰의 진단을 그대로 옮기지 않고 실제 코드에서 발견한 진짜
원인으로 고쳤다. 모든 수정은: (1) 버그 재현 테스트를 먼저 작성해서 실패를 확인,
(2) 최소 변경으로 수정, (3) 전체 테스트 스위트로 회귀 없음 확인, 순서로 진행했다.

### P0 작업 중 우연히 발견한 별도 버그 → PR #1 리뷰(2차)에서 다시 지적됨 → 수정 완료
Import batch 수정을 검증하는 테스트를 짜다가, **JSON `self.db`(순수 Python dict)는
SQLite와 달리 트랜잭션/롤백 개념이 전혀 없다**는 게 명확히 드러났다. Import 도중
예외가 나면 SQLite 쪽은 정확히 rollback되지만, `self.db`는 이미 mutate된 상태로
메모리에 남고, 이후 무관한 `_save_db()` 호출이 그 stale `self.db`를 JSON/SQLite에
다시 저장하면 "rollback했던 데이터가 되살아나는" 결과로 이어질 수 있었다.

PR #1을 올린 뒤 다른 AI의 2차 리뷰가 이 문제를 다시 정확히 지적하며(자체적으로
발견한 게 아니라 이 memory.md의 기록을 근거로 지적한 것으로 보임) merge 전
최우선으로 고칠 것을 권고 - `Api._db_rollback_guard()`(contextmanager)를 추가해서
고쳤다. `self.db["roms"]`를 import 시작 전에 deepcopy해뒀다가 예외 시 그대로
복원한다(전체 `self.db`가 아니라 import가 실제로 건드리는 `"roms"` 키만 - 다른
설정 값들은 import가 손대지 않으므로). `start_import_local_to_masterdb`,
`import_local_to_masterdb`(API 메서드), `compare_copy_row`의 내부 import 호출,
3곳 전부에 적용. 회귀 테스트(`DbRollbackGuardTests`)로 "실패 후 `self.db["roms"]`가
빈 상태로 남는지" + "재시도가 처음부터 정상적으로 끝까지 성공하는지"를 확인.

전체 rom 개수가 많을수록 매 import마다 deepcopy 비용이 들지만(수만 ROM 규모),
데이터 유실 위험을 없애는 게 우선이라고 판단했다. 리뷰가 장기적으로 제안한
"working_db 분리 + 성공시에만 스왑" 구조나 "SQLite를 authoritative source로"는
더 큰 리팩터라 이번엔 하지 않음 - 지금 고친 deepcopy 방식으로 정확성 문제 자체는
해소됐다고 판단.

### 커밋 목록 (브랜치 `fix/sqlite-data-safety`, base `main`@8f9dd77)
1. `fix: use with for import's SQLite batch transaction (P0)`
2. `fix: make per-ROM media copy atomic, never delete before copy succeeds (P0)`
3. `fix: serialize background jobs and deletes that mutate the shared SQLite connection (P0)`
4. `fix: Compare's COPY reports real success/failure instead of always ok (P0/P1)`
5. `fix: add missing FK on similar_groups.representative_rom_id (P1)`
6. `fix: Compare uses canonical system so msx/msx1-style aliases actually match (P1)`
7. `perf: index exact-filename matches in Compare instead of O(N*M) scan (P1)`
8. `test: verify backup/mutating-job concurrency is already prevented (P1)`
9. `docs: document SQLite data-safety review response in memory.md (P2)`
10. `fix: roll back self.db when a mid-import exception occurs (P0, PR #1 review)`
11. `fix: delete DB record before removing media, not after (P1)`

전체 테스트: 204개 통과 (base 191 + 신규 13). PR #1로 push/PR 생성 완료
(https://github.com/moning-1664/RetroGameManager/pull/1), 10번 커밋은 PR #1의
2차 리뷰 대응으로 추가됨. 11번(delete 순서 수정)은 PR #1이 이미 main에
merge된 뒤 브랜치에 추가로 쌓인 로컬 커밋으로, 이번(2026-09-02) 세션에서
main에 별도 merge 커밋으로 반영했다.

### 2차 리뷰 (다른 AI, 위 8개 커밋 적용 후 상태를 다시 봄) 대응
사용자가 또 다른 AI의 리뷰 의견(SQLite를 authoritative로 확정하자는 아키텍처
제안 포함)을 전달했다. 이번에도 항목별로 직접 코드에서 재검증했다.

- **아키텍처 제안 자체**: `database/sqlite_db.py` 상단 docstring에 이미
  "JSON remains the compatibility/write source for this transition"라고
  명시돼 있고, Favorites/GameListSet 멤버십/SimilarGroup은 이미 JSON에 전혀
  안 남고 SQLite에만 있는 native-only 데이터다. 즉 프로젝트는 이미 이 방향
  (JSON -> SQLite 단계적 전환)으로 v0.5 8~11단계를 밟아온 중이었다 - 리뷰가
  "지금 당장 뒤집자"는 투로 말한 건 과전제였고, 스키마 마이그레이션
  프레임워크가 없는 v0.x 단계에서는 지금의 점진적 전환이 더 안전하다고
  판단해 큰 리팩터는 하지 않기로 함.
- P0(self.db 롤백), P1(FK 미소급), P2(`_db_lock` 범위)는 위 표/문단에 이미
  기록된 내용과 동일한 재확인이었다 - 새 조치 없음.
- P1 "Media 여러 파일 rename이 개별적" - 정확하지만 media type 단위로는 이미
  원자적(커밋 2 참고)이고 type 간 실패해도 기존 값이 보존되므로 실사용
  위험도는 낮다고 재평가, 착수 안 함.
- **P1 "Delete 작업의 JSON/SQLite/filesystem 정합성" - 이번에 처음 나온
  지적이자 실제로 갭이 있었다.** `delete_masterdb_games()`가 media
  디렉토리를 먼저 `shutil.rmtree`로 지우고 그 다음에 SQLite `delete_rom()`을
  시도했음 - 이게 실패하면(`continue`) DB entry(JSON+SQLite)는 그대로
  남는데 media만 이미 사라진, DB가 존재하지 않는 파일을 가리키는 상태가 될
  수 있었다. 커밋 11에서 순서를 "DB(SQLite) 삭제 확정 -> JSON 삭제 -> media
  삭제"로 뒤집어 고쳤다 - 최악의 경우도 이제 "고아 media 디렉토리"(용량
  낭비)일 뿐 dangling 참조는 생기지 않는다. 회귀 테스트로
  `_sqlite.delete_rom`을 실패하도록 monkeypatch해서 media/DB entry가 둘 다
  그대로 남는지 검증.

### 남은 것 (리뷰의 P1/P2, 착수 안 함 - merge 차단 사유 아님)
- Media 여러 파일(screenshots/videos) 교체 중 일부만 성공하고 일부 실패하면
  이미 교체된 파일은 그대로 남는 문제(디렉터리 단위 staging+rollback 필요 - 지금은
  파일 하나 단위로만 atomic).
- SimilarGroup FK는 신규 DB부터만 적용됨 - 기존 master.db는 스키마 마이그레이션
  프레임워크가 없어 별도 migration 없이는 반영 안 됨.
- `_db_lock` 범위가 media I/O까지 포함해서 다소 넓음(DB 트랜잭션 lock과 job
  serialization을 분리하면 더 좋음) - 지금 당장 문제는 아님.
- 실제 10,000 ROM 규모 벤치마크 (기존 "1,000 ROM 7.73초" 실측을 10,000으로
  extrapolation한 값만 있고 실측 없음).
- 위에 적은 `self.db` JSON 쪽 트랜잭션/롤백 부재 문제 → 수정 완료(위 참고).
- Delete 작업의 JSON/SQLite/filesystem 정합성 → 커밋 11로 수정 완료(위 2차 리뷰
  대응 참고). Media 여러 type 간 cross-type 원자성 부재는 여전히 남아있음(개별
  type은 원자적이라 위험도 낮다고 판단해 보류).

이 브랜치는 이후 `main`에 PR #1로 merge되었다 (아래 GUI 시리즈보다 나중에 main에
반영됨 - 두 브랜치가 8f9dd77 이후 완전히 별개로 진행되다가 이 merge 커밋에서 처음
합쳐짐. `api.py`/`import_engine.py`에 충돌이 있었고 두 브랜치의 변경을 모두 보존하는
방향으로 수동 해결함 - `_db_lock`/`_db_rollback_guard`로 감싸는 구조는 유지하고, 그
안에서 GUI 쪽이 추가한 favorite 자동제외/`selected_media_types` 필터 로직을 그대로
살렸다).

## 0.4.1.x GUI 개선 시리즈 — 계획, 구현, 위험도별 버전 재배치 (2026-09-01, Claude Code)

**다른 AI가 이 항목을 리뷰할 것을 전제로 작성함.** 브랜치
`claude/retrogamanager-github-review-vngai9`에서 작업했고, `main`에 merge되어 push
완료되었다. git 태그 `v0.4.1.1`~`v0.4.1.5`가 각 버전 경계에 있고, `pre-version-restructure-backup`
태그는 재배치 전 원본 커밋(구현 순서 그대로였던 상태)을 가리키는 안전장치로 남아있다.

### 배경 / 요청 사항
사용자가 "0.4.1.x는 기존 GUI 개선이 목적"이라며 9개 항목을 요청했고(백엔드 신규
배선은 최소화, 이미 있는 기능/스키마를 최대한 재활용하는 방향으로 검토 후 진행하기로
합의):
1. Local(GameListSet) 롬/메타데이터 추가·삭제를 사이드바로 드래그앤드롭 + 목표
   용량 대시보드
2. 사이드바 라벨/순서 변경(Dashboard/ArchiveDB/GameListSet), Settings 톱니바퀴 위치
3. (2에 포함) GameListSet 목표 용량 대시보드
4. Settings 체계화 (7개 카테고리)
5. **드래그앤드롭 롬/메타데이터 이동 + 전송 선택 모달** — 사용자가 맨 뒤로 미룸, 미착수
6. F2 파일명 변경(연쇄 media 이동) + Ctrl+C/V(metadata+media 복사)
7. **우클릭 컨텍스트 메뉴(롬만/메타만/전체 삭제)** — 사용자가 맨 뒤로 미룸, 미착수
8. 유사롬 묶어보기 + 대표 자동 지정
9. Favorite 필드 + 삭제 시 자동 제외

**5번과 7번은 사용자 요청으로 이번 사이클에서 완전히 제외했다 (미착수).** 다음
세션이 이어받을 때 우선순위 1순위로 볼 것.

### 구현된 것 (파일별 핵심 변경)

**단위 1 — 프로그레스 바 스타일**
`gui_web/app.js`의 `showJobProgress`/`updateJobProgress`를 채움 막대에서
`[||||||][      ] (55%)` 브라켓 스타일(모노스페이스 텍스트 기반)로 교체. 아래 줄에
현재 처리 중인 파일명 표시. 순수 렌더링 변경, 백엔드 무관.

**단위 2 — 사이드바 재구성**
`renderSidebar()`에서 라벨만 교체: `MasterDB` → `ArchiveDB`, `Local` → `GameListSet`.
**내부 view key(`"masterdb"`, `"local-<id>"`)와 `import_engine.py`/`export_engine.py`/
`api.py`의 함수명은 전혀 안 바꿈** — HANDOFF.md 6절에 있는 "GUI 라벨은 화면 기준
상대 명명, 내부 함수는 항상 MasterDB 고정 기준" 원칙과 충돌하지 않도록 의도적으로
GUI 레이어만 건드림. 순서도 Dashboard→ArchiveDB→GameListSet으로 변경. Settings
톱니바퀴를 상단 브랜드 영역에서 사이드바 최하단(`.nav-spacer` 뒤, flex로 바닥에
고정)으로 이동.

**단위 3 — GameListSet 목표 용량 대시보드**
`config.py`의 Local 엔트리에 `target_capacity_bytes` 필드가 **스키마엔 이미
있었지만 GUI에서 설정할 방법이 없어서 항상 null이었던 것**을 발견하고 재활용.
`api.py`에 `set_local_target_capacity(local_id, bytes)` 신규 (config.json에 값
하나만 기록, 스키마 변경 없음). Dashboard에 GameListSet별 사용량 게이지 + 슬라이더/
숫자입력 조절 패널 신규, 상단 SOURCE 바 카드에도 목표 설정 시 소형 게이지 표시.

**단위 4 — Settings 체계화**
`renderSettings()`를 General/GameListSet/Metadata/Media/ArchiveDB/Interface/Advanced
7개 카테고리로 전면 재구성. **원칙: 실제로 백엔드 로직이 있는 설정만 조작 가능하게
두고, 없는 건 "Coming soon" 배지가 붙은 비활성 행으로 명시** (거짓으로 동작하는
척하는 설정 UI를 만들지 않기 위함 - Cache/Debug/Performance/Scan Interval/Title
Normalization/Media Naming 등 다수). 새로 실제 동작하게 만든 설정: Startup Page,
Confirmations(끄면 `showConfirm()`이 확인창 없이 즉시 `onConfirm()` 실행),
Logging(켜면 `api-client.js`의 `RMApi._call()`이 모든 브릿지 호출을 `console.debug`로
남김), 기본 목록 보기(List/Preview). `config.py`의 `ui.*`에 `startup_page`/
`confirm_destructive_actions`/`logging_enabled`/`default_list_view` 필드 추가,
`api.py`에 `save_ui_settings()` 신규, `get_settings()`가 이 필드들을 같이 반환하도록
확장(기존 `test_settings_roundtrip` 등 하위 호환 확인됨). Export/Import 기본값
체크박스를 MetaData(1)/Media(세부 7종 grid)/Rom(1) 그룹 레이아웃으로 통일
(`renderTransferCheckboxGroups()` 헬퍼로 분리 — **5번(드래그앤드롭 전송 모달)이
나중에 구현될 때 이 레이아웃을 그대로 재사용할 의도로 미리 분리해둔 것**, 5번
자체는 아직 없음).

**단위 6 — F2 파일명 변경 (이번 시리즈에서 유일하게 실제 파일시스템을 조작)**
`db.py`/`api.py`에 `rename_masterdb_rom(rom_key, new_filename)` 신규:
- ROM 실물 파일(`<masterdb_root>/roms/<system>/<filename>`)과 media 폴더
  (`<masterdb_root>/media/<system>/<rom_stem>/`)를 새 이름으로 함께 rename.
- media 딕셔너리에 저장된 경로 문자열도 새 stem으로 재작성(`_remap()` 헬퍼 -
  media 파일 자체의 이름은 `covers.png`처럼 media_type 고정이라 안 바뀌고, 부모
  폴더 stem만 바뀌면 됨 — 이게 이 함수를 상대적으로 단순하게 만든 핵심 전제).
- **대상 파일명이 이미 존재하면(디스크 또는 DB 어느 쪽이든) 아무 것도 바꾸지 않고
  즉시 취소** — rename 전에 전부 검사 후 실행하는 방식이라 부분 적용으로 인한
  데이터 불일치가 없음.
- `db["roms"]`의 dict key(=rom_key)도 옮겨야 해서 `self.db["roms"][new_key] = entry;
  del self.db["roms"][rom_key]` 후 `self._save_db()`(SQLite 전체 재동기화 포함).
`app.js`: F2 keydown(ArchiveDB, 단일 선택일 때만) → 이름 입력 모달(`buildRenameModal`,
Enter 확정/Escape 취소) → 백엔드 에러(이름 충돌)는 모달 안에 inline으로 표시하고
아무 것도 반영 안 함. Ctrl+C/V(metadata+media 복사, ArchiveDB 한정)는 **이미
구현되어 있던 기존 기능**임을 확인만 함 — 요청하신 "media+메타데이터 복사(default
기준)"와 정확히 일치해서 손대지 않았음.

**단위 8 — 유사롬 묶어보기 + 대표 자동 지정**
게임 리스트 상단에 "유사롬 묶기" 체크박스(ArchiveDB + 특정 system 선택 시에만
노출, 기존 "유사롬 찾기"/"결과 보기" 버튼과 같은 조건). 켜면
`getSortedFilteredGames()`가 캐시된 그룹 정보로 대표 1개만 남기고 나머지 멤버를
필터링, 대표 행에 `+N` 뱃지. `api.py`의 `start_find_similar_roms()`가 그룹을 새로
저장한 직후 **대표를 자동으로 지정**하도록 변경 — 신규
`_auto_pick_similar_representative(member_keys)`: favorite → default 버전 metadata
필드 채움 개수 → description 길이 → media 총 용량, 각 단계에서 동률이면 다음 단계로
좁혀가고 끝까지 동률이면 romKey 사전순으로 확정(항상 결정적). 결과 모달에서 별표로
수동 지정하면 언제든 덮어씀(기존 `set_similar_group_representative` 그대로 사용).

**단위 9 — Favorite 필드 + 삭제 시 자동 제외**
`database/sqlite_db.py`의 스키마에 **이미 예약만 되어 있고 read/write 메서드가
전혀 없던 `favorites` 테이블**(`rom_id INTEGER PRIMARY KEY REFERENCES roms(rom_id)
ON DELETE CASCADE`)을 실제로 쓰기 시작함 - `is_favorite()`/`set_favorite()`/
`list_favorite_keys()` 신규. **의도적으로 JSON(`self.db`)에는 저장하지 않는
native-only 플래그**: `_save_db()`의 `replace_from_dict()`가 "실제로 사라진 ROM만
DELETE, 나머지는 rom_id 유지"하는 최적화를 이미 갖고 있어서(memory.md의 10단계
항목 및 `sqlite_db.py` 주석 참고), favorite가 매 JSON 저장마다 사라지지 않는다.
`api.py`: `set_rom_favorite()` 신규, `list_masterdb_games()`가 `favorite` 필드를
같이 반환, `delete_masterdb_games()`가 **삭제 대상에서 favorite인 rom_key를 먼저
걸러내고**(`favoriteSkipped` 카운트 반환) 나머지만 처리. `app.js`: 게임 리스트/
Preview 카드에 별 아이콘(클릭 또는 선택 후 Space로 토글, 다중선택 시 "전부 켜져
있으면 전부 끄고 아니면 전부 켠다" 방식 일괄 토글), "즐겨찾기만 보기" 필터, Delete
삭제 시 자동 제외된 개수를 토스트로 안내.

### Playwright UI 테스트 인프라 (신규 도입)
`api-client.js`가 `window.pywebview`가 없으면 자동으로 내장 mock 모드로 폴백하는
기존 구조를 이용해, **실제 pywebview/Windows 없이도** headless Chromium(Playwright)
으로 진짜 클릭/드래그/키보드 이벤트를 흘려서 프론트엔드 로직을 검증할 수 있게 했다.
`playwright.config.js`(이 sandbox에 미리 설치된 Chromium 빌드 번호가 최신
`@playwright/test`가 기대하는 것과 달라서 `launchOptions.executablePath`로
직접 지정해야 했음 - `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`),
`tests_ui/*.spec.js` 4개 파일(설정/대시보드, F2+Ctrl+C/V, 유사롬 묶기, favorite),
총 30개 테스트. `npm run test:ui`로 실행. **한계**: 네이티브 폴더 대화상자, 실제
파일시스템 드래그, WebView2 렌더링 버그(HANDOFF.md에 기록된 "Local 추가 시 화면
사라짐" 등)는 이 방식으로 재현 불가 - 여전히 Windows 실기 확인이 필요함.

### 버전 재배치 — 위험도 낮은 것부터 0.4.1.1~0.4.1.5로 분리
원래 구현 순서(1→2→3→4→6→8→9)대로 한 브랜치에 쭉 커밋했었는데, 사용자가 "위험도
낮은 것부터 순서대로 버전을 나눠서 반영"을 요청해서 **`git reset --hard`로 base
커밋(`8f9dd77`, 즉 v0.4.1.0)까지 되돌린 뒤 `git cherry-pick`으로 커밋을
재배치**했다(전부 unpushed 상태였기 때문에 안전하게 가능했음 - 이미 push된
히스토리였다면 이 방법 대신 `git revert`/새 커밋으로 처리했을 것).

최종 버전 매핑:
- **v0.4.1.1**(낮음): 단위 1+2. 데이터를 전혀 안 건드리는 렌더링/라벨 변경만.
- **v0.4.1.2**(중간): 단위 3. config.json 필드 하나.
- **v0.4.1.3**(중간): 단위 4 + Playwright 인프라 최초 도입.
- **v0.4.1.4**(중간): 단위 8+9. **같은 버전으로 묶은 이유**: 8의 favorite tier가
  9가 만드는 SQLite `favorites` 테이블을 참조하도록 최종 구현되어 있어서, 분리
  배포하면 이득 없이 cherry-pick 충돌(같은 함수의 같은 줄을 양쪽이 수정)만
  인위적으로 만들 뿐이었음.
- **v0.4.1.5**(높음): 단위 6. **이 시리즈에서 유일하게 실제 파일 rename이 있는 변경.**

각 버전 경계마다 `git tag`를 남겼고(`v0.4.1.1`~`v0.4.1.5`), `HANDOFF.md`
"12. [0.4.1.x] GUI 개선 - 위험도 단계별 롤아웃" 절에 요청 항목별 위험도 분류표,
버전별 상태, **롤백 절차**(`git diff <이전태그> <의심버전태그>`로 원인 좁히기,
문제 있으면 `git revert` 또는 `git reset --hard <이전태그>`)를 정리해뒀다.
`CHANGELOG.md`에도 각 버전별 상세 변경 로그가 있다.

**⚠️ 재배치 중 발견한 세그폴트 버그 (중요 - 커밋 재배치 작업 시 일반적으로 유의할
점)**: cherry-pick 재배치 도중, 단위 8의 테스트 2개
(`test_auto_pick_similar_representative_prefers_favorite`/`..._falls_back_to_
description_length`)가 호출하는 `_wait_job()` 헬퍼가 **원래 단위 6(F2) 커밋에서
정의됐던 것**이라는 암묵적 의존성을 처음엔 놓쳤다. 그 상태로는 헬퍼가 없어서
`tests/test_api.py` 실행이 **Python 프로세스 자체가 죽는 세그폴트**를 냈다
(백그라운드 job 스레드가 끝나기도 전에 `tearDown()`이 `Api.close()`를 호출하면서
SQLite C 확장과 스레드가 경합한 것으로 추정 - `_wait_job()`이 있으면 job 완료를
기다린 뒤 tearDown이 실행되니 문제가 안 됨). `_wait_job()` 정의를 단위 8이 필요로
하는 시점(v0.4.1.4)으로 옮겨서 해결. **교훈: 커밋을 재배치/cherry-pick 할 때는
"코드 diff에는 안 보이지만 다른 커밋에 정의가 있는 테스트 헬퍼" 같은 암묵적
의존성을 놓치기 쉽다. 각 버전 경계에서 반드시 전체 테스트 스위트를 돌려서 조용한
실패(테스트 개수가 예상과 다름)나 최악의 경우(프로세스 자체가 죽음)가 없는지
확인해야 한다.** 최종적으로 `git diff pre-version-restructure-backup HEAD`로
검증한 결과, 문서/버전 파일을 제외한 실제 코드는 원래 구현과 **기능적으로 100%
동일**(함수 정의 순서 차이만 있음)함을 확인했다.

### 로고 반영 (버전 번호와 무관한 순수 UI 변경, 마지막 커밋)
사용자가 만든 "THE RETRO CABINET" 로고 이미지(플러스 D패드+두 버튼 컨트롤러 아이콘
+ "Personal Retro game collection" 태그라인)를 참고해서, 사이드바 좌측 상단
브랜드 영역("Retro Metadata" 플레이스홀더 텍스트였음)을 교체했다. `app.js`에
`BRAND_LOGO_SVG` 상수로 손으로 그린 컨트롤러 마크(stroke 기반, 기존 아이콘 세트와
동일한 방식이라 `--accent` 색을 그대로 물려받음 - 코드 squiggle + 둥근 사각 몸체 +
D패드 + 버튼 2개)를 추가하고, `renderSidebar()`의 brand 블록을 "THE"(작게) /
"RETRO CABINET"(굵게) 2줄 워드마크 + "Personal Retro Game Collection" 태그라인
(truncate) + 버전 표시로 재구성. 224px 사이드바 폭에 맞게 폰트 크기를 축소했고,
headless 스크린샷으로 실제 렌더링을 확인한 뒤 반영(`.brand-icon`을 34x27px로
살짝 넓힘, `.brand-title-row`를 column 방향으로 변경 등 `style.css`도 같이 수정).
CSS/마크업 변경만 있고 상태/API에는 영향 없음.

### 최종 검증 상태 (이 세션 종료 시점)
- 백엔드: `python3 -m unittest tests.test_engines tests.test_api` → **110개 통과**
  (신규: rename_masterdb_rom 3개, favorite 4개, auto-pick tier 2개 - 나머지는
  기존 101개 유지).
- UI: `npx playwright test` → **30개 통과** (`npm run test:ui`).
- 커밋 14개가 `claude/retrogamanager-github-review-vngai9` 브랜치에 있었고, `main`에
  merge되어 push 완료됨. 전체 목록은 `git log --oneline 8f9dd77..0756897`로,
  `git tag -l "v0.4.1.*"`로 버전 경계를 확인할 것.
- 다음 우선순위: 5번(드래그앤드롭 전송 모달 - 단위 4에서 만든
  `renderTransferCheckboxGroups()` 재사용 가능), 7번(우클릭 컨텍스트 메뉴 삭제 -
  백엔드 `delete_masterdb_games(rom_keys, delete_metadata, delete_rom)`가 이미
  옵션별 삭제를 지원하므로 프론트만 만들면 됨).

## Compare 화면 리뷰 대응 — P1 5건 + P2 1건 (2026-09-02, Claude Code, 브랜치 `feature/gamelist-ux-refresh`)

다른 AI 리뷰가 지적한 Compare 화면 항목 6개(P1 4개, P2 2개) 중 실제로 미구현이던
5개를 고쳤다. 나머지 2개(항목 4 "진입 경로 기억", 항목 5 "Ctrl+A 후 Esc는 선택
해제")는 이미 이 브랜치에 구현돼 있었다(`S.compare.returnView` / `exitCompare()`,
Esc 키다운 분기) - 리뷰 시점 기준 최신 코드가 아니었던 것으로 보임, 코드 변경 없음.

- **항목 1(P1) 같은 소스를 양쪽에 선택 가능**: `sourceTitleDropdown()`이 반대편
  `sourceA`/`sourceB`와 같은 소스를 메뉴에서 그냥 보여주기만 했다. `otherId`를
  계산해 그 항목만 `disabled` + `.dropdown-menu button:disabled` 스타일로 막고
  클릭 리스너 자체를 안 붙인다.
- **항목 2(P1) 소스 변경 후 System 필터 무효화**: `loadCompareRows()`가 새
  `c.rows`를 받은 뒤, `S.selectedSystem`이 그 안에 없으면 `"all"`로 되돌린다.
  이전엔 "표시할 항목이 없습니다"만 뜨고 원인(필터가 죽은 시스템을 가리킴)을 알
  방법이 없었다.
- **항목 3(P1) ≠가 정보 표시일 뿐**: `centerCell()`의 diff 분기를 `≠` 텍스트 대신
  `<`/`≠`/`>` 3요소 구조로 바꿨다 - 기본은 `≠`만 보이고, `:hover`로 양옆
  `compare-center-diff-btn`(chevronLeft/Right)이 나타나 눌린 방향으로
  `copySingleCompareRow()`를 호출한다. ≠ 자체는 클릭 불가(요청대로).
- **항목 6(P2) Ctrl+A가 항상 양쪽 다 선택**: 클릭 즉시 `renderCompare()`가 행
  DOM을 다시 그려 실제 DOM 포커스가 사라지므로, DOM `:focus` 대신
  `S.compare.lastActiveSide`(handleCompareRowClick이 클릭마다 갱신)로 "마지막으로
  다루던 쪽"을 추적한다. Ctrl+A는 그 쪽만 전체 선택, 반대쪽은 건드리지 않는다.
  아직 아무 쪽도 다룬 적 없으면(`null`) 왼쪽 기본.
- **항목 8(P2) SOURCE 카드 비교 버튼 아이콘이 chevronDown(▼)이라 의미 불명확**:
  `icons.js`에 `arrowLeftRight`(⇄) 추가, `compareEntryBtn()`이 이걸 쓰도록 교체.
  텍스트 라벨("Compare")까지 넣는 안은 카드가 인라인 pill 형태로 폭이 좁아
  레이아웃 재설계가 필요해서 이번엔 보류 - 아이콘 교체만으로 핵심 지적(▼의 의미
  불명확)은 해소된다고 판단.

항목 1/2/3/6에 대한 회귀 테스트를 `tests_ui/compare.spec.js`에 4개 추가했다.
테스트에 필요해서 `gui_web/api-client.js`의 mock 소스 목록에 `l2`("Local
2")를 추가했다(snes가 전혀 없는 genesis 전용 소스) - 기존 `masterdb`/`l1` 조합
mock 응답은 그대로 두고, `compare_sources` 목업이 `l2`가 끼면 diff:true인
genesis 행을 반환하도록 분기했다. `list_locals` 목업에 항목이 하나 늘어난 것이
다른 스펙에 영향 없는지 확인함(`Local 1`을 `exact: true`로 찾는 다른 스펙과
충돌 없음).

**검증**: `npx playwright test tests_ui/compare.spec.js` → 10개 전체 통과(기존 6
+ 신규 4). 전체 UI 스위트도 돌려 회귀 없음을 확인했다 - `tests_ui/favorite.spec.js`
의 "즐겨찾기한 게임은 다중 삭제 대상에서 제외" 테스트 1개가 타임아웃으로
실패하지만, 이 브랜치를 건드리기 전(stash 상태)에서도 동일하게 실패해 이번
변경과 무관한 기존 문제로 확인했다 - 손대지 않음.

이 세션은 `main`이 아니라 origin에만 있던 `feature/gamelist-ux-refresh` 브랜치를
로컬로 새로 체크아웃해서 진행했다 - 아직 `main`에 merge되지 않은 브랜치이므로,
리뷰의 다른 항목(SOURCE 카드 UX, GameList 리프레시 등)이나 이번에 고친 5건 모두
main에는 반영되어 있지 않다.

## [P0 버그] alias 병합 시 SQLite 재동기화 조건이 반대로 뒤집혀 있었음 (2026-09-02, Claude Code)

**사용자 실사용 리포트**: "Compare에서 복사한 뒤 ArchiveDB로 들어갔는데 목록엔
아무것도 안 뜨는데 전체 개수는 3029로 정상으로 뜬다." — 목록(SQLite 기반)과
총 개수(JSON 기반)가 서로 다른 소스를 읽는 데서 오는 전형적인 SQLite/JSON
desync 증상이라 판단하고 코드를 추적했다.

**원인**: `api.py`에 `alias_merge_occurred` 이후 `_save_db()`를 호출하는 4곳
(`start_import_local_to_masterdb`, `import_local_to_masterdb`,
`start_export_to_local`(metadata 모드), `_compare_copy_one` - Compare 복사 경로)
전부가 다음과 같이 `not`이 반대로 붙어 있었다:
```python
self._save_db(sync_sqlite=not result.get("alias_merge_occurred", False))
```
`import_engine.py`의 `import_local_to_masterdb()` 문서화된 계약은 "alias
병합(예: msx1→msx, genesis→megadrive 같은 레거시 시스템명 정규화)이 일어난
ROM은 native targeted SQLite write를 안 하니, 호출자가 **반드시** 전체
`replace_from_dict()`로 재동기화해야 한다"인데, 코드는 정확히 그 경우에만
재동기화를 **건너뛰고** 있었다(바로 위 주석조차 올바른 의도를 설명하는데 코드만
반대였다). 결과: alias 병합이 있었던 회차의 ROM이 `self.db`(JSON, 항상 정상
저장됨)에는 들어가지만 `self._sqlite`에는 반영 안 됨 → `list_masterdb_games()`는
SQLite만 읽으므로 그 ROM들이 안 보이거나(또는 옛 alias 키 항목이 유령처럼 남고)
→ `get_masterdb_info()`의 romCount는 JSON 기준이라 정상 값을 보고하는 모순이
발생. Compare에서 alias 시스템(예: msx/msx1)의 ROM을 ArchiveDB로 복사하는
경우가 정확히 이 경로(`_compare_copy_one`)를 탄다.

**수정**: 4곳 전부 `sync_sqlite=bool(result.get("alias_merge_occurred", False))`로
(부정 제거) 고쳤다. 회귀 테스트 `tests/test_api.py::AliasMergeSqliteResyncTests`
추가 - `not`을 다시 붙인 버전으로 실제로 fail하는 것까지 확인했다(레거시 alias 키
`genesis|Sonic.zip`를 미리 심어두고 `megadrive` Local에서 import하면
`alias_merge_occurred=True`가 되는데, 버그가 있으면 `list_masterdb_games()`가
새 canonical 키 대신 옛 alias 키를 그대로 반환했다).

**사용자에게 필요한 조치**: 이미 이 버그를 겪은 기존 설치는 `self.db`(JSON, 항상
정확했음)와 `self._sqlite`가 어긋난 상태로 남아있을 수 있다 - **앱을
재시작하면** `_load_db_if_configured()`가 시작 시 항상 무조건
`self._sqlite.replace_from_dict(self.db, ...)`로 전체 재구축하므로 별도
"복구" 기능 없이 즉시 정상화된다. 코드 수정만으로는 이미 떠 있는 프로세스의
SQLite 상태를 소급 수정하지 못한다는 점을 안내할 것.

**검증**: `python -m unittest discover -s tests -p "test_*.py"` → 233개 전체 통과
(신규 1개 포함).

## 리뷰 피드백 9건 중 즉시 적용분 (2026-09-02, Claude Code, 브랜치 `feature/gamelist-ux-refresh`)

사용자 + 다른 AI 리뷰(교차검증)로 들어온 9개 항목 중 원인이 명확하고 범위가 작은
6개를 먼저 반영했다. 나머지 3개(스캔 progress 3-phase, SHA256, Export "기존
Metadata 보존" 필드 병합)는 설계 결정이 필요해 다음 라운드로 미룸.

1. **[P0] Compare metadata-only 항목 TITLE/DESCRIPTION 안 보임** - `compare_engine.py`
   `collect_local_entries()`가 `scan_local()`이 채우는 키 `"_fields"`를 `"fields"`로
   잘못 읽고 있었다(오타). `m.get("_fields") or m.get("fields")`로 수정 + 회귀 테스트.
2. **[신규] Compare에서 ROM 실물 없는 항목 파일명 빨간색** - entry에 `rom_matched`
   불리언을 새로 꿰었다: Local 쪽은 `scan_result`에 이미 있던 정보를 그대로 쓰고,
   MasterDB 쪽은 `collect_masterdb_entries(masterdb_root=...)`를 넘기면
   `dbmod.rom_storage_path(...).exists()`로 실제 파일 존재를 확인한다(안 넘기면
   기존 테스트 하위호환을 위해 항상 True). `summarize_entry()`가 `romMatched`로
   camelCase 변환해 GUI에 넘기고, `.compare-row-file.missing-rom { color:
   var(--danger) }`로 표시(diff [d] 표시와 동시에 있어도 danger가 이기도록 selector
   순서/specificity 조정).
3. **Favorite 토글 체감 지연** - `toggleGameFavorite()`가 `await api.setRomFavorite()`가
   끝날 때까지 별 아이콘 갱신을 기다리고, 끝난 뒤엔 `renderListArea()`로 리스트
   전체를 다시 그렸다. 클릭 즉시 `applyFavoriteVisual()`로 별 아이콘만 patch(다중선택
   patch와 같은 패턴)하고, 저장은 백그라운드로 진행해 실패 시에만 되돌린다.
   "즐겨찾기만 보기" 필터가 켜져 있을 때만(행 자체가 나타나거나 사라져야 하므로)
   전체를 다시 그린다.
4. **MetaData/Media 패널 폭 15% 축소** - `--panel-min/--panel-pref/--panel-max`를
   280/340/420px → 250/290/360px로. identity-grid가 좁아져 타이트해 보일 수 있어
   실제 화면에서 확인 요청함(Playwright 스크린샷 재현이 mock 모드 타이밍 이슈로
   막혀 시각 검증은 못 함).
5. **시작 화면이 Dashboard로 뜸** - `S.view` JS 기본값은 이미 "masterdb"였지만,
   `config.py`/`api.py`의 `startup_page` 기본값이 "dashboard"라 `init()`이 그걸로
   덮어썼다. 셋 다(`config.py` 기본 dict, `api.py`의 `get_settings()` fallback,
   `save_ui_settings()`의 invalid-value fallback) "archivedb"로 변경.
6. **GameListSet 추가 직후 빨간색 → 스캔 끝나면 정상 색** - `gamelistBarIcon()`이
   `S.scanningLocalId`를 전혀 안 봐서 스캔 상태가 색에 반영되지 않았다. 스캔 중이면
   최우선으로 `var(--danger)` + pulse 애니메이션(정적인 "오류" 상태와 구분).
   `ensureLocalScanned()`가 Dashboard에서 백그라운드로 불릴 때도(그 Local이
   "현재 화면"이 아니어도) 사이드바가 최신 스캔 상태를 반영하도록 시작/성공/실패
   세 지점 모두에 `renderSidebar()` 호출을 추가했다(예전엔 `isCurrentView()`일
   때만 `renderListArea()`를 불러서, 그 경우 사이드바 자체가 갱신 안 됐다).
7. **Settings 톱니바퀴 위치** - 사이드바 하단(`.nav-item-settings`, 텍스트 라벨 있음)에서
   브랜드 바로 아래(`.sidebar-settings-btn`, 아이콘만)로 이동. 관련 Playwright
   테스트(`settings-and-dashboard.spec.js`, `rename-and-copy.spec.js`)의 선택자와
   "맨 아래에 있다" 단언을 새 위치/구조에 맞게 다시 씀.

**다음 라운드로 미룬 3개 (설계 논의 필요)**:
- 스캔 "스캔 중입니다" 왔다갔다 - `scan_local()`의 `_bulk_metadata`/`_bulk_media`에는
  progress_cb가 아예 없고 ROM 순회 구간에만 있다(다른 AI가 정확히 짚음). 3-phase
  가중 progress로 갈지, 단순 min()으로 갈지 결정 필요.
- SHA256 표시 - 계산 자체가 없음(신규 기능). 캐시 전략(size+mtime+sha256) 필요.
- Export "기존 Metadata 보존" - `import_local_to_masterdb()`는 이미
  `has_metadata=False`일 때 version을 안 만들고 media만 동기화해 기존 metadata를
  보존한다(그 케이스는 이미 됨). 진짜 빠진 건 "일부 필드만 채워진 경우"의 필드
  단위 병합(현재는 다르면 새 version을 만들어 기존 default를 통째로 대체) - 그리고
  정확히 어느 방향(Local→ArchiveDB "Export to ArchiveDB" vs ArchiveDB→Local "Export
  to GameListSet") 다이얼로그를 말하는지 확인 필요.

**검증**: 백엔드 `python -m unittest discover -s tests` → 236개 통과(신규 4개
포함 - compare_engine 3개 + Ctrl+A 관련 없음, 이전 세션 alias 회귀 1개 포함).
UI `npx playwright test` → 45/46 통과, 실패 1건은 `favorite.spec.js`의 무관한
기존 문제(이 세션 이전부터 있었음, 확인 완료 - 이번 변경과 무관).
