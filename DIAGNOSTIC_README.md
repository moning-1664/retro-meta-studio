# Retro Metadata Manager v0.4.0.21 Diagnostic Build

이 빌드는 동작을 바꾸기 위한 버전이 아니라 Local/MasterDB 상태 전환과 Preview Cover 문제를 추적하기 위한 진단용 빌드입니다.

## 로그 위치

실행 파일(개발 실행이면 소스 폴더) 아래에 자동 생성됩니다.

`logs/retro_manager_diagnostic.log`

앱을 새로 실행할 때 로그 파일은 비워지고 현재 실행 세션만 기록됩니다.

## 권장 재현 순서

1. 문제가 재현되는 기존 MasterDB를 설정한 상태에서 앱 실행
2. Local 선택
3. GameList가 나오거나 나오지 않는 상태까지 기다림
4. MasterDB로 이동
5. 다시 동일 Local로 이동
6. Preview/Card View로 전환
7. 우측 Metadata에서 대표 이미지가 정상인 게임 하나를 클릭
8. Dashboard로 이동했다가 다시 Local로 이동
9. 앱 종료
10. `logs/retro_manager_diagnostic.log` 파일 전체를 전달

비교용으로 빈 MasterDB에서도 같은 순서를 한 번 수행하면 더 좋습니다. 두 실행은 로그가 덮어써지므로 첫 로그를 다른 이름으로 복사한 뒤 두 번째 테스트를 수행하세요.

## 기록하는 핵심 이벤트

- Python Local scan 시작/종료, 시스템 수, gamelist 항목 수
- Local scan 결과의 game count / Missing ROM / hasCover count
- MasterDB game count / cover count
- Web GUI의 view 전환과 Local cache 상태
- 필터 전/후 GameList 수
- Preview DOM 실제 카드 수
- Preview cover 요청/응답
- 우측 Metadata media 조회 결과
- JavaScript exception / unhandled Promise rejection

## 특히 확인할 가설

현재 v0.4.0.21 코드에는 ROM이 없는 metadata-only ES-DE 항목에 대해 scan 단계의 media 검사를 건너뛰는 경로가 있습니다. 그 경우 GameList 항목의 `hasCover`가 false가 되어 Card View가 cover API를 호출하지 않지만, 우측 Metadata는 media를 직접 조회하여 이미지가 보일 수 있습니다. 이 진단 빌드는 해당 상태를 명시적으로 기록합니다.
