/* ==========================================================================
   system-icons.js
   사이드바 System 목록 전용 아이콘 자산 세트.

   icons.js의 범용(generic) 아이콘 세트와는 완전히 분리된 별도 리소스다.
   시스템 키(normalizeSystemName 결과) 1개당 SVG path 1개를 매핑한다.
   app.js의 renderSystemIcon()이 실제 lookup 순서를 관리한다:
   system-icons-raster.js(전용 PNG) -> 이 파일(전용 SVG) -> icons.js(범용 카테고리)
   - 여기 없는 키라도 마지막 단계에서 항상 뭔가는 나온다.

   색상은 <svg>에 고정하지 않고 stroke="currentColor"만 써서 사이드바의
   현재 텍스트/accent 색을 그대로 물려받는다(라이트/다크 테마, hover/active
   상태 전환은 전부 CSS의 color 값 변경만으로 처리됨 - 아이콘 자체는 불변).

   사용: RMSystemIcons.has(key) / RMSystemIcons.svg(key, size)
   ========================================================================== */

(function () {
  const STROKE = 'fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"';

  // 각 path는 24x24 기준 좌표. size는 렌더링 시점에 22px 등으로 스케일된다.
  const SYSTEM_PATHS = {
    // ---- 닌텐도 거치형 ----
    nes: '<rect x="2" y="8" width="20" height="8" rx="1.5"/><path d="M5 12h4M7 10v4"/><circle cx="15.5" cy="12" r="1"/><circle cx="18.5" cy="12" r="1"/><rect x="9.5" y="6" width="5" height="2"/>',
    famicom: '<rect x="2" y="8" width="20" height="8" rx="1.5"/><path d="M5 12h4M7 10v4"/><circle cx="16" cy="12" r="1.1" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.1" fill="currentColor" stroke="none"/>',
    snes: '<path d="M3 9c0-2 1.5-3 3.5-3h11c2 0 3.5 1 3.5 3v3.5c0 2.5-1.8 4.5-4 4.5-1.2 0-2-1-3-2H10c-1 1-1.8 2-3 2-2.2 0-4-2-4-4.5z"/><path d="M6.5 11h3M8 9.5v3"/><circle cx="17" cy="9.8" r=".9"/><circle cx="19" cy="11.5" r=".9"/><circle cx="17" cy="13.2" r=".9"/><circle cx="15" cy="11.5" r=".9"/>',
    superfamicom: '<path d="M3 9c0-2 1.5-3 3.5-3h11c2 0 3.5 1 3.5 3v3.5c0 2.5-1.8 4.5-4 4.5-1.2 0-2-1-3-2H10c-1 1-1.8 2-3 2-2.2 0-4-2-4-4.5z"/><path d="M6.5 11h3M8 9.5v3"/><path d="M14 9.5h6M14 13.5h6"/>',
    n64: '<path d="M12 3v6"/><path d="M12 9c-4 0-7 3-7 6.5S7 21 9.5 21c1.5 0 2-1.5 2.5-3 .5 1.5 1 3 2.5 3 2.5 0 4.5-2.9 4.5-5.5S16 9 12 9z"/><circle cx="12" cy="6" r="1.4"/><circle cx="9.2" cy="15.5" r=".9"/><circle cx="14.8" cy="15.5" r=".9"/>',
    gamecube: '<path d="M12 4c-4.5 0-8 3.2-8 7.3 0 4.4 2.8 8.2 6.3 8.2 1.2 0 1.7-1.4 1.7-3 0-1 .8-1.5 2-1.5s2 .5 2 1.5c0 1.6.5 3 1.7 3 3.5 0 6.3-3.8 6.3-8.2C24 7.2 20.5 4 16 4"/><circle cx="8.5" cy="10.5" r="1.6"/><circle cx="16.5" cy="9" r=".8"/><circle cx="18.5" cy="11" r=".8"/><circle cx="16.5" cy="13" r=".8"/>',
    wii: '<rect x="9" y="2" width="6" height="20" rx="3"/><circle cx="12" cy="6.3" r="1"/><line x1="10.2" y1="10.5" x2="13.8" y2="10.5"/><line x1="10.2" y1="13" x2="13.8" y2="13"/><circle cx="12" cy="17" r="1"/>',
    wiiu: '<rect x="3" y="7" width="18" height="12" rx="2.5"/><rect x="9" y="10" width="6" height="5" rx=".5"/><path d="M5.5 12h2.2M6.6 10.8v2.4"/><circle cx="18" cy="10.5" r=".8"/><circle cx="18" cy="14" r=".8"/>',
    switch: '<rect x="2" y="6" width="6" height="12" rx="2.5"/><rect x="16" y="6" width="6" height="12" rx="2.5"/><rect x="8" y="4" width="8" height="16" rx="1.5"/><circle cx="5" cy="10" r="1"/><path d="M4 15h2M5 14v2"/><circle cx="19" cy="10" r=".8"/><circle cx="19" cy="14" r=".8"/>',

    // ---- 닌텐도 휴대용 ----
    gb: '<rect x="6" y="2" width="12" height="20" rx="2"/><rect x="8" y="4.5" width="8" height="6" rx=".5"/><path d="M8.5 15h2.6M9.8 13.7v2.6"/><circle cx="14.7" cy="14" r=".9"/><circle cx="16.3" cy="15.6" r=".9"/>',
    gbc: '<rect x="6" y="2" width="12" height="20" rx="2"/><rect x="7.7" y="4.5" width="8.6" height="6" rx=".5"/><path d="M8.5 15h2.6M9.8 13.7v2.6"/><circle cx="14.7" cy="14" r=".9"/><circle cx="16.3" cy="15.6" r=".9"/><circle cx="17.5" cy="4" r=".6" fill="currentColor" stroke="none"/>',
    gba: '<rect x="1.5" y="7" width="21" height="10" rx="2.5"/><rect x="8" y="9" width="8" height="6" rx=".5"/><path d="M3.5 12.3h2.6M4.8 11v2.6"/><circle cx="18.5" cy="11" r=".8"/><circle cx="20" cy="12.5" r=".8"/>',
    nds: '<rect x="5" y="2" width="14" height="9.2" rx="1.3"/><rect x="5" y="12.8" width="14" height="9.2" rx="1.3"/><rect x="7.2" y="4" width="9.6" height="5.4" rx=".4"/><circle cx="15" cy="16.5" r=".8"/><circle cx="16.6" cy="18.1" r=".8"/><path d="M8 17.4h2.4M9.2 16.2v2.4"/>',
    n3ds: '<rect x="4" y="2" width="16" height="9.2" rx="1.3"/><rect x="4" y="12.8" width="16" height="9.2" rx="1.3"/><rect x="6" y="4" width="12" height="5.4" rx=".4"/><circle cx="7.5" cy="16.4" r="1.3"/><circle cx="16" cy="15.6" r=".8"/><circle cx="17.5" cy="17.2" r=".8"/><circle cx="14.5" cy="17.2" r=".8"/>',
    psp: '<rect x="1.5" y="7" width="21" height="10" rx="4"/><circle cx="6" cy="12" r="2.2"/><rect x="10" y="9.5" width="4" height="5" rx=".5"/><circle cx="17.3" cy="10.3" r=".8"/><circle cx="19" cy="12" r=".8"/><circle cx="17.3" cy="13.7" r=".8"/>',
    psvita: '<rect x="3" y="2" width="18" height="20" rx="3"/><rect x="6" y="5" width="12" height="9" rx=".6"/><circle cx="7.5" cy="17.5" r="1.4"/><circle cx="16.5" cy="17.5" r="1.4"/>',
    gamegear: '<rect x="4" y="3" width="16" height="18" rx="2.5"/><rect x="6.5" y="5.5" width="11" height="7" rx=".5"/><path d="M8 16.3h2.4M9.2 15.1v2.4"/><circle cx="15" cy="15.7" r=".8"/><circle cx="16.5" cy="17.2" r=".8"/>',
    wonderswan: '<rect x="6" y="2" width="12" height="20" rx="2"/><rect x="8" y="4.5" width="8" height="7" rx=".5"/><circle cx="9.8" cy="15.3" r="1.6"/><circle cx="14.7" cy="15.3" r="1.6"/>',

    // ---- 소니 ----
    psx: '<circle cx="12" cy="12" r="9.2"/><path d="M9 8.3 12 3l3 5.3M9 15.7 12 21l3-5.3"/><circle cx="12" cy="12" r="1.6"/>',
    ps2: '<circle cx="12" cy="12" r="9.2"/><path d="M9 8.3 12 3l3 5.3M9 15.7 12 21l3-5.3"/><circle cx="12" cy="12" r="1.6"/><circle cx="12" cy="12" r="4.4"/>',
    ps3: '<ellipse cx="12" cy="12" rx="10.5" ry="6.4"/><path d="M9 9.4 12 5l3 4.4M9 14.6 12 19l3-4.4"/><circle cx="12" cy="12" r="1.4"/>',
    ps4: '<path d="M4 8c0-2.5 3.5-3.5 8-3.5S20 5.5 20 8v3.5c0 3.5-2 6.5-4.7 6.5-1 0-1.5-1-2-2H10.7c-.5 1-1 2-2 2C6 18 4 15 4 11.5z"/><circle cx="16" cy="8.5" r=".9"/><circle cx="18" cy="10.3" r=".9"/><circle cx="16" cy="12.1" r=".9"/><circle cx="14" cy="10.3" r=".9"/><path d="M7.5 10h3M9 8.5v3"/>',
    ps5: '<path d="M4 8.3c0-2.6 3.6-3.6 8-3.6s8 1 8 3.6v3.3c0 3.6-2 6.7-4.8 6.7-1 0-1.5-1-2-2H10.8c-.5 1-1 2-2 2-2.8 0-4.8-3.1-4.8-6.7z"/><path d="M7.5 10.1h3M9 8.6v3"/><path d="M14.5 9.2h4M14.5 12.6h4"/>',

    // ---- 세가 ----
    megadrive: '<path d="M4 10c0-2.8 2.4-4.3 8-4.3S20 7.2 20 10v2c0 3-2 5.6-4.6 5.6-1.3 0-2-1-2.6-2.2-.4-.8-1.6-.8-2 0-.5 1.2-1.3 2.2-2.6 2.2C6 17.6 4 15 4 12z"/><path d="M6.7 11.3h3M8.2 9.8v3"/><circle cx="16.5" cy="9.5" r=".8"/><circle cx="18" cy="11" r=".8"/><circle cx="16.5" cy="12.5" r=".8"/>',
    genesis: '<path d="M4 10c0-2.8 2.4-4.3 8-4.3S20 7.2 20 10v2c0 3-2 5.6-4.6 5.6-1.3 0-2-1-2.6-2.2-.4-.8-1.6-.8-2 0-.5 1.2-1.3 2.2-2.6 2.2C6 17.6 4 15 4 12z"/><path d="M6.7 11.3h3M8.2 9.8v3"/><circle cx="16.5" cy="9.5" r=".8"/><circle cx="18" cy="11" r=".8"/><circle cx="16.5" cy="12.5" r=".8"/><circle cx="15" cy="11" r=".8"/>',
    mastersystem: '<rect x="2" y="9" width="20" height="7" rx="1.3"/><path d="M4.8 12.5h3M6.3 11v3"/><circle cx="15.3" cy="11.6" r=".9"/><circle cx="17.8" cy="13.4" r=".9"/>',
    saturn: '<circle cx="12" cy="12" r="9.2"/><path d="M8 8.5h2.4M9.2 7.3v2.4"/><circle cx="14.6" cy="8.4" r=".8"/><circle cx="16.4" cy="9.6" r=".8"/><circle cx="14.6" cy="10.8" r=".8"/><circle cx="12.8" cy="9.6" r=".8"/><path d="M4 14.5c2 2.4 5 3.8 8 3.8s6-1.4 8-3.8"/>',
    dreamcast: '<circle cx="12" cy="11" r="7.6"/><path d="M12 6.5v3.3M12 9.8l-2.6 1.9M12 9.8l2.6 1.9M12 9.8l-1.6 3.1M12 9.8l1.6 3.1"/><path d="M5 18.5c2 1.6 4.4 2.5 7 2.5s5-.9 7-2.5"/>',
    pcengine: '<rect x="3" y="9.5" width="18" height="6" rx="3"/><path d="M6.2 12.5h2.6M7.5 11.2v2.6"/><circle cx="14.5" cy="11.5" r=".8"/><circle cx="16.5" cy="13.5" r=".8"/><circle cx="16.5" cy="11.5" r=".8"/><circle cx="14.5" cy="13.5" r=".8"/>',
    pcenginecd: '<circle cx="12" cy="12" r="9.2"/><circle cx="12" cy="12" r="2"/><rect x="3.5" y="15.5" width="17" height="4" rx="1"/>',

    // ---- 아케이드 ----
    arcade: '<rect x="5" y="2" width="6" height="14" rx="1"/><circle cx="8" cy="4.6" r="1.6"/><rect x="13" y="16" width="9" height="6" rx="1"/><circle cx="15.6" cy="19" r="1"/><circle cx="18" cy="17.6" r="1"/><circle cx="20.4" cy="19" r="1"/><circle cx="18" cy="20.4" r="1"/>',
    mame: '<rect x="2" y="15" width="20" height="6" rx="1.4"/><rect x="9.5" y="2" width="5" height="13" rx="1"/><circle cx="12" cy="4.6" r="1.5"/><circle cx="6" cy="18" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="18" r="1"/><circle cx="18" cy="18" r="1"/>',
    fbneo: '<rect x="2" y="15" width="20" height="6" rx="1.4"/><rect x="9.5" y="2" width="5" height="13" rx="1"/><circle cx="12" cy="4.6" r="1.5"/><circle cx="6.5" cy="18" r="1"/><circle cx="9.5" cy="18" r="1"/><circle cx="12.5" cy="18" r="1"/><circle cx="15.5" cy="18" r="1"/><circle cx="18.5" cy="18" r="1"/>',
    cps1: '<rect x="9.5" y="2" width="5" height="13" rx="1"/><circle cx="12" cy="4.6" r="1.5"/><rect x="2" y="15" width="20" height="6" rx="1.4"/><text x="12" y="19.4" font-size="4.6" font-family="monospace" text-anchor="middle" fill="currentColor" stroke="none">1</text>',
    cps2: '<rect x="9.5" y="2" width="5" height="13" rx="1"/><circle cx="12" cy="4.6" r="1.5"/><rect x="2" y="15" width="20" height="6" rx="1.4"/><text x="12" y="19.4" font-size="4.6" font-family="monospace" text-anchor="middle" fill="currentColor" stroke="none">2</text>',
    cps3: '<rect x="9.5" y="2" width="5" height="13" rx="1"/><circle cx="12" cy="4.6" r="1.5"/><rect x="2" y="15" width="20" height="6" rx="1.4"/><text x="12" y="19.4" font-size="4.6" font-family="monospace" text-anchor="middle" fill="currentColor" stroke="none">3</text>',
    neogeo: '<rect x="2" y="15" width="20" height="6" rx="1.4"/><rect x="9.5" y="2" width="5" height="13" rx="1"/><circle cx="12" cy="4.6" r="1.5"/><circle cx="6" cy="18" r="1.2"/><circle cx="10" cy="18" r="1.2"/><circle cx="14" cy="18" r="1.2"/><circle cx="18" cy="18" r="1.2"/>',

    // ---- 조이스틱 기반 홈콘솔 ----
    atari2600: '<path d="M12 15V6M12 6l-2.5-3.5h5z"/><rect x="4" y="15" width="16" height="5" rx="1"/><circle cx="18" cy="17.5" r=".9"/>',
    jaguar: '<path d="M12 15V6M12 6l-2.5-3.5h5z"/><rect x="4" y="15" width="16" height="5" rx="1"/><circle cx="16.6" cy="17.5" r=".8"/><circle cx="19.4" cy="17.5" r=".8"/>',
    colecovision: '<path d="M12 15V6M12 6l-2.5-3.5h5z"/><rect x="4" y="15" width="16" height="5" rx="1"/><circle cx="14.4" cy="17.5" r=".7"/><circle cx="16.6" cy="17.5" r=".7"/><circle cx="18.8" cy="17.5" r=".7"/>',
    intellivision: '<circle cx="12" cy="9" r="6.2"/><circle cx="9" cy="7.7" r=".7"/><circle cx="12" cy="7" r=".7"/><circle cx="15" cy="7.7" r=".7"/><circle cx="9" cy="10.3" r=".7"/><circle cx="12" cy="11" r=".7"/><circle cx="15" cy="10.3" r=".7"/><rect x="6" y="17" width="12" height="3.5" rx="1"/>',

    // ---- 마이크로컴퓨터 ----
    msx: '<rect x="1.5" y="8" width="21" height="10" rx="1.4"/><path d="M4 11h1.4M6.4 11h1.4M8.8 11h1.4M11.2 11h1.4M13.6 11h1.4M16 11h1.4M18.4 11h1.4"/><rect x="6" y="14" width="9" height="2" rx=".7"/>',
    msx2: '<rect x="1.5" y="8" width="21" height="10" rx="1.4"/><path d="M4 11h1.4M6.4 11h1.4M8.8 11h1.4M11.2 11h1.4M13.6 11h1.4M16 11h1.4M18.4 11h1.4"/><path d="M4 13.3h1.4M6.4 13.3h1.4M8.8 13.3h1.4"/><rect x="10.5" y="14.6" width="8" height="1.7" rx=".6"/>',
    dos: '<rect x="2.5" y="4" width="19" height="12" rx="1.2"/><path d="M6 20h12M12 16v4"/><path d="M5.5 7.5h1.4M7.9 7.5h1.4M10.3 7.5h1.4M12.7 7.5h1.4M15.1 7.5h1.4M17.5 7.5h1.4"/><rect x="9" y="10.4" width="6" height="1.6" rx=".6"/>',
    windows: '<rect x="2.5" y="4" width="19" height="12" rx="1.2"/><path d="M6 20h12M12 16v4"/><path d="M5.5 7.5h1.4M7.9 7.5h1.4M10.3 7.5h1.4M12.7 7.5h1.4M15.1 7.5h1.4M17.5 7.5h1.4"/><path d="M5.5 9.8h1.4M7.9 9.8h1.4M10.3 9.8h1.4"/><rect x="11.7" y="10.9" width="6.4" height="1.5" rx=".5"/>',
    amiga: '<rect x="1.5" y="9" width="21" height="8.5" rx="1.4"/><path d="M4 12h1.4M6.4 12h1.4M8.8 12h1.4M11.2 12h1.4M13.6 12h1.4M16 12h1.4M18.4 12h1.4"/><rect x="6" y="14.6" width="9" height="1.7" rx=".6"/><path d="M2 9v-1.6c0-.6.5-1 1-1h18c.5 0 1 .4 1 1V9"/>',
    c64: '<path d="M2.5 8.5c0-1.4 1.2-2.5 3-2.5h13c1.8 0 3 1.1 3 2.5V16c0 1.4-1.2 2.5-3 2.5h-13c-1.8 0-3-1.1-3-2.5z"/><path d="M5 10.6h1.4M7.4 10.6h1.4M9.8 10.6h1.4M12.2 10.6h1.4M14.6 10.6h1.4M17 10.6h1.4"/><rect x="8" y="13.2" width="6.5" height="1.6" rx=".6"/>',
    atarist: '<rect x="1.5" y="7" width="21" height="10" rx="1.2"/><path d="M4 10.2h1.4M6.4 10.2h1.4M8.8 10.2h1.4M11.2 10.2h1.4M13.6 10.2h1.4M16 10.2h1.4M18.4 10.2h1.4"/><rect x="6" y="13" width="9" height="1.7" rx=".6"/><circle cx="19.5" cy="14.7" r=".8"/>',
    zxspectrum: '<rect x="2" y="6" width="20" height="12" rx="1.4"/><path d="M4.5 9.5h1.3M6.8 9.5h1.3M9.1 9.5h1.3M11.4 9.5h1.3M13.7 9.5h1.3M16 9.5h1.3M18.3 9.5h1.3"/><rect x="4.5" y="12.3" width="15" height="2" rx=".6" fill="currentColor" stroke="none" opacity=".85"/>',
    scummvm: '<path d="M4 4h11l5 5v11H4z"/><path d="M15 4v5h5"/><circle cx="9" cy="14.5" r="2.6"/><path d="M9 12.6v3.8M7.1 14.5h3.8"/>',

    // ---- 마이크로소프트 ----
    xbox: '<path d="M12 21c-4.5 0-8-3.5-8-7.8C4 9.6 7 6.3 9.6 4.4c.6-.4 1.2-.1.8.6-1.7 3-2.9 5.8-2.9 8.2 0 2.6 1.9 4.3 4.5 4.3s4.5-1.7 4.5-4.3c0-2.4-1.2-5.2-2.9-8.2-.4-.7.2-1 .8-.6C17 6.3 20 9.6 20 13.2c0 4.3-3.5 7.8-8 7.8z"/>',
    xbox360: '<circle cx="12" cy="12" r="9.2"/><path d="M12 12c-3-2.7-4-5.2-2.6-8.4M12 12c3-2.7 4-5.2 2.6-8.4M12 12c-3 2.7-4 5.2-2.6 8.4M12 12c3 2.7 4 5.2 2.6 8.4"/>',
    xboxone: '<path d="M12 21c-4.5 0-8-3.5-8-7.8C4 9.6 7 6.3 9.6 4.4c.6-.4 1.2-.1.8.6-1.7 3-2.9 5.8-2.9 8.2 0 2.6 1.9 4.3 4.5 4.3s4.5-1.7 4.5-4.3c0-2.4-1.2-5.2-2.9-8.2-.4-.7.2-1 .8-.6C17 6.3 20 9.6 20 13.2c0 4.3-3.5 7.8-8 7.8z"/><circle cx="12" cy="13.5" r="1.3"/>',
    xboxseries: '<rect x="3" y="3" width="8" height="18" rx="1.6"/><path d="M14 3h7v8h-7z"/><path d="M14 21v-8h7v8z"/>',
  };

  function has(key) {
    const k = String(key || "").toLowerCase();
    return Object.prototype.hasOwnProperty.call(SYSTEM_PATHS, k) && !!SYSTEM_PATHS[k];
  }

  function svg(key, size) {
    size = size || 22;
    const k = String(key || "").toLowerCase();
    const inner = SYSTEM_PATHS[k];
    if (!inner) return "";
    return `<svg class="system-icon-svg" width="${size}" height="${size}" viewBox="0 0 24 24" ${STROKE}>${inner}</svg>`;
  }

  const NAMES = {
    sfc: "Super Famicom", superfamicom: "Super Famicom", snes: "Super Nintendo",
    fc: "Famicom", famicom: "Famicom", nes: "Nintendo Entertainment System",
    n64: "Nintendo 64", gc: "GameCube", gamecube: "GameCube", wii: "Wii", wiiu: "Wii U",
    switch: "Nintendo Switch", gb: "Game Boy", gbc: "Game Boy Color", gba: "Game Boy Advance",
    nds: "Nintendo DS", n3ds: "Nintendo 3DS", md: "Mega Drive", megadrive: "Mega Drive",
    genesis: "Genesis", mastersystem: "Master System", gamegear: "Game Gear",
    saturn: "Sega Saturn", dreamcast: "Dreamcast", megacd: "Mega CD", segacd: "Sega CD",
    psx: "PlayStation", ps1: "PlayStation", ps2: "PlayStation 2", ps3: "PlayStation 3",
    ps4: "PlayStation 4", ps5: "PlayStation 5", psp: "PSP", vita: "PS Vita", psvita: "PS Vita",
    arcade: "Arcade", mame: "Arcade · MAME", mame2003: "Arcade · MAME 2003",
    fbneo: "Arcade · FBNeo", fba: "Arcade · FBA", cps1: "Capcom CPS-1", cps2: "Capcom CPS-2",
    cps3: "Capcom CPS-3", neogeo: "Neo Geo", ngp: "Neo Geo Pocket", ngpc: "Neo Geo Pocket Color",
    msx: "MSX", msx1: "MSX", msx2: "MSX2", msxturbor: "MSX turbo R",
    pc88: "PC-88", pc98: "PC-98", pce: "PC Engine", pcengine: "PC Engine",
    pcenginecd: "PC Engine CD", pcfx: "PC-FX", naomi: "Sega NAOMI", naomi2: "Sega NAOMI 2",
    windows: "Windows", dos: "DOS", xbox: "Xbox", xbox360: "Xbox 360", xboxone: "Xbox One",
  };
  const displayName = (key) => NAMES[String(key || "").toLowerCase()] || String(key || "").toUpperCase();
  window.RMSystemIcons = { has, svg, displayName };
})();
