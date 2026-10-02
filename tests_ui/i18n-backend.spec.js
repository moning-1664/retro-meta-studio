const {test, expect} = require('@playwright/test');
const {openApp} = require('./_helpers');
const fs = require('fs');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname,'../gui_web/i18n-messages.js'),'utf8');
const rules = JSON.parse(source.slice(source.indexOf('[',source.indexOf('addBackendMessages(')),source.lastIndexOf(']);')+1));
for (const language of ['en','ja','es','fr']) {
  test(`${language}: every registered backend message translates without changing parameters`, async ({page}) => {
    await openApp(page);
    const failures = await page.evaluate(({rules,language}) => {
      const i = window.RMSI18n; i.setLanguage(language);
      const failures = [];
      for (const rule of rules) {
        const params = Object.fromEntries([...rule.template.matchAll(/\{(\w+)\}/g)].map((m,n)=>[m[1],`RAW_${n}_D:/game.zip`]));
        const input = rule.template.replace(/\{(\w+)\}/g,(_,name)=>params[name]);
        const expected = i.t(rule.key,params)+(rule.prefix?params.detail:'');
        const actual = i.formatError(input);
        if (actual !== expected) failures.push({input,expected,actual});
      }
      return failures;
    },{rules,language});
    expect(failures).toEqual([]);
  });
}
test('backend localization preserves Korean paths, unknown diagnostics and game descriptions', async ({page}) => {
  await openApp(page);
  const result = await page.evaluate(() => {
    const i = window.RMSI18n; i.setLanguage('en');
    return [i.formatError('열 수 있는 Media 파일이 없습니다.'),
      i.formatError('D:/한글 게임/커버.png에 열 수 있는 Media 파일이 없습니다.'),
      i.formatError('알 수 없는 외부 오류: 한글 경로'),i.t(i.raw('게임 설명 원문'))];
  });
  expect(result[1]).toContain('D:/한글 게임/커버.png');
  expect(result[1]).not.toContain('열 수 있는');
  expect(result[2]).toBe('알 수 없는 외부 오류: 한글 경로');
  expect(result[3]).toBe('게임 설명 원문');
});

