# Archive Directory Design (2026-09-21)

## 문제
- Archive의 진실이 `archive.db` 한 곳에 있어 사용자가 꺼내 쓸 수 없다.
- 샘플(`Archives/`)을 보면 사용자 눈에 보이는 ES-DE 결과물이 매우 부분적이다
  (gamelist.xml 3개 system, downloaded_media 2.3k개) 반면 `.rms/media/<system>/<id>/`에
  22.9k개가 숨어 있다.

## 원칙
1. **디렉토리가 진실이다.** Archive 디렉토리는 사용자가 지정한 Frontend 형식
   (기본 ES-DE)의 완전한 Collection이다: `gamelists/`, `downloaded_media/`, (선택) ROM.
   Archive를 Collection처럼 열면 그대로 읽힌다.
2. **DB는 색인이다.** `<archive>/.rms/archive.db`는 Revision, 출처, conflict, preferred만
   관리한다. 지워도 디렉토리에서 다시 만들 수 있어야 한다.
3. **미디어는 한 곳에만 둔다.** `.rms/media/<system>/<identity>/` 같은 숨은 사본을 새로
   만들지 않는다. Frontend 규칙 위치(`downloaded_media/<system>/<type>/<stem>.ext`)가 원본이다.
4. Archive 설정: `frontend`, `archiveDir`, `romDir`(선택), `mediaInternal`(bool).
   설정 화면과 Archive 첫 화면([Archive 설정])에서 같은 값을 바꾼다.

## 단계
1. 설정 + 투영(projection) 쓰기: ingest 후 resolved fields/media를 Adapter로 디렉토리에 쓴다.
2. 기존 Archive 읽기: 디렉토리를 스캔해 DB를 재구성하고, 옛 `.rms/archive.db`와
   `.rms/media`는 1회 이관 후 사용하지 않는다.
3. Matching/conflict 재정의(값이 다를 때만, 중요 필드 기준).
4. Archive 안에서 미디어 복붙, ROM 실행, ROM only 표시.
