// 다국어 - UI 문구만 번역하고, 한국어로 되돌리면 원문이 그대로 돌아와야 한다.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("번역표는 언어별로 문구를 돌려주고 모르는 문구는 그대로 둔다", async ({ page }) => {
  const r = await page.evaluate(() => {
    const i = window.RMSI18n;
    i.setLanguage("en");
    const en = [i.t("취소"), i.t("3개 선택됨"), i.t("Archive 설정"), i.t("  저장 "), i.t("Final Fantasy X")];
    i.setLanguage("ja");
    const ja = i.t("취소");
    i.setLanguage("ko");
    return { en, ja, ko: i.t("취소") };
  });
  expect(r.en).toEqual(["Cancel", "3 selected", "Archive settings", "  Save ", "Final Fantasy X"]);
  expect(r.ja).toBe("キャンセル");
  expect(r.ko).toBe("취소");
});

test("Settings > General에서 언어를 바꾸면 화면이 바뀌고, 한국어로 되돌리면 원래대로다", async ({ page }) => {
  await page.locator(".settings-btn").click();
  await page.locator(".stg-nav-item[data-section='general']").click();
  const select = page.locator(".stg-row[data-key='general.language'] select");
  await expect(select.locator("option")).toHaveCount(5);
  await expect(page.locator(".stg-foot .btn")).toHaveText("확인");
  await select.selectOption("en");
  await expect(page.locator(".stg-foot .btn")).toHaveText("OK");
  await select.selectOption("ko");
  await expect(page.locator(".stg-foot .btn")).toHaveText("확인");
});

test("언어 드롭다운은 각 언어를 자기 나라 표기로 보여준다 - 번역을 거치지 않는다", async ({ page }) => {
  // "한국어"는 번역표에 "Korean"/"韓国語" 항목이 있는 흔한 문구다(i18n-data.js) - 이
  // 드롭다운의 옵션이 h()의 일반 문자열 자식처럼 번역을 거치면, 화면 언어가 영어일 때
  // "한국어" 옵션이 "Korean"으로 바뀌어 버린다(메뉴 정리 §9, 실사용 지적).
  await page.locator(".settings-btn").click();
  await page.locator(".stg-nav-item[data-section='general']").click();
  const select = page.locator(".stg-row[data-key='general.language'] select");
  await select.selectOption("en");
  const labels = await select.locator("option").allTextContents();
  expect(labels).toEqual(["한국어", "English", "日本語", "Español", "Français"]);
  await select.selectOption("ko");
});
