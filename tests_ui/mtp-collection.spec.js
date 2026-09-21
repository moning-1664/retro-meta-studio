/**
 * Collection 추가 > 안드로이드 기기(MTP).
 *
 * 기기는 폴더 선택 대화상자로 고를 수 없다 - 드라이브 문자가 없기 때문이다. 그래서
 * "저장 위치"를 먼저 고르고, 기기를 고르고, ES-DE 폴더는 자동으로 찾되 다르면 기기
 * 안을 한 단계씩 열어 보고 고른다(사용자 결정).
 */
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

const DEVICE_ROOT = "mtp://R58N30ABCDE";

async function openAddDialog(page) {
  await page.locator(".ctab-add").click();
  await expect(page.locator("#add-source")).toBeVisible();
}

test.beforeEach(async ({ page }) => { await openApp(page); });

test("기본은 이 PC - 기기 항목은 숨어 있다", async ({ page }) => {
  await openAddDialog(page);
  await expect(page.locator("#add-source .seg-btn.on")).toHaveText(/이 PC/);
  await expect(page.locator("#add-device")).toBeHidden();
});

test("기기를 고르면 기기 목록이 뜨고 ES-DE 폴더를 자동으로 찾는다", async ({ page }) => {
  await openAddDialog(page);
  await page.click("#add-source .seg-btn:has-text('MTP')");
  await expect(page.locator("#add-device")).toBeVisible();
  await expect(page.locator("#add-device option")).toHaveText(["Galaxy Test"]);
  await expect(page.locator("#add-metadata-path")).toHaveValue(`${DEVICE_ROOT}/Internal shared storage/ES-DE`);
  // 자동으로 찾았다는 사실과, 다르면 어떻게 하는지를 같이 말해 준다.
  await expect(page.locator(".field-hint")).toContainText("찾아보기");
});

test("기기 안을 한 단계씩 열어 보고 폴더를 고른다", async ({ page }) => {
  await openAddDialog(page);
  await page.click("#add-source .seg-btn:has-text('MTP')");
  // ROM 폴더는 선택 사항이다 - 넣으면 ROM 파일까지 확인한다(읽기는 전송이 아니다).
  // 찾아보기 버튼은 PC/Android 하나뿐이다 - 저장 위치는 위 탭에서 이미 골랐다.
  await page.locator("#add-rom-path").locator("xpath=..").getByText("찾아보기").click();
  await expect(page.locator("#mtp-browser")).toBeVisible();
  await page.click("#mtp-browser .picker-row:has-text('Internal shared storage')");
  await page.click("#mtp-browser .picker-row:has-text('ROMs')");
  await page.click("#mtp-pick-here");
  await expect(page.locator("#add-rom-path")).toHaveValue(`${DEVICE_ROOT}/Internal shared storage/ROMs`);
  await expect(page.locator("#mtp-browser")).toBeHidden();
});

test("위로 올라가면 한 단계 위 폴더가 보인다", async ({ page }) => {
  await openAddDialog(page);
  await page.click("#add-source .seg-btn:has-text('MTP')");
  await page.locator("#add-metadata-path").locator("xpath=..").getByText("찾아보기").click();
  await page.click("#mtp-browser .picker-row:has-text('Internal shared storage')");
  await expect(page.locator("#mtp-browser .picker-row:has-text('ES-DE')")).toBeVisible();
  // "위로"는 이제 목록 안 행이 아니라 탐색기 주소창처럼 생긴 헤더의 버튼이다
  // (실사용 피드백 - "explorer처럼 더 직관적인 선택을 원한다").
  await page.click(".mtp-up-btn");
  await expect(page.locator("#mtp-browser .picker-row:has-text('SD card')")).toBeVisible();
});

test("주소창 조각(breadcrumb)을 누르면 그 폴더로 바로 이동한다", async ({ page }) => {
  await openAddDialog(page);
  await page.click("#add-source .seg-btn:has-text('MTP')");
  await page.locator("#add-metadata-path").locator("xpath=..").getByText("찾아보기").click();
  await page.click("#mtp-browser .picker-row:has-text('Internal shared storage')");
  await page.click("#mtp-browser .picker-row:has-text('ES-DE')");
  await expect(page.locator(".mtp-crumb.current")).toHaveText("ES-DE");
  // 세 단계 위(기기 이름 조각)를 한 번에 누른다 - "위로"를 여러 번 누를 필요가 없다.
  await page.click(".mtp-crumb:has-text('Galaxy Test')");
  await expect(page.locator("#mtp-browser .picker-row:has-text('Internal shared storage')")).toBeVisible();
  await expect(page.locator(".mtp-crumb.current")).toHaveText("Galaxy Test");
});

test("찾아보기 버튼은 PC/Android 저장 위치마다 하나뿐이다", async ({ page }) => {
  // 예전엔 "찾아보기"와 "기기에서 찾기"가 나란히 있었다 - 저장 위치를 이미 탭에서
  // 골랐으니 같은 일을 하는 버튼 두 개였다(실사용 피드백).
  await openAddDialog(page);
  const romRow = page.locator("#add-rom-path").locator("xpath=..");
  await expect(romRow.getByRole("button")).toHaveCount(1);
  await page.click("#add-source .seg-btn:has-text('MTP')");
  await expect(romRow.getByRole("button")).toHaveCount(1);
});
