# HANDOFF — Claude.ai 대화에서 Claude Code로 이관

**이 프로젝트를 Claude Code에서 열면 이 문서를 가장 먼저 읽을 것.**
사용자가 Claude.ai 채팅에서 이어서 하던 작업을 Claude Code로 옮긴 것이며,
지금까지의 설계 결정/시행착오/사용자 피드백이 이 문서에 정리되어 있다.
같은 실수를 반복하지 않으려면 "지금까지 발견된 버그와 교훈" 섹션을 꼭 읽을 것.

## 1. 프로젝트 개요

Windows 데스크톱 앱. 여러 Frontend(ES-DE, EmulationStation, Pegasus, LaunchBox, Daijishō)에
흩어진 레트로 게임 ROM의 metadata/media를 중앙 MasterDB로 모아 관리하고, 다시 각 Frontend로
내보낼 수 있게 해주는 도구.

## 2. 아키텍처 (진행 중인 대전환)

**원래는 Tkinter GUI였다가, 사용자 피드백으로 "웹 기반(HTML/CSS/JS) + pywebview" 로 전환 중.**
이유: Tkinter는 렌더링 결과를 Claude가 미리 볼 수 없어서 디자인 반복이 비효율적이었음.
React 아티팩트로 목업을 만들면 사용자가 직접 보고 즉시 피드백을 줄 수 있어 채택.

```
retro_manager/
├── main.py              # (구) Tkinter 진입점 - 그대로 보존, 더 이상 개발 안 함
├── main_gui.py            # (신규) pywebview 진입점 - 이제부터 이걸로 개발
├── api.py                   # pywebview Api 브릿지 - JS <-> 기존 백엔드 연결. **완성+테스트됨**
├── gui_web/                  # ⚠️ 아직 비어있음 - 다음 작업이 여기
│   ├── index.html               # (없음, 만들어야 함)
│   ├── style.css                  # (없음, 만들어야 함)
│   ├── icons.js                     # (없음, 만들어야 함 - lucide 대체용 수제 SVG)
│   └── app.js                        # (없음, 만들어야 함 - 메인 로직)
├── config.py, db.py, utils.py       # 핵심 로직 (안 건드림, 이미 검증됨)
├── importers/, exporters/            # Frontend별 읽기/쓰기 (안 건드림)
├── import_engine.py, export_engine.py, cleanup_engine.py,
│   csv_engine.py, backup_engine.py    # 상위 오케스트레이션 (안 건드림, backup_engine.py만
│                                          테스트 격리성 위해 import 방식 소폭 수정함)
├── scraper/                            # ScreenScraper 연동 (현재 GUI엔 미노출)
└── tests/
    ├── test_engines.py                  # 백엔드 로직 20개 테스트 (전부 통과)
    └── test_api.py                       # api.py 브릿지 11개 테스트 (전부 통과, 한글 인코딩 검증 포함)
```

**중요: `python3 -m unittest tests.test_engines tests.test_api -v` 로 31개 테스트가
전부 통과하는 걸 확인하고 시작할 것.** (pywebview 자체는 이 sandbox에 설치가 안 되지만,
api.py는 webview import를 pick_folder() 메서드 안에서만 하므로 나머지는 전부 테스트 가능함)

## 3. 지금 당장 해야 할 일 (우선순위 순)

### 3-1. gui_web/ 프론트엔드 작성 (가장 중요, 아직 전혀 안 됨)

**`RetroMetadataManagerMockup.jsx`** 파일이 프로젝트 루트에 있다 (또는 대화 첨부파일에서 확인).
이게 React/Tailwind/lucide-react로 만든 프로토타입인데, **이 채팅에서 사용자와 8~9차례
반복하며 다듬어진 최종 UI/UX 사양이나 마찬가지**다. 이 로직/레이아웃/인터랙션을
**순수 HTML/CSS/vanilla JS로 최대한 그대로 이식**해야 한다.

⚠️ **왜 vanilla JS인가**: 이 개발 환경(sandbox)은 네트워크가 막혀 있어서 npm으로
react/lucide-react/tailwindcss를 설치할 수 없었다. **Claude Code 환경에서 네트워크가
된다면**, 정식으로 React+Vite+Tailwind로 빌드하는 게 더 낫다 - 그러면 .jsx 파일을
그대로 거의 재사용 가능하다. 네트워크 가능 여부를 먼저 확인하고 진행 방식을 정할 것.

.jsx 파일에 있는 주요 컴포넌트/기능 (전부 이식 대상):
- 사이드바 Nav (Dashboard / Local 목록 / + Local 추가 / MasterDB / Settings), 현재 위치 하이라이트
- 상단 Local/MasterDB 카드 (삭제 버튼은 제거됨 - Settings에서만 삭제 가능하도록 최종 결정됨)
- List/Preview 토글 (List=테이블, Preview=Cover 그리드 + 타이틀 한 줄)
- 시스템 드롭다운, 상태 필터 드롭다운(다중선택, 라벨은 **영어 고정**: Normal/Partial/
  Missing ROM/Missing Media/Duplicate ROM - 언어 토글과 무관)
- 게임 리스트 테이블: **CSS Grid 기반**(table 태그 아님) - 컬럼 순서 No/File/Title/
  Description/Genre/Status, **드래그로 컬럼 폭 조절 가능**, 정렬 가능, 헤더가 가로스크롤을
  같이 따라가야 함(sticky top), **배경은 흰색**(나머지 앱은 다크모드인데 이 리스트 카드만 예외)
- 우측 상세 패널: 게임 클릭 시 **5초 후 자동으로 사라짐**, Pin 버튼으로 고정 가능
  (Pin 버튼은 모바일 전체화면 모드에선 숨김 - 거기선 자동숨김 개념이 없음)
- 상세 패널: Metadata/Media 탭 전환, **저장 버튼은 탭 전환과 무관하게 항상 하단에 고정 표시**
  (텍스트+이미지 변경분을 한 번에 저장)
- Metadata 탭: Title, Description, 2열 그리드(Genre/Developer/Publisher/Release/Region/
  Players/Rating), Version 드롭다운 + 복제/기본값/삭제/Ver Diff 버튼, 최하단 Cover 미리보기
- Media 탭: Covers/Miximages/Screenshots/Wheel 4개 타입 탭, **드래그앤드롭으로 이미지
  교체 가능** (놓으면 미리보기 즉시 반영, 저장 버튼 눌러야 실제 반영 - "저장 필요" 뱃지 표시),
  클릭해도 파일선택 대화상자 열림
- Ver Diff 모달: 좌/우 각각 버전 선택(드롭다운), **편집 가능**, 슬롯별 삭제 버튼, 저장/취소
- Local 추가 모달: 이름/Frontend/ROM경로/Metadata경로. **same_dir 로직 중요**:
  Pegasus/Daijishō만 ROM=Metadata 경로 자동 미러링(필드 비활성화), ES-DE/EmulationStation/
  LaunchBox는 별도(이 3개가 한 그룹, Pegasus/Daijishō가 다른 그룹 - 처음엔 반대로
  잘못 알고 있었으니 주의). ES-DE/EmulationStation은 "gamelist/downloaded_media 경로
  (예: ES-DE\ES-DE)" 짧은 안내문구. 경로 입력은 **커스텀 모달**(브라우저 네이티브
  폴더선택 API가 샌드박스에서 막혀서 자체 prompt 모달로 구현했었음 - **실제 pywebview
  환경에서는 `api.pick_folder()`가 진짜 네이티브 폴더 선택 대화상자를 열 수 있으니
  이걸 쓸 것**, 커스텀 prompt 모달은 필요 없어짐)
- 확인 대화상자(ConfirmDialog), 토스트(Toast) - 둘 다 브라우저 네이티브 confirm()/alert()
  안 쓰고 자체 구현했음 (아마 이 샌드박스의 iframe 제약 때문이었는데, 실제 pywebview
  환경에선 네이티브써도 될 수도 있음 - 굳이 다시 네이티브로 바꿀 필요는 없음, 이미
  일관된 디자인이라 커스텀 유지 권장)
- Dashboard: Local별/MasterDB 탭, 요약 카드 4개(전체 ROM/전체용량/Missing ROM/Missing Media),
  시스템별 통계 테이블(전체용량/ROM개수·용량/Media개수·용량/Video개수·용량/상태)
- Settings: 일반(언어/테마/저장간격) + Local관리(목록+삭제) + Export설정(4개 체크박스+설명문+
  각 항목 옆 설명) + 백업/복원(백업 버튼+복원 시 백업파일 목록에서 선택)
- 상태 표시: title&&desc 둘 다 없으면 뱃지 대신 "-" 표시 (뭔가 잘못된 것처럼 보이지 않게)
- 모바일 반응형 (1024px 기준), Fold 같은 큰 화면 고려해서 압축 레이아웃

**연결**: 모든 데이터 조작은 `window.pywebview.api.<메서드>(...)`를 호출 (Promise 반환).
api.py에 이미 다 구현되어 있음 - 메서드 목록은 api.py 소스 참고. 예:
```js
window.pywebview.api.list_locals().then(res => {
  if (res.ok) { /* res.data 사용 */ } else { /* res.error 표시 */ }
});
```
모든 메서드가 `{ok: bool, data?: any, error?: string}` 형태로 반환함 (일관됨).

**중요**: media 이미지 표시는 `get_game_detail()`이 반환하는 `data.media.Covers` 등이
이미 `data:image/png;base64,...` 형태 data URI이므로 `<img src="...">` 에 그대로 넣으면 됨.
드래그앤드롭 업로드는 JS의 FileReader로 파일을 base64로 읽어서
`api.save_media(romKey, "Covers", base64문자열, 파일명)` 호출.

### 3-2. gui_web/ 작성 후 검증

- `main_gui.py` 실행해서 실제 창이 뜨는지, 클릭/드래그/키입력이 실제로 되는지 확인
  (이건 Claude Code가 사용자 PC에서 실행하며 같이 확인해야 함 - 이 sandbox는 pywebview
  설치 자체가 안 됨, `pip install pywebview` 필요)
- `tests/test_api.py`가 이미 있으니 프론트를 붙인 후에도 계속 통과하는지 재확인

### 3-3. build.bat 갱신

기존 `build.bat`은 `main.py`(Tkinter)를 빌드 대상으로 함. `main_gui.py`를 빌드하려면
PyInstaller에 `--add-data "gui_web;gui_web"` 옵션을 추가해서 HTML/CSS/JS 파일들이
exe 안에 같이 포함되도록 해야 함. 필요하면 `main_gui.py`용 별도 `build_web.bat`을
만들거나, 기존 `build.bat`에 선택 옵션을 추가.

## 4. 사용자가 명시적으로 결정한 것들 (재확인/재질문 하지 말 것)

- **테마(Dark/Light 전환)**: 사용자가 확답을 아직 안 줬음 (이관 직전에 질문함). 답이
  없으면 우선 다크모드로 통일하고, 라이트 테마 관련 코드는 있어도 되지만 완성 우선순위
  낮게. 사용자에게 다시 물어봐도 됨.
- **언어(한/영) 전환 범위**: 확답 대기 중이었음. 기본값은 "핵심 UI 문자열만" (상태
  라벨은 항상 영어 고정, 전체 완전 번역은 하지 않음).
- **강제 덮어쓰기(force_overwrite)**: 구현 완료. `config.py`의 `export_options`에 필드
  추가했고 `export_engine.py`에서 실제로 충돌 대화상자를 건너뛰고 바로 덮어쓰도록 연결함.
- **다이지쇼(Daijishō)**: 여전히 미구현 상태 유지하기로 확정. `importers/daijisho.py`의
  `read_metadata_fields`/`read_media`가 NotImplementedError를 내고, `api.scan_local()`이
  이를 하드 실패가 아니라 `notImplemented: true` 플래그로 우아하게 처리하도록 이미 구현됨.
  Daijishō 실제 폴더 구조가 확보되기 전까지 손대지 말 것.
- **경로 관계(중요, 실수했던 부분)**: ES-DE/EmulationStation/LaunchBox = ROM 경로가
  Metadata/Media 경로와 별도. Pegasus/Daijishō만 동일(자동 미러링). 처음에 "ES-DE/
  EmulationStation만 예외"라고 잘못 판단했다가 LaunchBox도 별도 그룹이라는 걸
  나중에 바로잡음.
- **버전(Version) 관리 모델**: 하나의 ROM이 여러 metadata Version을 가질 수 있음
  (스크랩 소스별로). 하지만 **media는 ROM당 단일 세트만 존재**(Version과 무관하게
  공유) - 이건 설계 초기에 확정된 핵심 원칙이니 절대 다시 Version별 media로 되돌리지 말 것.
- **5초 자동숨김 + Pin 상세패널**: 원래 설계서(v2)는 상시 도킹된 우측 패널이었는데,
  사용자가 "게임 고를 때마다 5초만 보여주고 사라지되 Pin으로 고정 가능"으로 명시적으로
  UX를 바꿔달라고 요청해서 이렇게 확정됨. 원래 설계서와 다르다고 되돌리지 말 것.

## 5. 지금까지 발견된 버그와 교훈 (같은 실수 반복 방지용)

1. **`from config import BACKUP_DIR`처럼 모듈 top-level에서 `from X import Y`를 하면
   테스트에서 나중에 `X.Y`를 재할당해도 반영이 안 된다** (import 시점에 값이 복사되어
   버려짐). `backup_engine.py`에서 실제로 이 문제로 테스트가 깨졌었음. 앞으로는
   `import config as cfgmod` 후 `cfgmod.XXX`로 매번 조회하는 패턴을 쓸 것 (이미
   대부분의 파일이 이렇게 되어 있음 - `backup_engine.py`만 예외였다가 지금 고쳤음).

2. **`new_version_id()`가 예전엔 밀리초 단위 타임스탬프였는데, 짧은 시간에 여러 Version이
   생성되면 ID가 충돌해서 이전 데이터가 통째로 사라지는 심각한 버그가 있었음.**
   현재는 nanosecond 단위 모노토닉 카운터로 고쳐져 있음 (`db.py`의 `new_version_id`).
   혹시 이 함수를 다시 건드릴 일이 있으면 절대 밀리초 단위로 되돌리지 말 것.

3. **GUI가 보내는 Frontend 표시 라벨("ES-DE", "Daijishō" 등)과 백엔드 내부 키
   ("es-de", "daijisho" 등)가 다르다.** `api.py`의 `GUI_FRONTEND_TO_INTERNAL` 딕셔너리로
   변환하고 있음. 새 코드에서 frontend 문자열을 다룰 때 이 매핑을 거치는 걸 잊지 말 것.

4. **ES-DE/EmulationStation의 media 경로는 `<root>/downloaded_media/<system>/...`
   구조다.** `<root>/<system>/...`가 아니다 (예전에 이 부분 착각해서 media를 못 찾는
   버그가 있었음, `importers/base.py`의 `es_media_root()` 참고).

5. **Tailwind의 `truncate` 유틸리티 클래스에 의존한 1줄 표시가 이 sandbox의 아티팩트
   렌더러에서 계속 깨졌었다.** CSS Grid + 인라인 `overflow:hidden; white-space:nowrap;
   text-overflow:ellipsis`로 직접 강제하니 해결됨. vanilla JS로 이식할 때도 이 패턴
   그대로 유지할 것 (Tailwind 자체가 없으니 어차피 인라인/CSS 클래스로 직접 써야 함).

6. **브라우저 샌드박스(이 대화의 아티팩트 iframe)에서 `webkitdirectory` 폴더선택
   API와 `window.confirm/prompt` 네이티브 대화상자가 막혀서 커스텀 컴포넌트로 대체했었음.**
   실제 pywebview 환경에서는 이런 제약이 없을 가능성이 높음 - `api.pick_folder()`가
   진짜 OS 네이티브 폴더 선택 대화상자를 연다 (webview.FOLDER_DIALOG). 폴더 선택
   버튼은 이제 이걸 쓰면 됨. 확인창/토스트는 이미 커스텀으로 디자인이 통일되어
   있으니 그대로 유지 권장.

7. **Settings 화면이 라우팅이 안 먹혀서 항상 게임리스트만 보이던 버그가 있었음**
   (`view` state는 갱신되는데 실제 body 렌더링 분기가 없었음). vanilla JS로 옮길 때
   이 클래스의 실수를 참고해서 상태값과 렌더링 분기가 항상 같이 가는지 재차 확인할 것.

8. **Pin 버튼이 안 눌리던 버그**: 모바일 전체화면 모드에서 `pinned=true`를 강제
   고정하면서 토글 핸들러를 빈 함수로 넘겼는데, 버튼 자체를 숨기지 않아서 고장난
   것처럼 보였음. UI 요소를 조건부로 비활성화할 땐 "숨기기"와 "죽이기"를 구분해서
   사용자에게 혼란 주지 않도록 할 것.

## 6. 백엔드 함수 매핑 참고 (api.py 작성 시 사용한 기존 함수들)

⚠️ **"Import"/"Export"는 이 프로젝트에서 두 가지 다른 기준으로 쓰인다 — 헷갈리지만 둘 다 의도된 것이지 버그가 아니다.**
- **GUI 라벨**: 지금 보고 있는 화면(엔티티) 기준 상대 명명. Local 화면에서는 Local이 주어라서
  "Import from MasterDB" = MasterDB→Local(들어옴), "Export to MasterDB" = Local→MasterDB(나감).
  MasterDB 화면에서는 MasterDB가 주어라서 "Export to GameListSet" = MasterDB→Local(나감)이 된다.
  즉 같은 물리적 방향(MasterDB→Local)이라도 어느 화면에서 트리거됐는지에 따라 GUI 라벨의
  Import/Export가 바뀐다.
- **내부 코드**(`import_engine.py` / `export_engine.py`): 언제나 **MasterDB 고정 기준**.
  Local→MasterDB는 항상 `import_engine.py`, MasterDB→Local은 항상 `export_engine.py` — 어느
  화면/버튼에서 호출됐든 안 바뀐다.

앞으로 `local`을 `GameListSet`으로 개명하거나 Compare 화면(9번 단계)이 추가될 때도, GUI 쪽은
"그 화면 기준 in/out"이라는 규칙을 그대로 적용하면 되고, 내부 함수/파일명은 계속 MasterDB
고정 기준으로 유지하면 된다. 두 기준을 억지로 통일하려고 시도하지 말 것 — 각자 다른 용도로
이미 잘 동작하고 있다.

| GUI 액션 | api.py 메서드 | 내부적으로 부르는 기존 함수 |
|---|---|---|
| Local 추가 | `add_local` | `config.add_local`, `importers.scan.detect_local_structure` |
| Refresh List | `scan_local` | `importers.scan.scan_local`, `importer.read_metadata_fields` |
| CleanUp | `reset_metadata` | `cleanup_engine.reset_metadata` |
| Prune Data | `orphan_cleanup` | `cleanup_engine.orphan_cleanup` |
| Export to MasterDB (Local 화면) | `import_local_to_masterdb` | `import_engine.import_local_to_masterdb` |
| Import from MasterDB (Local 화면) / Export to GameListSet (MasterDB 화면) | `export_to_local` | `export_engine.export_masterdb_to_local` |
| Metadata 저장 | `save_version_fields` | `db.py` 직접 조작 |
| 버전 복제/기본값/삭제 | `clone_version`/`set_default_version`/`delete_version` | `db.clone_version` 등 |
| Media 드래그업로드 | `save_media` | `db.update_single_media` (신규 추가한 헬퍼) |
| 백업/복원 | `do_backup`/`list_backups`/`restore_backup` | `backup_engine.py` |
| 설정 저장 | `save_settings` | `config.save_config` |

## 7. 테스트 실행 방법

```bash
cd retro_manager
python3 -m unittest tests.test_engines tests.test_api -v
```
31개 전부 `ok`가 나와야 함. 새 기능을 추가할 때마다 관련 테스트도 같이 추가할 것
(이 프로젝트는 지금까지 모든 백엔드 로직 변경에 테스트를 동반해왔음 - 계속 유지).

## 8. 버전 정책

`version.py` 참고 - 사용자가 "1.0.0은 진짜 완성됐을 때만, 그 전까진 0.3.x, 0.4.x처럼
천천히 올려달라"고 명시적으로 요청함. 큰 기능(웹 GUI 전환)이 실제로 동작 확인되면
0.4.0으로 올리는 게 적절해 보이지만, 사용자와 상의 후 결정할 것.

## 9. [갱신] gui_web/ 프론트엔드 1차 완성 (2026-08-28)

**저장소 없이 같은 Claude.ai 세션에서 계속 진행하기로 함.** gui_web/의 5개 파일을
전부 작성했다:
- `style.css` (340줄): CSS 커스텀 프로퍼티로 테마 토큰화, `html[data-theme="light"]`로
  라이트 테마 전환 (JS에서 `document.documentElement.setAttribute('data-theme', ...)` 호출)
- `icons.js` (60여개 아이콘): lucide 대체용 수제 SVG, `RMIcons.svg(name, size)`
- `api-client.js`: `window.pywebview.api` 래퍼 + pywebview 없을 때(브라우저 단독 실행)
  자동 폴백되는 목업 모드 포함 (`RMApi._mockMode`)
- `app.js` (1286줄): 메인 로직 전체. 사이드바/상단카드/필터바/리스트(List+Preview)/
  상세패널(자동숨김+Pin+탭+Version관리+Media드래그업로드)/Ver Diff 모달/Local추가 모달/
  확인창/토스트/Dashboard/Settings 전부 구현
- `index.html`: 셸

### 검증한 것 (이 sandbox에서 가능한 범위)
- `node --check`로 3개 JS 파일 전부 문법 통과
- index.html의 모든 `id`와 app.js의 `getElementById` 호출 100% 교차 일치 확인
- app.js의 `api.*()` 호출 27개 전부 `api-client.js`에 정의된 메서드와 일치
- `api-client.js`가 호출하는 Python 메서드명 27개 전부 `api.py`의 실제 메서드와 일치
  (오탈자로 인한 런타임 에러 가능성을 최대한 사전 차단)
- 핵심 순수 로직(상태 필터링/정렬/컬럼 리사이즈 클램프/빈 상태 뱃지 처리)을 Node로
  독립 실행해서 검증
- 기존 백엔드 31개 테스트(test_engines.py 20개 + test_api.py 11개) 계속 통과 유지

### ⚠️ 아직 검증 못 한 것 (이 sandbox의 근본적 한계)
- **pywebview 자체가 설치 안 돼서 실제 창이 뜨는지, 진짜 마우스 드래그/클릭/드롭이
  브라우저에서 어떻게 동작하는지는 전혀 확인 못 했다.** 이건 사용자 PC에서만
  확인 가능하다.
- CSS 레이아웃이 실제로 의도한 대로 나오는지(특히 grid-template-columns 동적 갱신,
  detail-panel의 절대위치, 반응형 등)는 렌더링 엔진이 없어 눈으로 확인 불가.
- 드래그 컬럼 리사이즈(`startColumnDrag`)는 로직상 문제없어 보이지만 실제 마우스
  이벤트 시퀀스로 테스트된 적 없음.

### 다음 단계 제안
1. 사용자가 Windows에서 `pip install pywebview` 후 `python main_gui.py`로 실행
2. 실제로 창이 뜨는지, 각 화면 전환/클릭/드래그가 되는지 확인
3. 문제 발견 시 증상을 알려주면 (Claude Code 없이도) 이 세션에서 계속 디버깅 가능
   - `HANDOFF.md`의 "지금까지 발견된 버그와 교훈" 섹션에 새로 발견되는 것들 계속 추가할 것
4. `build.bat`을 `main_gui.py` + `gui_web/` 포함하도록 갱신 필요 (아직 안 함)


## 10. [갱신] gui_web/ 디자인 리뉴얼 + 실사용 버그 수정 (2026-08-28)

**Claude 프로젝트에 새 JSX 목업이 첨부되어(Midnight Arcade 테마), 이를 검토 후 실제
gui_web/에 반영함.** 이 시점부터 gui_web/의 실제 디자인 기준은 그 목업이다.

### 반영된 것
- 컬러 테마: 보라 계열(#8B5CF6) "Midnight Arcade" 팔레트로 교체
- 상단 카드바 제거 확정 (원래 목업에 TopCard/MasterCard 함수는 있었지만 실제 렌더링
  안 되고 있었음 - 사용자 확인 후 "없는 채로 진행" 결정)
- 사이드바에 GAME SYSTEMS 필터 목록 통합, Settings는 로고 옆 톱니바퀴 아이콘으로 진입
- Metadata/Media/Settings 패널 타이포그래피를 게임리스트 수준으로 통일
  (`gui_web/style.css`의 `--fs-*` 변수들 참고)
- 게임 전환 시 Metadata/Media 탭 + Media 타입 선택 유지 (이전엔 초기화됐음)
- 시스템 이름 정규화 규칙: ROM 디렉토리명 기준 + ES-DE 표준 소문자 축약형으로 교정
  (`app.js`의 `normalizeSystemName()`, `SYSTEM_ALIAS_MAP` - 별칭 목록은 필요시 계속 추가)

### 미확정/재확인 필요
- **"Local 추가 버튼을 누르면 화면이 사라진다" 버그**: 정적 분석으로 명확한 원인을
  못 찾음. pywebview + WebView2 조합에서 네이티브 폴더 선택창이 떠 있는 동안 뒤의
  webview가 빈 화면처럼 보이는 알려진 렌더링 이슈로 추정하고 `api.py`의
  `pick_folder()`에 `evaluate_js`로 강제 리페인트하는 완화 조치를 넣었지만, 실제
  해결됐는지는 사용자가 Windows에서 재확인해야 함. 안 고쳐졌다면 재현 조건을 더
  구체적으로 받아야 함 (Local 추가 버튼 자체인지, 그 안의 폴더 버튼인지 등).
- **"상단 버튼이 가려지고 스크롤바가 생긴다" 버그**: `#detail-panel`의 flex 구조
  (`header`/`tabs`/`footer`는 `flex-shrink:0`, `body`만 `flex:1 + overflow-y:auto`)는
  애초에 구조적으로는 맞게 되어 있었음 - 실제 원인은 폰트/버튼 크기가 너무 커서
  내용이 안 들어갔던 것으로 추정. 이번 타이포그래피 통일로 해결됐을 가능성이 높지만
  재확인 필요.

### 테스트
- `python3 -m unittest tests.test_engines tests.test_api -v` : 31개 전체 통과 유지
- JS 문법(`node --check`), HTML id / CSS 클래스 / api 메서드명 전부 교차검증 통과
- `normalizeSystemName`, `compactNum` 순수 로직 Node로 별도 검증 완료
- **pywebview 자체는 이 sandbox에 여전히 설치 불가 - 실제 창 렌더링/클릭/드래그는
  이번에도 사용자 PC에서만 최종 확인 가능함.**


## 11. [최종 갱신] v0.4.0 - 4단계(최종 코드 작성) 완료 (2026-08-28)

**gui_web/ + api.py가 실사용 가능한 수준으로 완성되어 v0.4.0으로 버전업했다.**
이 시점 이후 이 프로젝트를 이어받으면 아래를 우선 확인할 것.

### 검증 상태 (마지막 확인 시점 기준)
- `python3 -m unittest tests.test_engines tests.test_api -v` → **40개 전체 통과**
- Python/JS 문법 검사 전부 통과
- HTML id / CSS 클래스 / api.py 메서드명 3중 교차검증 스크립트 전부 통과
- 중복 함수/CSS 규칙 정리 완료

### ⚠️ 절대적으로 남아있는 한계
**pywebview 자체가 이 개발 sandbox에 설치 불가능해서, 실제 창이 뜨고 클릭/드래그/키입력이
진짜로 되는지는 이 프로젝트 전체 기간 동안 단 한 번도 실기 검증을 못 했다.** 정적 분석
(문법/참조 일치)으로 최대한 방어했지만, 이것이 실행 검증을 대체하지는 못한다.
**사용자가 Windows에서 `build_web.bat` 실행 -> `dist\RetroMetadataManagerWeb.exe`를
직접 켜보는 것이 유일한 진짜 검증 수단이다.**

### 아직 gui_web 화면에 없는 백엔드 기능 (필요시 순서: 화면 추가 -> api.py는 이미 있으니 배선만)
- Core 설정 (system_cores 커스텀 매핑)
- ScreenScraper 연동 (`scraper/screenscraper.py`)
- RetroArch .lpl Export (`exporters/retroarch_lpl.py`)
- CSV Import/Export (`csv_engine.py`)
- 버전 일괄 정리 (`cleanup_engine.py`의 `cleanup_non_default_versions` 계열)

### 다이지쇼(Daijishō)
여전히 미구현 확정 상태 유지 중. `api.scan_local()`이 NotImplementedError를 hard fail이
아니라 `notImplemented: true` 플래그로 우아하게 처리하는 것까지 되어 있음 - 실제 폴더
구조가 확보되면 `importers/daijisho.py`의 `read_metadata_fields`/`read_media`만
구현하면 된다 (구조 감지 쪽은 이미 가정 기반으로 구현되어 있음).

### 버전 정책 재확인
`version.py`가 `0.4.0`. GUI 사이드바는 이제 하드코딩이 아니라 `api.get_version()`으로
실시간 조회한다 - 앞으로 버전 올릴 때 `version.py`만 고치면 됨 (JS 쪽 안 건드려도 됨).


## 12. [0.4.1.x] GUI 개선 - 위험도 단계별 롤아웃 (2026-09-01~)

**사용자가 "기존 gui 개선"을 목적으로 9개 항목을 요청했고, 검토 후 위험도(데이터/파일을
실제로 건드리는 정도) 낮은 것부터 높은 것 순으로 별도 버전에 나눠 반영하기로 했다.**
이 절은 그 계획과 각 버전의 롤백 지점을 기록한다 - **문제가 생기면 아래 git 태그로
`git reset --hard <태그>` 하면 그 버전 이전 상태로 정확히 돌아간다** (각 버전은 이전
버전의 순수 상위집합이므로, 특정 기능이 의심되면 그 기능이 추가된 버전의 직전 태그로
돌아가면 원인 격리가 된다).

### 요청받은 9개 항목과 위험도 분류

| # | 항목 | 위험도 | 반영 버전 |
|---|---|---|---|
| 1 | 프로그레스 바 브라켓 스타일 | 낮음 (렌더링만) | 0.4.1.1 |
| 2 | 사이드바 라벨/순서(ArchiveDB/GameListSet), Settings 위치 | 낮음 (라벨만) | 0.4.1.1 |
| 3 | GameListSet 목표용량 대시보드 | 중간 (config.json 필드 기록) | 0.4.1.2 |
| 4 | Settings 7개 카테고리 재구성 | 중간 (ui 설정값 기록, 확인창 동작 변경) | 0.4.1.3 |
| 8 | 유사롬 묶어보기 + 대표 자동 지정 | 중간 (SQLite `similar_groups`/`favorites` 테이블 기록) | 0.4.1.4 |
| 9 | Favorite 필드 + 삭제 시 자동 제외 | 중간 (SQLite `favorites` 테이블 기록, 삭제 로직 변경) | 0.4.1.4 |
| 6 | F2 리네임(ROM+media 폴더 실제 이동) + Ctrl+C/V | **높음 (실제 파일시스템 rename/move)** | 0.4.1.5 |
| 5 | 드래그앤드롭 롬/메타데이터 이동 + 전송 선택 모달 | (미착수, 사용자가 맨 뒤로 미룸) | 미정 |
| 7 | 우클릭 컨텍스트 메뉴(롬/메타/전체 삭제) | (미착수, 사용자가 맨 뒤로 미룸) | 미정 |

**8/9가 왜 같은 버전(0.4.1.4)인가**: 8(유사롬 대표 자동 지정)의 favorite 우선순위
tier가 9(Favorite 필드)가 도입하는 SQLite `favorites` 테이블을 참조하도록 구현되어
있어 - 9 없이 8만 단독으로 존재하던 시점(원래 구현 순서)에는 그 tier가 자기 자신의
`self.db["roms"][k].get("favorite")`(항상 없는/False 필드)를 읽는 **무해한 자리표시자**
상태였다. 이 두 커밋은 같은 기능 계열이라 분리 배포의 이득이 적고, 실제로 갈라놓으면
git cherry-pick 충돌(같은 함수의 같은 줄을 양쪽이 수정)을 인위적으로 만들 뿐이라 하나의
버전으로 묶었다.

### 버전별 상태 (진행되는 대로 갱신할 것)

- **v0.4.1.1** — ✅ 적용 완료. 태그: `v0.4.1.1`. 포함: #1, #2.
  검증: 백엔드 101 테스트 통과(신규 없음, 순수 프론트). UI 테스트는 이 버전엔 아직 없음
  (Playwright 셋업 자체가 0.4.1.3에서 들어옴).
- **v0.4.1.2** — ✅ 적용 완료. 태그: `v0.4.1.2`. 포함: #3.
  검증: 백엔드 101 테스트 통과(신규 없음 - `set_local_target_capacity`는 기존
  스키마 필드를 쓰는 얇은 배선이라 별도 백엔드 테스트를 추가하지 않았음, 필요하면
  추후 추가할 것).
- **v0.4.1.3** — ✅ 적용 완료. 태그: `v0.4.1.3`. 포함: #4 + Playwright UI 테스트 인프라
  (`playwright.config.js`, `tests_ui/`) 최초 도입 - #1~#4를 커버하는 회귀 테스트가 이
  버전에 같이 들어감. `npm run test:ui`로 실행 (headless Chromium, mock API 모드 -
  실제 pywebview/Windows 없이도 클릭/키보드 이벤트로 검증 가능. 단, 네이티브 폴더
  대화상자·실제 파일시스템 드래그·WebView2 렌더링 버그는 커버 못 함).
  검증: 백엔드 101 테스트 통과, UI 테스트 16개 통과.
- **v0.4.1.4** — ✅ 적용 완료. 태그: `v0.4.1.4`. 포함: #8, #9.
  검증: 백엔드 107 테스트 통과, UI 테스트 25개 통과.
  ⚠️ 이 버전을 커밋 재배치로 만드는 과정에서 세그폴트를 하나 발견/수정했다 - 자세한
  경위는 CHANGELOG.md의 v0.4.1.4 항목 하단 "디버깅 메모" 참고. 요약: unit8/9 테스트가
  쓰는 `_wait_job()` 헬퍼가 원래 unit6(F2) 커밋에서 정의됐던 걸 놓쳐서, 재배치 직후
  잠깐 `tests/test_api.py`가 정의 없는 헬퍼를 호출해 background job 스레드와
  `Api.close()`가 경합하며 프로세스가 죽었다. `_wait_job()` 정의를 이 버전으로
  옮겨와서 해결(같은 커밋에 amend로 포함시킴 - 별도 fixup 커밋 없음).
- **v0.4.1.5** — ✅ 적용 완료 (0.4.1.x 시리즈 마지막). 태그: `v0.4.1.5`. 포함: #6.
  **이 시리즈에서 유일하게 실제 파일시스템을 조작하는 변경**(ROM 실물 파일 rename).
  검증: 백엔드 110 테스트 통과, UI 테스트 30개 통과 - 원래(재배치 전) 세션 종료 시점과
  정확히 동일한 개수. `git diff pre-version-restructure-backup HEAD`로 최종 확인한 결과,
  CHANGELOG/HANDOFF/version.py를 제외한 실제 코드 diff는 함수 정의 순서 차이뿐이고
  **기능적으로 100% 동일**함을 확인했다 (재배치가 어떤 코드도 잃어버리지 않았다는 뜻).
  **사용자가 실제 Windows 환경에서 MasterDB 백업 뜬 뒤 F2로 파일명 변경을 한 번
  실제 데이터로 테스트해보는 걸 강력히 권장** - 이 sandbox에서는 pywebview/Windows
  자체가 없어 실기 검증이 불가능하다 (HANDOFF.md 1~11절에 걸쳐 반복되는 근본적 한계와
  동일).

### 재배치 완료 후 정리
모든 버전(v0.4.1.1~v0.4.1.5)이 반영되었다. `pre-version-restructure-backup` 태그는
재배치 전 원본 상태를 가리키는 안전장치였고, 위 diff 검증으로 목적을 다했으므로 더 이상
필요하면 `git tag -d pre-version-restructure-backup`으로 지워도 된다(참고용으로 남겨둬도
무방 - 실제 브랜치 히스토리에는 영향 없음).

### 문제 발생 시 롤백 절차 (다른 세션/AI가 이어받을 경우)

1. `git log --oneline --all | grep "^v0.4.1\."` 로 각 버전의 커밋을 확인하거나,
   `git tag -l "v0.4.1.*"` 로 태그 목록을 본다.
2. 의심되는 기능이 어느 버전에서 들어갔는지 위 표에서 확인.
3. `git diff <이전버전 태그> <의심버전 태그>` 로 그 버전에서 실제로 뭐가 바뀌었는지 정확히 본다.
4. 되돌리려면 `git revert <범위>` (히스토리 보존, 권장) 또는 이미 push 전이라면
   `git reset --hard <이전버전 태그>` (히스토리 삭제, push 전에만 안전).
5. 각 버전 경계에서 `python3 -m unittest tests.test_engines tests.test_api`와
   (0.4.1.3부터는) `npx playwright test`가 전부 통과하는 상태였으므로, 롤백 직후에도
   같은 커맨드로 그 지점이 실제로 건강한 상태인지 재확인할 것.

### 이 재구성이 필요했던 이유 (다음 세션이 git log를 보고 의아해할 경우)

원래 이 9개 항목은 구현 순서(1→2→3→4→6→8→9)대로 커밋되어 있었다. 사용자가 "위험도
낮은 것부터 버전을 나눠서 반영"을 요청해서, 위 표의 위험도 순서(1,2 → 3 → 4 → 8,9 → 6)로
**커밋을 재배치**했다 (unpushed 상태였기 때문에 `git reset --hard` + `git cherry-pick`으로
안전하게 재구성 가능했음 - 이미 원격에 올라간 히스토리였다면 이런 재배치 대신
`git revert`/새 커밋으로 처리했을 것). 각 기능의 실제 코드 내용은 원래 구현과 100%
동일하고, 어느 버전에 포함되는지만 재배치되었다.
