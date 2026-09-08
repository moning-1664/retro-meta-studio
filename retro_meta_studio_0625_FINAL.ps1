#requires -Version 5.1
$ErrorActionPreference = "Continue"

$PROJECT_DIR = "C:\Users\moning\retro-meta-studio"
$PERMISSION_MODE = "auto"
$MAX_TURNS = 120
$MAX_BUDGET_USD = 15

$PROMPT = @'
[RetroMeta Studio 자율 개발 작업]

대화 세션의 기억에 의존하지 말고 반드시 현재 프로젝트의 실제 파일, Git 상태, 설계서와 UI 예제를 조사하여 현재 상태를 판단한다.

목표:
현재 구현 Phase부터 마지막 구현 Phase까지 완료하고, 구현 완료 후 전체 기능 TC를 재검토/설계/실행/수정하고, 그 다음 전체 UX를 자체 검증하고 UI 예제에 최대한 근접하도록 개선한다. 실질적인 작업이 남아 있다면 설명만 하지 말고 계속 작업한다.

1. 시작 전
- 현재 디렉터리 확인
- git status, branch, 최근 commit 확인
- 설계서, UI 예제/목업, README, CHANGELOG 및 관련 문서 확인
- 코드와 문서를 비교하여 현재 구현 Phase를 판단
- 이미 완료된 작업은 반복하지 않는다
- 사용자 변경사항을 삭제하거나 덮어쓰지 않는다

2. 구현 Phase
- 현재 Phase가 미완료면 완성한다.
- 완료되어 있으면 다음 Phase로 진행한다.
- 현재 Phase부터 마지막 구현 Phase까지 순차적으로 가능한 한 계속 진행한다.
- 각 Phase: 요구사항 확인 → 구현 → 테스트 → 실패 수정 → 완료 판단
- 기존 Metadata / Media / ROM UI를 임의로 새로운 구조로 교체하지 않는다.
- Collection / Archive / Cache / Plan 및 FileOperationEngine 설계를 유지한다.

3. 전체 기능 TC
모든 구현 Phase가 완료되면 설계서를 기준으로 전체 TC를 새로 점검한다.
포함 범위:
Collection 생성/열기/닫기/재열기, Frontend/Target/OS/Architecture,
System 및 Internal/External, ALL/Gamelist, Game/ROM Identity,
Metadata/Media/ROM, Archive/Revision, Cache,
Plan Add/Delete/Move/Copy, Import/Export/Convert,
Auto Plan, Actual/Plan 용량, Internal↔External 이동,
Capacity 초과, Plan Apply, 외부 파일 변경 후 재검증,
Cleanup, Compare, heuristic match 사용자 확인,
frontend-specific data round-trip, FileOperationEngine,
오류/취소/회귀.

- TC 결과는 PASS/FAIL/BLOCKED로 판단한다.
- FAIL은 원인 분석 → 코드 수정 → 관련 TC 재실행
- 자동화 가능한 TC는 실제 테스트로 추가한다.
- GUI 전체 자동화가 어려우면 integration/state/smoke 검증으로 최대한 자동화한다.
- 전체 TC가 안정적으로 통과하도록 반복한다.

4. 전체 UX 검증
TC 완료 후 설계서와 UI 예제를 다시 검토한다.
다음 흐름을 실제 상태와 코드 관점에서 검증한다:
Collection → System → ALL → Game → Metadata/Media/ROM →
두 Collection Compare → Copy/Paste → Drag&Drop →
Auto Plan Add/Delete/Move → Actual/Plan 용량 → Apply →
Archive → Cache 재오픈 → Import/Export/Convert → Cleanup →
오류/취소 → 키보드/마우스 포커스 → 창 크기 변경 →
긴 제목/대량 게임/미디어 없는 게임 → Internal/External →
Compare 진입/종료

점검:
- 현재 Collection/System/Game 상태가 명확한가
- 선택 상태와 Plan 상태가 실제 상태와 혼동되지 않는가
- + / - / △ 표시가 일관적인가
- Actual/Plan 용량이 명확한가
- Internal/External이 명확한가
- 버튼/메뉴/우클릭/Drag&Drop이 예측 가능한가
- 동일 기능이 화면마다 동일하게 동작하는가
- Header/Tabs/Navigation/Gamelist/Detail/Bottom Status가 일관적인가
- 기존 Metadata/Media/ROM UI의 정보 밀도와 편집성을 유지하는가
- 긴 텍스트/대량 데이터에서 레이아웃이 깨지지 않는가
- 취소/확정 시점이 명확한가
- UI 예제에 최대한 근접하는가

문제가 발견되면 실제 코드/UI를 수정하고 관련 검증을 다시 한다.

5. 사용자 판단이 필요한 사항
설계서만으로 결정되지 않는 사항이 발견되어도 작업을 중단하지 않는다.
가장 합리적인 방식을 우선 선구현한다.
최종 보고에 다음을 남긴다:
- 결정이 필요한 내용
- 발견한 선택지
- 추천안
- 추천안을 선구현한 이유
- 실제 구현 결과
- 다른 선택지를 택할 경우 필요한 변경

6. Git 안전 및 context 안전
- 사용자 변경사항을 덮어쓰지 않는다.
- 강제 초기화나 강제 checkout으로 사용자 변경사항을 덮지 않는다.
- force push를 사용하지 않는다.
- commit 전 git status와 diff를 확인한다.
- 논리적으로 완료된 작업 단위마다 가능하면 commit한다.
- context/token 사용량이 약 85% 이상으로 판단되면 다음 큰 작업으로 넘어가지 말고 현재 논리적 작업 단위를 마무리하고 checkpoint commit한 뒤 종료한다.
- 다음 실행에서는 Git/파일/설계서를 다시 조사하여 이어간다.
- main에 안전하게 반영할 수 있으면 완료된 논리적 단계 단위로 main에 반영한다. 충돌이나 위험이 있으면 임의 해결하지 말고 보고한다.

7. 금지
- 설계서에 없는 대규모 기능 추가
- 테스트 없이 기존 기능 삭제
- Metadata/Media/ROM UI 임의 교체
- Collection을 MasterDB 중심 구조로 되돌리기
- Archive를 자동 동기화 원본으로 취급
- Storage를 독립 최상위 Collection으로 분리
- heuristic match 자동 적용
- Export/Convert 중 기존 media 임의 삭제
- Plan을 단순 copy queue로 축소
- FileOperationEngine 밖에서 실제 파일 작업 수행
- 테스트 없이 완료 선언

8. 종료 보고
현재 Phase, 완료 작업, TC 결과, 수정 버그, UX 검증/개선 결과,
선구현 후 사용자 판단이 필요한 사항, 남은 작업,
branch, 최근 commit, git status, 다음 실행 우선 작업을 보고한다.

'@

$LOG_DIR = Join-Path $PROJECT_DIR "logs"
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LOG_FILE = Join-Path $LOG_DIR "claude_0122_$timestamp.log"

function Write-Log([string]$Message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Message" |
        Tee-Object -FilePath $LOG_FILE -Append
}

Write-Log "=== RetroMeta Studio scheduled Claude Code run START ==="
Write-Log "Project: $PROJECT_DIR"
Write-Log "Permission mode: $PERMISSION_MODE"
Write-Log "Max turns: $MAX_TURNS"
Write-Log "Max budget USD: $MAX_BUDGET_USD"

if (-not (Test-Path -LiteralPath $PROJECT_DIR)) {
    Write-Log "ERROR: Project directory does not exist."
    exit 10
}

$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) {
    Write-Log "ERROR: Claude Code command was not found in PATH."
    exit 11
}

Set-Location -LiteralPath $PROJECT_DIR

# 기존 세션을 resume하지 않는다.
# 프로젝트 파일/Git/설계서를 source of truth로 사용한다.
$claudeArgs = @(
    "-p"
    $PROMPT
    "--permission-mode"
    $PERMISSION_MODE
    "--max-turns"
    "$MAX_TURNS"
    "--max-budget-usd"
    "$MAX_BUDGET_USD"
)

Write-Log "Claude executable: $($claude.Source)"
Write-Log "Starting Claude Code..."

try {
    & $claude.Source @claudeArgs 2>&1 |
        Tee-Object -FilePath $LOG_FILE -Append
    $exitCode = $LASTEXITCODE
}
catch {
    Write-Log "EXCEPTION: $($_.Exception.Message)"
    exit 20
}

Write-Log "Claude Code exit code: $exitCode"
Write-Log "=== RetroMeta Studio scheduled Claude Code run END ==="
exit $exitCode
