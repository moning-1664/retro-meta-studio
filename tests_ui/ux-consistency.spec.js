const { test, expect } = require('@playwright/test');
const { openApp } = require('./_helpers');

async function openScraper(page) {
  await page.locator('.lrow').first().click({ button: 'right' });
  await page.locator('.ctx-item').filter({ has: page.locator('.ctx-label', { hasText: /^게임 정보 스크랩…$/ }) }).click();
  await expect(page.locator('.scrape-context-card')).toBeVisible();
}

test('default selection opens the first game without starting scraping', async ({ page }) => {
  await openApp(page);
  await expect(page.locator('.lrow.selected')).toHaveCount(1);
  await expect(page.locator('.detail-filename')).toBeVisible();
  await openScraper(page);
  await expect(page.locator('.scrape-candidate')).toHaveCount(0);
  const apply = page.getByRole('button', { name: '선택 적용', exact: true });
  await expect(apply).toBeDisabled();
  const colors = await apply.evaluate(el => ({ disabled: getComputedStyle(el).backgroundColor,
    primary: getComputedStyle(document.documentElement).getPropertyValue('--primary').trim() }));
  expect(colors.disabled).not.toBe(colors.primary);
});

test('a single candidate is selected automatically and expansion preserves selection', async ({ page }) => {
  await openApp(page);
  await openScraper(page);
  await page.getByRole('button', { name: '스크랩 시작', exact: true }).click();
  await expect(page.locator('.scrape-candidate[aria-checked="true"]')).toHaveCount(1);
  await expect(page.getByRole('button', { name: '선택 적용', exact: true })).toBeEnabled();
  await page.locator('.scrape-expand').click();
  await expect(page.locator('.candidate-details-grid')).toBeVisible();
  const columns = await page.locator('.candidate-details-grid').evaluate(el =>
    getComputedStyle(el).gridTemplateColumns.split(' '));
  expect(columns).toHaveLength(2);
  await expect(page.locator('.scrape-candidate[aria-checked="true"]')).toHaveCount(1);
  await expect(page.getByRole('button', { name: '선택 적용', exact: true })).toBeInViewport();
});

test('no candidates keeps apply disabled even after a preceding successful result', async ({ page }) => {
  await openApp(page);
  await openScraper(page);
  await page.getByRole('button', { name: '스크랩 시작', exact: true }).click();
  await expect(page.getByRole('button', { name: '선택 적용', exact: true })).toBeEnabled();
  await page.evaluate(() => {
    const progress = window.api.jobProgress;
    window.api.jobProgress = async (...args) => {
      const result = await progress(...args);
      const item = result.data?.result?.item;
      if (item) { item.candidates = []; item.status = 'no_match'; item.selected_candidate_id = null; }
      return result;
    };
  });
  await page.locator('.scrape-query').fill('nonexistent game');
  await page.getByRole('button', { name: '스크랩 시작', exact: true }).click();
  await expect(page.locator('.scrape-candidate')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '선택 적용', exact: true })).toBeDisabled();
});

test('theme names and scaled header retain version and column alignment', async ({ page }) => {
  await openApp(page);
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'slate');
  await page.locator('.settings-btn').click();
  await page.locator('.stg-nav-item[data-section="appearance"]').click();
  const theme = page.locator('.stg-row[data-key="appearance.theme"] select');
  await expect(theme.locator('option')).toHaveText(['Slate', 'Pearl', 'Carbon', 'Sand', 'Aqua']);
  await page.locator('.stg-row[data-key="appearance.scale"] input').fill('130');
  await page.locator('.stg-row[data-key="appearance.scale"] input').dispatchEvent('input');
  await page.locator('.stg-confirm').click();
  await expect(page.locator('.nav-app-version')).toHaveText(await page.evaluate(() => `v${window.RMS_APP_VERSION}`));
  const layout = await page.evaluate(() => {
    const header = document.querySelector('.cheader').getBoundingClientRect();
    const eyebrow = document.querySelector('.nav-eyebrow').getBoundingClientRect();
    const brand = document.querySelector('.nav-app-title-line');
    return { gap: Math.abs(header.bottom - eyebrow.top), overflow: brand.scrollWidth - brand.clientWidth };
  });
  expect(layout.gap).toBeLessThanOrEqual(1.5);
  expect(layout.overflow).toBeLessThanOrEqual(1);
});

for (const theme of ['slate', 'sfc', 'md', 'nes', 'stitch']) {
  test(`primary buttons retain readable contrast in ${theme}`, async ({ page }, testInfo) => {
    await page.addInitScript(theme => { window.__RMS_MOCK_APP_SETTINGS = { appearance: { theme } }; }, theme);
    await openApp(page);
    await openScraper(page);
    const start = page.getByRole('button', { name: '스크랩 시작', exact: true });
    const contrast = await start.evaluate(el => {
      const rgb = text => text.match(/[\d.]+/g).slice(0, 3).map(Number);
      const luminance = channels => channels.map(value => {
        const c = value / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      }).reduce((sum, c, i) => sum + c * [0.2126, 0.7152, 0.0722][i], 0);
      const style = getComputedStyle(el);
      const light = [luminance(rgb(style.color)), luminance(rgb(style.backgroundColor))].sort((a, b) => b - a);
      return (light[0] + 0.05) / (light[1] + 0.05);
    });
    expect(contrast).toBeGreaterThanOrEqual(4.5);
    await start.click();
    await expect(page.locator('.scrape-candidate[aria-checked="true"]')).toHaveCount(1);
    await page.locator('.scrape-expand').click();
    await page.screenshot({ path: testInfo.outputPath(`candidate-${theme}.png`) });
  });
}
