/* RetroMeta Studio UI 다국어.
 * 원문은 한국어이고, 번역표(i18n-data.js / i18n-extra.js)에 없는 문자열은 그대로 보인다.
 * **UI 문구만 번역한다** - 게임 제목/설명 같은 사용자 데이터는 건드리지 않는다.
 */
(function () {
  "use strict";
  const LANGS = ["ko", "en", "ja", "es", "fr"];
  const LABELS = { ko: "한국어", en: "English", ja: "日本語", es: "Español", fr: "Français" };
  const TABLE = window.RMS_I18N_TABLE || {};
  const ATTRS = ["title", "aria-label", "placeholder"];

  // "N개 선택됨"처럼 숫자가 끼는 문구. 정규식은 리터럴이라 \d를 한 번만 쓴다.
  const N = String.raw`(\d[\d,]*)`;
  const P = (re, en, ja, es, fr) => ({ re: new RegExp(re), forms: { en, ja, es, fr } });
  const PATTERNS = [
    P(`^${N}개 선택됨$`, "$1 selected", "$1件を選択", "$1 seleccionados", "$1 sélectionnés"),
    P(`^충돌 ${N}$`, "Conflicts $1", "競合 $1", "Conflictos $1", "Conflits $1"),
    P(`^충돌 ${N}개$`, "Conflicts $1", "競合 $1件", "Conflictos $1", "Conflits $1"),
    P(`^실패 ${N}$`, "Failed $1", "失敗 $1", "Fallos $1", "Échecs $1"),
    P(`^${N}개 파일$`, "$1 files", "$1ファイル", "$1 archivos", "$1 fichiers"),
    P(`^UI 크기 (\\d+)%$`, "UI scale $1%", "UIサイズ $1%", "Escala de UI $1%", "Échelle de l’UI $1%"),
    P(`^${N}개$`, "$1", "$1件", "$1", "$1"),
    P(`^(.+)와 비교$`, "Compare with $1", "$1と比較", "Comparar con $1", "Comparer avec $1"),
    P(`^(.+) 설정$`, "$1 settings", "$1設定", "Configuración de $1", "Paramètres de $1"),
    P(`^(.+) 제거$`, "Remove $1", "$1を削除", "Quitar $1", "Supprimer $1"),
    P(`^(.+) 붙여넣기 완료$`, "$1 pasted", "$1を貼り付けました", "$1 pegado", "$1 collé"),
  ];

  let current = "ko";
  let extraPatterns = [];

  function lookup(value, lang) {
    const hit = TABLE[value];
    if (hit && hit[lang]) return hit[lang];
    for (const p of PATTERNS.concat(extraPatterns)) {
      const m = value.match(p.re);
      if (m && p.forms[lang]) return p.forms[lang].replace(/\$(\d)/g, (_, i) => m[+i] ?? "");
    }
    return null;
  }

  /** 앞뒤 공백은 보존하고 가운데만 번역한다. */
  function t(value) {
    if (typeof value !== "string" || current === "ko" || !value) return value;
    const core = value.trim();
    if (!core) return value;
    const out = lookup(core, current);
    if (out === null) return value;
    const lead = value.slice(0, value.indexOf(core));
    return lead + out + value.slice(lead.length + core.length);
  }

  // 정적 HTML은 원문(한국어)을 기억해 둬야 언어를 되돌릴 수 있다.
  const textOriginal = new WeakMap();
  const attrOriginal = new WeakMap();

  function retranslateExistingDOM() {
    if (!document.body) return;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((n) => {
      if (!textOriginal.has(n)) textOriginal.set(n, n.nodeValue);
      const next = t(textOriginal.get(n));
      if (next !== n.nodeValue) n.nodeValue = next;
    });
    document.body.querySelectorAll("[title],[aria-label],[placeholder]").forEach((el) => {
      let saved = attrOriginal.get(el);
      if (!saved) { saved = {}; attrOriginal.set(el, saved); }
      ATTRS.forEach((attr) => {
        if (!el.hasAttribute(attr)) return;
        if (!(attr in saved)) saved[attr] = el.getAttribute(attr);
        const next = t(saved[attr]);
        if (next !== el.getAttribute(attr)) el.setAttribute(attr, next);
      });
    });
  }

  function setLanguage(lang) {
    current = LANGS.includes(lang) ? lang : "ko";
    document.documentElement.lang = current;
    try { localStorage.setItem("rms.language", current); } catch (_) { /* 저장 못 해도 동작한다 */ }
    // 동적으로 그린 화면은 다시 그리고(원문에서 새로 번역), 정적 HTML은 원문 기억으로 되돌려 번역한다.
    if (typeof window.__rmsRelocalize === "function") window.__rmsRelocalize();
    retranslateExistingDOM();
    return current;
  }

  window.RMSI18n = {
    LANGS, LABELS, t, setLanguage, retranslateExistingDOM,
    getLanguage: () => current,
    /** h()가 만든 노드는 이미 번역돼 있다 - 원문을 기억해 둬야 다른 언어/한국어로 되돌릴 수 있다. */
    remember: (node, original) => { textOriginal.set(node, original); },
    rememberAttr: (el, attr, original) => {
      let saved = attrOriginal.get(el);
      if (!saved) { saved = {}; attrOriginal.set(el, saved); }
      saved[attr] = original;
    },
    addTable: (extra) => { Object.entries(extra || {}).forEach(([k, v]) => { TABLE[k] = { ...(TABLE[k] || {}), ...v }; }); },
    addPatterns: (list) => { extraPatterns = extraPatterns.concat(list || []); },
    P,
  };
  try { const cached = localStorage.getItem("rms.language"); if (LANGS.includes(cached)) current = cached; } catch (_) { /* 무시 */ }
  document.documentElement.lang = current;
})();
