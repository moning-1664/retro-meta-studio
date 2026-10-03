const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

const exactMenuItem = (page, label) => page.locator(".ctx-menu .ctx-item").filter({
  has: page.locator(".ctx-label", { hasText: new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`) }),
});

async function openForRows(page, count = 1, start = true) {
  const rows = page.locator(".lrow");
  await rows.nth(0).click();
  if (count > 1) {
    await page.keyboard.down("Control");
    for (let i = 1; i < count; i += 1) await rows.nth(i).click();
    await page.keyboard.up("Control");
  }
  await rows.nth(0).click({ button: "right" });
  const label = count === 1 ? "온라인에서 게임 정보 검색…" : `온라인에서 게임 정보 검색… (${count}개)`;
  await exactMenuItem(page, label).click();
  await expect(page.locator(".scrape-context-card")).toBeVisible();
  if (start) {
    await page.getByRole("button", { name: "스크랩 시작" }).click();
    await expect(page.locator(".scrape-candidate").first()).toBeVisible();
  }
}

test("Settings에서 연결 상태와 일일 요청량을 확인한다", async ({ page }) => {
  await page.locator(".settings-btn").click();
  await page.locator(".stg-nav-item[data-section='scraper']").click();
  await expect(page.locator(".stg-panel")).toContainText("ScreenScraper 개발자 정보 설정됨");
  await page.getByRole("button", { name: "연결 테스트" }).click();
  await expect(page.locator(".stg-scraper")).toContainText("오늘 12 / 100회");
  await expect(page.locator(".stg-scraper")).toContainText("동시 요청 1");
  await expect(page.locator(".stg-scraper")).toContainText("ROM 해시로 먼저 찾기");
  await expect(page.locator(".stg-scraper .stg-switch input").first()).toBeChecked();
  await expect(page.locator(".stg-scraper .stg-subsection-title", { hasText: /^가져올 미디어$/ })).toBeVisible();
  await expect(page.locator(".scrape-media-choice")).toHaveCount(12);
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

test("Settings 바깥을 눌러도 창이 유지된다", async ({ page }) => {
  await page.locator(".settings-btn").click();
  await page.locator(".stg-overlay").click({ position: { x: 2, y: 2 } });
  await expect(page.locator(".stg-panel")).toBeVisible();
});

test("단건 후보는 Detail 폭이며 카드를 눌러 선택한다", async ({ page }) => {
  await openForRows(page);
  await expect(page.locator(".scrape-quota")).toHaveText("오늘 12 / 100회");
  await expect(page.locator(".scrape-title-count")).toHaveText("스크랩 결과 (1/1)");
  await expect(page.locator(".scrape-file-tag")).toHaveText("ROM");
  await expect(page.locator(".scrape-results-head")).toContainText("후보 결과 : 1건 감지됨");
  const width = await page.locator(".scrape-context").evaluate((el) => Math.round(el.getBoundingClientRect().width));
  expect(width).toBe(297);
});

test("스크랩 창은 요청 없이 열리고 포인트 색 시작 버튼으로 검색한다", async ({ page }) => {
  await page.evaluate(() => {
    window.__scrapeStarts = 0;
    const original = window.api.startScrapeItem;
    window.api.startScrapeItem = (...args) => {
      window.__scrapeStarts += 1;
      return original(...args);
    };
  });
  await openForRows(page, 1, false);
  const start = page.getByRole("button", { name: "스크랩 시작" });
  await expect(page.locator(".scrape-candidate")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "선택 적용" })).toBeDisabled();
  expect(await page.evaluate(() => window.__scrapeStarts)).toBe(0);
  await expect(start).toHaveClass(/primary/);
  await start.click();
  await expect.poll(() => page.evaluate(() => window.__scrapeStarts)).toBe(1);
  await expect(page.locator(".scrape-candidate")).toHaveCount(1);
});

test("확정 게임은 다른 후보 검색 하나로 다시 검색한다", async ({ page }) => {
  await page.evaluate(() => {
    const create = window.api.createScrapeSession;
    window.api.createScrapeSession = async (...args) => {
      const result = await create(...args);
      result.data.items[0].confirmedGameId = "42";
      return result;
    };
    const start = window.api.startScrapeItem;
    window.api.startScrapeItem = (...args) => {
      window.__forceSearch = args[4];
      return start(...args);
    };
    window.__cleared = 0;
    const clear = window.api.clearScrapeConfirmedMatch;
    window.api.clearScrapeConfirmedMatch = (...args) => {
      window.__cleared += 1;
      return clear(...args);
    };
  });
  await openForRows(page, 1, false);
  await page.getByRole("button", { name: "다른 후보 검색" }).click();
  await expect.poll(() => page.evaluate(() => window.__forceSearch)).toBe(true);
  await expect(page.getByRole("button", { name: "확정·별칭 해제" })).toHaveCount(0);
});

test("아케이드 단축명 후보에는 설명 없는 확인 필요 배지를 붙이지 않는다", async ({ page }) => {
  await page.evaluate(() => {
    const original = window.api.jobProgress;
    window.api.jobProgress = async (...args) => {
      const result = await original(...args);
      const candidate = result.data?.result?.item?.candidates?.[0];
      if (candidate) candidate.confidence_reason = "아케이드 단축명 후보 · 직접 확인 필요";
      return result;
    };
  });
  await openForRows(page);
  await expect(page.locator(".scrape-candidate-review")).toHaveCount(0);
});

test("∨를 누르면 필드 비교와 미디어 선택을 펼친다", async ({ page }) => {
  await openForRows(page);
  await page.locator(".scrape-expand").first().click();
  await expect(page.locator(".candidate-detail-field", { hasText: "제목" })).toBeVisible();
  await expect(page.locator(".candidate-detail-current")).toHaveCount(0);
  await expect(page.locator(".scrape-evidence")).toHaveCount(0);
  await expect(page.locator(".scrape-media-option", { hasText: "covers" })).toHaveCount(0);
  await expect(page.locator(".candidate-detail-field input").first()).toBeChecked();
});

test("후보는 cover와 screenshot만 미리 보고 다른 설정 미디어도 적용 대상으로 유지한다", async ({ page }) => {
  await page.evaluate(() => {
    const progress = window.api.jobProgress;
    window.api.jobProgress = async (...args) => {
      const result = await progress(...args);
      const candidate = result.data?.result?.item?.candidates?.[0];
      if (candidate) {
        const url = candidate.media[0].url;
        candidate.media.push({ media_type: "screenshots", url });
        candidate.media.push({ media_type: "videos", url: "https://example.invalid/video.mp4" });
        candidate.media.push({ media_type: "wheel", url: "https://example.invalid/wheel.png" });
      }
      return result;
    };
    const select = window.api.selectScrapeCandidate;
    window.api.selectScrapeCandidate = (...args) => {
      window.__previewSelectedMedia = args[4];
      return select(...args);
    };
  });
  await openForRows(page);
  await page.locator(".scrape-expand").first().click();
  await expect(page.locator(".scrape-media-option")).toHaveCount(1);
  await expect(page.locator(".scrape-media-option img")).toHaveCount(1);
  await expect(page.locator(".scrape-media-option", { hasText: "videos" })).toHaveCount(0);
  await page.locator(".scrape-candidate-title").first().click();
  await expect.poll(() => page.evaluate(() => window.__previewSelectedMedia)).toEqual([0, 1, 2, 3]);
});

test("확장한 후보를 선택해도 확장 상태와 하단 적용 버튼이 유지된다", async ({ page }) => {
  await openForRows(page);
  await page.locator(".scrape-expand").first().click();
  await page.locator(".candidate-detail-field").first().click();
  await expect(page.locator(".scrape-candidate.selected.expanded")).toBeVisible();
  const apply = page.getByRole("button", { name: "선택 적용" });
  await expect(apply).toBeEnabled();
  await expect(apply).toBeInViewport();
});

test("스크랩 추정 사용량이 계정에서 확인한 횟수를 1회로 되돌리지 않는다", async ({ page }) => {
  await page.evaluate(() => {
    const status = window.api.jobProgress;
    window.api.jobProgress = async (...args) => {
      const result = await status(...args);
      if (String(args[0]) === "mock-scraper-account" && result.data?.done)
        result.data.result = { requestsToday: 126, requestsLimit: 20000 };
      if (String(args[0]).startsWith("mock-scrape-item:") && result.data?.result?.quota)
        result.data.result.quota = { requestsToday: 1, estimated: true };
      return result;
    };
  });
  await openForRows(page, 1, false);
  await expect(page.locator(".scrape-quota")).toContainText("126 / 20,000");
  await page.getByRole("button", { name: "스크랩 시작" }).click();
  await expect(page.locator(".scrape-candidate")).toBeVisible();
  await expect(page.locator(".scrape-quota")).toContainText("/ 20,000");
  await expect(page.locator(".scrape-quota")).not.toContainText("오늘 1 /");
});

test("검색 키를 고쳐 다시 스크랩하면 후보 제목이 바뀐다", async ({ page }) => {
  await openForRows(page);
  await page.locator(".scrape-query").fill("수동 원작 제목");
  await page.getByRole("button", { name: "스크랩 시작" }).click();
  await expect(page.locator(".scrape-candidate-title").first()).toHaveText("수동 원작 제목");
  await expect(page.locator(".scrape-quota")).toHaveText("오늘 12 / 100회");
});

test("후보가 없으면 선택 적용이 비활성화된다", async ({ page }) => {
  await page.evaluate(() => {
    const original = window.api.jobProgress;
    window.api.jobProgress = async (...args) => {
      const result = await original(...args);
      if (String(args[0]).startsWith("mock-scrape-item:") && result.data?.result?.item) {
        result.data.result.item.candidates = [];
        result.data.result.item.status = "not_found";
      }
      return result;
    };
  });
  const row = page.locator(".lrow").first();
  await row.click();
  await row.click({ button: "right" });
  await exactMenuItem(page, "온라인에서 게임 정보 검색…").click();
  await page.getByRole("button", { name: "스크랩 시작" }).click();
  await expect(page.locator(".scrape-candidates")).toContainText("후보가 없습니다");
  const apply = page.getByRole("button", { name: "선택 적용" });
  await expect(apply).toBeDisabled();
  await expect(apply).toHaveCSS("opacity", "0.5");
});

test("스크랩 진행률은 모달 안에 표시하고 스크랩 시작 버튼으로 중지한다", async ({ page }) => {
  await page.evaluate(() => {
    window.__scrapeStopCalls = 0;
    const progress = window.api.jobProgress;
    const cancel = window.api.cancelJob;
    window.api.jobProgress = async (id) => String(id).startsWith("mock-scrape-item:")
      ? { ok: true, data: window.__scrapeStopCalls
        ? { current: 1, total: 3, label: "취소", done: true, error: "취소", cancelled: true }
        : { current: 1, total: 3, label: "ROM 식별", done: false } }
      : progress(id);
    window.api.cancelJob = (...args) => {
      window.__scrapeStopCalls += 1;
      return cancel(...args);
    };
  });
  const row = page.locator(".lrow").first();
  await row.click();
  await row.click({ button: "right" });
  await exactMenuItem(page, "온라인에서 게임 정보 검색…").click();
  await page.getByRole("button", { name: "스크랩 시작" }).click();
  await expect(page.locator(".scrape-progress .scrape-progress-line")).toBeVisible();
  await expect(page.locator(".scrape-progress .job-progress-cancel")).toHaveCount(0);
  await expect(page.locator(".scrape-progress-line")).toHaveAttribute("title", /ROM 식별/);
  await expect(page.locator("#status-bar #job-progress .job-progress-item")).toHaveCount(0);
  await page.getByRole("button", { name: "스크랩 중지" }).click();
  await expect.poll(() => page.evaluate(() => window.__scrapeStopCalls)).toBeGreaterThan(0);
  await expect(page.getByRole("button", { name: "스크랩 시작" })).toBeVisible();
});

test("시스템 전체를 고르고 Enter를 누르면 빈 시스템으로 검색한다", async ({ page }) => {
  await openForRows(page);
  await page.evaluate(() => {
    window.__scrapeArgs = [];
    const original = window.api.startScrapeItem;
    window.api.startScrapeItem = (...args) => {
      window.__scrapeArgs.push(args);
      return original(...args);
    };
  });
  await page.locator(".scrape-system").selectOption("");
  await page.locator(".scrape-query").fill("Sonic");
  await page.locator(".scrape-query").press("Enter");
  await expect.poll(() => page.evaluate(() => window.__scrapeArgs.at(-1)?.[3])).toBe("");
});

test("스크랩 시스템 목록에는 현재 Collection의 System과 새 플랫폼이 보인다", async ({ page }) => {
  await openForRows(page);
  const values = await page.locator(".scrape-system option").evaluateAll((options) =>
    options.map((option) => option.value));
  for (const system of ["psvita", "wii", "wiiu", "switch", "arcade", "ps2",
                        "ngpc", "pc98", "mastersystem", "windows"])
    expect(values).toContain(system);
  expect(values).not.toContain("vita");
  expect(values).not.toContain("fbneo");
  for (const alias of ["mame", "mame2003", "fbern", "cps1", "cps2", "cps3"])
    expect(values).not.toContain(alias);
  await expect(page.locator(".scrape-system option:disabled")).toHaveCount(0);
});

for (const sourceSystem of ["fbneo", "mame2003"]) test(`${sourceSystem} ROM은 아케이드를 기본 검색 시스템으로 사용한다`, async ({ page }) => {
  await page.evaluate(() => {
    const create = window.api.createScrapeSession;
    window.api.createScrapeSession = async (...args) => {
      const result = await create(...args);
      result.data.items[0].system = window.__sourceScraperSystem;
      return result;
    };
    window.__scrapeArgs = [];
    const start = window.api.startScrapeItem;
    window.api.startScrapeItem = (...args) => {
      window.__scrapeArgs.push(args);
      return start(...args);
    };
  });
  await page.evaluate((name) => { window.__sourceScraperSystem = name; }, sourceSystem);
  await openForRows(page);
  await expect(page.locator(".scrape-system")).toHaveValue("arcade");
  await expect.poll(() => page.evaluate(() => window.__scrapeArgs[0]?.[3])).toBe("arcade");
});

test("스크랩 이동 버튼은 이전과 다음을 명확히 표시한다", async ({ page }) => {
  await openForRows(page, 2);
  await expect(page.getByRole("button", { name: "이전 스크랩" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "다음 스크랩" })).toBeEnabled();
  await page.getByRole("button", { name: "다음 스크랩" }).click();
  await expect(page.getByRole("button", { name: "이전 스크랩" })).toBeEnabled();
});

test("여러 게임은 적용 뒤 다음 항목을 자동으로 스크랩한다", async ({ page }) => {
  await openForRows(page, 2);
  await expect(page.locator(".scrape-title-count")).toHaveText("스크랩 결과 (1/2)");
  await page.locator(".scrape-candidate-title").first().click();
  await expect(page.locator(".scrape-title-count")).toHaveText("스크랩 결과 (1/2)");
  await expect(page.locator(".scrape-candidate.selected")).toBeVisible();
  const apply = page.getByRole("button", { name: "선택 적용" });
  await expect(apply).toBeEnabled();
  await page.getByRole("button", { name: "다음 스크랩" }).click();
  await expect(page.locator(".scrape-title-count")).toHaveText("스크랩 결과 (2/2)");
  await expect(page.locator(".scrape-candidate")).toHaveCount(0);
  await expect(apply).toBeDisabled();
  await page.getByRole("button", { name: "이전 스크랩" }).click();
  await expect(page.locator(".scrape-candidate.selected")).toBeVisible();
  await apply.click();
  await expect(page.locator(".scrape-context-card")).toBeVisible();
  await expect(page.locator(".scrape-title-count")).toHaveText("스크랩 결과 (2/2)");
  await expect(page.locator(".scrape-candidate").first()).toBeVisible();
  await expect(page.locator("#toast")).toContainText("1개 게임에 스크랩 결과를 적용했습니다");
});

test("적용 실패 시 해당 게임의 오류를 후보 화면에 표시한다", async ({ page }) => {
  await page.evaluate(() => {
    const create = window.api.createScrapeSession;
    window.api.createScrapeSession = async (...args) => {
      const result = await create(...args);
      window.__scrapeTestSession = result.data;
      return result;
    };
    window.api.scrapeSession = async () => ({ ok: true, data: window.__scrapeTestSession });
  });
  await openForRows(page);
  await page.evaluate(() => {
    const select = window.api.selectScrapeCandidate;
    window.api.selectScrapeCandidate = (...args) => {
      window.__selectedScrapeItemId = args[1];
      return select(...args);
    };
    const original = window.api.jobProgress;
    window.api.jobProgress = async (...args) => {
      const result = await original(...args);
      if (result.data?.done && result.data?.result?.applied) {
        result.data.result = { applied: [], partial: [], failed: [
          { itemId: window.__selectedScrapeItemId, error: "covers: 파일 형식을 확인할 수 없습니다." },
        ] };
      }
      return result;
    };
  });
  await page.locator(".scrape-candidate-title").first().click();
  await page.getByRole("button", { name: "선택 적용" }).click();
  await expect(page.locator(".scrape-context-card")).toBeVisible();
  await expect(page.locator(".scrape-context .modal-text.error")).toContainText("파일 형식을 확인할 수 없습니다");
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

test("compact candidate card uses click focus without a large selection button", async ({ page }) => {
  await openForRows(page);
  const card = page.locator(".scrape-candidate").first();
  await expect(card.locator(".scrape-candidate-desc")).toBeVisible();
  await expect(card.locator(".scrape-media-mark")).toHaveCount(0);
  await expect(card.locator(".scrape-choose")).toHaveCount(0);
  await expect(card.locator(".scrape-candidate-pick-hint")).toHaveCount(0);
  await expect(card.locator(".scrape-expand")).toBeVisible();
});

test("candidate card keeps secondary metadata in at most two compact rows", async ({ page }) => {
  await page.evaluate(() => {
    const original = window.api.jobProgress;
    window.api.jobProgress = async (...args) => {
      const result = await original(...args);
      const candidate = result.data?.result?.item?.candidates?.[0];
      if (candidate) {
        candidate.fields.rating = "16";
        candidate.fields.developer = "Nintendo";
        candidate.fields.genre = "Simulation";
      }
      return result;
    };
  });
  await openForRows(page);
  const card = page.locator(".scrape-candidate").first();
  await expect(card.locator(".scrape-candidate-facts")).toContainText("1999");
  await expect(card.locator(".scrape-candidate-facts")).toContainText("Nintendo");
  await expect(card.locator(".scrape-candidate-facts")).toContainText("Simulation");
  await expect(card.locator(".scrape-fact-row")).toHaveCount(2);
  await expect(card.locator(".scrape-expand svg")).toHaveCount(1);
});
