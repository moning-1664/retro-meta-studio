# MODULE_MAP.md — 파일 구조 가이드

문제가 생겼을 때 **전체 코드를 다시 붙여넣지 않고, 아래 표에서 관련 파일만 찾아
해당 파일만 업로드/다운로드하여 디버깅**할 수 있도록 정리한 지도입니다.

## 원칙
- 파일 하나는 하나의 책임만 갖는다 (예: "Pegasus에서 읽기"와 "Pegasus에 쓰기"는 다른 파일).
- GUI는 "화면 단위"로 쪼개져 있다 (`gui/mixins/*.py`). 특정 화면에 문제가 있으면 해당 파일만 보면 된다.
- 순수 로직(엔진)과 GUI는 완전히 분리되어 있다. 로직 버그는 `gui/`를 열 필요가 없다.

## 계층 구조

```
retro_manager/
├── version.py              # 버전 정보 (semver)
├── config.py                # 설정 로드/저장, Local 등록, 시스템명 매핑
├── db.py                    # MasterDB 스키마, Version/Core/중복판정/상태판정 로직
├── utils.py                  # 타이틀 정규화, 한글판별, GUI 보조(Undo/Redo, 스크롤)
├── main.py                   # 실행 진입점
│
├── importers/                # "Local -> 읽기" 전담 (frontend별 파일 형식 파싱)
│   ├── base.py                # 공용 ROM/미디어 판별 유틸
│   ├── scan.py                 # Local 구조 감지 + 전체 스캔 (Refresh List)
│   ├── es_de.py                 # ES-DE: gamelist.xml 읽기
│   ├── emulationstation.py      # legacy ES: gamelist.xml 읽기
│   ├── pegasus.py                # Pegasus: metadata.pegasus.txt 읽기
│   ├── launchbox.py              # LaunchBox: Platforms/*.xml 읽기
│   └── daijisho.py               # 다이지쇼 (미구현, NotImplementedError)
│
├── exporters/                 # "MasterDB -> Local 쓰기" 전담
│   ├── base.py                  # 공용 media 복사 유틸
│   ├── es_de.py / emulationstation.py / pegasus.py / launchbox.py  # frontend별 쓰기
│   ├── daijisho.py               # 미구현
│   └── retroarch_lpl.py           # RetroArch Playlist(.lpl) 생성
│
├── import_engine.py           # Local -> MasterDB 전체 오케스트레이션 (Version 매칭 포함)
├── export_engine.py           # MasterDB -> Local 전체 오케스트레이션 (충돌처리 포함)
├── cleanup_engine.py           # Reset Metadata / Orphan Cleanup
├── csv_engine.py               # MasterDB <-> CSV 일괄 편집 (add/upsert, media 제외)
├── backup_engine.py             # MasterDB 백업/복원 (backup/ 폴더, 날짜 postfix)
│
├── scraper/
│   └── screenscraper.py         # ScreenScraper API 클라이언트 (단건/일괄)
│
└── gui/
    ├── style.py                  # 디자인 토큰(SaaS 팔레트) + RoundedCard/animate_hover 컴포넌트
    ├── image_utils.py              # Media 썸네일 로딩 (Pillow 우선, 내장 PhotoImage 폴백)
    ├── dialogs.py                  # 공용 대화창 (Local 등록, MasterDB 설정, Export 충돌,
    │                                 Core 설정, 시스템 이름 매핑, Ver Diff)
    ├── scraper_dialogs.py          # 스크랩 관련 대화창 (단건/일괄 리뷰)
    ├── dashboard.py                 # Dashboard 화면
    ├── settings.py                   # Settings 화면 (Core/버전정리/CSV/백업 포함)
    ├── app.py                        # 코어 컨트롤러: 레이아웃/상단카드/Nav/자동저장/종료처리만 담당
    └── mixins/
        ├── local_view.py              # Local 화면 전체 (목록/필터/버튼/우클릭메뉴)
        ├── masterdb_view.py           # MasterDB 화면 전체 (목록/필터/버튼/우클릭메뉴)
        └── detail_panel.py             # 우측 Metadata/Media 상세 패널
                                          (Local=읽기전용 직접읽기, MasterDB=편집+Version관리)
```

## 중요 설계 원칙 (v0.2.0부터)

**media는 ROM 레벨 단일 관리다.** Metadata는 여러 Version을 가질 수 있지만, media(이미지)는
ROM 하나당 딱 1세트만 존재한다 (`rom_entry["media"]`, Version dict 안에는 없음).
이 원칙을 깨는 코드 변경(media를 다시 Version별로 저장하는 등)은 하지 말 것 - 저장 용량
절약과 "사용자가 채택한 이미지가 재Import마다 바뀌지 않아야 한다"는 요구사항 때문에
의도적으로 이렇게 설계되었다.

## "이런 문제가 생기면 이 파일부터" 빠른 참조표

| 증상 | 확인할 파일 |
|---|---|
| ES-DE/Pegasus/LaunchBox에서 metadata가 안 읽힘 | `importers/<frontend>.py` |
| Export한 파일이 이상하게 써짐 | `exporters/<frontend>.py` |
| Import 시 중복이 잘못 판정됨 (버전이 너무 많거나 안 늘어남) | `db.py`의 `is_same_metadata`/`find_matching_version`, `utils.py`의 `normalize_title` |
| 시스템 이름이 안 맞아서 Export가 안 됨 (Pegasus 등) | `config.py`의 `canonical_system`/`local_system_name`, `import_engine.py`/`export_engine.py` |
| RetroArch .lpl 파일 내용이 이상함 | `exporters/retroarch_lpl.py` |
| Core가 잘못 적용됨 | `db.py`의 `get_effective_core`, `gui/dialogs.py`의 `CoreSettingDialog` |
| 스크랩 결과가 이상함 | `scraper/screenscraper.py`의 `_parse_jeu` |
| Local 화면 목록/정렬/필터 문제 | `gui/mixins/local_view.py` |
| MasterDB 화면 목록/정렬/필터 문제 | `gui/mixins/masterdb_view.py` |
| 우측 상세 패널(Metadata/Media/Version) 문제 | `gui/mixins/detail_panel.py` |
| 창 레이아웃/상단 카드/네비/자동저장 문제 | `gui/app.py` |
| Reset Metadata / Orphan Cleanup이 이상하게 지움 | `cleanup_engine.py` |
| media(이미지)가 이상하게 사라지거나 재Import 때마다 바뀜 | `db.py`의 `set_rom_media` (overwrite 정책), `import_engine.py` |
| Version 개수가 이상함 (사라지거나 중복) | `db.py`의 `new_version_id`(충돌 방지), `list_versions_sorted` |
| CSV Export/Import 결과가 이상함 | `csv_engine.py` |
| 백업 파일이 안 보임/복원이 안 됨 | `backup_engine.py`, `config.py`의 `BACKUP_DIR` |
| Ver Diff 대화창 동작 이상 | `gui/dialogs.py`의 `VersionDiffDialog`, `db.py`의 `migrate_unique_fields`/`is_version_empty` |
| 버전 일괄 정리 결과가 이상함 | `db.py`의 `cleanup_non_default_versions` |
| Media 이미지가 안 보임 | `gui/image_utils.py`, `gui/mixins/detail_panel.py`의 `_render_media_tab` |
| Local 화면에서 metadata/media가 안 보임 | `gui/mixins/detail_panel.py`의 `_render_detail_local` |
| 목록의 Description이 여러 줄로 깨져 보임 | `utils.py`의 `single_line` |
| 카드/버튼 색상, 라운드 모서리, hover 애니메이션 | `gui/style.py` (토큰은 여기서만 정의, 다른 파일은 상수만 참조) |
| 설정이 저장 안 됨 | `config.py`의 `save_config`, `gui/app.py`의 `_on_close`/`_schedule_autosave` |

## 디버깅 워크플로 권장

1. 증상을 위 표에서 찾아 **관련 파일 1~2개만** 확인/첨부한다.
2. 순수 로직(엔진/importers/exporters/db/utils)은 tkinter 없이도 `python3 -c "..."`로
   바로 재현 가능하다 (자세한 예시는 `tests/` 폴더 참고).
3. GUI 문제는 `gui/mixins/*.py` 중 해당 화면 파일만 확인하면 된다. `gui/app.py`는
   레이아웃 골격만 갖고 있으므로 대부분의 화면별 버그와 무관하다.
