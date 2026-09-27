# Archive와 Collection 기능 차이 (2026-09-25)

Archive와 Collection은 목록과 상세 UI를 공유하지만 Archive에는 자체 Revision DB, 선택한 Frontend 디렉터리, ROM 디렉터리, 외부 원본 링크가 함께 있다. 쓰기 동작은 각 파일의 소유권을 확인해야 한다.

| 동작 | Archive 상태 | 근거와 남은 일 |
|---|---|---|
| 클릭·Ctrl+클릭·Ctrl+A 다중 선택 | 구현 | 문자열 Archive ID를 유지하고 전체 필터 결과를 선택한다. |
| File/Title/Description 정렬 및 ROM/Metadata/Media 우선 정렬 | 구현 | DB 정렬 후 페이지를 읽는다. |
| Favorites 보기 | 구현 | Archive 메타데이터의 즐겨찾기 값을 사용한다. |
| 복사·붙여넣기 및 Patch/Overwrite/Replace | 구현 | Archive에 직접 적용한다. 다중 Replace는 다른 항목 삭제를 막기 위해 Patch로 전환한다. |
| System을 대상으로 신규 게임만 붙여넣기 | 구현 | 대상 System에 같은 파일명이 있으면 건너뛴다. |
| Archive 보관 ROM 삭제 | 구현 | 설정된 ROM 루트 내부 파일만 삭제한다. 외부 원본 링크는 유지한다. |
| 선택 항목의 Media/Video 삭제, System별 Media 종류 선택 삭제 | 구현 | Archive 보관 파일에만 적용하고 외부 원본을 보존한다. |
| Metadata만 삭제 | 구현 | 현재 gamelist 표시를 제거하는 별도 상태를 DB에 기록한다. ROM, Media, Revision은 유지한다. 새 Archive 편집이나 붙여넣기로 다시 표시할 수 있다. 이 상태 자체는 아직 Revision 이력의 일부가 아니다. |
| Game 전체 삭제 | 제한적으로 구현 | 모든 ROM·Media가 Archive 소유인 게임만 허용한다. 요청 전체의 소유권을 먼저 검사한다. 파일 시스템과 DB를 묶는 트랜잭션은 없어 파일 삭제 중 실패하면 일부 파일만 남을 수 있다. |
| Status 아이콘별 삭제 메뉴 | 구현 | ROM/Metadata/Media/Video를 각각 처리한다. |
| 파일명 첫 글자로 목록 전체 탐색 | 구현 | 현재 필터·정렬 결과에서 찾는다. 큰 Archive에서는 전체 행 해석 비용을 줄일 여지가 있다. |
| 게임을 다른 System으로 이동 | 미구현 | 내부 ROM, Media, Frontend gamelist, DB Identity, Revision 경로를 한 작업으로 옮기고 실패 시 복구해야 한다. 현재 초안은 이 조건을 만족하지 않아 제거했다. |
| System 이름 변경 | 미구현 | 모든 소속 게임 이동과 동일한 경로·충돌·복구 문제를 갖는다. |
| Archive Plan 미리보기·충돌 결정·Apply·취소 | 미구현 | 현재 Archive 편집과 붙여넣기는 즉시 적용된다. Collection Plan은 Collection Cache와 Storage를 전제로 하므로 Archive 전용 계획 및 소유권 검사가 필요하다. |
| 빈 System 생성·숨기기 | 미구현 | Archive 목록은 DB에 항목이 있는 System만 반환한다. 빈 폴더의 표시 상태 모델이 없다. |
| 여러 Internal/External Storage 간 이동 | 모델 없음 | Archive 설정에는 ROM 루트 하나만 있다. 다중 Storage가 필요하면 설정 및 파일 소유권 모델을 먼저 확장해야 한다. |
| Frontend 전용 Collection 설정 | 적용 대상별 판단 | Frontend 투영은 Archive에서도 가능하지만 Collection Storage XML 같은 동작은 동일한 경로 모델이 없다. |

특히 System 이동과 이름 변경은 DB의 System 문자열만 바꿔서는 완료되지 않는다. 기존 Archive 파일과 Revision 참조가 깨질 수 있으므로 파일 이동·Frontend 갱신·DB 갱신의 실패 복구 설계가 먼저 필요하다.
