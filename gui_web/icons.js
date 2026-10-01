/* ==========================================================================
   icons.js
   lucide-react 대체용 최소 SVG 아이콘 세트 (외부 의존성 없음, 직접 작성한 심플한 획).
   사용: RMIcons.svg("search", 14) -> SVG 문자열 반환
   ========================================================================== */

(function () {
  const STROKE = 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';

  const PATHS = {
    dashboard: '<rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/>',
    database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    minus: '<line x1="5" y1="12" x2="19" y2="12"/>',
    search: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    refresh: '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    gamepad: '<line x1="6" y1="12" x2="10" y2="12"/><line x1="8" y1="10" x2="8" y2="14"/><circle cx="15" cy="13" r="1"/><circle cx="18" cy="11" r="1"/><rect x="2" y="6" width="20" height="12" rx="4"/>',
    play: '<polygon points="6 3 20 12 6 21 6 3" fill="currentColor" stroke="none"/>',
    pause: '<rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor" stroke="none"/>'
      + '<rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor" stroke="none"/>',
    image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
    imageOff: '<line x1="2" y1="2" x2="22" y2="22"/><path d="M10.41 10.41a2 2 0 1 1-2.83-2.83"/><line x1="13.5" y1="13.5" x2="6" y2="21"/><path d="M18 12v6a2 2 0 0 1-2 2H6"/><path d="M21 15V5a2 2 0 0 0-2-2H9"/>',
    chevronDown: '<polyline points="6 9 12 15 18 9"/>',
    chevronUp: '<polyline points="18 15 12 9 6 15"/>',
    arrowLeftRight: '<path d="M8 3 4 7l4 4"/><path d="M4 7h16"/><path d="m16 21 4-4-4-4"/><path d="M20 17H4"/>',
    chevronLeft: '<polyline points="15 18 9 12 15 6"/>',
    chevronRight: '<polyline points="9 18 15 12 9 6"/>',
    star: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    globe: '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    tag: '<path d="M20.59 13.41 13.42 20.6a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><circle cx="7" cy="7" r="1.5"/>',
    building: '<rect x="4" y="2" width="16" height="20" rx="1"/><line x1="8" y1="6" x2="8" y2="6.01"/><line x1="16" y1="6" x2="16" y2="6.01"/><line x1="8" y1="10" x2="8" y2="10.01"/><line x1="16" y1="10" x2="16" y2="10.01"/><line x1="8" y1="14" x2="8" y2="14.01"/><line x1="16" y1="14" x2="16" y2="14.01"/>',
    trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    edit: '<path d="m16 3 5 5-12 12-6 1 1-6z"/><path d="m13 6 5 5"/>',
    scissors: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="m8 8 12 12M8 16 20 4"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    check: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    alertTriangle: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    xCircle: '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
    circle: '<circle cx="12" cy="12" r="10"/>',
    scale: '<line x1="12" y1="3" x2="12" y2="21"/><path d="M7 8l-4 8a3.5 3.5 0 0 0 8 0z"/><path d="M17 8l-4 8a3.5 3.5 0 0 0 8 0z"/><path d="M3 8h18"/><path d="M12 3l4 5"/><path d="M12 3l-4 5"/>',
    save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>',
    smartphone: '<rect x="6" y="2" width="12" height="20" rx="2"/><line x1="11" y1="18" x2="13" y2="18"/>',
    cornerUpLeft: '<polyline points="9 14 4 9 9 4"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/>',
    cornerUpRight: '<polyline points="15 14 20 9 15 4"/><path d="M4 20v-7a4 4 0 0 1 4-4h12"/>',
    history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><polyline points="3 3 3 8 8 8"/><path d="M12 7v5l3 2"/>',
    hardDrive: '<line x1="22" y1="12" x2="2" y2="12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><line x1="6" y1="16" x2="6.01" y2="16"/><line x1="10" y1="16" x2="10.01" y2="16"/>',
    hardDriveDownload: '<line x1="22" y1="12" x2="2" y2="12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><path d="M12 8v4m0 0-2-2m2 2 2-2"/>',
    hardDriveUpload: '<line x1="22" y1="12" x2="2" y2="12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><path d="M12 12V8m0 0 2 2m-2-2-2 2"/>',
    fileText: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="15" y2="13"/><line x1="8" y1="17" x2="13" y2="17"/>',
    fileWarning: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="13" x2="12" y2="17"/><line x1="12" y1="20.5" x2="12.01" y2="20.5"/>',
    sparkles: '<path d="M12 3l1.6 4.9L18.5 9.5 13.6 11 12 16l-1.6-5L5.5 9.5 10.4 7.9z"/><path d="M5 20l.8-2.4L8.2 17l-2.4-.8L5 13.8l-.8 2.4L1.8 17l2.4.8z"/>',
    eraser: '<path d="M20 20H9L4 15a1.5 1.5 0 0 1 0-2.12l9.5-9.5a1.5 1.5 0 0 1 2.12 0l5.29 5.29a1.5 1.5 0 0 1 0 2.12L13.5 18"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    eyeOff: '<path d="M9.9 5.2A10.6 10.6 0 0 1 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-2.6 3.6"/><path d="M6.6 6.6C3.7 8.4 2 12 2 12s3.5 7 10 7a10 10 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/><line x1="2" y1="2" x2="22" y2="22"/>',
    folderOpen: '<path d="M6 14v-3a2 2 0 0 1 2-2h2l2 2h6a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3l2 2"/>',
    menu: '<line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/>',
    x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    pin: '<line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24z"/>',
    pinOff: '<line x1="2" y1="2" x2="22" y2="22"/><line x1="12" y1="17" x2="12" y2="22"/><path d="M9 9v1.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V17h7"/><path d="M15 9.34V6h1a2 2 0 0 0 0-4H9.68"/>',
    listFilter: '<path d="M3 6h18M6 12h12M10 18h4"/>',
    layoutList: '<rect x="3" y="4" width="18" height="4" rx="1"/><rect x="3" y="10" width="18" height="4" rx="1"/><rect x="3" y="16" width="18" height="4" rx="1"/>',
    layoutGrid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
    previewPane: '<rect x="3" y="4" width="18" height="16" rx="2"/><line x1="14" y1="4" x2="14" y2="20"/>',
    moreHorizontal: '<circle cx="5" cy="12" r="1.7" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.7" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.7" fill="currentColor" stroke="none"/>',
    info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
    triangleAlert: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    console: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M7 12h6M10 9v6"/><circle cx="17" cy="10" r="1"/><circle cx="19" cy="13" r="1"/>',
    cartridge: '<path d="M7 3h10v4l2 2v12H5V9l2-2z"/><path d="M9 3v4h6V3M8 16h8"/>',
    disc: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2"/><path d="M12 3v7M21 12h-7"/>',
    arcade: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h3"/><circle cx="16" cy="16" r="1"/>',
    handheld: '<rect x="6" y="3" width="12" height="18" rx="3"/><rect x="8" y="6" width="8" height="5" rx="1"/><path d="M9 15h3M10.5 13.5v3M14 15h.01"/>',
    computer: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4M7 8h10v5H7z"/>',
    // [신규] 사이드바 시스템별 아이콘 확장 - 기존 6종(cartridge/disc/arcade/handheld/console/computer)만으로는
    // 8bit 컴퓨터/조이스틱 기반 시스템/리모컨형 콘솔을 구분하지 못해 추가.
    // 아케이드 스틱(레버+베이스+버튼) - 아케이드/MAME 계열 전체에 사용
    joystick: '<rect x="2" y="13" width="20" height="7" rx="1"/><line x1="7" y1="13" x2="7" y2="5"/><circle cx="7" cy="4" r="2"/><circle cx="13" cy="16.5" r="1"/><circle cx="16.5" cy="16.5" r="1"/><circle cx="20" cy="16.5" r="1"/>',
    // 키보드(키 두 줄 + 스페이스바) - MSX/DOS/Amiga/C64 등 8bit 컴퓨터
    keyboard: '<rect x="2" y="6" width="20" height="12" rx="2"/><line x1="5.5" y1="10" x2="5.5" y2="10.01"/><line x1="9" y1="10" x2="9" y2="10.01"/><line x1="12.5" y1="10" x2="12.5" y2="10.01"/><line x1="16" y1="10" x2="16" y2="10.01"/><line x1="19" y1="10" x2="19" y2="10.01"/><rect x="6" y="13.5" width="12" height="2" rx="1"/>',
    floppy: '<rect x="4" y="3" width="16" height="18" rx="1"/><path d="M8 3v6h8V3"/><rect x="8" y="13" width="8" height="6"/>',
    remote: '<rect x="9" y="2" width="6" height="20" rx="3"/><circle cx="12" cy="7" r="1"/><line x1="10" y1="11" x2="14" y2="11"/><line x1="10" y1="14" x2="14" y2="14"/>',
    // 각진 패드(십자키+버튼 2개, 손잡이 없는 평평한 형태) - NES/Famicom/마스터시스템류
    padRect: '<rect x="2" y="8" width="20" height="9" rx="2"/><line x1="6" y1="10.5" x2="6" y2="14.5"/><line x1="4" y1="12.5" x2="8" y2="12.5"/><circle cx="15" cy="12.5" r="1.1"/><circle cx="18.5" cy="12.5" r="1.1"/>',
    // Archive 탭 · App Title의 대표 아이콘(실사용 피드백 - "너무 DB 스러운
    // 아이콘이다. 인베이더 스타일로"). 8비트 스페이스 인베이더 픽셀 실루엣 -
    // 획이 아니라 칠한 사각형이라 fill/stroke를 로컬로 뒤집는다(play와 같은 방식).
    invader: '<g fill="currentColor" stroke="none">'
      + '<rect x="5" y="4" width="2" height="2"/><rect x="17" y="4" width="2" height="2"/>'
      + '<rect x="7" y="6" width="2" height="2"/><rect x="15" y="6" width="2" height="2"/>'
      + '<rect x="5" y="8" width="14" height="2"/>'
      + '<rect x="3" y="10" width="4" height="2"/><rect x="9" y="10" width="6" height="2"/><rect x="17" y="10" width="4" height="2"/>'
      + '<rect x="1" y="12" width="22" height="2"/>'
      + '<rect x="1" y="14" width="2" height="2"/><rect x="5" y="14" width="14" height="2"/><rect x="21" y="14" width="2" height="2"/>'
      + '<rect x="1" y="16" width="2" height="2"/><rect x="5" y="16" width="2" height="2"/><rect x="17" y="16" width="2" height="2"/><rect x="21" y="16" width="2" height="2"/>'
      + '<rect x="7" y="18" width="4" height="2"/><rect x="13" y="18" width="4" height="2"/>'
      + '</g>',
  };

  function svg(name, size) {
    size = size || 14;
    const inner = PATHS[name] || PATHS.circle;
    return `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" ${STROKE}>${inner}</svg>`;
  }

  window.RMIcons = { svg };
})();
