/* ==========================================================================
   title-affix.js — Title Prefix/Postfix 계산(app/title_affix.py의 JS 이식)

   실제로 파일에 쓰는 값은 항상 Python 쪽(bridge의 title_affix_preview/plan_title_edit)이
   계산한다 - 여기 있는 것은 **화면에서 미리 판단이 필요한 곳**(우클릭 메뉴에서 "적용할
   내용이 없으면 아예 못 고르게" 하는 것, 목업)에 쓰는 사본이다. 두 구현이 갈라지지
   않도록 규칙이 바뀌면 이 파일과 app/title_affix.py를 항상 같이 고쳐야 한다.

   api-client.js(목업)와 app.js(메뉴 활성/비활성 판단)가 같이 쓴다 - 로직을 두 곳에
   따로 베껴두지 않기 위해 index.html에서 그 둘보다 먼저 이 파일을 불러온다.
   ========================================================================== */
(function () {
  "use strict";

  const REGIONS = ["kr", "en", "jp", "eu"];   // global은 명시 매칭이 아니라 기본값이라 뺀다
  const KEYWORDS = {
    kr: ["kr", "kor", "korea"], jp: ["jp", "jpn", "japan"], eu: ["eu", "eur", "europe", "uk", "gb"],
    en: ["us", "usa", "na", "en", "eng", "english", "america"],
  };
  const DEFAULTS = {
    kr: { enabled: false, mode: "prefix", text: "KR" }, en: { enabled: false, mode: "prefix", text: "EN" },
    jp: { enabled: false, mode: "prefix", text: "JP" }, eu: { enabled: false, mode: "prefix", text: "EU" },
    global: { enabled: false, mode: "prefix", text: "WORLD" },
  };

  /** region 필드 값을 5개 구역 중 하나로. 한/영/일/유럽 중 어디에도 안 걸리면(빈 값,
   * "World" 같은 글로벌 표기, 못 알아보는 표기 전부) 글로벌로 본다 - region을 안 채운
   * Collection에서도 글로벌 설정은 써야 한다(사용자 결정). */
  function classifyRegion(region) {
    const tokens = String(region || "").toLowerCase().match(/[a-z가-힣]+/g) || [];
    for (const bucket of REGIONS) {
      if (tokens.some((t) => KEYWORDS[bucket].includes(t))) return bucket;
    }
    return "global";
  }

  //: 단어(Disk/Disc)가 있으면 총 장수 없이 번호 하나만 있어도("Disc A") 인정한다.
  const DISK_WORD_RE = /[([]\s*(dis[ck])\s*\.?\s*([0-9]+|[a-z])\s*(?:(?:of|\/)\s*([0-9]+|[a-z]))?\s*[)\]]/i;
  //: 단어 없이 숫자만 있으면("(2/2)") 번호와 총 장수가 **둘 다** 있을 때만 인정한다 -
  //: 하나뿐이면("(1994)") 발매연도와 구별할 수 없다.
  const DISK_FRACTION_RE = /[([]\s*([0-9]{1,2})\s*(?:of|\/)\s*([0-9]{1,2})\s*[)\]]/;

  function extractDisk(title) {
    let m = title.match(DISK_WORD_RE);
    let word, num, total;
    if (m) {
      [, word, num, total] = m;
      word = word[0].toUpperCase() + word.slice(1).toLowerCase();
      num = num.toUpperCase();
    } else {
      m = title.match(DISK_FRACTION_RE);
      if (!m) return [title, null];
      word = "Disk"; [, num, total] = m;
    }
    const marker = `(${word} ${num}${total ? ` of ${total.toUpperCase()}` : ""})`;
    return [(title.slice(0, m.index) + " " + title.slice(m.index + m[0].length)).trim(), marker];
  }

  function stripEdges(title) {
    let text = title.trim();
    for (let i = 0; i < 6; i += 1) {
      let stripped = text;
      [/^[\s_-]*[([{][^([){}\]]*[)\]}][\s_-]*/, /[\s_-]*[([{][^([){}\]]*[)\]}][\s_-]*$/,
        /^\s*[A-Za-z0-9]+[_-]+\s*/, /\s*[_-]+[A-Za-z0-9]+\s*$/].forEach((re) => {
        const candidate = stripped.replace(re, "").trim();
        if (candidate) stripped = candidate;
      });
      if (stripped === text) break;
      text = stripped;
    }
    return text || title.trim();
  }

  const DELIM = new Set("_-.~()[]{}".split(""));
  function joinAffix(text, title, isPrefix) {
    text = text.trim();
    if (!text) return title;
    const delimited = DELIM.has(isPrefix ? text[text.length - 1] : text[0]);
    return isPrefix ? `${text}${delimited ? "" : "_"}${title}` : `${title}${delimited ? "" : "_"}${text}`;
  }

  /** {oldTitle,newTitle,changed,regionBucket,diskMarker} - app/title_affix.py의
   * compute_new_title()과 같은 계산이다. */
  function compute(oldTitle, region, config) {
    oldTitle = oldTitle || "";
    const [withoutDisk, diskMarker] = extractDisk(oldTitle);
    const base = stripEdges(withoutDisk);
    const core = diskMarker ? `${base} ${diskMarker}` : base;
    const bucket = classifyRegion(region);
    const cfg = { ...DEFAULTS[bucket], ...(config && config[bucket]) };
    const newTitle = (cfg.enabled && cfg.text.trim())
      ? joinAffix(cfg.text, core, cfg.mode !== "postfix")
      : core;
    return { oldTitle, newTitle, changed: newTitle !== oldTitle, regionBucket: bucket, diskMarker };
  }

  window.RMSTitleAffix = { compute, classifyRegion, DEFAULTS };
})();
