// [체감 속도, Scan 2단계] Refresh List가 (1) 메타데이터+커버 (2) 나머지 미디어 2단계로
// 나뉘고, 1단계 결과는 즉시 화면에 반영된다. mock의 1단계 응답은 모든 게임을 일부러
// "부분"으로 덮어써서 반환하므로(실제로도 media 일부만 봤을 때의 상태 - 자세한 내용은
// api-client.js의 get_job_progress mock 참고), follow-up이 제대로 안 걸리면 최종
// 화면에 Mario가 계속 "Partial"로 잘못 남아있게 된다.
//
// [P0-2] 2단계도 진행률 바 없이 조용히 폴링되는 게 아니라, 1단계와 같은 바에서
// 계속 진행률을 보여준다("(2/2) 0->100%") - 바는 2단계까지 실제로 끝난 뒤에만 숨는다.
const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.goto("/index.html");
  await page.locator("#sidebar").getByRole("button", { name: "Local 1", exact: true }).click();
  await expect(page.locator('[data-rom-key="snes|Super Mario World.zip"]')).toBeVisible();
});

test("Refresh 후 1단계(부분) 결과가 2단계(전체) 결과로 갱신되고, 진행률 바는 2단계까지 계속 보인다", async ({ page }) => {
  const marioStatus = page.locator('[data-rom-key="snes|Super Mario World.zip"] .status-dot-wrap');
  await expect(marioStatus).toContainText("Normal");

  // [P0-2] 바가 2단계까지 계속 보이는지는(중간에 숨지 않는지) mock이 워낙 빨라서
  // 이 테스트에선 타이밍상 안정적으로 관측하기 어렵다 - 그건 아래 gate를 쓰는
  // 테스트가 결정적으로 검증한다. 여기서는 최종 결과(2단계까지 실제로 반영된
  // 상태)와 바가 결국 숨는지만 확인한다.
  await page.getByRole("button", { name: "새로고침", exact: true }).click();
  await expect(page.locator("#job-progress.show")).toBeHidden({ timeout: 5000 });
  await expect(marioStatus).toContainText("Normal");
});

// [Parent Job lifecycle 수정] 1단계(job1)만 끝난 시점에 "완료" 토스트를 띄우면
// 안 된다 - 2단계(follow-up)가 실제로 끝날 때까지 기다려야 한다. get_job_progress가
// mock-scan-job-2에 대해 응답하는 걸 일부러 gate로 붙잡아서, 그 사이에는 토스트가
// 뜨지 않고(진행률 바는 계속 떠 있고) gate를 풀어야만 완료 토스트가 뜨는지 확인한다.
test("Refresh 완료 토스트는 2단계까지 실제로 끝난 뒤에만 뜨고, 그동안 진행률 바는 계속 보인다", async ({ page }) => {
  await page.evaluate(() => {
    const gate = new Promise((resolve) => { window.__releaseJob2 = resolve; });
    const original = window.RMApi._call.bind(window.RMApi);
    window.RMApi._call = async (name, args) => {
      if (name === "get_job_progress" && args[0] === "mock-scan-job-2") await gate;
      return original(name, args);
    };
  });

  await page.getByRole("button", { name: "새로고침", exact: true }).click();
  // job2가 gate에 막혀 있는 동안엔 진행률 바가 계속 보이고, 완료 토스트는 뜨면 안 된다.
  await page.waitForTimeout(500);
  await expect(page.locator("#job-progress.show")).toBeVisible();
  await expect(page.locator("#toast.show")).toHaveCount(0);

  await page.evaluate(() => window.__releaseJob2());
  await expect(page.locator("#toast.show")).toContainText("Refresh 완료", { timeout: 3000 });
  await expect(page.locator("#job-progress.show")).toBeHidden();
});

// [Parent Job lifecycle 수정, _ensureLocalScannedOnce] Local 화면에 처음 들어갈 때
// 자동으로 도는 초기 스캔도, 사이드바의 "스캔 중"(빨간 점) 표시가 1단계만 끝나도
// 꺼지면 안 된다 - 2단계까지 실제로 끝나야 꺼져야 한다.
test("Local 최초 진입 시 사이드바 '스캔 중' 표시는 2단계까지 실제로 끝난 뒤에만 꺼진다", async ({ page }) => {
  await page.goto("/index.html");
  await expect(page.locator("#sidebar .nav-item").first()).toBeVisible();
  await page.evaluate(() => {
    const gate = new Promise((resolve) => { window.__releaseJob2 = resolve; });
    const original = window.RMApi._call.bind(window.RMApi);
    window.RMApi._call = async (name, args) => {
      if (name === "get_job_progress" && args[0] === "mock-scan-job-2") await gate;
      return original(name, args);
    };
  });

  const local1Row = page.locator("#sidebar .nav-item-local", { hasText: "Local 1" });
  await local1Row.click();

  // 1단계는 끝났지만 job2가 gate에 막혀 있는 동안에는 "스캔 중" 표시가 남아있어야 한다.
  await page.waitForTimeout(500);
  await expect(local1Row.locator(".bar-icon.scanning")).toBeVisible();

  await page.evaluate(() => window.__releaseJob2());
  await expect(local1Row.locator(".bar-icon.scanning")).toBeHidden({ timeout: 3000 });
});
