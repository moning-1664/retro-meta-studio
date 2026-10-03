/* Required source audit. Uses the parser already bundled with Playwright. */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const {babelParse, traverse} = require('../node_modules/playwright/lib/transform/babelBundle');
const root = path.resolve(__dirname, '..');
const context = {window:{}, document:{documentElement:{}, body:null}, localStorage:{getItem(){},setItem(){}}};
vm.createContext(context);
for (const file of ['i18n-data.js','i18n.js','i18n-extra.js','i18n-messages.js'])
  vm.runInContext(fs.readFileSync(path.join(root,'gui_web',file),'utf8'), context);
const i18n = context.window.RMSI18n;
const failures = [];
let checked = 0;
function check(text, location) {
  checked++;
  const sample = text.replace(/\{value(\d+)\}/g, (_, n) => '98765'+n+'43210');
  for (const language of ['en','ja','es','fr']) {
    i18n.setLanguage(language);
    if (/[가-힣]/.test(i18n.t(sample))) failures.push(`${location} (${language}): ${text}`);
  }
}
for (const file of ['app.js','scraper-ui.js','transfer-ui.js','translation-ui.js','archive-settings-ui.js','collection-setup-ui.js','settings.js','dashboard.js','candidate-ui.js','shortcut-help.js','title-affix.js']) {
  const source = fs.readFileSync(path.join(root,'gui_web',file),'utf8');
  traverse(babelParse(source,file), {
    StringLiteral({node}) {
      if (/[가-힣]/.test(node.value)) check(node.value,`${file}:${node.loc.start.line}`);
    },
    TemplateLiteral({node}) {
      if (node.quasis.some(q => /[가-힣]/.test(q.value.cooked || '')))
        check(node.quasis.map((q,n)=>(q.value.cooked||'')+(n<node.expressions.length?`{value${n}}`:'')).join(''),`${file}:${node.loc.start.line}`);
    }
  });
}
const html = fs.readFileSync(path.join(root,'gui_web','index.html'),'utf8').replace(/<!--[\s\S]*?-->/g,'');
for (const match of html.matchAll(/(?:title|placeholder|aria-label)="([^"]*)"|>([^<>]+)</g)) {
  const text = (match[1] || match[2] || '').trim();
  if (/[가-힣]/.test(text)) check(text,'index.html');
}
const backend = JSON.parse(fs.readFileSync(0,'utf8') || '[]');
for (const item of backend) check(item.text,`${item.file}:${item.line}`);
if (failures.length) {
  console.error(failures.join('\n')); process.exitCode = 1;
} else console.log(`Source translation audit: ${checked} UI/backend messages, no missing translations in four non-Korean languages.`);
