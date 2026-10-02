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

test('English favorite menu covers add and remove states', async ({page}) => {
  const row=page.locator('.lrow').first();
  await row.click({button:'right'});
  await expect(page.getByRole('menuitem',{name:/Add to favorites|Remove from favorites/})).toBeVisible();
  await expect.poll(() => untranslated(page)).toEqual([]);
  await page.getByRole('menuitem',{name:/Add to favorites|Remove from favorites/}).click();
  await row.click({button:'right'});
  await expect.poll(() => untranslated(page)).toEqual([]);
});

test('English paste conflict includes expanded comparison', async ({page}) => {
  await page.evaluate(() => {window.__RMS_MOCK_IMMEDIATE_PASTE=true;});
  await page.locator('.lrow').first().click();
  await page.keyboard.press('Control+c');
  await page.keyboard.press('Control+v');
  await expect(page.locator('.paste-conflict-card')).toBeVisible();
  await expect.poll(() => untranslated(page)).toEqual([]);
  await page.locator('.paste-conflict-expand').first().click();
  await expect.poll(() => untranslated(page)).toEqual([]);
});

test('English failed recovery includes close confirmation', async ({page}) => {
  await page.evaluate(() => {
    window.api.operationHistory=async()=>({ok:true,data:{items:[{id:'failed',status:'recovery_failed',action:'paste',createdAt:1,bytes:2048,canDiscard:false,canForceRecovery:true,recoveryError:'External file changed'}]}});
  });
  await page.locator('.settings-btn').click();
  await page.locator('.stg-nav-item[data-section="advanced"]').click();
  await page.getByRole('button',{name:'Open recovery records',exact:true}).click();
  await expect.poll(() => untranslated(page)).toEqual([]);
  await page.getByRole('button',{name:'Close record (keep backup)',exact:true}).click();
  await expect.poll(() => untranslated(page)).toEqual([]);
});

test('English connection failure remains visible and retryable', async ({page}) => {
  await page.evaluate(() => {window.api.startScraperAccountStatus=async()=>({ok:false,error:'HTTP 401'});});
  await page.locator('.settings-btn').click();
  await page.locator('.stg-nav-item[data-section="scraper"]').click();
  await page.getByRole('button',{name:'Connection settings…',exact:true}).click();
  const button=page.getByRole('button',{name:'Test connection',exact:true});
  await button.click();
  await expect(page.locator('.scrape-connection-result')).toContainText('HTTP 401');
  await expect(button).toBeEnabled();
  await expect.poll(() => untranslated(page)).toEqual([]);
});

test('Korean item count uses Korean UI text', async ({page}) => {
  await page.evaluate(() => window.RMSI18n.setLanguage('ko'));
  await expect(page.locator('#filter-total')).toContainText('개 항목');
  await expect(page.locator('#filter-total')).not.toContainText('items');
});

test('English backend connection error translates the reason and allows retry', async ({page}) => {
  await page.evaluate(() => {window.api.startScraperAccountStatus=async()=>({ok:false,error:'ScreenScraper 인증에 실패했습니다.'});});
  await page.locator('.settings-btn').click();
  await page.locator('.stg-nav-item[data-section="scraper"]').click();
  await page.getByRole('button',{name:'Connection settings…',exact:true}).click();
  await page.getByRole('button',{name:'Test connection',exact:true}).click();
  await expect(page.locator('.scrape-connection-result')).toContainText('ScreenScraper authentication failed.');
  await expect.poll(() => untranslated(page)).toEqual([]);
});

test('backend error translation preserves codes and unknown diagnostic text', async ({page}) => {
  expect(await page.evaluate(() => {
    const f=window.RMSI18n.formatError;
    return [f('ScreenScraper 응답 오류 (400)'),f('ScreenScraper 연결 실패 (ReadTimeout)'),f('ScreenScraper 서비스를 사용할 수 없습니다 (503).'),f('Collection을 찾을 수 없습니다.'),f('D:\\게임\\test.zip: unknown diagnostic')];
  })).toEqual(['ScreenScraper response error (400)','ScreenScraper connection failed (ReadTimeout)','ScreenScraper service unavailable (503).','Collection not found.','D:\\게임\\test.zip: unknown diagnostic']);
  await page.evaluate(() => window.RMSI18n.setLanguage('ko'));
  expect(await page.evaluate(() => window.RMSI18n.formatError('ScreenScraper 응답 오류 (400)'))).toBe('ScreenScraper 응답 오류 (400)');
});

for (const language of ['ja','es','fr']) {
  test(`partial language audit: ${language} settings and stable IDs`, async ({page}, testInfo) => {
    await page.evaluate(lang => window.RMSI18n.setLanguage(lang),language);
    await page.locator('.settings-btn').click();
    const report={language,settings:{},stableIds:null};
    for (const section of ['general','collections','metadata','scraper','transfer','archive','emulator','appearance','advanced']) {
      await page.locator(`.stg-nav-item[data-section="${section}"]`).click();
      report.settings[section]=await untranslated(page);
      expect(report.settings[section], `${language}: ${section}`).toEqual([]);

    }
    report.stableIds=await page.evaluate(lang => {
      const entries=Object.entries(window.RMSI18n.getMessages());
      return {total:entries.length,translated:entries.filter(([,forms])=>forms[lang]).length,englishFallback:entries.filter(([,forms])=>!forms[lang]).map(([id])=>id)};
    },language);
    expect(report.stableIds.translated).toBe(report.stableIds.total);
    expect(report.stableIds.englishFallback).toEqual([]);
    // This audit measures remaining gaps; it does not claim full translation.
    await testInfo.attach('partial-language-audit',{body:JSON.stringify(report,null,2),contentType:'application/json'});
    console.log('Language audit '+language+': '+JSON.stringify({translated:report.stableIds.translated,total:report.stableIds.total,koreanBySettings:Object.fromEntries(Object.entries(report.settings).map(([section,strings])=>[section,strings.length]))}));
    await page.locator('.stg-nav-item[data-section="general"]').click();
    await expect(page.locator('[data-key="general.language"] .stg-help')).toHaveText(await page.evaluate(()=>window.RMSI18n.t('ui.settings.languageCoverage')));
  });
}

test('ID migration reuses compatible translations but rejects changed parameters', async ({page}) => {
  expect(await page.evaluate(()=>{
    const i=window.RMSI18n;
    i.addTable({'호환 {count}':{ja:'互換 {count}'},'불일치 {count}':{ja:'不一致 {number}'}});
    i.addMessages({'ui.test.compatible':{ko:'호환 {count}',en:'Compatible {count}'},'ui.test.incompatible':{ko:'불일치 {count}',en:'Mismatch {count}'}});
    i.setLanguage('ja');
    return [i.t('ui.test.compatible',{count:3}),i.t('ui.test.incompatible',{count:3})];
  })).toEqual(['互換 3','Mismatch 3']);
});

for (const language of ['ja','es','fr']) {
  test(`translated scraper workflow: ${language}`, async ({page}) => {
    await page.evaluate(lang=>window.RMSI18n.setLanguage(lang),language);
    await page.locator('.lrow').first().click({button:'right'});
    const menuLabel=await page.evaluate(()=>window.RMSI18n.t('ui.menu.scrape'));
    await page.locator('.ctx-item',{hasText:menuLabel}).click();
    await expect(page.locator('.scrape-context-card')).toBeVisible();
    const name=id=>page.evaluate(key=>window.RMSI18n.t(key),id);
    await expect.poll(()=>untranslated(page)).toEqual([]);
    await page.getByRole('button',{name:await name('ui.scrape.start'),exact:true}).click();
    await expect(page.locator('.scrape-candidate').first()).toBeVisible();
    await expect.poll(()=>untranslated(page)).toEqual([]);
    await page.locator('.scrape-expand').first().click();
    await expect.poll(()=>untranslated(page)).toEqual([]);
    expect(await page.locator('.scrape-actions button').evaluateAll(nodes=>nodes.every(el=>el.scrollWidth<=el.clientWidth))).toBe(true);
    await page.keyboard.press('Escape');
    await page.locator('.settings-btn').click();
    await page.locator('.stg-nav-item[data-section="scraper"]').click();
    await page.getByRole('button',{name:await name('ui.scraper.connect'),exact:true}).click();
    await expect(page.locator('.scrape-setup-card')).toBeVisible();
    await expect.poll(()=>untranslated(page)).toEqual([]);
    await page.evaluate(()=>{window.api.startScraperAccountStatus=async()=>({ok:false,error:'ScreenScraper 인증에 실패했습니다.'});});
    await page.getByRole('button',{name:await name('ui.scraper.test'),exact:true}).click();
    await expect(page.locator('.scrape-connection-result')).toContainText(await name('ui.error.auth'));
    await expect.poll(()=>untranslated(page)).toEqual([]);
  });
}

for (const language of ['ja','es','fr']) {
  test(`translated menus, conflicts, recovery and help: ${language}`, async ({page}) => {
    await page.evaluate(lang=>window.RMSI18n.setLanguage(lang),language);
    await page.locator('.lrow').first().click({button:'right'});
    await expect.poll(()=>untranslated(page)).toEqual([]);
    await page.keyboard.press('Escape');
    await page.keyboard.press('F1');
    await expect(page.locator('.shortcut-help-body')).toBeVisible();
    await expect.poll(()=>untranslated(page)).toEqual([]);
    await page.keyboard.press('Escape');
    await page.evaluate(()=>{window.__RMS_MOCK_IMMEDIATE_PASTE=true;});
    await page.locator('.lrow').first().click();
    await page.keyboard.press('Control+c');
    await page.keyboard.press('Control+v');
    await expect(page.locator('.paste-conflict-card')).toBeVisible();
    await expect.poll(()=>untranslated(page)).toEqual([]);
    await page.locator('.paste-conflict-expand').first().click();
    await expect.poll(()=>untranslated(page)).toEqual([]);
    await page.keyboard.press('Escape');
    await page.evaluate(()=>{window.api.operationHistory=async()=>({ok:true,data:{items:[{id:'failed',status:'recovery_failed',action:'paste',createdAt:1,bytes:2048,canDiscard:false,canForceRecovery:true,recoveryError:'External file changed'}]}});});
    await page.locator('.settings-btn').click();
    await page.locator('.stg-nav-item[data-section="advanced"]').click();
    const label=id=>page.evaluate(key=>window.RMSI18n.t(key),id);
    await page.getByRole('button',{name:await label('ui.backup.open'),exact:true}).click();
    await expect.poll(()=>untranslated(page)).toEqual([]);
    await page.getByRole('button',{name:await label('ui.history.force'),exact:true}).click();
    await expect.poll(()=>untranslated(page)).toEqual([]);
    await page.keyboard.press('Escape');
    await page.locator('.settings-btn').click();
    await page.locator('.stg-nav-item[data-section="advanced"]').click();
    await page.getByRole('button',{name:await label('ui.backup.open'),exact:true}).click();
    await page.getByRole('button',{name:await label('ui.history.close'),exact:true}).click();
    await expect.poll(()=>untranslated(page)).toEqual([]);
  });
}

for (const language of ['en','ja','es','fr']) {
  test(`${language} Collection setup and Archive import candidates`, async ({page}) => {
    await page.evaluate(language => window.RMSI18n.setLanguage(language), language);
    await page.locator('.ctab-add').click();
    await expect.poll(() => untranslated(page)).toEqual([]);
    await page.keyboard.press('Escape');
    await page.evaluate(() => {
      window.api.matchCandidates=async () => ({ok:true,data:{source:{title:'한글 게임',filename:'게임.zip'},
        candidates:[{romIdentityId:998,filename:'원본.zip',title:'원본 게임',system:'ps2',score:88,
          fields:{name:'원본 게임',desc:'사용자 설명',developer:'Studio',genre:'RPG'},mediaTypes:[]}],
        linkedRomIdentityId:null}});
    });
    await page.locator('.lrow').first().click({button:'right'});
    await page.locator('.ctx-item').filter({hasText:await page.evaluate(() => window.RMSI18n.t('ui.menu.import'))}).hover();
    await page.locator('.ctx-submenu .ctx-item').filter({hasText:/^Archive$/}).click();
    await expect(page.locator('.match-option')).toHaveCount(1);
    await expect.poll(() => untranslated(page)).toEqual([]);
    await page.locator('.match-option .scrape-expand').click();
    await expect.poll(() => untranslated(page)).toEqual([]);
    await expect(page.locator('.match-source')).toContainText('한글 게임');
  });
}

for (const language of ['en','ja','es','fr']) {
  test(`${language} permanent deletion and non-undoable confirmation`, async ({page}) => {
    await page.evaluate(language => {
      window.RMSI18n.setLanguage(language);
      window.__deletions=[];
      window.api.deleteImmediate=async (...args) => {
        window.__deletions.push(args);
        return args[3] ? {ok:true,data:{jobId:'delete-i18n'}} : {ok:true,data:{requiresConfirmation:true}};
      };
      const original=window.api.jobProgress;
      window.api.jobProgress=async id => id==='delete-i18n' ?
        {ok:true,data:{done:true,result:{applied:1,undoOperationId:'undo-i18n'}}} : original(id);
    },language);
    await page.locator('.lrow').first().click();
    await page.keyboard.press('Shift+Delete');
    await expect(page.locator('.modal-text')).toBeVisible();
    await expect.poll(() => untranslated(page)).toEqual([]);
    expect(await page.evaluate(() => window.__deletions.length)).toBe(0);
    await page.keyboard.press('Escape');
    await page.keyboard.press('Delete');
    await expect(page.locator('.modal-text')).toBeVisible();
    await expect.poll(() => untranslated(page)).toEqual([]);
    expect(await page.evaluate(() => window.__deletions[0][3])).toBe(false);
    await page.locator('.modal-actions .danger').click();
    await expect(page.locator('#toast')).toContainText('Ctrl+Z');
    await expect.poll(() => untranslated(page)).toEqual([]);
    expect(await page.evaluate(() => window.__deletions[1][3])).toBe(true);
  });

  test(`${language} shared Archive conflict completion and concurrent change`, async ({page}) => {
    await page.evaluate(language => {
      window.RMSI18n.setLanguage(language);
      window.__sharedCalls=[];
      window.api.startArchiveRefresh=async () => ({ok:true,data:{jobId:'shared-i18n'}});
      const original=window.api.jobProgress;
      window.api.jobProgress=async id => id==='shared-i18n' ?
        {ok:true,data:{done:true,error:'자동으로 합칠 수 없습니다'}} : original(id);
      window.api.archiveSharedConflictStatus=async () => ({ok:true,data:{digest:'observed-digest'}});
      window.api.archiveResolveSharedConflict=async (choice,digest) => {
        window.__sharedCalls.push([choice,digest]);
        return {ok:true,data:choice==='local' ? {status:'published',backups:['D:/백업/local.db','D:/백업/shared.db']} : {status:'conflict'}};
      };
    },language);
    await page.locator('.settings-btn').click();
    await page.locator('.stg-nav-item[data-section="archive"]').click();
    await page.locator('.archive-rescan').click();
    await expect(page.locator('.modal-title')).toHaveText(await page.evaluate(() => window.RMSI18n.t('ui.archive.sharedTitle')));
    await expect.poll(() => untranslated(page)).toEqual([]);
    await page.getByRole('button',{name:await page.evaluate(() => window.RMSI18n.t('ui.archive.useLocal')),exact:true}).click();
    await expect(page.locator('#toast')).toHaveText(await page.evaluate(() => window.RMSI18n.t('ui.archive.resolved',{paths:'D:/백업/local.db · D:/백업/shared.db'})));
    expect(await page.evaluate(() => window.__sharedCalls)).toEqual([['local','observed-digest']]);
    // Raw paths inside the parameterized toast are deliberately preserved.
    await page.locator('.settings-btn').click();
    await page.locator('.stg-nav-item[data-section="archive"]').click();
    await page.locator('.archive-rescan').click();
    await page.getByRole('button',{name:await page.evaluate(() => window.RMSI18n.t('ui.archive.useShared')),exact:true}).click();
    await expect(page.locator('#toast')).toHaveText(await page.evaluate(() => window.RMSI18n.t('ui.archive.changedAgain')));
    await expect.poll(() => untranslated(page)).toEqual([]);
  });
}

for (const language of ['en','ja','es','fr']) {
  test(`${language} Archive record deletion preserves file warning`, async ({page}) => {
    await page.evaluate(language => {
      window.RMSI18n.setLanguage(language);
      window.api.archiveRows=async () => ({ok:true,data:{rows:[{romUid:'rid1',romIdentityId:'rid1',system:'ps2',file:'Game.iso',title:'Game',hasMetadata:true,present:true,storageId:'archive'}],total:1,offset:0}});
      window.api.archiveSystems=async () => ({ok:true,data:[{system:'ps2',count:1}]});
    },language);
    await page.locator('.ctab.archive').click();
    await page.locator('.lrow').first().click();
    await page.keyboard.press('Delete');
    await expect(page.locator('.modal-text')).toHaveText(await page.evaluate(() => window.RMSI18n.t('ui.delete.archiveRecord',{count:'1'})));
    await expect.poll(() => untranslated(page)).toEqual([]);
    await page.keyboard.press('Escape');
    await expect(page.locator('.modal-actions')).toHaveCount(0);
  });
}
