# RetroMeta Studio

여러 Retro Game Frontend(ES-DE, Pegasus, LaunchBox, EmulationStation)의 게임 목록·
메타데이터·ROM·Media를 하나의 작업 공간에서 관리하고 변환하는 Windows 데스크톱
애플리케이션.

[RetroGameManager](https://github.com/moning-1664/RetroGameManager)에서 코드를 가져와
시작했다. 기존 프로젝트는 모든 Import/Export가 중앙 MasterDB를 거치는 구조였는데,
그 구조 자체의 사용성 문제를 해결하기 위해 상위 아키텍처를 다시 설계한다.

핵심 개념은 넷을 명확히 분리하는 것이다.

| 개념 | 역할 |
|---|---|
| **Collection** | 실제 Frontend 환경을 나타내는 논리적 게임 라이브러리. 작업의 기본 단위 |
| **Archive** | 여러 Collection에서 수집한 Metadata/Identity 보관소. Canonical DB가 **아니다** |
| **Cache** | 파일시스템 Scan 결과. 언제든 버리고 다시 만들 수 있다 |
| **Plan** | 실제 파일을 바꾸기 전에 변경 결과를 미리 계산한 집합 |

설계 문서: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## 현재 상태

**Phase 0 (저장소 골격) 진행 중.** 아직 실행 가능한 앱이 아니다 - 진입점과 UI 연결은
Phase 2에서 붙는다.

| Phase | 내용 | 상태 |
|---|---|---|
| 0 | 저장소 스키마·마이그레이션, 다중 인스턴스 기반, Provider/Adapter 인터페이스, 레거시 정리 | 진행 중 |
| 1 | Core Model + ES-DE Adapter + Cache 스캔 | |
| 2 | Collection UI (탭/헤더/내비/Gamelist) + 기존 Detail 패널 연결 | |
| 3 | Plan (Auto Plan·용량 계산·Apply·인스턴스 간 복사/붙여넣기) | |
| 4~8 | Archive / Match / Compare / Frontend Adapters / MTP | |

## 구조

```
app/          Collection·Plan·Archive·Match·Compare·Scan 등 모든 비즈니스 로직
├── model/      순수 데이터 모델
├── store/      SQLite 저장소 (registry / cache / archive)
└── paths.py    앱 데이터 위치
adapters/     Frontend Adapter (읽기+쓰기를 한 곳에서 책임)
storage/      물리 접근 추상화 (Local/UNC, 후에 MTP)
engines/      파일 복사 엔진 + file_ops.py + native/  ← RetroGameManager에서 그대로 승계
bridge/       pywebview 브릿지와 Job 큐
gui_web/      웹 UI (Phase 2에서 새 구조에 맞춰 재배치)
importers/    기존 Frontend 파서 - Phase 1에서 adapters/로 흡수 예정
exporters/    기존 Frontend 라이터 - Phase 1에서 adapters/로 흡수 예정
```

앱 데이터는 실행 파일과 같은 폴더의 `db/`에 만들어진다.

```
db/
├── registry.db          Collection 등록 · Storage/System 배치 · 변경 로그 · 잠금
├── archive.db           Metadata / Identity / Revision
└── cache/<id>.db        Collection별 Scan 결과
```

## 요구 사항

- Windows 10/11
- Python 3.11 이상

## 테스트

```
python -m unittest discover -s tests
```

`native/MediaCopyWorker.exe`가 없으면 네이티브 워커 테스트는 skip된다. 워커를 빌드하려면
`native/build_worker.bat`을 실행한다.
