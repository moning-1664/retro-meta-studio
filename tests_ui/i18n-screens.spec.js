const {test, expect} = require('@playwright/test');
const {openApp} = require('./_helpers');

// Game titles, descriptions, ROM names and paths are user data, not UI copy.
async function untranslated(page) {
  return page.evaluate(() => {
    const found = new Set();
    const excluded = 'script,style,option,textarea,.lrow,.media-tab-identity,.scrape-candidate-desc,.scrape-candidate-title,[data-i18n-skip]';
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode, parent = node.parentElement;
      if (window.RMSI18n.isRawText(node)) continue;
      if (!parent || parent.closest(excluded) || !parent.getClientRects().length
          || getComputedStyle(parent).visibility === 'hidden') continue;
      if (/[가-힣]/.test(node.nodeValue)) found.add(node.nodeValue.trim());
    }
    document.querySelectorAll('button,input,textarea,[title]').forEach(el => {
      if (!el.getClientRects().length || el.closest('.lrow,[data-i18n-skip]')) return;
      for (const attr of ['placeholder','title','aria-label']) {
        if (window.RMSI18n.isRawAttribute(el, attr)) continue;
        const value = el.getAttribute(attr);
        if (value && /[가-힣]/.test(value)) found.add(value);
      }
    });
    document.querySelectorAll('select').forEach(select => {
      if (!select.getClientRects().length || select.closest('[data-key="general.language"],[data-i18n-skip]')) return;
      for (const option of select.options) if (/[가-힣]/.test(option.textContent)) found.add(option.textContent);
    });
    return [...found].sort();
  });
}

test.beforeEach(async ({page}) => {
  await openApp(page);
  await page.evaluate(() => window.RMSI18n.setLanguage('en'));
});

for (const section of ['general','collections','metadata','scraper','transfer','archive','emulator','appearance','advanced']) {
  test(`English settings: ${section} has no untranslated UI`, async ({page}) => {
    await page.locator('.settings-btn').click();
    await page.locator(`.stg-nav-item[data-section="${section}"]`).click();
    await expect.poll(() => untranslated(page)).toEqual([]);
  });
}

test('English main, context menu and dashboard have no untranslated UI', async ({page}) => {
  await expect.poll(() => untranslated(page)).toEqual([]);
  await page.locator('.lrow').first().click({button:'right'});
  await expect.poll(() => untranslated(page)).toEqual([]);
  await page.keyboard.press('Escape');
  await page.locator('.nav-dashboard').click();
  await expect.poll(() => untranslated(page)).toEqual([]);
});

test('English scraper includes ready, result and expanded candidate states', async ({page}) => {
  await page.locator('.lrow').first().click({button:'right'});
  await page.locator('.ctx-item', {hasText:'Search game information online'}).click();
  await expect(page.locator('.scrape-context-card')).toBeVisible();
  await expect.poll(() => untranslated(page)).toEqual([]);
  await page.getByRole('button', {name:'Start scraping', exact:true}).click();
  await expect(page.locator('.scrape-candidate').first()).toBeVisible();
  await expect.poll(() => untranslated(page)).toEqual([]);
  await page.locator('.scrape-expand').first().click();
  await expect(page.locator('.candidate-details-grid')).toBeVisible();
  await expect.poll(() => untranslated(page)).toEqual([]);
  expect(await page.locator('.scrape-actions button').evaluateAll(nodes =>
    nodes.every(el => el.scrollWidth <= el.clientWidth))).toBe(true);
});

test('English scraper settings include account test results and imported DAT counts', async ({page}) => {
  await page.evaluate(() => {
    window.api.datSources=async () => ({ok:true,data:[{name:'arcade.dat',system:'arcade',entries:15}]});
    window.api.pickFile=async () => ({ok:true,data:'D:\\arcade.dat'});
  });
  await page.locator('.settings-btn').click();
  await page.locator('.stg-nav-item[data-section="scraper"]').click();
  await expect(page.locator('.stg-help', {hasText:'arcade.dat'})).toBeVisible();
  await page.getByRole('button', {name:'Test connection',exact:true}).click();
  await expect(page.getByRole('button', {name:'Test connection',exact:true})).toBeEnabled();
  await expect.poll(() => untranslated(page)).toEqual([]);
  await page.getByRole('button', {name:'Add DAT…',exact:true}).click();
  await expect(page.locator('.stg-info', {hasText:'Sample DAT'})).toBeVisible();
  await expect.poll(() => untranslated(page)).toEqual([]);
});

test('English Archive settings include the folder detection result', async ({page}) => {
  await page.evaluate(() => {
    const original=window.api.jobProgress;
    window.api.startInspectCollectionFolder=async () => ({ok:true,data:{jobId:'translated-folder'}});
    window.api.jobProgress=async id => id !== 'translated-folder' ? original(id) : {
      ok:true,data:{done:true,current:1,total:1,result:{path:'D:/Archive',archive:true,
        suggestedFrontend:'es-de',findings:[{frontend:'es-de',evidence:'gamelists',systems:[]}]}}};
  });
  await page.locator('.settings-btn').click();
  await page.locator('.stg-nav-item[data-section="archive"]').click();
  await page.locator('.archive-dir').fill('D:/Archive');
  await page.locator('.archive-dir').press('Tab');
  await expect(page.locator('.folder-detection')).toContainText('Archive database detected');
  await expect.poll(() => untranslated(page)).toEqual([]);
});

test('English scraper setup and connection result are translated', async ({page}) => {
  await page.locator('.settings-btn').click();
  await page.locator('.stg-nav-item[data-section="scraper"]').click();
  await page.getByRole('button', {name:'Connection settings…',exact:true}).click();
  await expect(page.locator('.scrape-setup-card')).toBeVisible();
  await expect.poll(() => untranslated(page)).toEqual([]);
  await page.getByRole('button', {name:'Test connection',exact:true}).click();
  await expect(page.locator('.scrape-connection-result')).toContainText('Connected');
  await expect.poll(() => untranslated(page)).toEqual([]);
});

test('English scraper translates progress, stop and empty-result states', async ({page}) => {
  await page.evaluate(() => {
    const original=window.api.jobProgress;
    window.__scrapeStopped=false;
    window.api.cancelJob=async () => {window.__scrapeStopped=true; return {ok:true,data:true};};
    window.api.jobProgress=async job => {
      if (!String(job).startsWith('mock-scrape-item:')) return original(job);
      return {ok:true,data:{done:window.__scrapeStopped,current:2,total:3,label:'"Game 1" 검색',
        result:{item:{id:'1',status:'review',candidates:[],selectedCandidateId:null},quota:null}}};
    };
  });
  await page.locator('.lrow').first().click({button:'right'});
  await page.locator('.ctx-item', {hasText:'Search game information online'}).click();
  await page.getByRole('button', {name:'Start scraping',exact:true}).click();
  await expect(page.locator('.scrape-progress-line')).toHaveAttribute('title', /Searching/);
  await expect.poll(() => untranslated(page)).toEqual([]);
  await page.getByRole('button', {name:'Stop scraping',exact:true}).click();
  await expect(page.locator('.scrape-context')).toContainText('No candidates');
  await expect.poll(() => untranslated(page)).toEqual([]);
  await expect(page.getByRole('button', {name:'Apply',exact:true})).toBeDisabled();
});

test('English metadata detail has translated labels and description guidance', async ({page}) => {
  await page.locator('.lrow').first().locator('.lc-file').click();
  await expect(page.locator('#detail-panel')).toHaveClass(/open/);
  await expect(page.locator('textarea.field-input')).toHaveAttribute('placeholder', 'Enter a game description');
  await expect.poll(() => untranslated(page)).toEqual([]);
});

test('an empty Archive explains how to add games', async ({page}) => {
  await page.evaluate(() => {
    window.api.archiveRows = async () => ({ok:true, data:{rows:[],total:0}});
    window.api.archiveSystems = async () => ({ok:true, data:[]});
  });
  await page.locator('.ctab.archive').click();
  await expect(page.locator('.archive-empty')).toContainText('Collection');
  await expect(page.locator('.archive-empty')).toContainText('paste');
  await expect.poll(() => untranslated(page)).toEqual([]);
});

test('user text that matches a UI label stays unchanged on language switches', async ({page}) => {
  await page.evaluate(() => {
    const node=document.createElement('span');
    node.id='raw-user-text';
    node.dataset.i18nSkip='';
    node.textContent='설정';
    document.body.appendChild(node);
    window.RMSI18n.setLanguage('ko');
    window.RMSI18n.setLanguage('en');
  });
  await expect(page.locator('#raw-user-text')).toHaveText('설정');
});

test('stable IDs preserve parameters and reject missing keys or parameters', async ({page}) => {
  const result = await page.evaluate(() => {
    const i = window.RMSI18n;
    const result = {selected:i.t(i.message('ui.status.selected',{count:3})),
      raw:i.t(i.raw('설정')), empty:i.t(i.raw(undefined)), path:i.t('ui.archive.pathExample')};
    try {i.t('ui.unknown');} catch(e) {result.keyError=e.message;}
    try {i.t('ui.status.selected');} catch(e) {result.paramError=e.message;}
    i.setLanguage('ko');
    result.ko=i.t(i.message('ui.status.selected',{count:3}));
    return result;
  });
  expect(result.selected).toContain('3');
  expect(result.ko).toContain('3');
  expect(result.raw).toBe('설정');
  expect(result.empty).toBe('');
  expect(result.path).toContain('D:\\Archives');
  expect(result.keyError).toMatch(/Unknown/);
  expect(result.paramError).toMatch(/Missing/);
});

test('F1 opens help, Escape closes it, and F1 preserves an existing dialog', async ({page}) => {
  await page.keyboard.press('F1');
  await expect(page.getByRole('dialog')).toContainText('Ctrl+Z');
  await expect.poll(() => untranslated(page)).toEqual([]);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.locator('.settings-btn').click();
  await page.keyboard.press('F1');
  await expect(page.locator('.stg-nav-item')).toHaveCount(9);
});
