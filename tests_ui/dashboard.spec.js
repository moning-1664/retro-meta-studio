// Collection Dashboard - Navigator의 Dashboard가 중앙 영역을 바꾼다(사용자 결정: 전환 방식 유지).
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const openDashboard = async (page) => {
  await page.locator(".nav-dashboard").click();
  await expect(page.locator("#dashboard-view .dsb-title")).toBeVisible();
};

test("Dashboard를 누르면 목록 대신 Dashboard가 보인다", async ({ page }) => {
  await openDashboard(page);
  await expect(page.locator("#list-wrap")).toBeHidden();
  await expect(page.locator("#collection-header")).toBeHidden();
  await expect(page.locator(".nav-dashboard")).toHaveClass(/active/);
  await expect(page.locator(".dsb-title")).toHaveText("Master Library");
  await expect(page.locator(".dsb-tile").first()).toContainText("Games");
});

test("다시 누르면 목록으로 돌아간다", async ({ page }) => {
  await openDashboard(page);
  await page.locator(".nav-dashboard").click();
  await expect(page.locator("#list-wrap")).toBeVisible();
  await expect(page.locator("#dashboard-view")).toBeHidden();
});

test("사용량 막대에는 범례가 함께 있다(색만으로 구분하지 않는다)", async ({ page }) => {
  await openDashboard(page);
  const segments = await page.locator(".dsb-seg").count();
  expect(segments).toBeGreaterThan(1);
  await expect(page.locator(".dsb-legend-item")).toHaveCount(segments);
});

test("System 표의 행을 누르면 그 System의 목록으로 간다", async ({ page }) => {
  await openDashboard(page);
  await page.locator(".dsb-table tbody tr[data-system='snes']").click();
  await expect(page.locator("#list-wrap")).toBeVisible();
  await expect(page.locator(".cheader-name")).toHaveText("Super Nintendo · Master Library");
});

test("System 표는 머리글로 정렬된다", async ({ page }) => {
  await openDashboard(page);
  await page.locator(".dsb-sort", { hasText: "System" }).click();
  const first = await page.locator(".dsb-table tbody tr").first().getAttribute("data-system");
  expect(first).toBe("gba");
});

test("Validate Collection은 결과를 알려준다", async ({ page }) => {
  await openDashboard(page);
  await page.locator(".dsb-validate").click();
  await expect(page.locator(".dsb-validation")).toContainText("문제 없음");
});

// Metadata Validation 강화 - XML 문법뿐 아니라 ROM 연결/이름/중복/네 상태 집계까지
// 보여준다(사용자 요구). 최소 네 상태는 항상 보인다: Complete/Missing Media/
// Missing Description/Invalid XML.
test.describe("Validate Collection - 강화된 결과", () => {
  test("문제가 없어도 네 가지 상태 요약을 항상 보여준다", async ({ page }) => {
    await openDashboard(page);
    await page.locator(".dsb-validate").click();
    const summary = page.locator(".dsb-validate-summary");
    await expect(summary).toContainText("Complete");
    await expect(summary).toContainText("Invalid XML 0");
  });

  test("개수를 다시 세지 못했으면 숫자 대신 ?를 두고 이유를 말한다", async ({ page }) => {
    // 검사 전 재스캔이 실패하면 Complete/Missing 세 숫자는 지난 스캔의 기억이다.
    // 그대로 보여주면 지금 숫자인 줄 안다 - 못 믿는다는 것을 화면이 말해야 한다.
    await page.evaluate(() => {
      window.api.validateCollection = async () => ({ ok: true, data: {
        checked: 2, invalid: [], duplicates: [], issues: [],
        statuses: { complete: 1, missingMedia: 1, missingDescription: 1, invalidXml: 0 },
        countsStale: true, staleReason: "폴더를 읽지 못했습니다",
      } });
    });
    await openDashboard(page);
    await page.locator(".dsb-validate").click();
    const summary = page.locator(".dsb-validate-summary");
    await expect(summary).toContainText("Complete ?");
    await expect(summary).toContainText("스캔 실패");
    await expect(summary).toContainText("폴더를 읽지 못했습니다");
    // 파일을 직접 세는 항목은 이때도 정확하므로 숫자를 그대로 둔다.
    await expect(summary).toContainText("Invalid XML 0");
    // 숫자를 못 믿는데 "문제 없음"이라고 하면 안 된다.
    await expect(summary).not.toContainText("문제 없음");
  });

  test("Invalid XML이 있으면 요약과 목록에 모두 나온다", async ({ page }) => {
    await page.evaluate(() => {
      window.api.validateCollection = async () => ({ ok: true, data: {
        checked: 2, invalid: [{ system: "ps2", path: "D:\\ES-DE\\gamelists\\ps2\\gamelist.xml", error: "junk after document element" }],
        duplicates: [], issues: [],
        statuses: { complete: 0, missingMedia: 0, missingDescription: 0, invalidXml: 1 },
      } });
    });
    await openDashboard(page);
    await page.locator(".dsb-validate").click();
    await expect(page.locator(".dsb-validate-summary")).toContainText("Invalid XML 1");
    await expect(page.locator(".dsb-invalid")).toContainText("gamelist.xml");
  });

  test("중복 Metadata를 시스템/파일명/개수로 보여준다", async ({ page }) => {
    await page.evaluate(() => {
      window.api.validateCollection = async () => ({ ok: true, data: {
        checked: 1, invalid: [], issues: [],
        duplicates: [{ system: "ps2", filename: "FFX.iso", count: 2 }],
        statuses: { complete: 1, missingMedia: 0, missingDescription: 0, invalidXml: 0 },
      } });
    });
    await openDashboard(page);
    await page.locator(".dsb-validate").click();
    await expect(page.locator(".dsb-validation")).toContainText("중복된 Metadata");
    await expect(page.locator(".dsb-invalid")).toContainText("FFX.iso");
    await expect(page.locator(".dsb-invalid")).toContainText("2개");
  });

  test("ROM 없음/이름 없음 문제를 목록으로 보여준다", async ({ page }) => {
    await page.evaluate(() => {
      window.api.validateCollection = async () => ({ ok: true, data: {
        checked: 1, invalid: [], duplicates: [],
        issues: [
          { system: "ps2", filename: "Ghost.iso", issues: ["missingRom"] },
          { system: "ps2", filename: "NoName.iso", issues: ["missingMetadata"] },
        ],
        statuses: { complete: 0, missingMedia: 0, missingDescription: 0, invalidXml: 0 },
      } });
    });
    await openDashboard(page);
    await page.locator(".dsb-validate").click();
    await expect(page.locator(".dsb-validation")).toContainText("ROM 연결·이름 문제");
    await expect(page.locator(".dsb-invalid")).toContainText("Ghost.iso");
    await expect(page.locator(".dsb-invalid")).toContainText("ROM 없음");
    await expect(page.locator(".dsb-invalid")).toContainText("NoName.iso");
    await expect(page.locator(".dsb-invalid")).toContainText("이름 없음");
  });

  test("세부 문제는 접힌 채로 시작하고, ▼로 모두 펼쳐 칸 안에서 스크롤하며, ✕로 지운다", async ({ page }) => {
    await page.evaluate(() => {
      const issues = Array.from({ length: 25 }, (_, i) => ({
        system: "ps2", filename: `G${i}.iso`, issues: ["missingRom"],
      }));
      window.api.validateCollection = async () => ({ ok: true, data: {
        checked: 1, invalid: [], duplicates: [], issues,
        statuses: { complete: 0, missingMedia: 0, missingDescription: 0, invalidXml: 0 },
      } });
    });
    await openDashboard(page);
    await page.locator(".dsb-validate").click();
    const details = page.locator(".dsb-validate-details");
    await expect(details).toBeHidden();
    await expect(page.locator(".dsb-validate-toggle")).toContainText("세부 문제 25개");
    await page.locator(".dsb-validate-toggle").click();
    await expect(details).toBeVisible();
    await expect(page.locator(".dsb-invalid li")).toHaveCount(25);   // 잘라내지 않는다
    expect(await details.evaluate((el) => getComputedStyle(el).overflowY)).toBe("auto");
    await page.locator(".dsb-validate-toggle").click();
    await expect(details).toBeHidden();
    await page.locator(".dsb-validate-clear").click();
    await expect(page.locator(".dsb-validate-head")).toHaveCount(0);
  });

  test("검사 결과는 표를 다시 정렬해도 남는다", async ({ page }) => {
    await openDashboard(page);
    await page.locator(".dsb-validate").click();
    await expect(page.locator(".dsb-validation")).toContainText("문제 없음");
    await page.locator(".dsb-sort", { hasText: "Games" }).click();
    await expect(page.locator(".dsb-validation")).toContainText("문제 없음");
  });
});

test("System 표는 Media size 뒤에 Total size(ROM + Media)를 보여준다", async ({ page }) => {
  await openDashboard(page);
  const heads = (await page.locator(".dsb-table thead th").allTextContents()).map((t) => t.replace(/[↑↓]/g, "").trim());
  expect(heads).toEqual(["System", "Storage", "Games", "ROM size", "Media size", "Total size", "Status"]);
  const totals = await page.locator(".dsb-table tbody td.dsb-total").allTextContents();
  expect(totals.length).toBeGreaterThan(0);
  totals.forEach((text) => expect(text).toMatch(/\d/));
});

test("목표 용량을 바꾸면 그 Collection의 화면 상태로 저장된다", async ({ page }) => {
  const saved = [];
  await page.exposeFunction("__saved", (s) => saved.push(s));
  await page.evaluate(() => {
    const original = window.api.saveUiState;
    window.api.saveUiState = (id, s) => { window.__saved(s); return original(id, s); };
  });
  await openDashboard(page);
  const input = page.locator(".dsb-target[data-storage='internal'] .dsb-target-input");
  await input.fill("1 TB");
  await input.press("Enter");
  await expect.poll(() => saved.filter((s) => s.dashboardTargets).length).toBeGreaterThan(0);
  expect(saved.at(-1).dashboardTargets.internal).toBe(1024 ** 4);
  await expect(page.locator(".dsb-target[data-storage='internal'] .dsb-target-input")).toHaveValue("1 TB");
});

test("Archive 탭에서는 Dashboard를 열지 않고 이유를 알려준다", async ({ page }) => {
  await page.locator(".ctab.archive").click();
  await page.locator(".nav-dashboard").click();
  await expect(page.locator("#toast")).toContainText("Collection 탭");
  await expect(page.locator("#dashboard-view")).toBeHidden();
});

// Storage target Slider - 32GB~8TB를 로그 눈금으로 연속해서 움직이다가, 프리셋 근처에 오면 그 값에 딱
// 붙는다(사용자 결정). ▲▼는 세밀하게 한 칸씩 움직이고 프리셋에서 멈춘다. 키보드 ←→는 프리셋 단위.
// 기존 Storage Usage 계산(사용량 막대·표)에는 영향을 주지 않는다.
test.describe("Storage target Slider", () => {
  const GB = 1024 ** 3;
  const TB = 1024 ** 4;
  const row = (page) => page.locator(".dsb-target[data-storage='internal']");
  const slider = (page) => row(page).locator(".dsb-target-slider");
  const input = (page) => row(page).locator(".dsb-target-input");
  // 값을 보여주는 자리는 입력칸 하나뿐이다(실사용 피드백 §3) - 예전엔 따로
  // <span>이 있었는데, 굴리기(슬라이더)와 직접 입력(타이핑)이 서로 다른 칸에
  // 값을 보여줘서 "지금 이 숫자를 바꾸고 있다"는 게 헷갈렸다.
  const sliderValue = input;
  const posOf = (page, bytes) => page.evaluate((b) => window.RMSDashboard.toPos(b), bytes);
  // 드래그 중인 것처럼 값만 바꾸고 input 이벤트를 보낸다(손을 떼는 것은 release).
  const dragTo = (page, pos) => slider(page).evaluate((el, p) => {
    el.value = String(p);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }, pos);
  const release = (page) => slider(page).evaluate((el) => el.dispatchEvent(new Event("change", { bubbles: true })));

  const setTarget = async (page, text) => {
    await input(page).fill(text);
    await input(page).press("Enter");
  };

  test("텍스트로 512 GB를 정하면 Slider가 그 자리로 옮겨가고 그 눈금이 켜진다", async ({ page }) => {
    await openDashboard(page);
    await setTarget(page, "512 GB");
    await expect(slider(page)).toHaveAttribute("value", String(await posOf(page, 512 * GB)));
    await expect(sliderValue(page)).toHaveValue("512 GB");
    await expect(sliderValue(page)).toHaveClass(/snapped/);
    await expect(row(page).locator(`.dsb-tick[data-bytes='${512 * GB}']`)).toHaveClass(/on/);
  });

  test("끄는 동안 프리셋 근처에 오면 그 값에 딱 붙는다", async ({ page }) => {
    await openDashboard(page);
    await setTarget(page, "128 GB");
    const at = await posOf(page, 512 * GB);
    await dragTo(page, at + 9);
    await expect(sliderValue(page)).toHaveValue("512 GB");
    await expect(sliderValue(page)).toHaveClass(/snapped/);
    expect(await slider(page).evaluate((el) => el.value)).toBe(String(at));   // 손잡이도 눈금 위로 붙는다
    await release(page);
    await expect(input(page)).toHaveValue("512 GB");
  });

  test("프리셋에서 먼 자리에서는 세밀한 값이 된다", async ({ page }) => {
    await openDashboard(page);
    await setTarget(page, "128 GB");
    const a = await posOf(page, 256 * GB);
    const b = await posOf(page, 512 * GB);
    await dragTo(page, Math.round((a + b) / 2));
    await expect(sliderValue(page)).not.toHaveClass(/snapped/);
    const text = await sliderValue(page).inputValue();
    expect(text).toMatch(/^\d+ GB$/);
    const value = parseInt(text, 10);
    expect(value).toBeGreaterThan(300);
    expect(value).toBeLessThan(420);
    await release(page);
    await expect(input(page)).toHaveValue(text);
  });

  test("키보드 ←→는 프리셋 단위로 움직이고 초점이 Slider에 남는다", async ({ page }) => {
    await openDashboard(page);
    await setTarget(page, "512 GB");
    await slider(page).focus();
    await page.keyboard.press("ArrowRight");
    await expect(input(page)).toHaveValue("1 TB");
    await expect(slider(page)).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect(input(page)).toHaveValue("2 TB");
    await page.keyboard.press("ArrowLeft");
    await expect(input(page)).toHaveValue("1 TB");
  });

  test("Slider 값은 Collection ui_state에 저장된다", async ({ page }) => {
    const saved = [];
    await page.exposeFunction("__sliderSaved", (s) => saved.push(s));
    await page.evaluate(() => {
      const original = window.api.saveUiState;
      window.api.saveUiState = (id, s) => { window.__sliderSaved(s); return original(id, s); };
    });
    await openDashboard(page);
    await setTarget(page, "512 GB");
    await slider(page).focus();
    await page.keyboard.press("ArrowRight");
    await expect.poll(() => saved.filter((s) => s.dashboardTargets).length).toBeGreaterThan(0);
    expect(saved.at(-1).dashboardTargets.internal).toBe(TB);
  });

  test("최댓값은 8TB고 그 이상으로 넘어가지 않는다", async ({ page }) => {
    await openDashboard(page);
    await setTarget(page, "4 TB");
    await slider(page).focus();
    await page.keyboard.press("ArrowRight");
    await expect(sliderValue(page)).toHaveValue("8 TB");
    await page.keyboard.press("ArrowRight");
    await expect(sliderValue(page)).toHaveValue("8 TB");
    await expect(input(page)).toHaveValue("8 TB");
    await dragTo(page, 1000);
    await expect(sliderValue(page)).toHaveValue("8 TB");
  });

  // 실사용 피드백: "TARGET 용량은 최소가 8GB부터 시작하는게 맞겠다" - 1GB 같은
  // 비현실적인 값까지 텍스트로 내려갈 수 있었다.
  test("최솟값은 8GB고 그 아래로 내려가지 않는다", async ({ page }) => {
    await openDashboard(page);
    await setTarget(page, "1 GB");
    await expect(input(page)).toHaveValue("8 GB");
    await slider(page).focus();
    await page.keyboard.press("ArrowLeft");
    await expect(sliderValue(page)).toHaveValue("8 GB");
    await dragTo(page, 0);
    await expect(sliderValue(page)).toHaveValue("8 GB");
    await row(page).locator(".dsb-spin", { hasText: "▼" }).click();
    await expect(input(page)).toHaveValue("8 GB");
  });

  test("▲/▼는 세밀하게 한 칸씩 움직인다", async ({ page }) => {
    await openDashboard(page);
    await setTarget(page, "128 GB");
    await row(page).locator(".dsb-spin", { hasText: "▲" }).click();
    await expect(input(page)).toHaveValue("136 GB");
    await row(page).locator(".dsb-spin", { hasText: "▼" }).click();
    await expect(input(page)).toHaveValue("128 GB");
  });

  test("▲/▼는 프리셋을 건너뛰지 않고 거기서 멈춘다", async ({ page }) => {
    await openDashboard(page);
    await setTarget(page, "124 GB");
    await expect(input(page)).toHaveValue("124 GB");
    await row(page).locator(".dsb-spin", { hasText: "▲" }).click();
    await expect(input(page)).toHaveValue("128 GB");
    await setTarget(page, "600 GB");
    await row(page).locator(".dsb-spin", { hasText: "▲" }).click();
    await expect(input(page)).toHaveValue("616 GB");
  });

  test("Slider와 ▲▼는 사용량 막대·System 표 숫자를 바꾸지 않는다", async ({ page }) => {
    await openDashboard(page);
    const usageBefore = await page.locator(".dsb-tiles").textContent();
    const tableBefore = await page.locator(".dsb-table tbody").textContent();
    await setTarget(page, "512 GB");
    await slider(page).focus();
    await page.keyboard.press("ArrowRight");
    await row(page).locator(".dsb-spin", { hasText: "▲" }).click();
    await expect(page.locator(".dsb-tiles")).toHaveText(usageBefore);
    await expect(page.locator(".dsb-table tbody")).toHaveText(tableBefore);
  });
});
