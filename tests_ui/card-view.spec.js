// Card(격자) 보기 - QA 재검토 P1: 토글 버튼만 있고 실제로 아무것도 안 바뀌던 것을
// 고친다. List/Card 전환이 실제로 다른 DOM(가상 스크롤 행 vs grid 카드)을 그린다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("카드 우클릭은 목록과 같은 메뉴를 연다", async ({ page }) => {
  await page.locator("#filter-bar .seg-btn[title='카드 보기']").click();
  await page.locator(".preview-card").first().click({button:"right"});
  await expect(page.locator(".ctx-menu")).toBeVisible();
  await expect(page.locator(".ctx-menu")).toContainText("복사");
});

test("빈 공간에서 드래그하면 사각형 안의 카드를 선택한다", async ({ page }) => {
  await page.locator("#filter-bar .seg-btn[title='카드 보기']").click();
  const cards = await page.locator(".preview-card").evaluateAll((items) => items.map(item => {
    const rect=item.getBoundingClientRect(); return {left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom};
  }));
  await page.mouse.move(cards[0].left-3, cards[0].top-3);
  await page.mouse.down();
  await page.mouse.move(cards[1].right+2, cards[1].bottom+2, {steps:8});
  await page.mouse.up();
  await expect(page.locator(".preview-card.selected")).toHaveCount(2);
  await expect(page.locator(".card-selection-box")).toHaveCount(0);
});

test("Ctrl+Shift 클릭은 카드의 직사각형 영역을 고른다", async ({page}) => {
  await page.evaluate(() => {
    const original=window.api.listRows;
    window.api.listRows=async (...args) => {
      const result=await original(...args);
      result.data.rows=Array.from({length:12}, (_, index) => ({...result.data.rows[index%3],romUid:100+index}));
      result.data.total=12;
      return result;
    };
  });
  await page.locator(".lh-file").click();
  await page.locator("#filter-bar .seg-btn[title='카드 보기']").click();
  await expect(page.locator(".preview-card")).toHaveCount(12);
  const cards=page.locator(".preview-card");
  const geometry=await cards.evaluateAll(items => items.map(item => {
    const r=item.getBoundingClientRect();return {key:item.dataset.romUid,left:r.left,right:r.right,top:r.top,bottom:r.bottom};
  }));
  const first=geometry[0];
  const secondRow=geometry.findIndex(r=>r.top>first.top+1);
  expect(secondRow).toBeGreaterThan(1);
  const last=geometry[secondRow+1];
  const expected=geometry.filter(r=>r.left>=first.left-1 && r.right<=last.right+1 && r.top>=first.top-1 && r.bottom<=last.bottom+1).map(r=>r.key);
  await cards.first().click();
  await cards.nth(secondRow+1).click({modifiers:['Control','Shift']});
  expect(await page.locator(".preview-card.selected").evaluateAll(items=>items.map(item=>item.dataset.romUid))).toEqual(expected);
});

test("기본은 List 보기다", async ({ page }) => {
  await expect(page.locator(".lrow")).toHaveCount(3);
  await expect(page.locator(".preview-card")).toHaveCount(0);
});

test("Card를 누르면 카드 격자로 바뀐다", async ({ page }) => {
  await page.locator("#filter-bar .seg-btn[title='카드 보기']").click();
  await expect(page.locator(".preview-card")).toHaveCount(3);
  await expect(page.locator(".lrow")).toHaveCount(0);
  await expect(page.locator("#list-window")).toHaveClass(/card-mode/);
});

test("카드에 제목이 보인다", async ({ page }) => {
  await page.locator("#filter-bar .seg-btn[title='카드 보기']").click();
  await expect(page.locator(".preview-title").first()).not.toBeEmpty();
});

test("카드를 누르면 선택되고 상세 패널이 열린다", async ({ page }) => {
  await page.locator("#filter-bar .seg-btn[title='카드 보기']").click();
  await page.locator(".preview-card").first().click();
  await expect(page.locator(".preview-card").first()).toHaveClass(/selected/);
  await expect(page.locator("#detail-panel")).toHaveClass(/open/);
});

test("다시 List를 누르면 원래대로 돌아온다", async ({ page }) => {
  await page.locator("#filter-bar .seg-btn[title='카드 보기']").click();
  await expect(page.locator(".preview-card")).toHaveCount(3);
  await page.locator("#filter-bar .seg-btn[title='목록 보기']").click();
  await expect(page.locator(".lrow")).toHaveCount(3);
  await expect(page.locator(".preview-card")).toHaveCount(0);
});

// ======================================================================
// 다시 만들지 않는다 (P0 - "깜박이며 전부 다시 읽는" 증상의 정체)
// ======================================================================
//
// 예전에는 `renderListWindow()`가 카드 갈래로 넘기기 전에 `clear(win)`을 했고,
// 스크롤 이벤트가 rAF마다 그것을 불렀다. 그래서 스크롤할 때마다 모든 카드가
// 사라졌다 다시 생기고, 카드 수만큼 표지 이미지 요청이 다시 나갔다. 게임 하나를
// 고르는 것도 같은 경로였다.
//
// 여기서는 **DOM 요소가 그대로인가**로 확인한다. 개수만 보면 다시 만들어도 같다.
async function toCardMode(page) {
  await page.locator("#filter-bar .seg-btn[title='카드 보기']").click();
  await expect(page.locator(".preview-card")).toHaveCount(3);
  // 각 카드에 표식을 남긴다. 다시 만들어지면 이 표식이 사라진다.
  await page.evaluate(() => {
    document.querySelectorAll(".preview-card").forEach((el, i) => { el.dataset.mark = "m" + i; });
  });
}

const marks = (page) => page.evaluate(() =>
  [...document.querySelectorAll(".preview-card")].map((el) => el.dataset.mark || "GONE"));

test.describe("카드는 다시 만들어지지 않는다", () => {
  test("선택해도 카드 DOM이 그대로다", async ({ page }) => {
    await toCardMode(page);
    await page.locator(".preview-card").first().click();
    await expect(page.locator(".preview-card").first()).toHaveClass(/selected/);
    expect(await marks(page)).toEqual(["m0", "m1", "m2"]);
  });

  test("선택을 옮겨도 카드 DOM이 그대로다", async ({ page }) => {
    await toCardMode(page);
    await page.locator(".preview-card").nth(0).click();
    await page.locator(".preview-card").nth(1).click();
    await expect(page.locator(".preview-card").nth(1)).toHaveClass(/selected/);
    await expect(page.locator(".preview-card").nth(0)).not.toHaveClass(/selected/);
    expect(await marks(page)).toEqual(["m0", "m1", "m2"]);
  });

  test("스크롤해도 카드 DOM이 그대로다", async ({ page }) => {
    await toCardMode(page);
    await page.evaluate(() => {
      const el = document.getElementById("list-scroll");
      el.scrollTop = 200; el.dispatchEvent(new Event("scroll"));
      el.scrollTop = 0;   el.dispatchEvent(new Event("scroll"));
    });
    await page.waitForTimeout(120);   // rAF 두어 프레임
    expect(await marks(page)).toEqual(["m0", "m1", "m2"]);
  });

  test("선택 때문에 표지 이미지를 다시 요청하지 않는다", async ({ page }) => {
    let calls = 0;
    await page.exposeFunction("__cover", () => { calls += 1; });
    await page.evaluate(() => {
      const original = window.api.getMediaImage;
      window.api.getMediaImage = (...args) => { window.__cover(); return original(...args); };
    });

    await toCardMode(page);
    await page.waitForTimeout(150);
    const afterRender = calls;

    await page.locator(".preview-card").nth(0).click();
    await page.locator(".preview-card").nth(1).click();
    await page.waitForTimeout(150);

    // 상세 패널이 열리며 그 게임의 media를 받는 것은 정상이다. 확인하려는 것은
    // "카드 전체가 다시 요청되지 않는가"이므로, 카드 수만큼 늘어나면 안 된다.
    expect(calls - afterRender).toBeLessThan(3);
  });

  test("행 집합이 바뀌면 그때는 새로 짓는다", async ({ page }) => {
    await toCardMode(page);
    // System을 좁히면 보여줄 행 자체가 달라진다 - 이때는 다시 지어야 맞다.
    await page.locator(".nav-system", { hasText: "SNES" }).click();
    await expect(page.locator(".preview-card")).toHaveCount(1);
    expect(await marks(page)).toEqual(["GONE"]);
  });
});
