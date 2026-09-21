/* ==========================================================================
   system-icons-pack.js — System 아이콘 팩(파일명 기반)

   `gui_web/system-icons-50/<system>.png` 파일이 그 System의 아이콘이다. 사용자가
   파일명을 바꾸거나 새 PNG를 넣는 것만으로 매칭된다 - 코드 표를 고칠 필요가 없다.
   편집 전 원본 자산(가공하지 않은 PNG, 안 쓰는 레거시 SVG 스크립트)은 `system-icons-50/org/`에
   보관한다. 시도했지만 채택하지 않은 대체 스타일 팩은 `system-icons-neon/`에 따로 둔다(같은
   파일명 규칙이라 나중에 쓰기로 하면 `BASE`만 바꾸면 된다) - `org/`와 달리 이건 완결된 팩이다.

   찾는 순서(candidates): 폴더명 그대로 → 구분자 제거 → 별칭 → 지역/변형 접미사를
   뗀 이름. 끝까지 없으면 app.js가 기존 SVG(system-icons.js) → 범용 아이콘으로 넘긴다.

   이 파일은 이름 목록만 만든다. 그리는 것과 폴백은 app.js의 systemIcon()이 한다 -
   ui/stitch-v2-redesign처럼 RMSystemIcons.svg/has를 가로채지 않는다.
   ========================================================================== */
(function () {
  "use strict";

  const BASE = "system-icons-50/";

  //: 같은 기계의 다른 이름. 왼쪽은 compact(구분자 제거) 형태다.
  const ALIASES = {
    superfamicom: "sfc", supernintendo: "snes",
    genesis: "genesis", sega32x: "sega32x", "32x": "sega32x",
    ps1: "psx", playstation1: "psx", playstation2: "ps2", playstation3: "ps3",
    playstation4: "ps4", playstation5: "ps5", playstationvita: "psvita", vita: "psvita",
    xbox360: "xbox360", xboxone: "xboxone", xboxseriesx: "xboxseries",
    turbografx: "turbografx16", tg16: "turbografx16", turbografxcd: "pcenginecd",
    gameboy: "gb", gameboycolor: "gbc", gameboyadvance: "gba",
    nintendods: "nds", nintendo3ds: "n3ds", "3ds": "n3ds", n64dd: "n64",
    gamecube: "gc", ngc: "gc",
    sms: "mastersystem", mastersystem2: "mastersystem", sg1000: "mastersystem",
    megacdjp: "megacdjp", segacd: "segacd",
    neogeopocket: "ngp", neogeopocketcolor: "ngpc",
    msxturbor: "msxturbor", msx2plus: "msx2",
    fbalpha: "fba", finalburnneo: "fbneo", mame2003plus: "mame2003", mame2010: "mame",
    zxspectrum: "zxspectrum", c64: "commodore64", pc98: "pc98", pc9801: "pc98",
    x68k: "x68000", windows9x: "windows", win: "windows",
  };

  //: 지역/변형 접미사. 파일이 없으면 떼고 다시 찾는다(megadrivejp.png가 없으면 megadrive.png).
  const SUFFIXES = ["plus", "jp", "japan", "usa", "us", "eu", "europe", "kr", "korea", "cd", "hack", "homebrew"];

  function compact(name) {
    return String(name || "").toLowerCase().trim().replace(/\.png$/, "").replace(/[\s_\-.]+/g, "");
  }

  function candidates(name) {
    const raw = String(name || "").toLowerCase().trim();
    if (!raw) return [];
    const out = [];
    const push = (value) => { if (value && !out.includes(value)) out.push(value); };
    const key = compact(raw);
    push(raw.replace(/\s+/g, ""));
    push(key);
    push(ALIASES[key]);
    for (const suffix of SUFFIXES) {
      if (key.length > suffix.length + 1 && key.endsWith(suffix)) {
        const base = key.slice(0, -suffix.length);
        push(base);
        push(ALIASES[base]);
      }
    }
    // **앞 이름으로도 찾는다**(사용자 결정 - "FBNEO xxxx, MAME xxxx도 앞에 이름을 기준으로 아이콘").
    // `FBNEO ACT`는 FBNEO 중 액션만 모아 둔 폴더라 같은 기계다 - 정확한 이름이 없으면 앞 토막으로 찾는다.
    // 정확한 이름을 먼저 넣었으므로 `mame2003.png`처럼 전체 이름 파일이 있으면 그쪽이 이긴다.
    const head = raw.split(/[\s_\-.]+/).filter(Boolean)[0];
    if (head && head !== key) {
      push(head);
      push(ALIASES[head]);
    }
    return out;
  }

  window.RMSystemIconPack = {
    base: BASE,
    candidates,
    src: (file) => `${window.RMSystemIconPack.base}${file}.png`,
  };
})();
