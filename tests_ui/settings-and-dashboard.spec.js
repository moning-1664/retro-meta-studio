// gui_web UI 회귀 테스트 (headless Chromium, mock API 모드).
// pywebview 없이 index.html을 직접 열면 api-client.js가 자동으로 mock 모드로 폴백하므로
// (RMApi._mockMode), 실제 Windows/pywebview 없이도 클릭/드래그/키보드로 순수 프론트엔드
// 로직/렌더링을 검증할 수 있다. 네이티브 폴더 대화상자, 실제 파일 I/O, WebView2 특유의
// 렌더링 버그는 이 테스트로 재현되지 않으며 여전히 Windows 실기 확인이 필요하다.
const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.goto("/index.html");
  // init()이 mock getSettings/getVersion/refreshAll을 모두 마칠 때까지 대기.
  await expect(page.locator("#sidebar .nav-item").first()).toBeVisible();
});

test.describe("사이드바 (단위 2)", () => {
  test("Dashboard/ArchiveDB/GameListSet 순서와 라벨", async ({ page }) => {
    const sidebar = page.locator("#sidebar");
    await expect(sidebar.getByText("Dashboard", { exact: true })).toBeVisible();
    await expect(sidebar.getByText("ArchiveDB", { exact: true })).toBeVisible();
    await expect(sidebar.getByText("GameListSet 추가", { exact: true })).toBeVisible();
    // MasterDB/Local이라는 옛 라벨은 더 이상 노출되지 않아야 한다.
    await expect(sidebar.getByText("MasterDB", { exact: true })).toHaveCount(0);

    // 기본 진입 화면(ArchiveDB)에서는 SYSTEM 필터 섹션도 함께 노출된다.
    const labels = await sidebar.locator(".nav-section-label").allTextContents();
    expect(labels).toEqual(["ARCHIVEDB", "MY GAMELISTS", "SYSTEM"]);
  });

  // [수정] 리뷰 반영으로 Settings 톱니바퀴를 사이드바 하단에서 좌측 상단(브랜드
  // 바로 아래)으로 옮겼다 - 아이콘만 두고 텍스트 라벨은 뺐다.
  test("Settings 톱니바퀴가 사이드바 상단(브랜드 바로 아래)에 아이콘만으로 있다", async ({ page }) => {
    const sidebar = page.locator("#sidebar");
    const secondChild = sidebar.locator("> *").nth(1);
    await expect(secondChild).toHaveClass(/sidebar-settings-btn/);
    await expect(secondChild).toHaveText("");
  });
});

test.describe("Dashboard 용량 패널 (단위 3)", () => {
  test.beforeEach(async ({ page }) => {
    await page.getByRole("button", { name: "Dashboard", exact: true }).click();
    await expect(page.locator(".capacity-dash-panel")).toBeVisible();
  });

  test("목표 미설정 GameListSet은 '미설정'으로 표시된다", async ({ page }) => {
    const item = page.locator(".capacity-dash-item").first();
    await expect(item.locator(".capacity-dash-item-value")).toContainText("미설정");
  });

  // [GUI 정돈] 목표 용량 편집(슬라이더/숫자입력)은 Settings > GameListSet과 중복이라
  // Dashboard에서는 제거되고 읽기 전용 요약만 남았다 - 편집은 Settings에서 하고,
  // 그 결과가 Dashboard에도 반영되는지를 검증한다.
  test("Settings에서 목표 용량을 저장하면 Dashboard 표시도 갱신된다", async ({ page }) => {
    await expect(page.locator(".capacity-dash-controls")).toHaveCount(0);
    await page.locator(".sidebar-settings-btn").click();
    await page.locator(".settings-menu").getByText("GameListSet", { exact: true }).click();
    const numberInput = page.locator(".capacity-dash-number").first();
    await numberInput.fill("500");
    await numberInput.dispatchEvent("change");
    // 저장은 400ms 디바운스 후 실행된다 (commit()) - Dashboard로 넘어가 다시 렌더링될
    // 때는 이미 반영되어 있어야 하므로, 디바운스가 끝나길 기다렸다가 넘어간다.
    await page.waitForTimeout(600);

    await page.getByRole("button", { name: "Dashboard", exact: true }).click();
    const item = page.locator(".capacity-dash-item").first();
    await expect(item.locator(".capacity-dash-item-value")).toContainText("500");
    await expect(item.locator(".capacity-dash-item-value")).not.toContainText("미설정");
  });
});

test.describe("Settings 재구성 (단위 4)", () => {
  test.beforeEach(async ({ page }) => {
    // 톱니바퀴 클릭으로 Settings 진입.
    await page.locator(".sidebar-settings-btn").click();
    await expect(page.locator(".settings-menu")).toBeVisible();
  });

  const expectedTabs = ["General", "GameListSet", "Metadata", "Media", "ArchiveDB", "Interface", "Advanced"];

  test("7개 카테고리가 요청한 순서로 노출된다", async ({ page }) => {
    const tabs = await page.locator(".settings-menu > button").allTextContents();
    expect(tabs).toEqual(expectedTabs);
  });

  for (const tab of expectedTabs) {
    test(`${tab} 탭이 에러 없이 렌더링된다`, async ({ page }) => {
      await page.locator(".settings-menu").getByText(tab, { exact: true }).click();
      await expect(page.locator(".settings-content")).toBeVisible();
      // 콘텐츠가 완전히 비어있으면(렌더링 실패) 테스트 실패.
      await expect(page.locator(".settings-content")).not.toBeEmpty();
    });
  }

  // [체감 속도] Advanced 탭에 "비디오 지연 복사" 토글이 생겼다 - Coming soon
  // 배지 없이 바로 동작하는 설정이어야 한다.
  test("Advanced 탭은 Coming soon 배지 없이 비디오 지연 복사 토글을 표시한다", async ({ page }) => {
    await page.locator(".settings-menu").getByText("Advanced", { exact: true }).click();
    await expect(page.locator(".settings-content .settings-soon-badge")).toHaveCount(0);
    await expect(page.locator(".settings-content")).toContainText("비디오 지연 복사");
  });

  test("General에서 Confirmations를 끄면 위험 작업이 확인창 없이 즉시 실행된다", async ({ page }) => {
    await page.locator(".settings-menu").getByText("General", { exact: true }).click();
    const confirmToggle = page.locator(".settings-checkbox-row", { hasText: "Confirmations" }).locator("input[type=checkbox]");
    await expect(confirmToggle).toBeChecked();
    await confirmToggle.uncheck();
    await page.getByRole("button", { name: "설정 저장" }).click();
    await expect(page.locator("#toast.show")).toContainText("저장");

    // GameListSet 관리 화면에서 삭제 버튼을 눌러도 확인 모달이 뜨지 않고 바로 처리되어야 한다.
    // (경로 변경 버튼이 같은 행에 추가되었으므로 삭제 버튼은 전용 클래스로 지정해서 찾는다.)
    await page.locator(".settings-menu").getByText("GameListSet", { exact: true }).click();
    await page.locator(".local-mgmt-row .icon-btn-danger").first().click();
    await expect(page.locator(".modal-overlay")).toHaveCount(0);
  });

  test("Media 탭은 MetaData/Media/Rom 그룹 레이아웃을 공유한다", async ({ page }) => {
    await page.locator(".settings-menu").getByText("Media", { exact: true }).click();
    const titles = await page.locator(".settings-content .settings-section-title").allTextContents();
    expect(titles.slice(0, 3)).toEqual(["MetaData", "Media", "Rom"]);
    // Media 세부 7종 체크박스가 그리드로 노출된다.
    await expect(page.locator(".settings-checkbox-grid input[type=checkbox]")).toHaveCount(7);
  });
});

// [GUI 정돈] "[||||||||][    ]" 텍스트 브라켓 스타일 대신 일반 채움 바(fill div)로 바뀌었다.
test.describe("프로그레스 바 스타일 (단위 1)", () => {
  test("job-progress 컨테이너가 존재한다", async ({ page }) => {
    const hasBar = await page.evaluate(() => !!document.getElementById("job-progress"));
    expect(hasBar).toBe(true);
  });
});
