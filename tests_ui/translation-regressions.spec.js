const {test,expect}=require('@playwright/test');
const {openApp}=require('./_helpers');
test.beforeEach(async({page})=>openApp(page));
for(const language of ['en','ja','es','fr']) {
  test(`status tooltips refresh in ${language}`,async({page})=>{
    await page.evaluate(language=>window.RMSI18n.setLanguage(language),language);
    const titles=await page.locator('.status-icon').evaluateAll(nodes=>nodes.map(el=>el.title));
    expect(titles.length).toBeGreaterThan(0);
    expect(titles.every(text=>!/[가-힣]/.test(text))).toBe(true);
  });
}
test('French selection singular and long save label',async({page})=>{
  await page.setViewportSize({width:1000,height:640});
  await page.evaluate(()=>window.RMSI18n.setLanguage('fr'));
  expect(await page.evaluate(()=>window.RMSI18n.t('ui.status.selectedOne',{count:1}))).toBe('1 sélectionné');
  await page.locator('.lrow').first().click();
  const button=page.locator('.detail-save');
  await expect(button).toBeVisible();
  expect(await button.evaluate(el=>getComputedStyle(el).whiteSpace)).toBe('nowrap');
  expect(await button.evaluate(el=>el.scrollWidth<=el.clientWidth&&el.getBoundingClientRect().right<=innerWidth)).toBe(true);
  await page.locator('.lrow').first().click({button:'right'});
  expect(await page.locator('.ctx-label').evaluateAll(nodes=>nodes.every(el=>el.title===el.textContent))).toBe(true);
});
test('DeepL key suggests endpoint but manual override remains possible',async({page})=>{
  await page.locator('.settings-btn').click();
  await page.locator('.stg-nav-item[data-section="metadata"]').click();
  const mode=page.locator('.translation-mode');
  await mode.selectOption('deepl-pro');
  await page.locator('.translation-key').fill('fake-key:fx');
  await expect(mode).toHaveValue('deepl-free');
  await mode.selectOption('deepl-pro');
  await expect(mode).toHaveValue('deepl-pro');
});
test('Korean warning requires explicit second click without a first API request',async({page})=>{
  const result=await page.evaluate(async()=>{
    let calls=0;
    const input=document.createElement('textarea'); input.value='이 게임은 한국어 설명으로 작성되어 있습니다';document.body.appendChild(input);
    const h=(tag,attrs={},children=[])=>{const el=document.createElement(tag);for(const [key,value]of Object.entries(attrs)){if(key==='onClick')el.addEventListener('click',value);else if(key==='class')el.className=value;else el[key]=value;}for(const child of children)el.append(child);return el;};
    const ui=window.RMSTranslationUI.create({h,api:{translationSettings:async()=>({ok:true,data:{mode:'deepl-free',hasKey:true,verified:true}}),originalDescription:async()=>({ok:true,data:null}),startTranslateDescription:async()=>{calls++;return{ok:false,error:'ui.translation.connection'};}},showModal:(title,body)=>document.body.appendChild(body),closeModal:()=>{},showToast:()=>{},openSettings:()=>{},language:()=> 'ko'});
    await ui.open(input,null,'game-key',()=>true,()=>{});
    document.querySelector('.translation-start').click();
    const first=calls, warning=document.querySelector('.translation-status').textContent;
    document.querySelector('.translation-start').click();
    return{first,calls,warning};
  });
  expect(result.first).toBe(0);expect(result.calls).toBe(1);expect(result.warning).toContain('이미 한국어');
});
