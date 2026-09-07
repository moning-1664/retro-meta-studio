// Favorite 필드 회귀 테스트 (단위 9): 별 클릭/Space 토글, 즐겨찾기만 보기 필터,
// 삭제 시 자동 제외. mock 모드 배경은 settings-and-dashboard.spec.js 상단 주석 참고.
const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.goto("/index.html");
  await expect(page.locator('[data-rom-key="snes|Super Mario World.zip"]')).toBeVisible();
});

test.describe("즐겨찾기 토글", () => {
  test("별 아이콘 클릭으로 즐겨찾기를 켜고 끌 수 있다", async ({ page }) => {
    const star = page.locator('[data-rom-key="snes|Super Mario World.zip"] .favorite-star');
    await expect(star).not.toHaveClass(/active/);
    await star.click();
    await expect(star).toHaveClass(/active/);
    await star.click();
    await expect(star).not.toHaveClass(/active/);
  });

  test("별 클릭이 행 선택(클릭 전파)을 트리거하지 않는다", async ({ page }) => {
    await page.locator('[data-rom-key="snes|Zelda.zip"]').click();
    const star = page.locator('[data-rom-key="snes|Super Mario World.zip"] .favorite-star');
    await star.click();
    // 여전히 Zelda가 선택된 상태여야 한다 (SMW 행이 선택으로 바뀌지 않음).
    await expect(page.locator('[data-rom-key="snes|Zelda.zip"]')).toHaveClass(/selected/);
    await expect(page.locator('[data-rom-key="snes|Super Mario World.zip"]')).not.toHaveClass(/selected/);
  });

  test("Space 키로 선택된 게임의 즐겨찾기를 토글한다", async ({ page }) => {
    await page.locator('[data-rom-key="snes|Zelda.zip"]').click();
    await page.keyboard.press("Space");
    await expect(page.locator('[data-rom-key="snes|Zelda.zip"] .favorite-star')).toHaveClass(/active/);
    await page.keyboard.press("Space");
    await expect(page.locator('[data-rom-key="snes|Zelda.zip"] .favorite-star')).not.toHaveClass(/active/);
  });
});

test.describe("즐겨찾기만 보기 필터", () => {
  test("토글을 켜면 즐겨찾기한 게임만 남는다", async ({ page }) => {
    await page.locator('[data-rom-key="snes|Zelda.zip"] .favorite-star').click();

    const filterToggle = page.locator("#filter-bar .favorite-only-toggle input[type=checkbox]");
    await filterToggle.check();

    await expect(page.locator('[data-rom-key="snes|Zelda.zip"]')).toBeVisible();
    await expect(page.locator('[data-rom-key="snes|Super Mario World.zip"]')).toHaveCount(0);

    await filterToggle.uncheck();
    await expect(page.locator('[data-rom-key="snes|Super Mario World.zip"]')).toBeVisible();
  });
});

test.describe("삭제 시 자동 제외", () => {
  test("즐겨찾기한 게임은 다중 삭제 대상에서 제외되고 안내 토스트가 뜬다", async ({ page }) => {
    await page.locator('[data-rom-key="snes|Zelda.zip"] .favorite-star').click();

    // 두 행 모두 multiSelect에 들어가도록 둘 다 Ctrl+클릭한다 (일반 클릭 후 Ctrl+클릭하면
    // 앞서 선택된 selectedGame은 multiSelect에 합쳐지지 않는다).
    await page.keyboard.down("Control");
    await page.locator('[data-rom-key="snes|Zelda.zip"]').click();
    await page.locator('[data-rom-key="snes|Super Mario World.zip"]').click();
    await page.keyboard.up("Control");

    // Rom 삭제 대상 체크박스를 켠 뒤 Delete.
    await page.locator("#delete-bar label", { hasText: "Rom" }).locator("input").check();
    await page.keyboard.press("Delete");

    const confirmBox = page.locator(".modal-box", { hasText: "게임 삭제" });
    await expect(confirmBox).toBeVisible();
    await confirmBox.getByRole("button", { name: "확인" }).click();

    await expect(page.locator("#toast.show")).toContainText("즐겨찾기 1개는 자동 제외됨");
    // 즐겨찾기였던 Zelda는 남아있고, Super Mario World는 삭제되어야 한다.
    await expect(page.locator('[data-rom-key="snes|Zelda.zip"]')).toBeVisible();
    await expect(page.locator('[data-rom-key="snes|Super Mario World.zip"]')).toHaveCount(0);
  });
});
