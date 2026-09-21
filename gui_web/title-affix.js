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

  const REGIONS = ["kr", "en", "jp", "eu", "global"];
  const KEYWORDS = {
    kr: ["k", "kr", "kor", "korea", "korean"],
    en: ["u", "us", "usa", "na", "en", "eng", "english", "america"],
    jp: ["j", "jp", "jpn", "jap", "japan"],
    eu: ["e", "eu", "eur", "europe", "pal", "uk", "gb"],
    global: ["w", "world", "global", "int", "intl", "international"],
  };
  const DEFAULTS = {
    kr: { enabled: false, mode: "prefix", text: "KR" }, en: { enabled: false, mode: "prefix", text: "EN" },
    jp: { enabled: false, mode: "prefix", text: "JP" }, eu: { enabled: false, mode: "prefix", text: "EU" },
    global: { enabled: false, mode: "prefix", text: "WORLD" },
  };

  //: 괄호/대괄호로 감싼 덩어리 - 안에 무엇이 들어 있든 일단 잡고, **전부 지역 표기일 때만** 인정한다.
  const GROUP_RE = /[([]\s*([^()[\]]{1,40}?)\s*[)\]]/g;
  //: 한 괄호 안의 여러 지역을 가르는 구분 - `(Japan, Europe)`, `(USA/Europe)`, `(Japan & USA)`.
  const GROUP_SPLIT_RE = /\s*(?:,|\/|\+|&|\band\b)\s*/i;
  const WORD_RE = /^[A-Za-z]{1,12}$/;
  //: 구분자로 붙인 태그 - `Game_k`, `global_Game`. 공백은 구분자로 치지 않는다.
  const TAG_DELIMITED_RE = /(?:^|[_-])([A-Za-z]{1,12})(?=[_-]|$)/g;
  const ALL_KEYWORDS = new Set([].concat(...Object.values(KEYWORDS)));

  /** 파일명의 지역 태그에 해당하는 구역을 **모두** 돌려준다(REGIONS 순서).
   * `(Japan, Europe)`는 일본과 유럽 둘 다다. `(En,Fr,De)`는 언어 목록이라 지역이 아니다. */
  function classifyRegions(filename) {
    let stem = String(filename || "");
    if (stem.includes(".")) stem = stem.slice(0, stem.lastIndexOf("."));
    const tokens = new Set();
    for (const m of stem.matchAll(GROUP_RE)) {
      const parts = m[1].split(GROUP_SPLIT_RE).filter(Boolean);
      if (!parts.length || !parts.every((p) => WORD_RE.test(p))) continue;   // (Disc 1), (2/2), (Rev A)
      const lowered = parts.map((p) => p.toLowerCase());
      if (lowered.length > 1 && !lowered.every((t) => ALL_KEYWORDS.has(t))) continue;
      lowered.forEach((t) => tokens.add(t));
    }
    for (const m of stem.matchAll(TAG_DELIMITED_RE)) tokens.add(m[1].toLowerCase());
    return REGIONS.filter((bucket) => KEYWORDS[bucket].some((k) => tokens.has(k)));
  }

  /** 대표 구역 하나(여럿이면 앞선 것). 태그가 없으면 null(미분류) - 자동 적용 대상에서 빠진다. */
  function classifyRegion(filename) {
    const found = classifyRegions(filename);
    return found.length ? found[0] : null;
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
  const isSpace = (ch) => /\s/.test(ch);
  //: 앞뒤 공백은 지우지 않는다 - `" (KR)"`처럼 일부러 넣은 공백이 곧 구분자다(실사용 피드백).
  //: 자동 구분자(`_`)는 문구가 이미 구분자나 공백으로 끝날 때(접두)/시작할 때(접미)만 생략한다.
  function joinPrefix(text, title) {
    if (!text.trim()) return title;
    const last = text[text.length - 1];
    return `${text}${DELIM.has(last) || isSpace(last) ? "" : "_"}${title}`;
  }
  function joinPostfix(title, text) {
    if (!text.trim()) return title;
    return `${title}${DELIM.has(text[0]) || isSpace(text[0]) ? "" : "_"}${text}`;
  }

  const WRAPPED_RE = /^(\s*)([([{])(.*)([)\]}])(\s*)$/;
  /** 여러 지역의 문구를 하나로 - 모두 같은 괄호면 `[JP]` `[EU]`가 `[JP,EU]`가 된다. */
  function mergeTexts(texts) {
    if (texts.length === 1) return texts[0];
    const wrapped = texts.map((t) => t.match(WRAPPED_RE));
    if (wrapped.every(Boolean) && new Set(wrapped.map((m) => m[2] + m[4])).size === 1) {
      const first = wrapped[0], last = wrapped[wrapped.length - 1];
      return `${first[1]}${first[2]}${wrapped.map((m) => m[3].trim()).join(",")}${last[4]}${last[5]}`;
    }
    return texts.join("");
  }

  /** {oldTitle,newTitle,changed,regionBucket,regionBuckets,diskMarker} - app/title_affix.py의
   * compute_new_title()과 같은 계산이다. 구역은 **파일명**으로 정한다. */
  function compute(oldTitle, filename, config) {
    oldTitle = oldTitle || "";
    const buckets = classifyRegions(filename);
    // 미분류는 장식을 떼지도, 붙이지도 않는다(사용자 결정: 자동 적용 대상에서 제외).
    if (!buckets.length) {
      return { oldTitle, newTitle: oldTitle, changed: false, regionBucket: null, regionBuckets: [], diskMarker: null };
    }
    const [withoutDisk, diskMarker] = extractDisk(oldTitle);
    const base = stripEdges(withoutDisk);
    let newTitle = diskMarker ? `${base} ${diskMarker}` : base;
    const active = buckets
      .map((b) => ({ ...DEFAULTS[b], ...(config && config[b]) }))
      .filter((c) => c.enabled && String(c.text || "").trim());
    const prefixes = active.filter((c) => c.mode !== "postfix").map((c) => c.text);
    const postfixes = active.filter((c) => c.mode === "postfix").map((c) => c.text);
    if (postfixes.length) newTitle = joinPostfix(newTitle, mergeTexts(postfixes));
    if (prefixes.length) newTitle = joinPrefix(mergeTexts(prefixes), newTitle);
    return { oldTitle, newTitle, changed: newTitle !== oldTitle, regionBucket: buckets[0],
             regionBuckets: buckets, diskMarker };
  }

  window.RMSTitleAffix = { compute, classifyRegion, classifyRegions, DEFAULTS };
})();
