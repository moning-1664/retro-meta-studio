# MANUAL_GUI_TEST_CHECKLIST.md

개발 환경(샌드박스)에는 네트워크가 차단되어 있어 **tkinter 자체를 설치할 수 없었습니다.**
아래 항목은 코드 리뷰와 정적 검증(문법 검사, self.method 교차 참조 검증, BT 레벨 로직 테스트)까지는
마쳤지만, 실제 Windows에서 tkinter가 렌더링하는 결과는 확인하지 못했습니다.
`python main.py`로 실행 후 아래 항목을 순서대로 확인해주세요.

## 1. 최초 실행 / MasterDB 강제 설정
- [ ] config.json이 없는 상태로 최초 실행 시 MasterDB 경로 설정 대화창이 뜨는가
- [ ] 대화창에서 **취소**를 눌러도 화면이 빈 채로 멈추지 않고 안내 문구(또는 Local 화면)가 보이는가
- [ ] 경로를 지정하고 **확인**을 누르면 상단 MASTER DB 카드가 즉시 갱신되는가

## 2. Local 등록 (+)
- [ ] Frontend를 Pegasus로 선택하면 ROM 경로 입력란이 회색(비활성)으로 바뀌고 Metadata 경로 값이 그대로 미러링되는가
- [ ] "구조 검사" 클릭 시 색상(초록/주황/빨강)과 메시지가 상황에 맞게 표시되는가
- [ ] 완전히 빈 폴더를 지정해도 앱이 죽지 않고 경고 메시지로 처리되는가

## 3. 시스템 이름 매핑 (Pegasus 등)
- [ ] Local 화면 좌측 필터 패널의 "시스템 이름 매핑" 버튼 클릭 시 감지된 시스템 목록이 뜨는가
- [ ] 매핑을 저장한 뒤 Export to MasterDB 실행 시 올바른 시스템으로 매칭되는가 (Dashboard에서 확인)

## 4. 목록 정렬 / 마우스 스크롤
- [ ] Local/MasterDB 화면 모두에서 컬럼 헤더 클릭 시 오름차순 → 재클릭 시 내림차순으로 바뀌는가 (헤더에 ↑/↓ 표시)
- [ ] 목록에 스크롤바가 보이고, 마우스 휠로 스크롤되는가
- [ ] 창을 작게 줄였을 때도 스크롤로 전체 목록에 접근 가능한가

## 5. 한글 입력 (Description 필드)
- [ ] MasterDB 화면에서 게임 선택 후 Description(Text 위젯)에 한글을 빠르게 입력할 때
      글자가 밀리거나 커서 위치가 깨지지 않는가
- [ ] 문제가 재현되면: 사용 중인 Python의 Tcl/Tk 버전을 `python -c "import tkinter; print(tkinter.TkVersion)"`로
      확인해주세요. 8.6.10 미만이면 최신 Python(3.11+ 권장, Tcl/Tk 8.6.12+ 번들)으로 업그레이드가
      가장 확실한 해결책입니다.

## 6. Ctrl+X / Ctrl+V / Ctrl+Z
- [ ] 단일행 Entry 필드(Title, Genre 등)에서 Ctrl+C/V/X가 동작하는가 (Tk 기본 지원)
- [ ] 같은 필드에서 Ctrl+Z(실행 취소)가 실제로 이전 값으로 되돌아가는가
      (utils.bind_entry_undo_redo로 수동 구현됨 - 여러 번 눌러 히스토리가 순서대로 되돌아가는지 확인)
- [ ] Description(Text 위젯)에서도 Ctrl+Z/Ctrl+Shift+Z(Redo)가 동작하는가 (Tk Text 자체 undo=True 기능)

## 7. Ctrl+S 저장
- [ ] MasterDB 게임 상세 화면에서 필드를 수정한 뒤 Ctrl+S를 누르면 저장되는가
- [ ] 저장 후 하단 상태바에 "저장 완료 (파일명) - HH:MM:SS" 형태로 표시되는가
- [ ] 저장 버튼 클릭과 Ctrl+S가 동일하게 동작하는가

## 8. 설정 자동 저장
- [ ] Export 설정, Core 설정 등을 변경한 뒤 **앱을 창 닫기(X) 버튼으로 종료**했다가 다시 열었을 때
      변경사항이 유지되는가
- [ ] config.json의 `ui.auto_save_interval_min`에 짧은 값(예: 1)을 넣고, 그 시간 동안 대기 후
      다른 값을 변경하지 않고 강제 종료(작업관리자 등)해도 마지막 주기적 자동저장 시점까지는
      반영되어 있는가

## 9. 기타
- [ ] Dashboard의 원형 그래프(matplotlib)가 정상적으로 그려지는가 (미설치 시 텍스트 통계만 표시되어야 함)
- [ ] 다중 선택 후 우클릭 메뉴(선택 항목 Export, 일괄 스크랩)가 정상적으로 뜨는가
- [ ] System 우클릭 메뉴(Export, RetroArch Export, Core 설정, 시스템 전체 스크랩)가 정상적으로 뜨는가

---
문제가 발견되면 `MODULE_MAP.md`의 빠른 참조표를 보고 **해당 파일만** 알려주시면 됩니다.
