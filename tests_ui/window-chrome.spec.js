// frameless 창의 자체 크롬 (Phase 7.6).
//
// 창에서 네이티브 제목 표시줄을 없앴으므로(`frameless=True`), 제목 표시줄과 **크기 조절
// 손잡이**를 앱이 직접 그린다. 네이티브 테두리가 사라진 자리를 이것들이 대신하므로,
// 없어지면 사용자는 창을 옮기거나 크기를 바꿀 수 없게 된다.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

// TopBar(레이아웃 재검토로 App Title 막대 + Collection 탭 막대를 하나로
// 합쳤다) - Archive/Collection 탭은 클릭 영역, 그 오른쪽 빈 공간
// (#topbar-drag)만 창을 끄는 자리다. 탭과 드래그가 한 줄에 있으므로 이 둘이
// 겹치지 않는지가 예전보다 더 중요해졌다.

test("탭 오른쪽 빈 공간이 끌 수 있는 영역이다", async ({ page }) => {
  // pywebview는 이 클래스가 붙은 곳을 끌 때만 창을 옮긴다.
  await expect(page.locator("#topbar-drag.pywebview-drag-region")).toHaveCount(1);
});

test("Archive/Collection 탭과 창 버튼은 끌기 영역이 아니다", async ({ page }) => {
  // 탭이나 버튼에까지 끌기 영역이 붙으면 누를 때 창이 딸려 움직인다.
  await expect(page.locator(".ctab.pywebview-drag-region")).toHaveCount(0);
  await expect(page.locator("#window-controls.pywebview-drag-region")).toHaveCount(0);
  await expect(page.locator("#window-controls .win-btn")).toHaveCount(3);
});

test("Archive 탭이 맨 앞이다", async ({ page }) => {
  const first = page.locator("#tabs-bar .ctab").first();
  await expect(first).toHaveClass(/archive/);
});

test("창 버튼은 윈도우와 같은 기호를 쓴다", async ({ page }) => {
  const labels = await page.locator("#window-controls .win-btn").allTextContents();
  expect(labels).toEqual(["–", "□", "×"]);
});

test("App Title은 없앴다", async ({ page }) => {
  await expect(page.locator("#topbar")).not.toContainText("RetroMeta Studio");
});

test("Window Controls는 TopBar 오른쪽 끝에 고정된다", async ({ page }) => {
  const bar = await page.locator("#topbar").boundingBox();
  const controls = await page.locator("#window-controls").boundingBox();
  expect(controls.x + controls.width).toBeCloseTo(bar.x + bar.width, 0);
});

test("탭 오른쪽 빈 공간은 최소 폭 아래로 사라지지 않는다", async ({ page }) => {
  const dragBox = await page.locator("#topbar-drag").boundingBox();
  expect(dragBox.width).toBeGreaterThan(0);
});

test("Collection이 많아져도 Window Controls와 최소 Drag 공간은 유지된다", async ({ page }) => {
  // 탭이 넘치면 #tabs-bar 안에서 스크롤될 뿐, 옆의 Drag 공간과 Window
  // Controls를 밀어내지 않아야 한다.
  for (let i = 0; i < 8; i++) {
    await page.locator(".ctab-add").click();
    await page.locator(".modal-body input[placeholder='예: Android ES-DE']").fill(`탭 스트레스 ${i}`);
    await page.locator(".modal-body .btn", { hasText: "찾아보기" }).first().click();
    await modalButton(page, "Add").click();
  }
  await expect(page.locator("#tabs-bar .ctab")).toHaveCount(10); // Archive + 원래 2개 + 새 8개

  const bar = await page.locator("#topbar").boundingBox();
  const controls = await page.locator("#window-controls").boundingBox();
  const dragBox = await page.locator("#topbar-drag").boundingBox();
  expect(controls.x + controls.width).toBeCloseTo(bar.x + bar.width, 0);
  expect(dragBox.width).toBeGreaterThan(0);
});

test("크기 조절 손잡이가 오른쪽 아래에 있다", async ({ page }) => {
  const grip = page.locator("#resize-grip");
  await expect(grip).toBeVisible();

  const box = await grip.boundingBox();
  const viewport = page.viewportSize();
  expect(box.x + box.width).toBeGreaterThan(viewport.width - 4);
  expect(box.y + box.height).toBeGreaterThan(viewport.height - 4);
});

test("손잡이를 끌면 창 크기 변경을 요청한다", async ({ page }) => {
  const calls = [];
  await page.exposeFunction("__recordResize", (w, h) => calls.push([w, h]));
  await page.evaluate(() => {
    const original = window.api.windowResize;
    window.api.windowResize = (w, h) => { window.__recordResize(w, h); return original(w, h); };
  });

  const grip = page.locator("#resize-grip");
  const box = await grip.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + 200, box.y + 150, { steps: 5 });
  await page.mouse.up();

  await expect.poll(() => calls.length).toBeGreaterThan(0);
  const [width, height] = calls[calls.length - 1];
  expect(width).toBeGreaterThanOrEqual(900);
  expect(height).toBeGreaterThanOrEqual(640);
});

test("손잡이를 반대로 끌어도 최소 크기 아래로는 안 내려간다", async ({ page }) => {
  // 창은 줄었는데 안쪽 레이아웃이 깨지는 상태를 만들면 안 된다.
  const calls = [];
  await page.exposeFunction("__recordShrink", (w, h) => calls.push([w, h]));
  await page.evaluate(() => {
    window.api.windowResize = (w, h) => { window.__recordShrink(w, h); return Promise.resolve({ ok: true }); };
  });

  const grip = page.locator("#resize-grip");
  const box = await grip.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x - 600, box.y - 600, { steps: 5 });
  await page.mouse.up();

  await expect.poll(() => calls.length).toBeGreaterThan(0);
  for (const [width, height] of calls) {
    expect(width).toBeGreaterThanOrEqual(900);
    expect(height).toBeGreaterThanOrEqual(640);
  }
});

test("상세 패널은 고정 컬럼이다 - 선택 전에도 자리를 지킨다", async ({ page }) => {
  // 예전에는 width 0 <-> 340px를 오가며 슬라이드해서 목록 폭이 그때그때 달라졌다.
  const panel = page.locator("#detail-panel");
  const before = await panel.boundingBox();
  expect(before.width).toBe(340);
  await expect(panel.locator(".panel-empty-state")).toBeVisible();

  await page.locator(".lrow").first().click();
  await expect(panel).toHaveClass(/open/);
  const after = await panel.boundingBox();
  expect(after.width).toBe(before.width);
});
