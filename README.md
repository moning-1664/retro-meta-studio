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

**Phase 7까지 완료.** `python main.py`로 실행된다. Collection 등록·스캔·탐색·메타데이터
편집, Plan을 통한 복사/삭제/Storage 이동(인스턴스 간 복사 포함), 그리고 여러 Collection의
Metadata를 출처와 함께 모으는 Archive, 그리고 이름이 어긋난 항목을 사람이 이어주는
Match까지 동작한다.

| Phase | 내용 | 상태 |
|---|---|---|
| 0 | 저장소 스키마·마이그레이션, 다중 인스턴스 기반, Provider/Adapter 인터페이스, 레거시 정리 | 완료 |
| 1 | Core Model + ES-DE Adapter + Cache 스캔 | 완료 |
| 2 | Collection UI (탭/헤더/내비/Gamelist) + 기존 Detail 패널 연결 | 완료 |
| 3 | Plan (Auto Plan·용량 계산·Apply·인스턴스 간 복사/붙여넣기) | 완료 |
| 4 | Archive (Source Tracking·Revision·Archive→Collection) | 완료 |
| 5 | Match (Exact → Normalized → Heuristic 후보 UI) | 완료 |
| 6 | Compare Mode (Same/Only A/Only B/Conflict + 좌우 Detail 비교) | 완료 |
| 7 | 나머지 Frontend Adapter(Pegasus/LaunchBox/EmulationStation) + Round-trip 검증 + ES-DE custom systems XML | 완료 |
| 8 | MTP Provider (선택) | 필요성 재평가 후 |

## 구조

```
app/          Collection·Plan·Archive·Match·Compare·Scan 등 모든 비즈니스 로직
├── model/      순수 데이터 모델
├── store/      SQLite 저장소 (registry / cache / archive)
└── paths.py    앱 데이터 위치
adapters/     Frontend Adapter (읽기+쓰기를 한 곳에서 책임)
storage/      물리 접근 추상화 (Local/UNC, 후에 MTP)
engines/      파일 복사 엔진 (Robocopy 기본 / 네이티브 워커 대안) + file_ops.py
bridge/       pywebview 브릿지와 Job 큐
gui_web/      웹 UI (셸 + 가상 스크롤 Gamelist + 기존 Detail 패널)
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

백엔드:

```
python -m unittest discover -s tests
```

`native/MediaCopyWorker.exe`가 없으면 네이티브 워커 테스트는 skip된다. 워커를 빌드하려면
`native/build_worker.bat`을 실행한다.

### ES-DE 외 Frontend 호환성

`tests/test_frontend_compat.py`는 "우리 왕복이 맞는가"가 아니라 **"각 Frontend의 공식
포맷 규칙에 맞는가"**를 본다. 둘은 다르다 - Pegasus의 rating 스케일이 틀렸을 때
`test_adapters.py`의 ES-DE → Pegasus → ES-DE 왕복은 통과했다. 읽기와 쓰기가 **같은
방식으로 틀려서** 대칭으로 상쇄됐기 때문이다. 아직 못 고친 것은 `expectedFailure`로
박혀 있어서, 고치면 unexpected success로 suite가 실패해 알려준다.

그래도 "우리 코드가 포맷 문서대로인가"까지다. **그 결과를 Frontend가 실제로 화면에
띄우는가**는 물려 봐야 안다:

```
python -m tools.make_test_pack <출력 폴더>
```

4개 Frontend의 공식 배치대로 작은 라이브러리를 만든다. ROM은 내용이 `TEST ROM`인
텍스트 파일이라 실행되지 않고, 검증 대상도 파일 발견 / 메타데이터 / media 표시까지다.
각 이미지에 게임 이름과 media 종류가 그려져 있어서 `Box - Front` 자리에 `COVERS`가
보이는지로 슬롯이 맞게 붙었는지 눈으로 판정한다. 케이스별로 무엇을 왜 보는지는 생성된
`CHECKLIST.md`에 있다.

GUI (Playwright, 헤드리스 Chromium):

```
npm install
npx playwright install chromium
npx playwright test
```

`gui_web/`은 pywebview가 없으면 `api-client.js`가 내장 목업으로 폴백하므로(`api.isMock()`),
실제 앱을 띄우지 않고도 클릭/입력/스크롤 시나리오를 검증할 수 있다. 목업에 없는 호출은
`{ok:false}`가 되어 그 화면이 조용히 오류 경로만 지나가므로, `tests/test_wiring.py`가
`app.js → api-client.js → bridge/api.py`의 이름·인자 개수와 **목업 커버리지**를 함께
감시한다. 네이티브 폴더 대화상자, 실제 파일 I/O, WebView2 고유 렌더링은 여전히 실기
확인이 필요하다.

## 파일 복사 엔진

대량 파일 작업을 앱이 직접 하면 백신의 행동 기반 탐지에 걸린다. 그래서 실제 작업은
별도 프로세스에 맡기며, 두 가지 엔진을 지원한다.

| 엔진 | 설명 |
|---|---|
| **Robocopy** (기본) | Windows 내장, 마이크로소프트 서명 바이너리. 백신이 문제 삼지 않는다 |
| Native Worker | 자체 `MediaCopyWorker.exe`. 서명이 없어 AhnLab에 탐지된 사례가 있다 |

설정은 `copy_engine`(`auto`/`robocopy`/`worker`)이며 기본값 `auto`는 Robocopy를 우선한다.
