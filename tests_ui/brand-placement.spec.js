const { test, expect } = require('@playwright/test');
const { openApp } = require('./_helpers');

for (const width of [1000, 1280]) for (const scale of [100, 130]) {
  test(`brand stays readable at ${width}px and ${scale}%`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 640 });
    await page.addInitScript(scale => { window.__RMS_MOCK_APP_SETTINGS = { appearance: { scale } }; }, scale);
    await openApp(page);
    const geometry = await page.evaluate(() => {
      const rect = selector => document.querySelector(selector).getBoundingClientRect().toJSON();
      const title = document.querySelector('.nav-app-title-name');
      const version = document.querySelector('.nav-app-version');
      return { title: rect('.nav-app-title-name'), version: rect('.nav-app-version'),
        brand: rect('.nav-app-title-text'), nav: rect('.nav-top'),
        titleSize: getComputedStyle(title).fontSize, versionSize: getComputedStyle(version).fontSize,
        small: getComputedStyle(document.querySelector('.nav-app-subtitle')).fontSize,
        overflow: title.scrollWidth - title.clientWidth };
    });
    expect(geometry.titleSize).toBe('18px');
    expect(geometry.versionSize).toBe('9px');
    expect(parseFloat(geometry.small)).toBeCloseTo(9 * scale / 100, 1);
    expect(geometry.version.y).toBeGreaterThanOrEqual(geometry.title.bottom);
    expect(Math.abs(geometry.version.right - geometry.brand.right)).toBeLessThanOrEqual(1);
    expect(geometry.title.right).toBeLessThanOrEqual(geometry.brand.right + 1);
    expect(geometry.brand.bottom).toBeLessThanOrEqual(geometry.nav.bottom + 1);
    expect(geometry.overflow).toBeLessThanOrEqual(1);
    await page.screenshot({ path: testInfo.outputPath('brand.png') });
  });
}
