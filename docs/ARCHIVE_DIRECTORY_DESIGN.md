# Archive Directory Design (2026-09-21)

## Portable DB cache (2026-09-24)

The running SQLite WAL database remains on the local PC. After Archive Apply or
an explicit directory refresh, the app publishes a consistent single-file
snapshot to `<archive>/.rms/archive.db`. Another PC loads that snapshot into an
empty local DB, or replaces a local DB only when it still matches the last
snapshot that PC read. A changed shared snapshot is never overwritten by a
stale local copy; the app reports a conflict and keeps the local DB.

The Archive tab reads the local DB immediately. Directory reconciliation is
explicit via "디렉터리 다시 읽기". Simultaneous edits on multiple PCs do not merge
automatically. The snapshot is a cache exchange, not a multi-writer database.

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
3. **현재 미디어는 Frontend 위치에 둔다.** `mediaInternal=true`일 때 현재 표시본은
   Frontend 규칙 위치(`downloaded_media/<system>/<type>/<stem>.ext`)가 원본이다.
   과거 Revision만 `.rms/revision-media`에 불변 스냅샷으로 보존한다.
4. Archive 설정: `frontend`, `archiveDir`, `romDir`(선택), `mediaInternal`(bool).
   설정 화면과 Archive 첫 화면([Archive 설정])에서 같은 값을 바꾼다.

## 단계
1. 설정 + 투영(projection) 쓰기: ingest 후 resolved fields/media를 Adapter로 디렉토리에 쓴다.
2. 기존 Archive 읽기: 디렉토리를 스캔해 DB를 재구성하고, 옛 `.rms/archive.db`와
   `.rms/media`는 1회 이관 후 사용하지 않는다.
3. Matching/conflict 재정의(값이 다를 때만, 중요 필드 기준).
4. Archive 안에서 미디어 복붙, ROM 실행, ROM only 표시.

## 자산 소유권
- 설정한 `romDir`(없으면 `archiveDir`) 안의 ROM은 **Archive 보관**이다.
- `mediaInternal=true`로 Frontend 위치에 만든 Media 복사본은 **Archive 보관**이다.
- 그 밖의 Collection 경로는 **원본 연결**이다.
- 한 항목에 두 종류가 함께 있으면 **혼합**으로 표시한다.
- Archive 보관 파일은 Archive에서 삭제·이동할 수 있다. 원본 연결 파일은 읽기와 복사만
  허용하며, 삭제는 Archive의 연결 또는 제거 상태만 바꾸고 외부 파일은 건드리지 않는다.
- Archive 항목 복사는 보관/연결 여부와 무관하게 공용 클립보드에 내보낼 수 있다. 이후
  Collection에 붙여넣을 때 기존 Collection의 Plan과 충돌 처리를 그대로 사용한다.
- Archive로 붙여넣으면 Metadata는 Archive 편집 Revision이 되고, ROM은 설정한 `romDir`
  아래로 복사된다. 같은 ROM 파일이 이미 있으면 덮어쓰지 않는다. Media는
  `mediaInternal=true`일 때 Archive 복사본으로 투영하고, 꺼져 있으면 원본을 연결한다.

## 성능 진단
- 설치본은 실행 파일 옆 `logs/retrometa.log`, 개발 실행은 프로젝트의
  `logs/retrometa.log`에 Archive 적용 대기/시작, 읽기·Revision·Frontend·공유 DB 단계 시간,
  목록 페이지 조회와 버전 충돌 계산 시간을 기록한다. 파일은 2MB씩 최대 3개로 순환한다.
- `mediaSeconds`는 파일 복사 시간만 뜻하지 않는다. 미디어 참조 조회·경로 비교·
  파일 상태 확인도 포함한다. `mediaLookupSeconds`로 조회 시간을 분리해 볼 수 있다.
- 목록의 ROM 소유권 표시는 기록된 경로를 문자열로 비교한다. 파일 삭제·이동 등
  실제 파일 작업에서는 경로를 해석해 안전 경계를 다시 확인한다.
