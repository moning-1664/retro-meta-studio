# RetroMeta Studio

레트로 게임 ROM/Metadata를 여러 Frontend(ES-DE, Pegasus, LaunchBox, EmulationStation,
다이지쇼) 사이에서 관리하는 Windows용 GUI 도구.

> [RetroGameManager](https://github.com/moning-1664/RetroGameManager)에서 코드를 그대로
> 가져와 시작한 프로젝트입니다. 기존 프로젝트는 모든 Import/Export가 중앙 MasterDB(JSON)를
> 거치는 구조였는데, 실사용해보니 그 구조 자체의 사용성이 떨어져서 아키텍처를 다시 설계하기
> 위해 새 저장소로 분리했습니다. 기능 대부분은 기존과 비슷하게 유지하면서 구조를 바꿔갈
> 예정이라, 문서상의 "MasterDB" 관련 설명은 앞으로 걷어낼 레거시 서술입니다.

- 현재 버전: `version.py` 참고 (`0.2.0`, 포크 시점 기준 - 이 프로젝트에서 새로 버전 체계를 정할 예정)
- 변경 이력: `CHANGELOG.md`
- 파일 구조/디버깅 가이드: `MODULE_MAP.md`
- 실제 GUI 동작 확인 체크리스트: `MANUAL_GUI_TEST_CHECKLIST.md`

## 요구 사항

- Windows 10/11
- Python 3.11 이상 (설치 시 "Add python.exe to PATH" 체크)

## 빠른 실행 (개발/디버깅용, 빌드 없이)

`run.bat` 더블클릭. 최초 실행 시 가상환경(`venv`)을 만들고 `requirements.txt`를 설치한 뒤
`python main.py`로 바로 실행합니다.

## 배포용 실행 파일(.exe) 빌드

`build.bat` 더블클릭. PyInstaller로 `dist\RetroMetadataManager.exe`를 생성합니다.
빌드에는 몇 분 정도 걸릴 수 있습니다.

빌드가 끝나면 `dist\RetroMetadataManager.exe` 하나만 원하는 위치로 옮겨서 실행하면 됩니다.
최초 실행 시 **exe와 같은 폴더에** `config.json`과 `backup\` 폴더가 자동 생성됩니다.

## 폴더 구조 요약

```
retro_manager/
├── build.bat / run.bat      # Windows 빌드/실행 스크립트
├── requirements.txt          # Python 의존성
├── main.py                    # 실행 진입점
├── version.py / CHANGELOG.md   # 버전 정보
├── config.py, db.py, utils.py   # Core 로직
├── importers/, exporters/        # Frontend별 읽기/쓰기
├── import_engine.py, export_engine.py, cleanup_engine.py,
│   csv_engine.py, backup_engine.py                          # 상위 오케스트레이션
├── scraper/                    # ScreenScraper 연동
├── gui/                          # GUI (app.py + mixins/ + dialogs 등)
└── tests/                         # BT 레벨 회귀 테스트 (python -m unittest tests.test_engines -v)
```

## 테스트

```
python -m unittest tests.test_engines -v
```

tkinter가 필요 없는 순수 로직(Import/Export/Cleanup/CSV/버전관리 등)만 자동 테스트합니다.
GUI 동작 자체는 `MANUAL_GUI_TEST_CHECKLIST.md`를 참고해 직접 확인해주세요.

## 알려진 제한사항

- 다이지쇼(Daijisho) Import/Export는 실제 폴더 구조 미확인으로 미구현
- LaunchBox media 매칭은 ROM stem 기준 위주
- `MODULE_MAP.md`에 "media는 ROM 레벨 단일 관리" 등 핵심 설계 원칙이 정리되어 있으니,
  코드 수정 전에 한 번 참고하는 것을 권장합니다.
