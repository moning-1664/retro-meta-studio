# 시스템 별칭과 메타데이터 공유 규칙

## 공통 규칙

- 기준 목록: [ES-DE Windows 시스템 설정](https://gitlab.com/es-de/emulationstation-de/-/blob/master/resources/systems/windows/es_systems.xml), 2026-10-02 대조.
- `app/model/constants.py`의 `SYSTEM_ALIAS_GROUPS`를 복붙, Collection/Archive 가져오기, 검색, ScreenScraper ID, RetroArch 코어 조회에서 재사용한다.
- 같은 기기의 지역별 이름·별칭과 메타데이터 공유 계열은 구분한다. MSX/MSX2, MAME/FBNeo, PC88/PC98, PC Engine/PC Engine CD는 메타데이터를 공유하도록 허용한 계열이지만 실행 코어를 합치지는 않는다.
- 폴더명·ROM 경로는 실제 Collection/Archive의 것을 유지한다. 시스템 키는 검색·매칭에만 정규화한다.
- 여러 게임 붙여넣기는 같은 파일명에만 충돌을 판정한다. 파일명이 다른 언어판은 자동 병합하지 않는다. 한 게임을 특정 행에 붙여넣기는 기존 명시적 대상 규칙을 따른다.
- 복사 대상에 원본 시스템이 있으면 그곳을 우선한다. 없고 같은 기기의 별칭 폴더가 하나면 그곳으로 연결한다. 여러 별칭 폴더가 있으면 사용자에게 대상을 지정하도록 요청한다.
- 가져오기 후보는 같은 기기 우선, 없을 때 기존 메타데이터 공유 계열에서 검색한다. 넓은 공유 계열로는 ROM을 교체하지 않는다.

## 동일 기기로 등록한 별칭

| 기준 키 | 별칭 |
|---|---|
| segacd | megacd, megacdjp |
| megadrive | megadrivejp, genesis, md |
| sfc | snes, snesna, superfamicom |
| nes | famicom, fc |
| sega32x | sega32xjp, sega32xna, 32x |
| mastersystem | mark3, sms |
| pcengine | tg16, turbografx16, pce |
| pcenginecd | tg-cd, turbografxcd, pcecd |
| saturn | saturnjp |
| neogeocd | neogeocdjp |
| sg-1000 | sg1000, multivision |
| odyssey2 | videopac |
| msx | msx1 |
| psx | ps1, playstation |
| psvita | vita |
| n3ds | 3ds |
| gc | gamecube |
| pc88 | pc8801 |
| pc98 | pc9801 |

일부 약어는 ES-DE 기본 폴더가 아닌 기존 사용자/다른 frontend 호환 이름이다. 알 수 없는 사용자 폴더를 이름 유사도로 자동 합치지 않는다.

## 공식 플랫폼 값에서 자동 병합하지 않은 항목

공식 XML 전체에서 같은 `<platform>`을 공유하는 항목을 대조했지만 이 값을 별칭 규칙으로 자동 변환하지 않았다.

- `arcade`: Naomi, Atomiswave, Model2/3, Triforce 등 서로 다른 보드도 포함한다. 기존 명시적 Arcade 메타데이터 계열만 사용한다.
- `pcwindows`: Windows와 AGS, Epic, Kodi, Desktop, Emulators 등을 구분한다. 게임 라이브러리와 실행 도구 폴더를 합치지 않는다.
- `android`: androidapps/androidgames는 다른 분류 폴더다.
- `amiga`: amiga600/amiga1200은 모델 차이이며 이번 별칭 확장에 포함하지 않는다.
- `n64/n64dd`, `ngage/symbian`, `moto/to8`: 확장 기기·범용 플랫폼·모델 차이를 같은 기기로 간주하지 않는다.
- `doom/ports/quake`, `lutris/pc`, `daphne/laserdisc`: 엔진·실행 방식·카테고리를 같은 물리 시스템으로 자동 합치지 않는다.
- `dragon32/tanodragon`: 모델/파생 기기의 추가 지원은 별도 검토한다.

## 코어 설정 호환

- 기존 별칭 이름으로 저장한 기본 코어와 게임별 코어도 읽는다. 기존의 서로 다른 별칭 설정이 충돌하면 해당 이름에 직접 저장된 값을 먼저 읽는다.
- 사용자가 코어를 다시 정하거나 해제하면 같은 기기의 기존 별칭 설정을 정리하고 기준 키 하나로 저장한다.
- 설정 UI는 실제 사용/저장 시스템만 나열하며, 별칭 해석 결과 때문에 사용하지 않는 시스템을 추가하지 않는다.
- 게임별 코어는 같은 시스템 별칭과 같은 파일명에만 재사용한다. 메타데이터 공유 계열과 다른 파일명에는 전파하지 않는다.
- ScreenScraper ID가 확인된 기준 시스템의 별칭에만 ID를 연결한다. ID가 없는 시스템을 전체 시스템 검색으로 바꾸지 않는다.

## 검증 (2026-10-02)

- 별칭 쌍, 다른 하드웨어 차단, 가족 계열의 코어 분리, 기존 설정 읽기/변경/해제, 실제 Collection 별칭 붙여넣기, 기존 Archive 별칭 Identity, 다른 파일명 자동 병합 방지를 포함한 새 테스트 78개 통과.
- 첫 전체 테스트에서 Archive 저장 키 변경에 따른 ROM 경로 회귀 2개를 발견했다. 기존 `normalize_system` 저장 키 규칙을 유지하고 별도 `canonical_system`/`same_system` 비교를 사용하도록 고쳤다. 수정 후 Archive·검색·코어 관련 296개 테스트 통과.
- 최종 전체 백엔드: 1605 passed, 1 skipped, 1 xfailed, 42 subtests passed (238.55초).
- 관련 UI: RetroArch·Scraper·복사/붙여넣기 58개 통과 (26.8초). UI는 Chromium 목업이다.
- JavaScript 문법 검사와 git diff --check 통과. 실제 ScreenScraper 서비스 호출이나 RetroArch 실행 파일을 실행한 검증은 포함하지 않는다.
