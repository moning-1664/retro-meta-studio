// Plan이 Gamelist/Status Bar에 어떻게 드러나는지 - 사용자 결정을 그대로 따른다:
//
//   "추가예정, 삭제 예정은 아래 status bar에 두는게 자연스럽지 않아?"
//   "실제로 추가/삭제될 항목은 +-로 no 대신 표시해주고"
//   "정보가 덮어질 항목은 +-말고 문서아이콘으로 파란색으로 표시하면 되겠구만"
//
// 그래서 최종 구성은 이렇다:
//   - No. 칸(왼쪽, 가장 먼저 눈에 들어오는 자리) - 번호 대신 +(추가)/-(삭제)/
//     파란 문서 아이콘(편집)이 선다.
//   - **행 전체는 물들이지 않는다**(사용자 결정 - "plan은 전체 색이 아니라 no쪽에 + - 를
//     표시하고 각각 노랑 빨강"). 행을 칠하면 선택/포커스 색과 겹쳐 오히려 흐려진다.
//   - 하단 Status Bar가 "몇 개가 바뀌는지"를 노랑(+N개)/빨강(-M개)으로 요약한다.
//
// (예전에 시도했던 "Gamelist 위 노란 미리보기 띠"는 자연스럽지 않다는 피드백으로
// 빠졌다 - ADD처럼 아직 디스크에 없는 항목은 No. 칸에 붙을 행 자체가 없어 표시할
// 수 없고, 그 개수/용량은 Status Bar가 이미 말해준다.)
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

/** planState()를 직접 바꿔 끼운 뒤, refreshPlan()을 거치는 기존 동작(Delete)을
 * 빌려 다시 읽게 한다 - 목업의 plan_delete()는 marks.rows를 실제로 기록하지
 * 않는 stub이라(plan-badge.spec.js와 같은 사정) 이 방법이 필요하다. */
async function servePlanState(page, patch) {
  await page.evaluate((patchSource) => {
    const original = window.api.planState;
    const apply = new Function("data", patchSource);
    window.api.planState = async (id) => {
      const r = await original(id);
      if (r.ok) apply(r.data);
      return r;
    };
  }, patch);
  await page.locator(".lrow").first().click();
  await page.keyboard.press("Delete");
}

test("삭제 예정 행은 No. 칸에 번호 대신 - 아이콘이 선다", async ({ page }) => {
  await servePlanState(page, 'data.marks = { rows: { "ps2|FFX.iso": "-" }, systems: [] };');
  const row = page.locator(".lrow").first();
  const noCell = row.locator(".lc-no");
  await expect(noCell.locator(".lno-mark.del")).toBeVisible();
  await expect(noCell).not.toContainText("1");

  const otherNoCell = page.locator(".lrow").nth(1).locator(".lc-no");
  await expect(otherNoCell.locator(".lno-mark")).toHaveCount(0);
});

test("추가 예정으로 표시된 기존 행(메타데이터만 있던 항목)은 No. 칸에 + 아이콘이 선다", async ({ page }) => {
  // ADD는 원래 대상 파일이 없어 행 자체가 없는 게 보통이지만, 이미 메타데이터만
  // 있던(present=false) 항목이 채워지는 경우는 행이 이미 존재한다 - 그 경우엔
  // No. 칸이 정상적으로 + 아이콘을 보여줘야 한다.
  await servePlanState(page, 'data.marks = { rows: { "ps2|FFX.iso": "+" }, systems: [] };');
  await expect(page.locator(".lrow").first().locator(".lc-no .lno-mark.add")).toBeVisible();
});

test("편집 예정(제목 등 정보가 덮어써질 항목)은 No. 칸에 파란 문서 아이콘이 선다", async ({ page }) => {
  await servePlanState(page, 'data.marks = { rows: { "ps2|FFX.iso": "\\u270e" }, systems: [] };');
  const mark = page.locator(".lrow").first().locator(".lc-no .lno-mark.edit");
  await expect(mark).toBeVisible();
  const color = await mark.evaluate((el) => getComputedStyle(el).color);
  const delColorProbe = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--danger").trim());
  // 편집(파랑)은 삭제(빨강) 색과 달라야 한다 - 서로 다른 뜻이 같은 색으로
  // 뭉개지면 안 된다.
  expect(color).not.toContain(delColorProbe);
});

test("예정 표시는 No. 칸에만 있고 행 전체를 물들이지 않는다", async ({ page }) => {
  await servePlanState(page, 'data.marks = { rows: { "ps2|FFX.iso": "-" }, systems: [] };');
  const row = page.locator(".lrow").first();
  await expect(row).not.toHaveClass(/row-pending-delete/);
  // 삭제를 Plan에 올리면 선택은 비워진다 - 배경은 평범한 목록 줄 색 그대로여야 한다.
  await page.mouse.move(700, 500);                       // hover 색이 섞이지 않게 포인터를 치운다
  const bg = await row.evaluate((el) => getComputedStyle(el).backgroundColor);
  const plainBg = await page.evaluate(() => {
    const probe = document.createElement("span");
    probe.style.background = "var(--list-bg)";
    document.body.appendChild(probe);
    const c = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return c;
  });
  expect(bg).toBe(plainBg);
});

test("+ 는 노랑, - 는 빨강이다", async ({ page }) => {
  await servePlanState(page, 'data.marks = { rows: { "ps2|FFX.iso": "+", "ps2|MGS2.iso": "-" }, systems: [] };');
  const color = (sel) => page.locator(sel).first().evaluate((el) => getComputedStyle(el).color);
  const token = (name) => page.evaluate((n) =>
    getComputedStyle(document.documentElement).getPropertyValue(n).trim(), name);
  const [add, del, warning, danger] = await Promise.all([
    color(".lno-mark.add"), color(".lno-mark.del"), token("--warning"), token("--danger")]);
  const rgb = async (hex) => page.evaluate((h) => {
    const probe = document.createElement("span");
    probe.style.color = h; document.body.appendChild(probe);
    const c = getComputedStyle(probe).color; probe.remove(); return c;
  }, hex);
  expect(add).toBe(await rgb(warning));
  expect(del).toBe(await rgb(danger));
  expect(add).not.toBe(del);
});

test("하단 Status Bar는 개수를 노랑(추가)/빨강(삭제)으로 보여준다", async ({ page }) => {
  await servePlanState(page, `
    data.total = 5; data.added = 3; data.deleted = 2;
    data.addedBytes = 3000000000; data.deletedBytes = 2000000000;
  `);
  const add = page.locator(".sb-add");
  const del = page.locator(".sb-del");
  await expect(add).toContainText("+3개");
  await expect(add).toContainText("GB");
  await expect(del).toContainText("−2개");
  await expect(del).toContainText("GB");

  const [addColor, delColor, baseColor] = await Promise.all([
    add.evaluate((el) => getComputedStyle(el).color),
    del.evaluate((el) => getComputedStyle(el).color),
    page.locator(".sb-left span").first().evaluate((el) => getComputedStyle(el).color),
  ]);
  expect(addColor).not.toBe(delColor);
  expect(addColor).not.toBe(baseColor);
  expect(delColor).not.toBe(baseColor);
});

test("추가/삭제가 없으면 Status Bar에 아무 배지도 안 뜬다", async ({ page }) => {
  await expect(page.locator(".sb-add")).toHaveCount(0);
  await expect(page.locator(".sb-del")).toHaveCount(0);
});
