# Scraper 설계

- 상태: 구현 기준안
- 대상: ScreenScraper 우선, 이후 TheGamesDB·RetroDB 확장
- 원칙: 기존 `scraper/screenscraper.py`의 구조와 계약을 승계하지 않고 새로 구현한다.

---

## 1. 목표

Scraper는 ROM을 외부 서비스의 게임과 식별하고, 여러 후보의 메타데이터와 미디어를
사용자가 비교한 뒤 현재 Collection 또는 Archive에 선택적으로 반영하는 기능이다.

외부 서비스의 응답은 참고 자료다. 응답을 곧바로 프로젝트 데이터로 저장하지 않는다.
검색, 후보 선택, 변경 검토, 적용을 서로 다른 단계로 둔다.

```text
ROM 정보
  -> 식별 요청
  -> 공급자 후보
  -> 공통 후보 모델로 정규화
  -> 사용자 비교·선택
  -> 변경안
  -> Collection 메타데이터 저장·미디어 Plan 또는 Archive Revision
```

## 2. 설계 원칙

1. **현재 작업 대상을 기준으로 적용한다.** 별도의 MasterDB를 만들지 않는다.
2. **후보는 자동 확정하지 않는다.** 해시는 식별 근거 중 하나이며 적용 전 검토 화면을 거친다.
3. **메타데이터와 미디어를 따로 고른다.** 제목은 한 후보, 표지는 다른 후보에서 가져올 수 있다.
4. **출처를 보존한다.** 공급자, 원격 게임 ID, 조회 시각, 매칭 근거를 적용 결과와 함께 기록한다.
5. **공급자 차이는 경계 안에 가둔다.** UI와 Collection·Archive 저장 로직은 공급자별 응답 형식을 알지 않는다.
6. **요청 수를 통제한다.** 검색 변형, 재시도, 미디어 조회는 명시적인 요청 예산 안에서 수행한다.
7. **오류와 검색 결과 없음은 구분한다.** 인증, 제한, 네트워크, 파싱, 결과 없음 상태를 각각 표시한다.

## 3. 범위

### 3.1 1차 범위

- ScreenScraper 연결 및 계정 상태 확인
- 선택한 게임 한 개 또는 여러 개의 스크랩 작업
- ROM 해시 조회와 제한된 이름 검색
- 후보 비교 및 하나 이상의 공급자 결과 병합 준비
- 필드별 메타데이터 선택
- 유형별 미디어 선택
- Collection과 Archive에 동일한 검토 UX 제공
- 적용 출처 기록
- 요청 진행률, 취소, 할당량과 오류 표시

### 3.2 후속 범위

- TheGamesDB·RetroDB 공급자 추가
- 시스템 전체 무인 자동 적용
- 사용자 선택 이력 기반 추천
- 여러 공급자 사이의 자동 우선순위 학습
- 대규모 미디어 선다운로드

## 4. 구성 요소

```text
gui_web/
  Scrape Dialog       후보 비교, 필드·미디어 선택, 변경 확인
  Scrape Queue        항목별 상태, 진행률, 재시도, 취소

bridge/
  Scrape API          입력 검증과 DTO 변환만 담당

app/scrape/
  service             전체 흐름 조정
  identity            ROM 식별 정보와 검색 변형 생성
  normalize           공급자 응답을 공통 후보로 변환
  rank                후보 정렬과 근거 계산
  proposal            선택 결과를 변경안으로 생성
  provenance          적용 출처 기록

app/scrape/providers/
  base                공급자 공통 계약
  screenscraper       ScreenScraper API 구현
  thegamesdb          후속 구현
  retrodb             후속 구현

app/store/
  scraper             조회 캐시, 작업 상태, 출처 저장

기존 경계
  Collection 적용     메타데이터 즉시 저장, 미디어는 Plan
  Archive Service     Archive edit revision 반영
  JobManager          긴 조회·해시·다운로드의 진행과 취소
```

`bridge/api.py`에는 검색 규칙, 점수 계산, 공급자 응답 해석을 넣지 않는다.

## 5. 공급자 공통 계약

각 공급자는 다음 능력을 선택적으로 구현한다.

```text
get_account_status(credentials) -> AccountStatus
identify_rom(identity, system_hint) -> CandidateSet
search_games(query, system_hint) -> CandidateSet
get_game(remote_game_id) -> ProviderGame
list_media(remote_game_id) -> ProviderMedia[]
```

공급자 기능 차이는 capability로 선언한다.

- 지원 해시: CRC32, MD5, SHA1
- 파일 크기·파일명 힌트 지원 여부
- 이름 검색 지원 여부와 최대 후보 수
- 계정별 동시 요청 수와 할당량 정보
- 지원 언어, 지역, 미디어 유형

서비스는 capability에 없는 요청을 만들지 않는다.

## 6. 공통 후보 모델

후보는 원본 응답과 UI용 정규화 결과를 함께 가진다.

```text
ScrapeCandidate
  candidate_id             앱 내부 임시 ID
  provider                 screenscraper | thegamesdb | retrodb
  remote_game_id
  system                   공급자 시스템 ID와 정규화된 시스템
  names[]                  언어·지역별 제목
  metadata                 설명, 장르, 개발사, 발매일, 등급 등
  media[]                  유형, 언어, 지역, 크기, 원격 위치
  match_evidence[]          sha1, md5, crc32, size, filename, title 등
  confidence               정렬용 점수
  confidence_reason        사람이 이해할 수 있는 근거
  source_url
  fetched_at
  raw_payload_ref          진단용 원본 캐시 참조
```

`confidence`는 후보 정렬에만 사용한다. 일정 점수 이상이라는 이유로 자동 적용하지 않는다.

## 7. 식별과 검색 순서

한 ROM에 대한 기본 순서는 다음과 같다.

1. 저장된 해시 캐시를 확인한다.
2. 필요한 해시를 백그라운드에서 한 번의 파일 읽기로 계산한다.
3. 일반 게임 DB와 패치·로컬라이징 DB에 해시, 파일 크기, 파일명, 시스템 힌트를 질의한다.
4. 패치 DB가 원작 게임을 가리키면 그 연결을 따라 일반 게임 DB의 메타데이터 후보를 찾는다.
5. 유효한 후보가 없으면 정리된 표시 이름으로 검색한다.
6. 이름 변형은 제한된 수만 사용하며 각 후보에 사용한 검색어를 기록한다.
7. 결과를 정규화하고 같은 게임을 가리키는 후보를 묶는다.

이름 변형은 괄호 속 지역·리비전·덤프 표식을 제거한 기본 이름을 중심으로 만든다. 구두점과
공백 변형은 최대 2~3개로 제한한다. 모든 변형을 조합해 요청 수가 늘어나는 방식은 쓰지 않는다.

압축 파일과 다중 디스크 게임은 별도 identity 정책을 둔다. 임의로 첫 파일만 대표 ROM으로
확정하지 않는다.

### 7.1 패치 ROM과 교차 확인

한글 패치, 번역, 개조, 트레이너 적용 ROM은 바이트가 달라지므로 원본 ROM의 해시와 일치하지
않는 것이 정상이다. 따라서 해시 불일치를 `다른 게임`으로 판정하지 않는다.

후보 식별 근거는 다음처럼 축적한다.

```text
직접 근거
  패치 ROM 해시 -> 패치·로컬라이징 DB 항목

연결 근거
  패치 DB 항목 -> 원작 게임 ID·원작 제목·대상 시스템

보조 근거
  파일명, 정리된 제목, 지역 태그, 언어 태그, 파일 크기

일반 메타데이터
  원작 게임 -> ScreenScraper·TheGamesDB 등의 후보
```

후보 카드에는 `패치 해시 일치`, `원작 연결`, `제목 일치`처럼 근거의 경로를 보여준다.
패치 DB 결과와 일반 DB 결과를 하나로 합치더라도 각각의 출처와 원격 ID는 모두 보존한다.
패치 DB에 없는 ROM은 이름과 시스템 기반 후보 탐색으로 계속 진행한다.

실제 파일에서 계산한 해시를 원본 해시로 덮어쓰지는 않는다. 두 값은 역할이 다르며 함께
보존한다.

```text
observed_identity
  현재 사용자가 가진 파일의 hash, size, filename

lookup_alias
  외부 패치 DB가 제공한 원본 ROM의 hash, size, canonical title
  source provider, patch id, mapping confidence
```

공급자 조회에는 `lookup_alias`를 사용할 수 있지만 결과 provenance에는 실제 파일과 조회 alias를
모두 기록한다. 원본 해시만 있고 원본 파일 크기가 없다면, 크기를 함께 요구하는 공급자의 직접
ROM 조회에는 사용하지 않고 원작 제목·시스템 후보를 만드는 근거로만 쓴다.

2026-09-23 확인 기준으로 RetroDB 공개 한글패치 목록과 개별 상세 페이지에는 ROM의 CRC·MD5·
SHA 해시가 노출되지 않는다. 공개 데이터에서 사용할 수 있는 연결은 패치 제목·버전·시스템과
IGDB 원작 게임이다. 따라서 초기 RetroDB 연동은 이 원작 게임 연결로 정규 제목과 시스템을 얻어
ScreenScraper 후보 검색을 보강한다. 향후 공식 API가 패치 결과 해시와 원본 해시·크기를 함께
제공하면 `lookup_alias` provider로 확장한다.

## 8. 검토와 적용 UX

### 8.1 공통 후보 목록

후보는 현재 Detail 열과 같은 폭의 세로 카드 목록으로 표시한다. 현재 UI 기준 폭은 297px이며,
고정 숫자를 새로 중복 정의하지 않고 Detail 열의 폭 token을 공유한다. Scraper와 Revision 비교가
같은 자리에 나타나므로 목록 폭이나 주변 GameList 배치가 바뀌지 않는다.

단건과 배치 모두 전용 스크랩 컨텍스트를 연다. 컨텍스트의 실제 콘텐츠 폭은 Detail과 같은
297px이고, 선택한 게임을 한 번에 하나씩 순서대로 처리한다. 여러 게임의 모든 후보 카드를
한꺼번에 가로로 펼치지 않는다.

한 화면에서 여러 후보를 빠르게 훑을 수 있도록 기본 카드는 작지만 정보 밀도를 높인다.

```text
┌ 표지 ─┬ 게임명              [SS]
│       │ 시스템 · 연도 · 지역 · 언어
│       │ 패치 해시 > 원작     높음  [∨]
└───────┴──────────────────────────
```

접힌 카드에는 다음 정보만 항상 보인다.

- 작은 대표 이미지
- 대표 제목과 대체 제목 하나
- 시스템, 발매연도, 지역, 언어
- 공급자
- 가장 중요한 매칭 근거와 신뢰도 등급
- 현재 후보가 패치판인지 원작 메타데이터인지 구분하는 표시

`∨`를 누르면 카드가 그 자리에서 확장된다. 확장 영역에는 다음을 표시한다.

- 전체 제목·지역·언어 목록
- 설명, 장르, 개발사, 퍼블리셔, 발매일
- 후보를 만든 모든 근거와 조회 경로
- 공급자별 원격 ID와 출처 링크
- 사용할 수 있는 미디어의 유형·수·지역·언어
- 현재 데이터와 달라지는 필드 요약

후보 하나를 선택하면 카드 테두리와 체크 표시로 선택 상태를 유지한다. 확장과 선택은 별개다.
사용자는 여러 카드를 펼쳐 놓고 비교할 수 있다.

297px 안에서 읽히도록 접힌 카드는 대표 이미지와 정보 영역의 2열만 사용한다. 긴 공급자 이름과
근거는 짧은 badge로 보여주고 전체 문구는 확장 영역에 둔다. 확장 영역은 다시 여러 열로 나누지
않고 한 열로 흐르게 한다. 화면이 좁아져도 Detail 최소 폭 아래로 카드를 압축하지 않고 기존
Detail 열의 표시·숨김 규칙을 따른다.

### 8.2 단건

1. 사용자가 게임의 `스크랩`을 누른다.
2. 후보 카드 목록에서 제목, 시스템, 지역, 패치·원작 연결 근거를 비교한다.
3. `∨`로 카드를 펼치면 현재 값과 가져올 값을 필드별로 고를 수 있다.
4. 메타데이터 필드와 미디어 유형을 각각 선택한다.
5. 후보를 선택하고 현재 작업 대상에 저장한다.

반환된 메타데이터 필드는 기본 선택되고 사용자가 체크를 해제할 수 있다. ROM 경로, 내부 ID,
frontend 전용 확장 데이터는 후보 필드에 포함하지 않는다.

### 8.3 여러 게임

배치 실행은 항목마다 다음 상태를 표시한다.

```text
대기 -> 해시 계산 -> 검색 중 -> 검토 필요 -> 적용 준비 -> 적용 완료
                              -> 결과 없음
                              -> 인증 오류 | 할당량 대기 | 네트워크 오류 | 응답 오류
```

전용 컨텍스트에서 `1번 검색 -> 후보 선택 -> 2번 검색 -> 후보 선택` 순서로 진행한다. 이전과
건너뛰기를 제공하고, 모든 항목을 검토해야 최종 적용 버튼이 활성화된다. 검색 키와 시스템 힌트는
항목마다 직접 바꿔 다시 검색할 수 있다. 우측 상단에는 확인된 일일 요청 사용량을 계속 표시한다.
취소하면 진행 중인 요청과 임시 세션을 함께 닫는다.

### 8.4 Revision 비교와 공통 UI

Scraper 후보와 Archive revision은 출처가 다르지만 사용자가 하는 일은 같다. 여러 버전을
간략히 훑고, 필요한 카드를 펼쳐 보고, 사용할 필드와 미디어를 고른다. 따라서 하나의
`CandidateList`와 `CandidateCard` UI를 사용하고 입력 데이터만 adapter로 바꾼다.

```text
CandidateViewModel
  id
  sourceLabel              ScreenScraper | 패치 DB | Collection 이름 | Archive edit
  title, subtitle
  thumbnail
  badges[]                 시스템, 지역, 언어, revision 번호 등
  evidence[]               스크랩 후보에만 존재할 수 있음
  summaryFields[]
  detailFields[]
  media[]
  changedFields[]
  selectedFields[]
  selectedMedia[]
```

- Scraper adapter는 공급자 후보와 매칭 근거를 이 모델로 변환한다.
- Archive adapter는 revision, 출처 Collection, ownership, 변경 시각을 이 모델로 변환한다.
- 카드 목록, 펼침 상태, 필드 선택, 미디어 선택 구조를 공유할 수 있게 유지한다.
- 실제 적용 동작만 Scrape proposal과 Archive preferred/edit revision으로 나뉜다.

## 9. Collection과 Archive 반영

Scraper가 만드는 최종 산출물은 저장 결과가 아니라 `ScrapeProposal`이다.

### 9.1 Collection

- 메타데이터는 기존 Collection 편집 정책에 따라 저장한다. 로컬 Collection은 즉시 저장하고,
  기기 Collection은 기존 메타데이터 Plan을 사용한다.
- 미디어 다운로드·복사도 기존 파일 작업 Plan을 통과한다.
- 후보 검토가 끝나기 전에는 gamelist와 파일을 바꾸지 않는다.

### 9.2 Archive

- 메타데이터 변경은 Archive 자체 편집 revision으로 기록한다.
- `mediaInternal=true`이면 선택한 미디어를 Archive 소유 경로로 가져오고 revision에 기록한다.
- `mediaInternal=false`이면 외부 URL을 영구 원본 링크처럼 취급하지 않는다. 사용자가 내려받을
  Collection 위치를 선택하거나 미디어 적용을 제외하도록 안내한다.
- 기존 revision과 원본 Collection의 provenance는 덮어쓰지 않고 scraper provenance를 추가한다.

같은 후보와 선택 내용으로 만든 proposal은 대상에 따라 적용기만 달라진다.

## 10. 미디어 정책

- 미디어는 `cover`, `box2d`, `box3d`, `screenshot`, `title`, `fanart`, `marquee`,
  `video`, `manual` 같은 공통 유형으로 정규화한다.
- 공급자 원본 유형과 지역·언어 정보도 보존한다.
- 1차 구현은 유형마다 하나를 고른다.
- 목록에서는 썸네일만 읽고, 실제 파일은 적용안이 확정된 뒤 받는다.
- 1차 구현은 공급자 URL 해시를 다운로드 캐시 키로 사용한다.
- 다운로드 실패는 메타데이터 적용과 분리해 재시도할 수 있다.

## 11. 자격 증명과 보안

ScreenScraper의 자격 증명은 두 종류로 분리한다.

- 애플리케이션 개발자 정보: `devid`, `devpassword`, `softname`
- 사용자 계정 정보: `ssid`, `sspassword`

비밀번호는 SQLite, 로그, Git 추적 파일에 평문으로 저장하지 않는다. Windows 자격 증명
관리자를 우선하고 사용할 수 없는 실행 환경에서는 Windows DPAPI로 암호화한다. DB에는
secret reference 또는 암호문만 둔다. API 요청 로그에는 비밀번호와 전체 요청
URL을 남기지 않는다. 개발자 debug password는 제품 설정과 요청에 포함하지 않는다.

설정 화면은 다음 정보만 보여준다.

- 공급자 사용 여부
- 사용자 ID와 비밀번호 입력
- 연결 테스트 결과
- 허용 동시 요청 수와 확인 가능한 할당량
- 마지막 성공·오류 시각

개발자 자격 증명은 사용자 계정 입력과 분리해 배포 설정 또는 로컬 secret로 공급한다.

## 12. 캐시와 저장 데이터

영속 데이터는 역할별로 나눈다.

- `rom_hash_cache`: 파일 identity, CRC32, MD5, SHA1, 계산 시각
- `scrape_response_cache`: 공급자, 요청 identity, 만료 시각, 원본 payload 참조
- `scrape_job`: 배치와 항목 상태, 오류 종류, 재시도 정보
- `scrape_provenance`: 적용 대상, 필드·미디어, 공급자, 원격 ID, 적용 시각

해시 캐시는 경로만으로 재사용하지 않는다. 파일 크기와 수정 시각을 빠른 판정에 쓰고,
불일치하면 다시 계산한다. 공급자 응답 캐시는 삭제해도 복구 가능한 cache DB에 둔다.
provenance는 사용자 데이터이므로 registry 또는 archive의 영속 저장소에 둔다.

## 13. 요청 제어와 오류

- 계정 상태가 알려주는 동시 요청 수와 요청 제한을 우선한다.
- HTTP 상태와 공급자 오류 코드를 분류해 재시도 가능 여부를 결정한다.
- 지수형 대기와 서버의 retry 정보가 있으면 함께 사용한다.
- 인증 실패와 일일 제한은 자동 재시도하지 않는다.
- 검색 결과 없음은 실패 횟수로 기록하지 않는다.
- 취소 시 새 요청을 만들지 않고 진행 중인 응답과 임시 파일을 정리한다.

## 14. 구현 순서

1. 공통 모델과 provider 계약
2. secret 저장과 ScreenScraper 계정 상태 확인
3. ROM identity·CRC32/MD5/SHA1 단일 스트림 계산
4. ScreenScraper 식별·이름 검색·정규화
5. 후보 비교와 필드·미디어 선택 UI
6. `ScrapeProposal`과 Collection 메타데이터·미디어 Plan 적용
7. Archive revision·media ownership 적용
8. 배치 queue, 취소, 제한 대응
9. provenance와 진단 화면
10. TheGamesDB provider 추가

기존 `scraper/screenscraper.py`는 새 흐름을 호출하는 호환 계층으로 만들지 않고 삭제한다.
현재 구현은 `app/scrape/`의 provider 계약과 세션 서비스만 사용한다.

## 15. 완료 기준

- 공급자 응답 형식이 UI와 Collection·Archive 코드로 새지 않는다.
- 검색만으로 프로젝트 데이터가 바뀌지 않는다.
- 사용자가 적용 전 변경 필드와 내려받을 미디어를 확인할 수 있다.
- Collection 메타데이터는 기존 편집 정책, 미디어는 Plan을 따르고 Archive는 revision과
  ownership 정책을 따른다.
- 중단·오류 뒤에도 완료 항목과 미완료 항목을 구분해 다시 시작할 수 있다.
- 로그와 DB에 자격 증명 평문이 남지 않는다.
- 후보마다 어떤 근거로 검색되고 정렬됐는지 설명할 수 있다.
