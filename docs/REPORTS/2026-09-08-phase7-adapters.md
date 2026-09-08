# Phase 7 — 나머지 Frontend Adapter와 Round-trip 검증

**요약.** Pegasus / LaunchBox / EmulationStation Adapter를 추가하고(총 4종),
Frontend 간 왕복에서 정보가 사라지지 않는지 검증했다(§50-51). ES-DE custom systems
XML(§22)도 Adapter 고유 기능으로 붙였다.

파이썬 276개(신규 40개), Playwright 45개(신규 4개) 전부 통과.

---

## 1. Adapter 인터페이스는 그대로 두고 늘렸다

Phase 1에서 정한 두 계약이 그대로 작동했다.

- **계약 1(bulk만 노출)** — 세 Adapter 모두 `read_index`/`write_index`가 System 단위다.
  이전 프로젝트가 겪은 "ROM마다 파일을 다시 여는 O(n²)"를 구조적으로 못 하게 막는다.
- **계약 2(모르는 필드를 버리지 않는다)** — 이번에 추가한 셋 다 미지 태그/키를
  `frontend_raw`에 담고 되살린다.

인터페이스를 바꾸지 않고 세 종류를 얹을 수 있었다는 것이, Phase 1의 설계가 맞았다는
증거다. 단 하나 예외가 EmulationStation의 `write_media_links()`인데 — 이유는 §4에 있다.

---

## 2. 각 Frontend의 함정

### Pegasus — 여러 줄 값과 미지 키

`metadata.pegasus.txt`는 빈 줄로 나뉜 `key: value` 블록이고, **들여쓴 줄은 앞 키의 값이
이어지는 것**이다(주로 `description`). 그 규칙을 모르면 여러 줄 설명이 줄마다 새 키로
잘못 읽힌다.

더 중요한 것은 이전 프로젝트의 writer가 **블록을 아는 필드만으로 다시 만들었다**는 점이다.
사용자가 넣어 둔 `sort-by:`, `x-favorite:`, `assets.*` 같은 키가 Export 한 번에 사라졌다.
지금은 블록의 모든 줄을 **순서까지 유지해** 보존하고, 쓸 때 원래 줄 순서를 최대한 지킨다.

### LaunchBox — media 파일명이 ROM이 아니라 **제목**을 따른다

ES-DE와 Pegasus는 media 파일명이 ROM stem을 따르지만, LaunchBox는 게임 제목을 쓴다.
`FFX.iso`의 커버가 `Final Fantasy X.jpg`로 저장되는 식이라, ROM stem으로만 인덱싱하면
**커버를 하나도 못 찾는다.**

플랫폼 XML의 `<Title>`로 "제목 → ROM stem" 대응표를 먼저 만들고, media를 훑을 때 그
표로 되돌린다. 표에 없는 파일은 파일명 자체를 stem으로 본다(ROM 이름으로 저장해 둔
사람도 있고, 그것까지 버리면 멀쩡한 media를 놓친다). LaunchBox가 제목의 금지 문자를
`_`로 바꾸는 규칙도 같이 반영했다.

`<ApplicationPath>`는 **원본 그대로 보존한다.** 상대/절대 경로가 섞여 있어서, 우리가
파일명만 알고 다시 조립하면 사용자의 경로 설정이 깨진다.

### EmulationStation(원조) — gamelist가 media 경로를 들고 있다

ES-DE는 폴더 규칙(`downloaded_media/<system>/covers/<stem>.png`)으로 media를 찾지만,
원조 ES는 **gamelist.xml의 `<image>`/`<video>`/`<marquee>`가 경로를 직접 가리킨다.**
배포판마다 위치가 제각각이라(RetroPie / Batocera / Recalbox) 폴더 규칙을 가정하는 순간
사용자의 media를 통째로 놓친다.

그래서 이 Adapter만 media 인덱스를 **gamelist가 가리키는 경로에서** 만든다. 상대 경로와
절대 경로를 모두 받고, 가리키지만 실제로 없는 파일은 조용히 건너뛴다.

`detect()`도 다르다. ES-DE도 `gamelists/`를 쓰므로, `downloaded_media/`가 함께 있으면
**확신을 낮춰**(0.9 → 0.5) 사용자가 고르게 한다. 확신하면 사용자가 잘못된 Frontend로
Collection을 열게 된다.

---

## 3. Round-trip 검증 (§50-51)

`tests/test_adapters.py::RoundTripTests`가 두 종류를 확인한다.

| 검증 | 지키는 것 |
|---|---|
| 같은 Frontend 제자리 왕복 | **공통 필드 + `frontend_raw`** 둘 다 |
| Frontend 간 왕복(ES-DE → Pegasus → ES-DE) | **공통 필드** |

두 번째에서 `frontend_raw`가 따라가지 않는 것은 결함이 아니라 정의다 — ES-DE의
`<playcount>`를 Pegasus 블록에 적을 수는 없다. 원본 보존은 **같은 Frontend로 돌아왔을
때**의 이야기이고, 다른 Frontend로 건너갈 때 지켜야 하는 것은 공통 모델이다. 이 구분을
테스트 docstring에 적어 뒀다.

Pegasus 왕복에서 `region`만 빠지는데, Pegasus 포맷에 region 키가 없기 때문이다. 테스트가
그 사실을 `skip=("region",)`으로 명시한다 — 조용히 통과시키지 않고 "여기는 원래 없다"를
기록으로 남기기 위함이다.

---

## 4. ES-DE Custom Systems XML (§22)

`AdapterAction`으로 노출하고 헤더 확장의 `[ES-DE XML 생성]`으로 실행한다. Storage 같은
일반 기능으로 올리지 않았다 — ES-DE의 사정이고, 다른 Frontend는 같은 문제를 다른
방식으로 푼다.

**Collection root 안에 있는 System은 적지 않는다.** ES-DE가 스스로 찾기 때문이고, 전부
적으면 사용자가 ES-DE에서 직접 손본 설정까지 덮어쓰게 된다. 확장자와 실행 명령도 비워
둔다 — 추측해서 채우면 사용자의 에뮬레이터 설정을 밀어버리는 셈이다.

만들 내용이 없을 때(`written: false`)와 실패는 화면에서 구분해 알린다.

### 계약에서 벗어난 것 하나 — `write_media_links()`

EmulationStation Adapter에만 있는 메서드다. 원조 ES는 gamelist가 가리키는 경로만 보므로,
media를 복사한 뒤 **gamelist에 그 경로를 적어주지 않으면 파일은 복사됐는데 화면에는 안
나온다.** ES-DE/Pegasus/LaunchBox에는 없는 단계라 공통 인터페이스에 올리지 않고 이
Adapter의 메서드로 두었다. Plan Apply가 EmulationStation Collection에 media를 쓰게 되는
시점에 이걸 호출하도록 연결해야 한다 — **지금은 Adapter에 준비만 되어 있고 Apply 경로에는
아직 연결되지 않았다.**

---

## 5. 다음

Phase 8(MTP Provider)은 스펙에서도 "필요성 재평가 후 착수"로 둔 선택 항목이다.
그보다 먼저 정리할 후보:

1. **`write_media_links()`를 Plan Apply에 연결** (위 §4). EmulationStation Collection으로
   media를 내보내는 실제 경로가 생길 때 반드시 필요하다.
2. **Adapter 간 변환 UI**. 지금은 Adapter가 다 갖춰졌지만 "ES-DE Collection을 Pegasus로
   변환"하는 화면은 없다. 스펙 §349의 Import(Source → Match → Target)와 맞물린다.
3. 이월된 것들 — `match_links`의 rename 취약성(Phase 5), Compare Row key 구조화(Phase 6),
   SHA-256 비교.
