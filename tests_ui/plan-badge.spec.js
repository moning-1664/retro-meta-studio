// Apply 버튼의 개수 표시 - 실사용 결정: 괄호 글자 "Apply (N)" 대신, 오른쪽 위
// 대각선에 빨간 동그라미 뱃지로 보여준다. 알림 뱃지와 같은 언어라 글자를 읽지
// 않아도 "지금 처리될 게 있다"는 게 한눈에 들어온다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const applyButton = (page) => page.locator("#filter-bar .plan-actions .seg-btn", { hasText: "Apply" });

// plan_state 목업을 원하는 total/runnable로 바꾸고, Delete는 refreshPlan()을
// 거치는 기존 동작이라 그걸 빌려 새 상태를 읽게 한다(storage-move.spec.js와 같은 방식).
const setPlanTotals = async (page, { total, runnable }) => {
  await page.evaluate(({ total, runnable }) => {
    const original = window.api.planState;
    window.api.planState = async (id) => {
      const r = await original(id);
      if (r.ok) { r.data.total = total; r.data.runnable = runnable; }
      return r;
    };
  }, { total, runnable });
  await page.locator(".lrow").first().click();
  await page.keyboard.press("Delete");
};

test("Plan이 비어 있으면 뱃지도 없고 글자 그대로 'Apply'다", async ({ page }) => {
  await expect(applyButton(page)).toHaveText("Apply");
  await expect(applyButton(page).locator(".plan-apply-badge")).toHaveCount(0);
});

test("처리될 게 있으면 괄호 글자가 아니라 뱃지로 개수를 보여준다", async ({ page }) => {
  await setPlanTotals(page, { total: 3, runnable: 3 });
  await expect(applyButton(page)).toHaveClass(/on/);
  // 버튼 자체의 글자는 "Apply"뿐이다 - 개수는 뱃지 안에만 있다.
  await expect(applyButton(page)).not.toContainText("Apply (3)");
  const badge = applyButton(page).locator(".plan-apply-badge");
  await expect(badge).toBeVisible();
  await expect(badge).toHaveText("3");
});

test("99개를 넘으면 '99+'로 자른다(원 모양이 무너지지 않게)", async ({ page }) => {
  await setPlanTotals(page, { total: 150, runnable: 150 });
  await expect(applyButton(page).locator(".plan-apply-badge")).toHaveText("99+");
});

test("뱃지는 버튼 상자 밖(오른쪽 위)으로 튀어나온다", async ({ page }) => {
  // .seg의 기본 overflow:hidden에 잘리면 실제로는 안 보인다 - .plan-actions는
  // 그 규칙을 풀어 둬야 한다(style.css).
  await setPlanTotals(page, { total: 3, runnable: 3 });
  const overflow = await page.locator(".plan-actions").evaluate((el) => getComputedStyle(el).overflow);
  expect(overflow).toBe("visible");
  const btnBox = await applyButton(page).boundingBox();
  const badgeBox = await applyButton(page).locator(".plan-apply-badge").boundingBox();
  expect(badgeBox.y).toBeLessThan(btnBox.y);   // 버튼 위쪽 경계보다 더 위
  expect(badgeBox.x + badgeBox.width).toBeGreaterThan(btnBox.x + btnBox.width - 4);   // 오른쪽 경계 근처
});

test("뱃지가 Cancel 버튼에 가려지지 않는다(실사용 확인)", async ({ page }) => {
  // Apply가 DOM에서 Cancel보다 먼저 오는 형제라, z-index를 안 주면 뒤에 오는
  // Cancel이 그냥 위에 그려져서 뱃지의 오른쪽 절반이 잘려 보였다.
  await setPlanTotals(page, { total: 99, runnable: 150 });
  const applyZ = await applyButton(page).evaluate((el) => getComputedStyle(el).zIndex);
  expect(applyZ).not.toBe("auto");
  // 뱃지 중심점이 실제로 Cancel이 아니라 뱃지 자신에게 히트 테스트된다.
  const badgeBox = await applyButton(page).locator(".plan-apply-badge").boundingBox();
  const topEl = await page.evaluate(({ x, y }) => {
    const el = document.elementFromPoint(x, y);
    return el ? el.className : null;
  }, { x: badgeBox.x + badgeBox.width / 2, y: badgeBox.y + badgeBox.height / 2 });
  expect(topEl).toContain("plan-apply-badge");
});

test("충돌만 있어 Apply를 못 누르면 뱃지도 없다", async ({ page }) => {
  // runnable이 0이면(총 개수는 있어도 전부 충돌) Apply 자체가 비활성이고,
  // 뱃지가 뜨면 "이 개수만큼 지금 처리된다"는 거짓 정보가 된다.
  await setPlanTotals(page, { total: 5, runnable: 0 });
  await expect(applyButton(page)).toBeDisabled();
  await expect(applyButton(page).locator(".plan-apply-badge")).toHaveCount(0);
});

test("하단 추가 개수를 누르면 Plan 항목을 확인할 수 있다", async ({ page }) => {
  await page.evaluate(() => {
    const original = window.api.planState;
    window.api.planState = async (id) => {
      const result = await original(id);
      if (result.ok) Object.assign(result.data, {
        total: 1, runnable: 1, added: 1,
        entries: [{ op: "add", system: "ps2", filename: "New Game.iso", status: "pending" }],
      });
      return result;
    };
  });
  await page.locator(".lrow").first().click();
  await page.keyboard.press("Delete");
  await page.locator("#status-bar .sb-plan-count").click();
  await expect(page.locator(".modal-title")).toContainText("Plan · 1개");
  await expect(page.locator(".plan-overview-row")).toContainText("ps2 / New Game.iso");
});
