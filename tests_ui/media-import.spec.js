const { test, expect } = require("@playwright/test");
const { openApp } = require("./_helpers");

test.beforeEach(async ({ page }) => { await openApp(page); });

test("Media 슬롯에 외부 그림을 놓으면 기존 Plan 미디어 경로로 전달한다", async ({ page }) => {
  await page.locator(".lrow", { hasText: "FFX.iso" }).locator(".lc-file").click();
  await page.locator(".detail-tab", { hasText: "Media" }).click();
  await page.evaluate(() => {
    window.__externalImageCalls = [];
    window.api.importMediaImage = (...args) => {
      window.__externalImageCalls.push(args);
      return Promise.resolve({ ok: true, data: { added: 1 } });
    };
    const transfer = new DataTransfer();
    transfer.items.add(new File([new Uint8Array([137, 80, 78, 71])], "cover.png", { type: "image/png" }));
    document.querySelector(".media-tile").dispatchEvent(new DragEvent("drop", {
      bubbles: true, cancelable: true, dataTransfer: transfer,
    }));
  });
  await expect.poll(() => page.evaluate(() => window.__externalImageCalls.length)).toBe(1);
  const args = await page.evaluate(() => window.__externalImageCalls[0]);
  expect(args[0]).toBe("collection");
  expect(args[3]).toBe("Covers");
  expect(args[4]).toMatch(/^[A-Za-z0-9+/=]+$/);
});
