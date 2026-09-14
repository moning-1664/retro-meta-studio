// Media 영상 재생 - Screenshot 자리에서 3초 뒤 자동 재생(소리 켬, 반복 켬), 누르면 멈춤.
// 헤드리스 Chromium은 mp4를 재생하지 못하므로 HTMLMediaElement를 막아 두고 동작만 본다:
// src가 언제 들어가는지, 첫 프레임(`playing`) 뒤에만 보이는지, 멈추면 치워지는지.
const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(HTMLMediaElement.prototype, "src", {
      configurable: true,
      get() { return this.getAttribute("data-test-src") || ""; },
      set(value) { this.setAttribute("data-test-src", value); },
    });
    HTMLMediaElement.prototype.play = function () { this.__played = true; return Promise.resolve(); };
    HTMLMediaElement.prototype.pause = function () { this.__paused = true; };
    HTMLMediaElement.prototype.load = function () {};
  });
  await openApp(page);
  await page.clock.install();
});

const openMediaOf = async (page, file) => {
  await page.locator(".lrow", { hasText: file }).locator(".lc-file").click();
  await page.locator(".detail-tab", { hasText: "Media" }).click();
};
const video = (page) => page.locator(".media-tile.wide video.media-video");

test("3초 전에는 영상을 요청하지 않고, 3초가 지나면 소리·반복을 켠 채 재생한다", async ({ page }) => {
  await openMediaOf(page, "FFX.iso");
  await expect(video(page)).toHaveCount(1);
  await page.clock.runFor(2500);
  expect(await video(page).getAttribute("data-test-src")).toBeNull();
  await page.clock.runFor(700);
  await expect(video(page)).toHaveAttribute("data-test-src", /FFX\.iso\.mp4$/);
  const state = await video(page).evaluate((v) => ({ loop: v.loop, muted: v.muted, played: !!v.__played }));
  expect(state).toEqual({ loop: true, muted: false, played: true });
});

test("첫 프레임이 나오기 전에는 보이지 않고, 나온 뒤에 서서히 보인다", async ({ page }) => {
  await openMediaOf(page, "FFX.iso");
  await page.clock.runFor(3200);
  await expect(page.locator(".media-tile.wide")).toHaveClass(/video-loading/);
  await expect(page.locator(".media-tile.wide")).not.toHaveClass(/video-playing/);
  await video(page).evaluate((v) => v.dispatchEvent(new Event("playing")));
  await expect(page.locator(".media-tile.wide")).toHaveClass(/video-playing/);
});

test("재생 중에 누르면 멈추고 Screenshot으로 돌아간다 - 확대 창은 열지 않는다", async ({ page }) => {
  await openMediaOf(page, "FFX.iso");
  await page.clock.runFor(3200);
  await video(page).evaluate((v) => v.dispatchEvent(new Event("playing")));
  await page.locator(".media-tile.wide").click();
  await expect(page.locator(".media-tile.wide")).not.toHaveClass(/video-playing/);
  await page.clock.runFor(500);
  await expect(video(page)).toHaveCount(0);
  await expect(page.locator(".lightbox-img")).toHaveCount(0);
});

test("3초 전에 다른 게임으로 넘기면 영상을 요청하지 않는다", async ({ page }) => {
  await page.evaluate(() => {
    window.__videoCalls = 0;
    const original = window.api.getMediaVideoUrl;
    window.api.getMediaVideoUrl = (...args) => { window.__videoCalls += 1; return original(...args); };
  });
  await openMediaOf(page, "FFX.iso");
  await page.clock.runFor(2000);
  await page.locator(".lrow", { hasText: "MGS2.iso" }).locator(".lc-file").click();
  await page.clock.runFor(6000);
  expect(await page.evaluate(() => window.__videoCalls)).toBe(0);
});

test("영상이 없는 게임에는 영상 자리가 생기지 않는다", async ({ page }) => {
  await openMediaOf(page, "MGS2.iso");
  await expect(video(page)).toHaveCount(0);
});

test.describe("Settings > Metadata & Media > Video", () => {
  const openVideoSettings = async (page) => {
    await page.locator(".nav-top .icon-btn[title='Settings']").click();
    await page.locator(".stg-nav-item[data-section='metadata']").click();
  };

  test("기본값은 자동 재생 / 3초 / 소리 켬 / 반복 켬", async ({ page }) => {
    await openVideoSettings(page);
    await expect(page.locator(".stg-row[data-key='media.videoMode'] select")).toHaveValue("auto");
    await expect(page.locator(".stg-row[data-key='media.videoDelay'] select")).toHaveValue("3");
    expect(await page.locator(".stg-row[data-key='media.videoDelay'] option").allTextContents())
      .toEqual(["0초", "1초", "3초", "5초", "10초", "15초"]);
    await expect(page.locator(".stg-row[data-key='media.videoSound'] input")).toBeChecked();
    await expect(page.locator(".stg-row[data-key='media.videoLoop'] input")).toBeChecked();
  });

  test("재생 안 함이면 영상 자리를 만들지 않는다", async ({ page }) => {
    await openVideoSettings(page);
    await page.locator(".stg-row[data-key='media.videoMode'] select").selectOption("off");
    await page.locator(".stg-close").click();
    await openMediaOf(page, "FFX.iso");
    await expect(video(page)).toHaveCount(0);
  });

  test("눌러서 재생이면 재생 버튼을 누를 때만 재생하고, 소리/반복 설정을 따른다", async ({ page }) => {
    await openVideoSettings(page);
    await page.locator(".stg-row[data-key='media.videoMode'] select").selectOption("manual");
    await page.locator(".stg-row[data-key='media.videoSound'] .stg-switch").click();
    await page.locator(".stg-row[data-key='media.videoLoop'] .stg-switch").click();
    await page.locator(".stg-close").click();
    await openMediaOf(page, "FFX.iso");
    await page.clock.runFor(20000);
    expect(await video(page).getAttribute("data-test-src")).toBeNull();
    await page.locator(".media-video-play").click();
    await expect(video(page)).toHaveAttribute("data-test-src", /FFX\.iso\.mp4$/);
    const state = await video(page).evaluate((v) => ({ loop: v.loop, muted: v.muted }));
    expect(state).toEqual({ loop: false, muted: true });
  });

  test("대기 0초면 고르자마자 재생한다", async ({ page }) => {
    await openVideoSettings(page);
    await page.locator(".stg-row[data-key='media.videoDelay'] select").selectOption("0");
    await page.locator(".stg-close").click();
    await openMediaOf(page, "FFX.iso");
    await page.clock.runFor(100);
    await expect(video(page)).toHaveAttribute("data-test-src", /FFX/);
  });

  test("대기 시간을 바꾸면 그 시간 뒤에 재생한다", async ({ page }) => {
    await openVideoSettings(page);
    await page.locator(".stg-row[data-key='media.videoDelay'] select").selectOption("10");
    await page.locator(".stg-close").click();
    await openMediaOf(page, "FFX.iso");
    await page.clock.runFor(6000);
    expect(await video(page).getAttribute("data-test-src")).toBeNull();
    await page.clock.runFor(4500);
    await expect(video(page)).toHaveAttribute("data-test-src", /FFX/);
  });
});
