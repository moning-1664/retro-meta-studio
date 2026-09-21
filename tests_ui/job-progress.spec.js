// 진행률 막대 - 작업마다 자기 줄이 있다.
//
// 예전에는 막대가 화면에 하나뿐이라, 복사가 도는 동안 새로고침을 누르면 (뒤에서 기다리는) 스캔 job과
// 복사 job이 같은 막대를 번갈아 덮어썼다("막힌 작업 대기 중"과 복사 진행률이 번갈아 나타났다).
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

/** 두 job이 동시에 도는 상황을 만든다: 하나는 복사 중, 하나는 앞에서 막혀 기다리는 중. */
async function twoJobs(page) {
  await page.evaluate(() => {
    let started = 0;
    window.api.startScan = async () => ({ ok: true, data: { jobId: `scan-${++started}` } });
    window.api.jobProgress = async (jobId) => ({ ok: true, data: jobId === "scan-1"
      ? { current: 1, total: 3, label: "복사 중: Final Fantasy X · 1/3", done: false, result: null }
      : { current: 0, total: 1, label: "대기 중 (앞에서 막고 있는 작업 1개)", done: false, result: null } });
  });
  const rescan = page.locator("button[title='다시 스캔']");
  await rescan.click();
  await expect(page.locator(".job-progress-item")).toHaveCount(1);
  await rescan.click();
}

test("동시에 도는 작업은 각자 줄이 있다", async ({ page }) => {
  await twoJobs(page);
  await expect(page.locator(".job-progress-item")).toHaveCount(2);
});

test("각 줄이 자기 작업의 문구와 진행률을 유지한다 - 서로 덮어쓰지 않는다", async ({ page }) => {
  await twoJobs(page);
  const items = page.locator(".job-progress-item");
  await expect(items.nth(0).locator(".job-progress-label")).toContainText("복사 중: Final Fantasy X");
  await expect(items.nth(1).locator(".job-progress-label")).toContainText("대기 중");
  await expect(items.nth(0).locator(".job-progress-pct")).toHaveText("33%");
  await expect(items.nth(1).locator(".job-progress-pct")).toHaveText("0%");
  // 한참 뒤에도 그대로다(번갈아 바뀌지 않는다).
  await page.waitForTimeout(700);
  await expect(items.nth(0).locator(".job-progress-label")).toContainText("복사 중");
  await expect(items.nth(1).locator(".job-progress-label")).toContainText("대기 중");
});

test("기다리는 작업은 흐리게 표시된다", async ({ page }) => {
  await twoJobs(page);
  await expect(page.locator(".job-progress-item").nth(1)).toHaveClass(/waiting/);
  await expect(page.locator(".job-progress-item").nth(0)).not.toHaveClass(/waiting/);
});

test("문구가 이미 개수로 끝나면 개수를 또 붙이지 않는다", async ({ page }) => {
  await twoJobs(page);
  const label = await page.locator(".job-progress-item").nth(0).locator(".job-progress-label").innerText();
  expect(label).toBe("복사 중: Final Fantasy X · 1/3");        // (1/3)이 두 번 나오지 않는다
});

test("작업이 끝난 줄만 사라지고 막대는 남은 작업이 있으면 유지된다", async ({ page }) => {
  await page.evaluate(() => {
    let started = 0;
    window.__done = false;
    window.api.startScan = async () => ({ ok: true, data: { jobId: `scan-${++started}` } });
    window.api.jobProgress = async (jobId) => ({ ok: true, data: jobId === "scan-1"
      ? { current: window.__done ? 3 : 1, total: 3, label: "복사 중", done: window.__done, result: {} }
      : { current: 0, total: 1, label: "스캔 중", done: false, result: null } });
  });
  const rescan = page.locator("button[title='다시 스캔']");
  await rescan.click();
  await rescan.click();
  await expect(page.locator(".job-progress-item")).toHaveCount(2);
  await page.evaluate(() => { window.__done = true; });
  await expect(page.locator(".job-progress-item")).toHaveCount(1);
  await expect(page.locator("#job-progress")).toHaveClass(/show/);
});
