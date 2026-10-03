const {test,expect}=require('@playwright/test');
const {openApp}=require('./_helpers');

async function fitted(panel) {
  await expect(panel).toBeVisible();
  const issues=await panel.evaluate(root=>{
    const found=[],rect=root.getBoundingClientRect();
    if(rect.left<0 || rect.right>innerWidth+1 || rect.top<0 || rect.bottom>innerHeight+1) found.push('panel outside viewport');
    if(root.scrollWidth>root.clientWidth+1) found.push('panel horizontal overflow');
    for(const button of root.querySelectorAll('button')) {
      if(!button.getClientRects().length) continue;
      if(button.scrollWidth>button.clientWidth+1) found.push('button overflow: '+button.textContent.trim());
    }
    return found;
  });
  expect(issues).toEqual([]);
}

for(const language of ['ko','en','ja','es','fr']) {
  for(const scale of [100,130]) {
    test(`compact translated dialogs: ${language} at ${scale}%`,async({page})=>{
      await page.setViewportSize({width:1000,height:640});
      await openApp(page);
      await page.evaluate(({language,scale})=>{
        window.RMSI18n.setLanguage(language);
        document.documentElement.style.setProperty('--font-scale',String(scale/100));
      },{language,scale});
      await page.keyboard.press('F1');
      await fitted(page.locator('.modal-card'));
      await page.keyboard.press('Escape');
      await page.locator('.settings-btn').click();
      for(const section of ['general','scraper','archive','advanced']) {
        await page.locator(`.stg-nav-item[data-section="${section}"]`).click();
        await fitted(page.locator('.stg-panel'));
      }
      await page.keyboard.press('Escape');
      await page.locator('.lrow').first().click({button:'right'});
      await fitted(page.locator('.ctx-menu').first());
      const label=await page.evaluate(()=>window.RMSI18n.t('ui.menu.scrape'));
      await page.locator('.ctx-item',{hasText:label}).click();
      await fitted(page.locator('.scrape-context-card'));
      const start=await page.evaluate(()=>window.RMSI18n.t('ui.scrape.start'));
      await page.getByRole('button',{name:start,exact:true}).click();
      await expect(page.locator('.scrape-candidate').first()).toBeVisible();
      await page.locator('.scrape-expand').first().click();
      await fitted(page.locator('.scrape-context-card'));
      await page.keyboard.press('Escape');
      await page.evaluate(()=>{window.__RMS_MOCK_IMMEDIATE_PASTE=true;});
      await page.locator('.lrow').first().click();
      await page.keyboard.press('Control+c');
      await page.keyboard.press('Control+v');
      await fitted(page.locator('.paste-conflict-card'));
      await page.locator('.paste-conflict-expand').first().click();
      await fitted(page.locator('.paste-conflict-card'));
      await expect(page.locator('.paste-conflict-card .modal-actions')).toBeInViewport();
      expect(await page.locator('.paste-conflict-card .modal-actions').evaluate(el=>{
        const r=el.getBoundingClientRect(),p=el.parentElement.getBoundingClientRect();
        return r.top>=p.top && r.bottom<=p.bottom && r.bottom<=innerHeight;
      })).toBe(true);
      await expect(page.locator('#toast.show.info')).toHaveCount(0);
      if(language==='fr' && scale===130) await page.screenshot({path:'.codex-test-tmp/fr-conflict-compact.png'});
      await page.keyboard.press('Escape');
      await page.evaluate(()=>{window.api.operationHistory=async()=>({ok:true,data:{items:[{id:'failed',status:'recovery_failed',action:'paste',createdAt:1,bytes:2048,canDiscard:true,canForceRecovery:true,recoveryError:'External file changed'}]}});});
      await page.evaluate(()=>{window.api.operationState=async()=>({ok:true,data:{recoveryError:'interrupted'}});});
      await page.locator('.ctab.archive').click();
      await page.locator('.modal-actions .btn.primary').click();
      await fitted(page.locator('.modal-card'));
      if(language==='fr' && scale===130) await page.screenshot({path:'.codex-test-tmp/fr-recovery-compact.png'});
    });
  }
}
