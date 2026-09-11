# MEMORY — RetroMeta Studio

> 상태 문서: **현재 무엇이 어떻게 동작/구성되어 있는가**를 기록한다.
> 설계 의도는 INTEND.md에 기록한다.

## 기록 원칙

- 각 기능/Phase의 실제 구현 상태와 관찰된 행위를 기록한다.
- 구현이 변경되면 이전 상태를 현재 상태로 갱신하고 필요한 경우 변경 이유를 남긴다.
- 다른 AI/새 세션이 이어받을 때 이 문서만 읽어도 현재 행위를 오해하지 않도록 한다.
- 아직 구현되지 않은 항목은 구현된 것처럼 기록하지 않는다.

---

## Settings — Initial Definition

### 현재 상태

- Settings 기능은 **구성/설계 단계**다.
- 현재 빌드가 정상적으로 검증되지 않은 상태이므로 이번 단계에서는 기존 기능을 깨뜨리는 소스 변경을 하지 않는다.
- Settings의 실제 UI 및 persistence 구현은 빌드/기본 기능 안정화 후 진행한다.

### 메뉴 구성

```text
SETTINGS
├─ General
├─ Collections
├─ Metadata & Media
│  ├─ Metadata
│  ├─ GameList Columns
│  └─ Media
├─ Import / Export
├─ Emulator
├─ Appearance
└─ Advanced
```

### GameList Columns — 정의된 행위

- `No.` 컬럼은 항상 첫 번째이며 고정한다.
- 사용 가능한 GameList 컬럼은 표시/숨김을 지원한다.
- 사용자는 컬럼 순서를 변경할 수 있다.
- `File`, `Title`, `Description`, `Region`, `Rating`, `Genre` 등 현재 GameList에 존재하거나 향후 지원할 metadata field를 대상으로 한다.
- 컬럼 폭 조절은 컬럼 순서/표시 여부와 별도의 기존 GameList 기능으로 유지한다.
- 컬럼 설정은 가능하면 Collection별 UI state로 저장하는 방향으로 설계한다.
- 실제 구현 시 기존 `COLUMNS` 및 Collection별 UI state 저장 구조를 우선 검토하고 불필요한 별도 상태 저장 구조를 만들지 않는다.

### 디자인 행위 원칙

- Settings는 기존 RetroMeta Studio의 Navigator/Inspector/dense row UI와 동일한 시각 언어를 사용한다.
- Settings 전용의 별도 SaaS dashboard/card-heavy 레이아웃을 도입하지 않는다.
- 기존 Theme/Accent/spacing/typography를 재사용한다.

---

## 향후 기록 규칙

새 기능을 구현할 때 다음 형식으로 실제 행위를 추가한다.

```text
## [Phase/Feature]

### 구현 상태
완료 / 부분 완료 / 미구현

### 실제 동작
사용자가 무엇을 하면 시스템이 어떻게 동작하는가?

### 저장 상태
어떤 값이 어디에 저장되는가?

### 검증
어떤 테스트를 수행했으며 무엇이 확인되었는가?

### 주의사항
다음 세션/AI가 오해하면 안 되는 사항.
```
