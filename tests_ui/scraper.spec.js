const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const exactMenuItem = (page, label) => page.locator(".ctx-menu .ctx-item").filter({
  has: page.locator(".ctx-label", { hasText: new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`) }),
});

async function openForRows(page, count = 1) {
  const rows = page.locator(".lrow");
  await rows.nth(0).click();
  if (count > 1) {
    await page.keyboard.down("Control");
    for (let i = 1; i < count; i += 1) await rows.nth(i).click();
    await page.keyboard.up("Control");
  }
  await rows.nth(0).click({ button: "right" });
  const label = count === 1 ? "메타데이터 스크랩…" : `메타데이터 스크랩… (${count}개)`;
  await exactMenuItem(page, label).click();
  await expect(page.locator(".scrape-context-card")).toBeVisible();
  await expect(page.locator(".scrape-candidate").first()).toBeVisible();
}

test("Settings에서 연결 상태와 일일 요청량을 확인한다", async ({ page }) => {
  await page.locator(".settings-btn").click();
  await page.locator(".stg-nav-item[data-section='scraper']").click();
  await expect(page.locator(".stg-panel")).toContainText("ScreenScraper 개발자 정보 설정됨");
  await page.getByRole("button", { name: "연결 테스트" }).click();
  await expect(page.locator(".stg-scraper")).toContainText("오늘 12 / 100회");
  await expect(page.locator(".stg-scraper")).toContainText("동시 요청 1");
  await expect(page.locator(".stg-scraper")).toContainText("ROM 해시로 먼저 찾기");
  await expect(page.locator(".scrape-media-settings summary")).toHaveText("가져올 미디어 종류");
});

test("연결 정보를 저장한 뒤에도 Settings의 Scraper 메뉴에 머문다", async ({ page }) => {
  await page.locator(".settings-btn").click();
  await page.locator(".stg-nav-item[data-section='scraper']").click();
  await page.getByRole("button", { name: "연결 설정…" }).click();
  await page.locator(".scrape-setup-card input").nth(0).fill("changed-dev");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.locator(".stg-panel")).toBeVisible();
  await expect(page.locator(".stg-nav-item[data-section='scraper']")).toHaveClass(/active/);
});

test("단건 후보는 Detail 폭이며 접힌 상태에서도 바로 선택할 수 있다", async ({ page }) => {
  await openForRows(page);
  await expect(page.locator(".scrape-quota")).toHaveText("오늘 12 / 100회");
  await expect(page.locator(".scrape-candidate .scrape-choose").first()).toBeVisible();
  const width = await page.locator(".scrape-context").evaluate((el) => Math.round(el.getBoundingClientRect().width));
  expect(width).toBe(297);
});

test("∨를 누르면 필드 비교와 미디어 선택을 펼친다", async ({ page }) => {
  await openForRows(page);
  await page.locator(".scrape-expand").first().click();
  await expect(page.locator(".scrape-field", { hasText: "name" })).toBeVisible();
  await expect(page.locator(".scrape-field", { hasText: "비어 있음" }).first()).toBeVisible();
  await expect(page.locator(".scrape-media-option", { hasText: "covers" })).toBeVisible();
  await expect(page.locator(".scrape-media-option input")).toBeChecked();
});

test("검색 키를 고쳐 다시 스크랩하면 후보 제목이 바뀐다", async ({ page }) => {
  await openForRows(page);
  await page.locator(".scrape-query").fill("수동 원작 제목");
  await page.getByRole("button", { name: "다시 스크랩" }).click();
  await expect(page.locator(".scrape-candidate-title").first()).toHaveText("수동 원작 제목");
  await expect(page.locator(".scrape-quota")).toHaveText("오늘 12 / 100회");
});

test("여러 게임은 후보 선택 후 다음 항목으로 진행하고 모두 검토한 뒤 적용한다", async ({ page }) => {
  await openForRows(page, 2);
  await expect(page.locator(".scrape-context-head")).toContainText("1 / 2");
  await page.locator(".scrape-choose").first().click();
  await expect(page.locator(".scrape-context-head")).toContainText("2 / 2");
  await expect(page.locator(".scrape-candidate").first()).toBeVisible();
  await page.locator(".scrape-choose").first().click();
  const apply = page.getByRole("button", { name: "선택 결과 적용" });
  await expect(apply).toBeEnabled();
  await apply.click();
  await expect(page.locator(".scrape-context-card")).toHaveCount(0);
  await expect(page.locator("#toast")).toContainText("1개 게임에 스크랩 결과를 적용했습니다");
});

test("취소는 진행 세션을 폐기한다", async ({ page }) => {
  await page.evaluate(() => {
    window.__scrapeCancelled = 0;
    const original = window.api.cancelScrapeSession;
    window.api.cancelScrapeSession = (...args) => {
      window.__scrapeCancelled += 1;
      return original(...args);
    };
  });
  await openForRows(page);
  await page.getByRole("button", { name: "취소" }).click();
  await expect(page.locator(".scrape-context-card")).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => window.__scrapeCancelled)).toBe(1);
});
