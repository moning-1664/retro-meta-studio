import { useState, useEffect, useRef } from "react";
import {
  LayoutDashboard, Database, Settings, Plus, Search, RefreshCw, Upload,
  Gamepad2, Image as ImageIcon, ChevronDown, ChevronUp, ChevronLeft, Star, Calendar, Users,
  Globe, Building2, Tag, Trash2, Copy, CheckCircle2, AlertTriangle, XCircle, Circle,
  Scale, Save, HardDrive, Menu, X, Pin, PinOff, ListFilter, ImageOff, Copy as CopyIcon,
  HardDriveDownload, HardDriveUpload, FileWarning, Sparkles, Eraser, FolderOpen, TriangleAlert, Info,
  LayoutList, LayoutGrid,
} from "lucide-react";

// [재구성 안내] 이 파일은 Claude 프로젝트에 첨부된 RetroMetadataManager_Mockup.jsx를
// project_knowledge_search로 조각조각 검색해 최대한 원본에 가깝게 재구성한 것입니다.
// 검색이 청크 단위라 100% 원문 그대로는 아닐 수 있으나, 구조/스타일/동작은 충실히 반영했습니다.
// v0.3 design pass: dense information layout, persistent detail tabs/media focus, and pinned detail navigation.

const DARK = {
  bg: "#090B18", card: "#12172A", card2: "#191F36", card3: "#252B4A", border: "#30385B",
  text: "#F4F3FF", muted: "#9DA8C8", accent: "#8B5CF6", accentHover: "#A78BFA",
  success: "#39D98A", warning: "#FFB74D", danger: "#FF647C",
  listBg: "#10162A", listHead: "#1B2340", listBorder: "#30385B", listRowBorder: "#252D4A", listText: "#F4F3FF", listMuted: "#9DA8C8", listSelected: "#24204A",
};
const LIGHT = {
  bg: "#F3F1FF", card: "#FFFFFF", card2: "#F8F7FF", card3: "#ECE9FE", border: "#DDD9F5",
  text: "#1A1830", muted: "#6E7190", accent: "#7357E8", accentHover: "#6145D0",
  success: "#1EA96B", warning: "#D88919", danger: "#DF4864",
  listBg: "#FFFFFF", listHead: "#F7F6FF", listBorder: "#DDD9F5", listRowBorder: "#EEECEF", listText: "#1A1830", listMuted: "#6E7190", listSelected: "#F0ECFF",
};
let C = { ...DARK };
function applyTheme(mode) {
  let effective = mode;
  if (mode === "system") {
    effective = (typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
  }
  Object.assign(C, effective === "light" ? LIGHT : DARK);
}

const STRINGS = {
  ko: {
    dashboard: "Dashboard", settings: "Settings", addLocal: "Local 추가", delete: "삭제", refresh: "새로고침",
    colNo: "No.", colFile: "File", colTitle: "Title", colDesc: "Description", colRegion: "Region", colRating: "Rating", colGenre: "Genre", colStatus: "Status",
    statusNormal: "정상", statusPartial: "일부만", statusMissing: "누락",
    filterAll: "전체", filterNormal: "정상", filterPartial: "일부만", filterMissingRom: "롬 없음", filterMissingMedia: "미디어 없음", filterDuplicate: "중복 ROM",
    refreshList: "Refresh List (F5)", cleanup: "CleanUp", pruneData: "Prune Data", exportMasterDB: "Export to MasterDB",
    metricTotalRom: "전체 ROM", metricTotalSize: "전체 용량", metricMissingRom: "롬 없음", metricMissingMedia: "미디어 없음",
    save: "저장 (Ctrl+S)", local: "LOCAL", server: "SERVER",
  },
  en: {
    dashboard: "Dashboard", settings: "Settings", addLocal: "Add Local", delete: "Delete", refresh: "Refresh",
    colNo: "No.", colFile: "File", colTitle: "Title", colDesc: "Description", colRegion: "Region", colRating: "Rating", colGenre: "Genre", colStatus: "Status",
    statusNormal: "Normal", statusPartial: "Partial", statusMissing: "Missing",
    filterAll: "All", filterNormal: "Normal", filterPartial: "Partial", filterMissingRom: "Missing ROM", filterMissingMedia: "Missing Media", filterDuplicate: "Duplicate ROM",
    refreshList: "Refresh List (F5)", cleanup: "CleanUp", pruneData: "Prune Data", exportMasterDB: "Export to MasterDB",
    metricTotalRom: "Total ROM", metricTotalSize: "Total Size", metricMissingRom: "Missing ROM", metricMissingMedia: "Missing Media",
    save: "Save (Ctrl+S)", local: "LOCAL", server: "SERVER",
  },
};
let LANG = "ko";
const t = (k) => STRINGS[LANG][k] || k;

const FRONTENDS = ["ES-DE", "EmulationStation", "Pegasus", "LaunchBox", "Daijishō"];
const SAME_DIR_FRONTENDS = new Set(["Pegasus", "Daijishō"]);
const ES_STYLE_FRONTENDS = new Set(["ES-DE", "EmulationStation"]);
const normalizeSystemName = (s) => (s || "").toUpperCase();

const LOCALS0 = [
  { id: "l1", label: "Local 1", frontend: "ES-DE", romPath: "D:\\Roms\\ES-DE\\", romCount: 12342, sizeGB: 1.21, status: "정상" },
  { id: "l2", label: "Local 2", frontend: "Pegasus", romPath: "D:\\Roms\\Pegasus\\", romCount: 8421, sizeGB: 0.82, status: "경고" },
  { id: "l3", label: "Local 3", frontend: "LaunchBox", romPath: "D:\\Roms\\LaunchBox\\", romCount: 5231, sizeGB: 0.51, status: "정상" },
];
const MASTERDB = { romCount: 25481, sizeGB: 2.45, status: "정상" };

const GAMES0 = [
  { id: 1, local: "l1", system: "snes", file: "Super Mario World.zip", title: "Super Mario World", desc: "Mario's off on his biggest adventure yet, and this time he's brought his best friend along! Ride Yoshi through the Mushroom Kingdom.", genre: "Platform", developer: "Nintendo EAD", publisher: "Nintendo", release: "1990-11-21", region: "USA (NTSC)", players: "1-2", rating: 4.8, status: "완료" },
  { id: 2, local: "l1", system: "snes", file: "Zelda - A Link to the Past.zip", title: "The Legend of Zelda: A Link to the Past", desc: "Link must rescue Princess Zelda and save Hyrule from Ganon's forces across two worlds.", genre: "Action RPG", developer: "Nintendo EAD", publisher: "Nintendo", release: "1991-11-21", region: "USA (NTSC)", players: "1", rating: 4.9, status: "완료" },
  { id: 3, local: "l1", system: "snes", file: "Donkey Kong Country.zip", title: "Donkey Kong Country", desc: "Classic side-scrolling platform adventure with Donkey Kong and Diddy Kong.", genre: "Platform", developer: "Rare", publisher: "Nintendo", release: "1994-11-21", region: "USA (NTSC)", players: "1-2", rating: 4.5, status: "부분" },
  { id: 4, local: "l1", system: "snes", file: "Chrono Trigger.zip", title: "Chrono Trigger", desc: "A time-traveling RPG that changed the world of games forever.", genre: "RPG", developer: "Square", publisher: "Square", release: "1995-03-11", region: "USA (NTSC)", players: "1", rating: 5.0, status: "완료" },
  { id: 5, local: "l1", system: "snes", file: "Super Metroid.zip", title: "Super Metroid", desc: "Explore the planet Zebes and uncover its secrets.", genre: "Action", developer: "Nintendo R&D1", publisher: "Nintendo", release: "1994-03-19", region: "USA (NTSC)", players: "1", rating: 4.9, status: "완료" },
  { id: 6, local: "l1", system: "snes", file: "Contra III - The Alien Wars.zip", title: "Contra III: The Alien Wars", desc: "Alien Red Falcon is back in this run-and-gun classic.", genre: "Run & Gun", developer: "Konami", publisher: "Konami", release: "1992-08-28", region: "USA (NTSC)", players: "1-2", rating: 4.7, status: "완료" },
  { id: 7, local: "l1", system: "nes", file: "Mega Man 2.zip", title: "Mega Man 2", desc: "Mega Man returns to stop Dr. Wily's newest army of robot masters.", genre: "Platform", developer: "Capcom", publisher: "Capcom", release: "1988-12-24", region: "USA (NTSC)", players: "1", rating: 4.9, status: "완료", missingMedia: true },
  { id: 8, local: "l2", system: "genesis", file: "Sonic the Hedgehog 2.zip", title: "Sonic the Hedgehog 2", desc: "Sonic and Tails team up to stop Dr. Robotnik's Death Egg from launching.", genre: "Platform", developer: "Sonic Team", publisher: "Sega", release: "1992-11-21", region: "USA (NTSC)", players: "1-2", rating: 4.7, status: "완료" },
  { id: 9, local: "l2", system: "genesis", file: "Streets of Rage 2.zip", title: "Streets of Rage 2", desc: "Take back the city from Mr. X's criminal empire in this classic beat 'em up.", genre: "Beat 'em up", developer: "Sega AM7", publisher: "Sega", release: "1992-12-11", region: "USA (NTSC)", players: "1-2", rating: 4.8, status: "완료" },
  { id: 10, local: "l2", system: "genesis", file: "Gunstar Heroes.zip", title: "", desc: "", genre: "", developer: "", publisher: "", release: "", region: "", players: "", rating: "", status: "누락" },
  { id: 11, local: "l3", system: "psx", file: "Final Fantasy VII.bin", title: "Final Fantasy VII", desc: "Cloud Strife joins eco-terrorist group AVALANCHE to fight the Shinra corporation.", genre: "RPG", developer: "Square", publisher: "Square", release: "1997-09-07", region: "USA (NTSC)", players: "1", rating: 4.9, status: "완료" },
  { id: 12, local: "l3", system: "psx", file: "Metal Gear Solid.bin", title: "Metal Gear Solid", desc: "Solid Snake infiltrates a nuclear weapons facility to stop a terrorist takeover.", genre: "Stealth Action", developer: "Konami", publisher: "Konami", release: "1998-10-21", region: "USA (NTSC)", players: "1", rating: 4.9, status: "완료", missingMedia: true },
  { id: 13, local: "l3", system: "psx", file: "Crash Bandicoot.bin", title: "Crash Bandicoot", desc: "A bandicoot fights Dr. Neo Cortex to stop his evil plans for world domination.", genre: "Platform", developer: "Naughty Dog", publisher: "Sony", release: "1996-09-09", region: "USA (NTSC)", players: "1", rating: 4.5, status: "부분" },
];

const mockMedia = (title, kind, index = 0) => {
  const palettes = ["#8B5CF6", "#39D98A", "#FFB74D", "#5B8CFF", "#FF647C"];
  const accent = palettes[index % palettes.length];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800" viewBox="0 0 600 800"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="${accent}"/><stop offset="1" stop-color="#090B18"/></linearGradient></defs><rect width="600" height="800" rx="28" fill="url(#g)"/><circle cx="300" cy="300" r="150" fill="#ffffff22"/><path d="M175 380 Q300 190 425 380 L390 455 Q300 390 210 455Z" fill="#fff" opacity=".85"/><text x="40" y="650" fill="#fff" font-family="Segoe UI, sans-serif" font-size="38" font-weight="700">${title.replace(/&/g,'&amp;').replace(/</g,'&lt;')}</text><text x="40" y="700" fill="#fff" opacity=".7" font-family="Segoe UI, sans-serif" font-size="24">${kind}</text></svg>`;
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
};
GAMES0.forEach((g, i) => {
  if (!g.media) {
    g.media = { Covers: mockMedia(g.title || g.file, "COVER", i), Miximages: mockMedia(g.title || g.file, "MIXIMAGE", i + 1), Screenshots: mockMedia(g.title || g.file, "SCREENSHOT", i + 2), Wheel: mockMedia(g.title || g.file, "WHEEL", i + 3) };
  }
});

const STATUS_META = {
  "완료": { color: () => C.success, label: () => "Normal" },
  "부분": { color: () => C.warning, label: () => "Partial" },
  "누락": { color: () => C.danger, label: () => "Missing" },
};
const STATUS_FILTERS = [
  { key: "normal", label: "Normal", icon: CheckCircle2 },
  { key: "partial", label: "Partial", icon: AlertTriangle },
  { key: "missingRom", label: "Missing ROM", icon: FileWarning },
  { key: "missingMedia", label: "Missing Media", icon: ImageOff },
  { key: "duplicate", label: "Duplicate ROM", icon: CopyIcon },
];

const AUTO_HIDE_MS = 5000;
const fs = (px) => `calc(${px}px * var(--font-scale, 1))`;
// [수정] Region/Genre는 내용이 길어서(예: "USA (NTSC)", "Stealth Action") Status와 같은 52px로는
// 잘려 보였음 -> 두 컬럼만 78px로 넓힘. Rating/Status는 짧은 값이라 52px 유지.
const DEFAULT_COL_WIDTHS = { file: 180, title: 207, desc: 480, region: 78, rating: 52, genre: 78, status: 52 };
const COL_MIN_WIDTH = 60;
const NO_COL_WIDTH = 40;
const APP_HEIGHT = 720;

function useIsMobile(bp = 1024) {
  const [m, setM] = useState(false);
  useEffect(() => {
    const c = () => setM(window.innerWidth < bp);
    c(); window.addEventListener("resize", c);
    return () => window.removeEventListener("resize", c);
  }, [bp]);
  return m;
}
function gameMatchesStatusFilter(g, selected) {
  if (selected.has("all")) return true;
  let ok = false;
  if (selected.has("normal") && g.status === "완료") ok = true;
  if (selected.has("partial") && g.status === "부분") ok = true;
  if (selected.has("missingRom") && g.status === "누락") ok = true;
  if (selected.has("missingMedia") && g.missingMedia) ok = true;
  if (selected.has("duplicate") && g.duplicate) ok = true;
  return ok;
}
function computeSystemStats(games) {
  const map = {};
  games.forEach((g) => {
    const s = map[g.system] || { system: g.system, romCount: 0, romMB: 0, mediaCount: 0, mediaMB: 0, videoCount: 0, videoMB: 0, missing: 0 };
    s.romCount += 1; s.romMB += 6 + (g.file.length % 14);
    if (!g.missingMedia && g.status !== "누락") { s.mediaCount += 1; s.mediaMB += 0.6; }
    if (!g.missingMedia && g.status === "완료") { s.videoCount += 1; s.videoMB += 14; }
    if (g.status === "누락" || g.missingMedia) s.missing += 1;
    map[g.system] = s;
  });
  return Object.values(map);
}
const fmtMB = (mb) => (mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${mb.toFixed(0)} MB`);

function useColumnResize(initial) {
  const [widths, setWidths] = useState(initial);
  const dragRef = useRef(null);
  useEffect(() => {
    function onMove(e) {
      if (!dragRef.current) return;
      const { key, startX, startWidth } = dragRef.current;
      setWidths((w) => ({ ...w, [key]: Math.max(COL_MIN_WIDTH, startWidth + (e.clientX - startX)) }));
    }
    function onUp() { dragRef.current = null; document.body.style.cursor = ""; }
    window.addEventListener("mousemove", onMove); window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, []);
  function startDrag(key, e) {
    dragRef.current = { key, startX: e.clientX, startWidth: widths[key] };
    document.body.style.cursor = "col-resize"; e.preventDefault(); e.stopPropagation();
  }
  return [widths, startDrag];
}

function StatusDot({ status, isEmpty }) {
  if (isEmpty) return <span style={{ color: C.listMuted, fontSize: fs(11.5) }}>-</span>;
  const meta = STATUS_META[status] || { color: () => C.muted, label: () => status };
  const Icon = status === "완료" ? CheckCircle2 : status === "부분" ? AlertTriangle : XCircle;
  return <Icon size={14} strokeWidth={2.4} aria-label={meta.label()} title={meta.label()} style={{ color: meta.color() }} />;
}
function Toast({ toast }) {
  if (!toast) return null;
  const color = toast.type === "error" ? C.danger : toast.type === "warning" ? C.warning : C.success;
  return (
    <div className="absolute left-1/2 z-40 rounded-lg shadow-2xl" style={{ bottom: 16, transform: "translateX(-50%)", backgroundColor: C.card3, border: `1px solid ${color}`, padding: "9px 16px", maxWidth: "80%" }}>
      <span style={{ color: C.text, fontSize: fs(12.5) }}>{toast.msg}</span>
    </div>
  );
}
function ConfirmDialog({ open, title, message, danger, confirmLabel = "확인", onConfirm, onCancel }) {
  if (!open) return null;
  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center" style={{ backgroundColor: "rgba(0,0,0,0.55)" }} onClick={onCancel}>
      <div onClick={(e) => e.stopPropagation()} className="rounded-xl shadow-2xl" style={{ backgroundColor: C.card, border: `1px solid ${C.border}`, width: 340, padding: 18 }}>
        <div className="flex items-center gap-2 mb-2">
          <TriangleAlert size={16} style={{ color: danger ? C.danger : C.warning }} />
          <span className="font-semibold" style={{ color: C.text, fontSize: fs(13.5) }}>{title}</span>
        </div>
        <p style={{ color: C.muted, fontSize: fs(12), lineHeight: 1.5 }}>{message}</p>
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onCancel} className="rounded-lg" style={{ backgroundColor: C.card2, color: C.text, fontSize: fs(12), padding: "6px 12px" }}>취소</button>
          <button onClick={onConfirm} className="rounded-lg font-medium" style={{ backgroundColor: danger ? C.danger : C.accent, color: "#fff", fontSize: fs(12), padding: "6px 12px" }}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
function PathPromptModal({ title, initial, onSubmit, onCancel }) {
  const [value, setValue] = useState(initial || "");
  const ref = useRef(null);
  useEffect(() => { setTimeout(() => { ref.current?.focus(); ref.current?.select(); }, 50); }, []);
  return (
    <div className="absolute inset-0 flex items-center justify-center" style={{ backgroundColor: "rgba(0,0,0,0.6)", zIndex: 60 }} onClick={onCancel}>
      <div onClick={(e) => e.stopPropagation()} className="rounded-xl shadow-2xl" style={{ backgroundColor: C.card, border: `1px solid ${C.border}`, width: 380, padding: 16 }}>
        <div className="font-semibold mb-1" style={{ fontSize: fs(12.5), color: C.text }}>{title}</div>
        {/* 브라우저 미리보기라 진짜 OS 폴더 선택창을 띄울 수 없어 대신 경로를 직접 입력받는다.
            실제 Windows 앱(pywebview)에서는 이 자리에 진짜 탐색기 창이 열린다. */}
        <div className="mb-2" style={{ fontSize: fs(10), color: C.muted, lineHeight: 1.4 }}>
          ※ 이건 브라우저 미리보기용 임시 입력창입니다. 실제 Windows 앱에서는 진짜 폴더 탐색기가 열립니다.
        </div>
        <input ref={ref} value={value} onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") onSubmit(value); if (e.key === "Escape") onCancel(); }}
          placeholder="D:\Roms\..." className="w-full rounded-md px-2.5 py-1.5 outline-none mb-3" style={{ fontSize: fs(12.5) }}
          style={{ backgroundColor: C.card2, border: `1px solid ${C.border}`, color: C.text }} />
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="rounded-lg" style={{ backgroundColor: C.card2, color: C.text, fontSize: fs(12), padding: "6px 12px" }}>취소</button>
          <button onClick={() => onSubmit(value)} className="rounded-lg font-medium" style={{ backgroundColor: C.accent, color: "#fff", fontSize: fs(12), padding: "6px 12px" }}>확인</button>
        </div>
      </div>
    </div>
  );
}
function FolderPickButton({ onPick, disabled, label }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" disabled={disabled} onClick={() => !disabled && setOpen(true)} title={label}
        className="rounded-md px-2.5 transition-opacity" style={{ backgroundColor: C.card2, color: disabled ? C.border : C.muted, opacity: disabled ? 0.5 : 1, cursor: disabled ? "not-allowed" : "pointer" }}>
        <FolderOpen size={13} />
      </button>
      {open && <PathPromptModal title={label} initial="" onSubmit={(value) => { onPick(value); setOpen(false); }} onCancel={() => setOpen(false)} />}
    </>
  );
}
// [BUG FIX] 이전엔 "항상 마운트된 채로 open prop만 토글" + useEffect로 필드를 리셋하는
// 방식이었는데, 부모의 재렌더 타이밍에 따라 "+" 버튼을 눌러도 반응이 없는 것처럼 보이는
// 문제가 있었다. 이제 addLocalOpen이 true일 때만 이 컴포넌트 자체를 마운트하는 방식으로
// 바꿔서, useState 초기값이 항상 새로 적용되고 별도의 리셋 useEffect도 필요 없게 했다.
function AddLocalModal({ onClose, onAdd, defaultLabel }) {
  const [label, setLabel] = useState("");
  const [frontend, setFrontend] = useState(FRONTENDS[0]);
  const [romPath, setRomPath] = useState("");
  const [metaPath, setMetaPath] = useState("");
  const [error, setError] = useState("");
  const sameDir = SAME_DIR_FRONTENDS.has(frontend);
  const isEsStyle = ES_STYLE_FRONTENDS.has(frontend);
  useEffect(() => { if (sameDir) setMetaPath(romPath); }, [romPath, sameDir]);
  const inputStyle = { backgroundColor: C.card2, border: `1px solid ${C.border}`, color: C.text, fontSize: fs(12.5) };
  const metaLabel = isEsStyle ? "gamelist / downloaded_media 경로" : "Metadata / Media 경로";
  const metaHint = isEsStyle ? `예: ${frontend}\\${frontend}` : sameDir ? "ROM 경로와 동일" : "";
  function handleSubmit() {
    // [요청 반영] 이름을 안 넣으면 에러 대신 placeholder(LOCAL N)를 그대로 이름으로 사용한다.
    const finalLabel = label.trim() || defaultLabel;
    if (!romPath.trim()) { setError("ROM 경로를 지정해주세요."); return; }
    if (!sameDir && !metaPath.trim()) { setError(`${metaLabel}를 지정해주세요.`); return; }
    setError("");
    onAdd({ label: finalLabel, frontend, romPath, metaPath: sameDir ? romPath : metaPath });
  }
  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center" style={{ backgroundColor: "rgba(0,0,0,0.55)" }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="rounded-xl shadow-2xl flex flex-col gap-3" style={{ backgroundColor: C.card, border: `1px solid ${C.border}`, width: 400, padding: 18, maxHeight: "85%", overflowY: "auto" }}>
        <span className="font-semibold" style={{ color: C.text, fontSize: fs(14) }}>Local 추가</span>
        <div><div className="uppercase tracking-wide mb-1" style={{ fontSize: fs(10), color: C.muted }}>Local 이름</div>
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={defaultLabel} className="w-full rounded-md px-2.5 py-1.5 outline-none" style={{ ...inputStyle, color: C.text }} /></div>
        <div><div className="uppercase tracking-wide mb-1" style={{ fontSize: fs(10), color: C.muted }}>Frontend</div>
          <select value={frontend} onChange={(e) => setFrontend(e.target.value)} className="w-full rounded-md px-2.5 py-1.5 outline-none" style={inputStyle}>
            {FRONTENDS.map((f) => <option key={f}>{f}</option>)}
          </select></div>
        <div><div className="uppercase tracking-wide mb-1" style={{ fontSize: fs(10), color: C.muted }}>ROM 경로</div>
          <div className="flex gap-1.5"><input value={romPath} onChange={(e) => setRomPath(e.target.value)} placeholder="D:\Roms\..." className="flex-1 rounded-md px-2.5 py-1.5 outline-none" style={inputStyle} />
          <FolderPickButton onPick={setRomPath} label="ROM 경로 입력" /></div></div>
        <div><div className="uppercase tracking-wide mb-1" style={{ fontSize: fs(10), color: C.muted }}>{metaLabel}</div>
          {metaHint && <div className="mb-1" style={{ fontSize: fs(10), color: C.muted }}>{metaHint}</div>}
          <div className="flex gap-1.5"><input value={metaPath} disabled={sameDir} onChange={(e) => setMetaPath(e.target.value)} placeholder="D:\Roms\..." className="flex-1 rounded-md px-2.5 py-1.5 outline-none" style={{ ...inputStyle, opacity: sameDir ? 0.55 : 1 }} />
          <FolderPickButton onPick={setMetaPath} disabled={sameDir} label={metaLabel + " 입력"} /></div></div>
        {error && <div className="rounded-md px-2.5 py-2" style={{ fontSize: fs(11.5), backgroundColor: C.danger + "1A", color: C.danger }}>{error}</div>}
        <div className="flex justify-end gap-2 mt-1">
          <button onClick={onClose} className="rounded-lg" style={{ backgroundColor: C.card2, color: C.text, fontSize: fs(12), padding: "7px 14px" }}>취소</button>
          <button onClick={handleSubmit} className="rounded-lg font-medium" style={{ backgroundColor: C.accent, color: "#fff", fontSize: fs(12), padding: "7px 14px" }}>등록</button>
        </div>
      </div>
    </div>
  );
}

function NavItem({ icon: Icon, label, active, indent, small, onClick, dot, branch }) {
  const [hover, setHover] = useState(false);
  return (
    <button onClick={onClick} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      className={`w-full flex items-center gap-2.5 rounded-lg text-left transition-colors duration-150 ${indent ? "py-1.5 px-2.5 ml-3" : "py-2 px-3"}`}
      style={{ backgroundColor: active ? C.card3 : hover ? C.card2 : "transparent", color: active ? C.text : C.muted, boxShadow: active ? `inset 2px 0 0 ${C.accent}` : "inset 2px 0 0 transparent" }}>
      {dot && <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: dot }} />}
      {branch && <span className="shrink-0" style={{ color: C.border, fontSize: 11, marginLeft: 1 }}>└</span>}
      {Icon && <Icon size={indent ? 13 : 16} strokeWidth={2} className="shrink-0" />}
      <span className={`truncate ${small ? "" : "font-medium"}`} style={{ fontSize: fs(small ? 12 : 13) }}>{label}</span>
    </button>
  );
}

// [원본 그대로 재현] TopCard/MasterCard 함수는 정의돼 있지만 아래 App 컴포넌트의
// 최종 return 어디에서도 호출되지 않아 실제로는 렌더링되지 않습니다.
function TopCard({ local, active, onClick, compact }) {
  const [hover, setHover] = useState(false);
  const cardFs = compact ? 10 : 11;
  return (
    <button onClick={onClick} className="text-left rounded-xl transition-all duration-150 shrink-0"
      style={{ background: active ? `linear-gradient(135deg, ${C.card3}, ${C.card})` : C.card, border: `1.5px solid ${active ? C.accent : hover ? C.muted : C.border}`,
        boxShadow: active ? `0 0 0 3px ${C.accent}20, 0 8px 20px #00000022` : hover ? "0 5px 14px #00000018" : "none",
        transform: hover ? "translateY(-1px)" : "translateY(0)", padding: compact ? "7px 10px" : "9px 12px", minWidth: compact ? 130 : 170 }}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <div className="flex items-center gap-1.5 mb-1"><HardDrive size={compact ? 11 : 13} style={{ color: C.text }} />
        <span className="font-semibold truncate" style={{ color: C.text, fontSize: fs(cardFs) }}>{local.label} ({local.frontend})</span></div>
      <div className="truncate" style={{ color: C.muted, fontSize: fs(cardFs - 1) }}>{local.romCount.toLocaleString()} ROMs · {local.sizeGB} GB</div>
    </button>
  );
}
function MasterCard({ active, onClick, compact }) {
  const [hover, setHover] = useState(false);
  return (
    <button onClick={onClick} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      className="text-left rounded-xl transition-all duration-150 shrink-0"
      style={{ background: active ? `linear-gradient(135deg, ${C.card3}, ${C.card})` : C.card, border: `1.5px solid ${active ? C.accent : hover ? C.muted : C.border}`,
        boxShadow: active ? `0 0 0 3px ${C.accent}20, 0 8px 20px #00000022` : hover ? "0 5px 14px #00000018" : "none",
        transform: hover ? "translateY(-1px)" : "translateY(0)", padding: compact ? "7px 10px" : "9px 12px", minWidth: compact ? 130 : 170 }}>
      <div className="flex items-center gap-1.5 mb-1"><Database size={compact ? 11 : 13} style={{ color: C.text }} />
        <span className="font-semibold truncate" style={{ color: C.text, fontSize: compact ? 10 : 11 }}>MasterDB</span></div>
      <div className="truncate" style={{ color: C.muted, fontSize: compact ? 9 : 10 }}>{MASTERDB.romCount.toLocaleString()} ROMs · {MASTERDB.sizeGB} GB</div>
    </button>
  );
}

function IconButton({ icon: Icon, label, onClick, primary, compact, light }) {
  const [hover, setHover] = useState(false);
  const bg = light ? (hover ? C.card3 : C.card2) : primary ? (hover ? C.accentHover : C.accent) : hover ? C.card3 : C.card2;
  const fg = light ? C.text : primary ? "#fff" : C.text;
  return (
    <button onClick={onClick} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      className="inline-flex items-center gap-1.5 rounded-lg font-medium transition-colors duration-150 shrink-0"
      style={{ backgroundColor: bg, color: fg, padding: compact ? "6px" : "6px 10px", fontSize: fs(11.5) }}>
      <Icon size={12.5} />{!compact && label}
    </button>
  );
}
function FieldGroup({ icon: Icon, label, value, inputRef }) {
  return (
    <div>
      <div className="flex items-center gap-1 mb-0.5" style={{ fontSize: fs(8), color: C.muted }}><Icon size={8} /><span className="uppercase tracking-wide">{label}</span></div>
      <input ref={inputRef} defaultValue={value} className="w-full rounded-md px-1.5 py-0.5 outline-none focus:ring-2" style={{ fontSize: fs(10.5), backgroundColor: C.card2, border: `1px solid ${C.border}`, color: C.text }} />
    </div>
  );
}
function Dropdown({ buttonIcon: BIcon, buttonLabel, children, width = 200 }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((v) => !v)} className="inline-flex items-center gap-1.5 rounded-lg font-medium transition-colors duration-150"
        style={{ backgroundColor: C.card2, color: C.text, padding: "6px 10px", fontSize: fs(11.5), border: `1px solid ${C.border}` }}>
        <BIcon size={12.5} />{buttonLabel}<ChevronDown size={12} style={{ color: C.muted }} />
      </button>
      {open && <div className="absolute z-30 mt-1.5 rounded-lg overflow-hidden shadow-xl" style={{ backgroundColor: C.card2, border: `1px solid ${C.border}`, minWidth: width, maxHeight: 260, overflowY: "auto" }}>
        {children(() => setOpen(false))}
      </div>}
    </div>
  );
}

function GameListCard({ games, selectedGame, panelOpen, onRowClick, onSelectAdjacent, sortField, sortDir, onSort, compact, onRefresh, onCleanup, onPrune, onExport, viewMode }) {
  const cols = [
    { key: null, label: t("colNo") }, { key: "file", label: t("colFile") }, { key: "title", label: t("colTitle") },
    { key: "desc", label: t("colDesc") }, { key: "region", label: t("colRegion") }, { key: "rating", label: t("colRating") },
    { key: "genre", label: t("colGenre") }, { key: "status", label: t("colStatus") },
  ];
  const rowH = compact ? 31 : 33;
  const listFs = compact ? 9.5 : 10;
  const [colWidths, startDrag] = useColumnResize(DEFAULT_COL_WIDTHS);
  const gridTemplate = `${NO_COL_WIDTH}px ${colWidths.file}px ${colWidths.title}px ${colWidths.desc}px ${colWidths.region}px ${colWidths.rating}px ${colWidths.genre}px ${colWidths.status}px`;
  const gridMinWidth = NO_COL_WIDTH + colWidths.file + colWidths.title + colWidths.desc + colWidths.region + colWidths.rating + colWidths.genre + colWidths.status;

  function handleListKeyDown(e) {
    if (!games.length) return;
    const currentIndex = selectedGame ? games.findIndex((g) => g.id === selectedGame.id) : -1;
    let nextIndex = currentIndex;
    if (e.key === "ArrowDown") nextIndex = Math.min(games.length - 1, currentIndex < 0 ? 0 : currentIndex + 1);
    else if (e.key === "ArrowUp") nextIndex = Math.max(0, currentIndex < 0 ? 0 : currentIndex - 1);
    else if (e.key === "PageDown") nextIndex = Math.min(games.length - 1, Math.max(0, currentIndex) + Math.max(1, Math.floor(games.length / 10)));
    else if (e.key === "PageUp") nextIndex = Math.max(0, Math.max(0, currentIndex) - Math.max(1, Math.floor(games.length / 10)));
    else if (e.key === "Home") nextIndex = 0;
    else if (e.key === "End") nextIndex = games.length - 1;
    else if (e.key === "Enter" && selectedGame) { onRowClick(selectedGame); e.preventDefault(); return; }
    else return;
    e.preventDefault();
    onSelectAdjacent(games[nextIndex]);
  }

  return (
    <div tabIndex={0} onKeyDown={handleListKeyDown} className="h-full min-h-0 rounded-xl overflow-hidden flex flex-col outline-none"
      style={{ backgroundColor: C.listBg, border: `1px solid ${C.listBorder}`, boxShadow: "0 14px 32px #05071426" }}>
      {viewMode === "preview" ? (
        <div className="flex-1 min-h-0 overflow-y-auto p-3">
          <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${compact ? 92 : 116}px, 1fr))` }}>
            {games.map((g) => {
              const selected = selectedGame?.id === g.id;
              const cover = g.media && g.media.Covers;
              return (
                <button key={g.id} onClick={() => onRowClick(g)} className="flex flex-col rounded-lg overflow-hidden text-left transition-colors"
                  style={{ border: `2px solid ${selected ? C.accent : "transparent"}`, backgroundColor: C.listHead }}>
                  <div style={{ width: "100%", aspectRatio: "3 / 4", backgroundColor: C.listBorder, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden" }}>
                    {cover ? <img src={cover} alt={g.title || g.file} className="w-full h-full object-cover" /> : <ImageIcon size={compact ? 20 : 26} style={{ color: C.listMuted }} />}
                  </div>
                  <div className="px-1.5 py-1.5" style={{ backgroundColor: C.listBg }}>
                    <div className="truncate text-center" style={{ fontSize: compact ? 9.5 : 10.5, color: C.listText }}>{g.title || g.file}</div>
                  </div>
                </button>
              );
            })}
          </div>
          {games.length === 0 && <div className="text-center py-10" style={{ color: C.listMuted, fontSize: fs(12) }}>조건에 맞는 게임이 없습니다.</div>}
        </div>
      ) : (
        <div className="flex-1 min-h-0 overflow-auto">
          <div style={{ minWidth: gridMinWidth }}>
            <div className="grid sticky top-0 z-10" style={{ gridTemplateColumns: gridTemplate, backgroundColor: C.listHead, borderBottom: `1px solid ${C.listBorder}` }}>
              {cols.map((c) => (
                <div key={c.label} onClick={() => c.key && onSort(c.key)}
                  style={{ position: "relative", padding: "7px 9px", fontSize: fs(9.5), fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em", color: sortField === c.key ? C.listText : C.listMuted, cursor: c.key ? "pointer" : "default", whiteSpace: "nowrap", overflow: "hidden", userSelect: "none", display: "flex", alignItems: "center", gap: 3 }}>
                  {c.label}{sortField === c.key && (sortDir === "asc" ? <ChevronUp size={11} /> : <ChevronDown size={11} />)}
                  {c.key && <div onMouseDown={(e) => startDrag(c.key, e)} title="드래그해서 폭 조절"
                    style={{ position: "absolute", right: -3, top: 0, bottom: 0, width: 7, cursor: "col-resize", zIndex: 5 }}
                    onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = C.accent + "40"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "transparent"; }}
                    onClick={(e) => e.stopPropagation()} />}
                </div>
              ))}
            </div>
            {games.map((g, i) => {
              const selected = selectedGame?.id === g.id;
              const cellBase = { padding: `0 9px`, fontSize: fs(listFs), whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", display: "flex", alignItems: "center", height: rowH };
              const descCell = { ...cellBase, whiteSpace: "nowrap", textOverflow: "ellipsis", display: "flex", alignItems: "center" };
              return (
                <div key={g.id} onClick={() => onRowClick(g)} className="grid cursor-pointer"
                  style={{ gridTemplateColumns: gridTemplate, backgroundColor: selected ? C.listSelected : C.listBg, borderBottom: `1px solid ${C.listRowBorder}` }}
                  onMouseEnter={(e) => { if (!selected) e.currentTarget.style.backgroundColor = C.listHead; }}
                  onMouseLeave={(e) => { if (!selected) e.currentTarget.style.backgroundColor = C.listBg; }}>
                  <div style={{ ...cellBase, color: C.listMuted }}>{i + 1}</div>
                  <div style={{ ...cellBase, color: C.listText }}>{g.file}</div>
                  <div style={{ ...cellBase, color: C.listText, fontWeight: 500 }}>{g.title || "-"}</div>
                  <div style={{ ...descCell, color: C.listMuted }}>{g.desc || "-"}</div>
                  <div style={{ ...cellBase, color: C.listMuted }}>{g.region || "-"}</div>
                  <div style={{ ...cellBase, color: C.listMuted }}>{g.rating || "-"}</div>
                  <div style={{ ...cellBase, color: C.listMuted }}>{g.genre || "-"}</div>
                  <div style={cellBase}><StatusDot status={g.status} isEmpty={!g.title && !g.desc} /></div>
                </div>
              );
            })}
            {games.length === 0 && <div className="text-center py-10" style={{ color: C.listMuted, fontSize: fs(12) }}>조건에 맞는 게임이 없습니다.</div>}
          </div>
        </div>
      )}
      <div className="shrink-0" style={{ borderTop: `1px solid ${C.listBorder}` }}>
        <div style={{ padding: "6px 12px", fontSize: fs(11), color: C.listMuted, borderBottom: `1px solid ${C.listBorder}` }}>
          전체 {games.length.toLocaleString()}개　|　선택 {selectedGame && panelOpen ? 1 : 0}개
        </div>
        <div className="flex items-center justify-between flex-wrap gap-2" style={{ padding: "8px 12px" }}>
          <div className="flex items-center gap-2 flex-wrap">
            <IconButton icon={RefreshCw} label={t("refreshList")} light onClick={onRefresh} />
            <IconButton icon={Sparkles} label={t("cleanup")} light onClick={onCleanup} />
            <IconButton icon={Eraser} label={t("pruneData")} light onClick={onPrune} />
            <IconButton icon={Upload} label={t("exportMasterDB")} light onClick={onExport} />
          </div>
          <div className="flex items-center gap-3" style={{ fontSize: fs(11), color: C.listMuted }}>
            <span>Ready</span>
            <span className="inline-flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: C.success }} />총 {games.length.toLocaleString()}개 게임</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function FieldSummary({ label, value }) {
  // [수정] 대표 이미지(72x92)와 높이가 맞도록 폰트를 다시 키움 (직전엔 너무 작아 정렬이 안 맞았음)
  return <div className="min-w-0"><div style={{ color: C.muted, fontSize: fs(9), textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div><div className="truncate font-medium" style={{ color: C.text, fontSize: fs(11) }}>{value}</div></div>;
}

function DetailPanel({ game, pinned, onTogglePin, onClose, onSaveGame, showToast, showPin = true }) {
  // Deliberately keep tab/media selection alive while the selected game changes.
  // This enables a pinned "Screenshots only" workflow with ArrowUp/ArrowDown.
  const [tab, setTab] = useState("metadata");
  const [mediaType, setMediaType] = useState("Covers");
  const [versions, setVersions] = useState([]);
  const [activeIdx, setActiveIdx] = useState(0);
  const [defaultIdx, setDefaultIdx] = useState(0);
  const [pendingMedia, setPendingMedia] = useState({});
  const fileInputRef = useRef(null);
  const nameRef = useRef(null), descRef = useRef(null);
  const genreRef = useRef(null), devRef = useRef(null), pubRef = useRef(null), relRef = useRef(null), regRef = useRef(null), plyRef = useRef(null), ratRef = useRef(null);

  const mediaSlots = [
    { key: "Covers", label: "Cover", hint: "대표 커버" },
    { key: "Screenshots", label: "Screenshot", hint: "게임 화면" },
    { key: "Miximages", label: "Miximage", hint: "혼합 이미지" },
    { key: "Marquees", label: "Marquee", hint: "가로 배너" },
    { key: "Wheel", label: "Wheel", hint: "휠 아트" },
    { key: "Videos", label: "Video", hint: "게임 영상" },
  ];

  useEffect(() => {
    if (!game) return;
    setVersions([{ id: "v1", source: game.local ? "Local" : "MasterDB", fields: { name: game.title, desc: game.desc, genre: game.genre, developer: game.developer, publisher: game.publisher, release: game.release, region: game.region, players: game.players, rating: game.rating } }]);
    setActiveIdx(0); setDefaultIdx(0); setPendingMedia({});
    // tab/mediaType intentionally NOT reset here.
  }, [game?.id]);

  if (!game || versions.length === 0) return null;
  const active = versions[activeIdx];
  const selectedMedia = mediaSlots.find((m) => m.key === mediaType) || mediaSlots[0];

  function readFieldsFromRefs() {
    return {
      name: nameRef.current?.value ?? active.fields.name, desc: descRef.current?.value ?? active.fields.desc,
      genre: genreRef.current?.value ?? active.fields.genre, developer: devRef.current?.value ?? active.fields.developer,
      publisher: pubRef.current?.value ?? active.fields.publisher, release: relRef.current?.value ?? active.fields.release,
      region: regRef.current?.value ?? active.fields.region, players: plyRef.current?.value ?? active.fields.players,
      rating: ratRef.current?.value ?? active.fields.rating,
    };
  }
  function handleSave() {
    const fields = readFieldsFromRefs();
    setVersions((prev) => prev.map((v, i) => (i === activeIdx ? { ...v, fields } : v)));
    const hasMediaChanges = Object.keys(pendingMedia).length > 0;
    if (activeIdx === defaultIdx) onSaveGame(game.id, fields, hasMediaChanges ? pendingMedia : undefined);
    if (hasMediaChanges) setPendingMedia({});
    showToast(hasMediaChanges ? "저장 완료 · Media 반영" : "저장 완료");
  }
  function handleClone() {
    const fields = readFieldsFromRefs();
    setVersions((prev) => [...prev, { id: "v" + (prev.length + 1), source: "복제됨", fields: { ...fields } }]);
    setActiveIdx(versions.length);
    showToast("버전이 복제되었습니다.");
  }
  function handleSetDefault() {
    setDefaultIdx(activeIdx);
    onSaveGame(game.id, versions[activeIdx].fields);
    showToast("기본 버전으로 설정되었습니다.");
  }
  function handleDeleteVersion() {
    if (versions.length <= 1) { showToast("최소 1개의 Version은 유지되어야 합니다.", "warning"); return; }
    const removedIdx = activeIdx;
    const next = versions.filter((_, i) => i !== removedIdx);
    setVersions(next);
    setActiveIdx(Math.max(0, removedIdx - 1));
    if (defaultIdx === removedIdx) { setDefaultIdx(0); onSaveGame(game.id, next[0].fields); }
    else if (defaultIdx > removedIdx) setDefaultIdx(defaultIdx - 1);
    showToast("버전이 삭제되었습니다.", "warning");
  }
  function handleMediaFile(mt, file) {
    if (!file) return;
    const isVideo = mt === "Videos";
    const valid = isVideo ? file.type.startsWith("video/") : file.type.startsWith("image/");
    if (!valid) { showToast(isVideo ? "영상 파일만 지원됩니다." : "이미지 파일만 지원됩니다.", "warning"); return; }
    const url = URL.createObjectURL(file);
    setPendingMedia((p) => ({ ...p, [mt]: url }));
    showToast(`${selectedMedia.label}이(가) 임시 적용되었습니다. 저장하세요.`, "warning");
  }
  function chooseMedia() {
    if (fileInputRef.current) fileInputRef.current.click();
  }

  const currentMediaUrl = pendingMedia[mediaType] || (game.media && game.media[mediaType]);
  const hasCurrentMedia = !!currentMediaUrl;
  const isPending = !!pendingMedia[mediaType];

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-1.5 px-2.5 pt-2 pb-1.5 shrink-0" style={{ borderBottom: `1px solid ${C.border}` }}>
        <div className="min-w-0 flex-1">
          <div className="font-bold" style={{ color: C.accent, fontSize: fs(8.5), letterSpacing: "0.12em" }}>DETAIL</div>
          <div className="truncate mt-0.5" style={{ color: C.text, fontSize: fs(10), fontWeight: 600 }}>{game.file}</div>
        </div>
        {pinned && <span className="rounded-full px-1.5 py-0.5 font-bold tracking-wide" style={{ backgroundColor: C.accent + "2B", color: C.accentHover, fontSize: fs(8.5) }}>PINNED</span>}
        {showPin && <button onClick={onTogglePin} className="p-1.5 rounded-md transition-colors" style={{ backgroundColor: pinned ? C.accent : C.card2, color: pinned ? "#fff" : C.muted }} title={pinned ? "상세 패널 고정 해제" : "상세 패널 고정"} aria-label="Pin detail panel">
          {pinned ? <Pin size={13} /> : <PinOff size={13} />}
        </button>}
        <button onClick={onClose} className="p-1.5 rounded-md" style={{ color: C.muted }} title="닫기"><X size={14} /></button>
      </div>

      <div className="flex px-2.5 gap-1 shrink-0" style={{ borderBottom: `1px solid ${C.border}` }}>
        {["metadata", "media"].map((tb) => (
          <button key={tb} onClick={() => setTab(tb)} className="font-medium px-3 py-1.5 transition-colors" style={{ backgroundColor: tab === tb ? C.card2 : "transparent", color: tab === tb ? C.text : C.muted, fontSize: fs(10), borderBottom: `2px solid ${tab === tb ? C.accent : "transparent"}` }}>
            {tb === "metadata" ? "Metadata" : "Media"}
          </button>
        ))}
      </div>

      {tab === "metadata" ? (
        <div className="flex-1 min-h-0 overflow-y-auto px-2.5 pt-2 pb-2" style={{ backgroundColor: C.card2 }}>
          {/* Compact identity summary belongs inside Metadata, not above the tabs. */}
          <div className="rounded-lg p-2 mb-2.5" style={{ backgroundColor: C.card3, border: `1px solid ${C.border}` }}>
            <div className="flex gap-2.5">
              <div className="shrink-0 rounded-md overflow-hidden flex items-center justify-center" style={{ width: 72, height: 92, backgroundColor: C.listBorder }}>
                {(game.media && game.media.Covers) ? <img src={game.media.Covers} alt="" className="w-full h-full object-cover" /> : <ImageIcon size={17} style={{ color: C.muted }} />}
              </div>
              <div className="min-w-0 flex-1 grid grid-cols-2 gap-x-3 gap-y-2.5 content-start">
                <FieldSummary label="Genre" value={game.genre || "-"} />
                <FieldSummary label="Release" value={game.release || "-"} />
                <FieldSummary label="Players" value={game.players || "-"} />
                <FieldSummary label="Region" value={game.region || "-"} />
                <FieldSummary label="Developer" value={game.developer || "-"} />
                <FieldSummary label="Publisher" value={game.publisher || "-"} />
              </div>
            </div>
          </div>

          <div className="uppercase tracking-wide mb-1" style={{ fontSize: fs(10), color: C.muted }}>Title</div>
          <input key={game.id + "-" + active.id + "-name"} ref={nameRef} defaultValue={active.fields.name} className="w-full rounded-md px-2 py-1 font-semibold outline-none mb-2" style={{ fontSize: fs(10.5), backgroundColor: C.card3, border: `1px solid ${C.border}`, color: C.text }} />
          <div className="uppercase tracking-wide mb-1" style={{ fontSize: fs(10), color: C.muted }}>Description</div>
          <textarea key={game.id + "-" + active.id + "-desc"} ref={descRef} defaultValue={active.fields.desc} rows={7} className="w-full rounded-md px-2 py-1 outline-none mb-2.5 resize-none" style={{ fontSize: fs(9.5), backgroundColor: C.card3, border: `1px solid ${C.border}`, color: C.text, lineHeight: 1.35 }} />

          <div className="grid grid-cols-2 gap-x-2 gap-y-1 mb-1.5" key={game.id + "-" + active.id + "-grid"}>
            <FieldGroup icon={Tag} label="Genre" value={active.fields.genre} inputRef={genreRef} />
            <FieldGroup icon={Building2} label="Developer" value={active.fields.developer} inputRef={devRef} />
            <FieldGroup icon={Building2} label="Publisher" value={active.fields.publisher} inputRef={pubRef} />
            <FieldGroup icon={Calendar} label="Release" value={active.fields.release} inputRef={relRef} />
            <FieldGroup icon={Globe} label="Region" value={active.fields.region} inputRef={regRef} />
            <FieldGroup icon={Users} label="Players" value={active.fields.players} inputRef={plyRef} />
            <FieldGroup icon={Star} label="Rating" value={active.fields.rating} inputRef={ratRef} />
          </div>
          <div className="flex items-center gap-2 mb-1">
            <div className="uppercase tracking-wide" style={{ fontSize: fs(10), color: C.muted }}>Version</div>
            <div className="flex gap-1.5 flex-wrap">
              <IconButton icon={Copy} label="복제" compact onClick={handleClone} />
              <IconButton icon={CheckCircle2} label="기본값" compact onClick={handleSetDefault} />
              <IconButton icon={Trash2} label="삭제" compact onClick={handleDeleteVersion} />
            </div>
          </div>
          <select value={activeIdx} onChange={(e) => setActiveIdx(Number(e.target.value))} className="w-full rounded-md px-2 py-1 outline-none" style={{ fontSize: fs(11), backgroundColor: C.card3, border: `1px solid ${C.border}`, color: C.text }}>
            {versions.map((v, i) => <option key={v.id} value={i}>v{i + 1}{i === defaultIdx ? " (Default)" : ""} · {v.source}</option>)}
          </select>
        </div>
      ) : (
        <div className="flex-1 min-h-0 overflow-y-auto px-2.5 pt-2 pb-2" style={{ backgroundColor: C.card2 }}>
          <div className="mb-2">
            <div className="font-semibold mb-1" style={{ color: C.text, fontSize: fs(10.5) }}>Media</div>
          </div>

          {/* [디자인 개선] 라디오 버튼 -> 세그먼트 pill 버튼으로 교체 (선택 시 배경색+텍스트로 강조,
              보유 여부는 우측 작은 점으로 표시) */}
          <div className="grid grid-cols-2 gap-1 mb-2 rounded-lg p-1" style={{ backgroundColor: C.card3, border: `1px solid ${C.border}` }}>
            {mediaSlots.map((mt) => {
              const exists = !!(pendingMedia[mt.key] || (game.media && game.media[mt.key]));
              const active = mediaType === mt.key;
              return (
                <button key={mt.key} onClick={() => setMediaType(mt.key)}
                  className="flex items-center gap-1.5 rounded-md px-2 py-1.5 cursor-pointer transition-colors"
                  style={{ backgroundColor: active ? C.accent : "transparent", color: active ? "#fff" : C.muted, fontWeight: active ? 600 : 400 }}>
                  <span className="truncate flex-1 text-left" style={{ fontSize: fs(9.5) }}>{mt.label}</span>
                  <span className="rounded-full shrink-0" style={{ width: 6, height: 6, backgroundColor: exists ? (active ? "#fff" : C.success) : (active ? "rgba(255,255,255,.35)" : C.border) }} />
                </button>
              );
            })}
          </div>

          <input ref={fileInputRef} type="file" accept={mediaType === "Videos" ? "video/*" : "image/*"} className="hidden" onChange={(e) => { handleMediaFile(mediaType, e.target.files?.[0]); e.target.value = ""; }} />
          <div className="rounded-xl p-2.5" style={{ backgroundColor: C.card3, border: `1px solid ${C.border}` }}>
            <div className="flex items-center justify-between mb-1.5">
              <div>
                <div className="font-semibold" style={{ color: C.text, fontSize: fs(10) }}>{selectedMedia.label}</div>
                <div style={{ color: C.muted, fontSize: fs(8.5) }}>{selectedMedia.hint}</div>
              </div>
              <span className="rounded-full px-1.5 py-0.5" style={{ backgroundColor: isPending ? C.warning + "30" : hasCurrentMedia ? C.success + "22" : C.card2, color: isPending ? C.warning : hasCurrentMedia ? C.success : C.muted, fontSize: fs(8.5) }}>
                {isPending ? "저장 대기" : hasCurrentMedia ? "등록됨" : "없음"}
              </span>
            </div>
            <div className="rounded-lg flex flex-col items-center justify-center relative" style={{ backgroundColor: C.card2, border: `1px dashed ${isPending ? C.warning : C.border}`, minHeight: 225, overflow: "hidden" }}
              onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); handleMediaFile(mediaType, e.dataTransfer.files?.[0]); }}>
              {hasCurrentMedia ? (
                mediaType === "Videos" ? <div className="flex flex-col items-center gap-2"><div style={{ color: C.text, fontSize: fs(11) }}>▶ Video selected</div><div className="truncate max-w-full px-4" style={{ color: C.muted, fontSize: fs(8.5) }}>{isPending ? "새 파일 · 저장 대기" : "기존 미디어"}</div></div> : <img src={currentMediaUrl} alt="" className="max-w-full object-contain" style={{ maxHeight: 210 }} />
              ) : (
                <button onClick={chooseMedia} className="flex flex-col items-center gap-1.5 rounded-lg px-5 py-4" style={{ color: C.muted }} title="파일 선택">
                  <div className="w-10 h-10 rounded-full flex items-center justify-center" style={{ backgroundColor: C.card3, border: `1px solid ${C.border}` }}><Plus size={20} /></div>
                  <span style={{ color: C.text, fontSize: fs(10) }}>파일 없음</span>
                  <span style={{ fontSize: fs(8.5) }}>+ 파일 선택 또는 여기에 드롭</span>
                </button>
              )}
              {hasCurrentMedia && <button onClick={chooseMedia} className="absolute right-2 bottom-2 rounded-md px-2 py-1" style={{ backgroundColor: C.card, border: `1px solid ${C.border}`, color: C.text, fontSize: fs(9) }}>→ 파일 선택</button>}
              {isPending && <div className="absolute left-2 bottom-2 rounded-md px-2 py-1" style={{ backgroundColor: C.warning, color: "#111", fontSize: fs(8.5), fontWeight: 700 }}>저장하면 실제 Media 폴더에 반영</div>}
            </div>
            <div className="text-center mt-1.5" style={{ color: C.muted, fontSize: fs(8.5) }}>파일을 이 영역으로 드래그하면 {selectedMedia.label}로 임시 지정됩니다.</div>
          </div>
        </div>
      )}

      <div className="px-2.5 pb-2.5 pt-1 shrink-0 flex items-center justify-between gap-2" style={{ backgroundColor: C.card2, borderTop: `1px solid ${C.border}` }}>
        <div className="truncate" style={{ color: C.muted, fontSize: fs(8.5) }}>{tab === "media" ? `${selectedMedia.label} · ${hasCurrentMedia ? "등록됨" : "미등록"}` : "변경 사항을 저장하세요"}</div>
        <IconButton icon={Save} label={t("save")} primary onClick={handleSave} />
      </div>
    </div>
  );
}

function MetricCard({ icon: Icon, label, value, color, compact }) {
  return (
    <div className="rounded-xl flex-1" style={{ backgroundColor: C.card, border: `1px solid ${C.border}`, padding: compact ? "10px 12px" : "12px 16px" }}>
      <div className="flex items-center gap-2 mb-1.5"><Icon size={13} style={{ color: color || C.muted }} /><span className="uppercase tracking-wide" style={{ color: C.muted, fontSize: fs(9.5) }}>{label}</span></div>
      <div className="font-semibold" style={{ color: C.text, fontSize: compact ? 16 : 19 }}>{value}</div>
    </div>
  );
}
function SystemStatsTable({ games, compact }) {
  const stats = computeSystemStats(games);
  const tableFs = compact ? 10.5 : 11.5;
  return (
    <div className="rounded-xl overflow-hidden" style={{ backgroundColor: C.card, border: `1px solid ${C.border}` }}>
      <table className="w-full" style={{ fontSize: fs(tableFs) }}>
        <thead><tr style={{ backgroundColor: C.card2 }}>{["System", "전체 용량", "ROM (개수/용량)", "Media (개수/용량)", "Video (개수/용량)", "상태"].map((h) => (
          <th key={h} className="text-left font-semibold uppercase tracking-wide" style={{ color: C.muted, padding: compact ? "6px 8px" : "7px 9px", fontSize: fs(tableFs - 1), borderBottom: `1px solid ${C.border}` }}>{h}</th>
        ))}</tr></thead>
        <tbody>{stats.map((s) => {
          const total = s.romMB + s.mediaMB + s.videoMB, ok = s.missing === 0;
          return (
            <tr key={s.system} style={{ borderBottom: `1px solid ${C.border}` }}>
              <td style={{ padding: compact ? "6px 8px" : "7px 9px", color: C.text, textTransform: "uppercase", fontWeight: 600 }}>{s.system}</td>
              <td style={{ padding: compact ? "6px 8px" : "7px 9px", color: C.text }}>{fmtMB(total)}</td>
              <td style={{ padding: compact ? "6px 8px" : "7px 9px", color: C.muted }}>{s.romCount} / {fmtMB(s.romMB)}</td>
              <td style={{ padding: compact ? "6px 8px" : "7px 9px", color: C.muted }}>{s.mediaCount} / {fmtMB(s.mediaMB)}</td>
              <td style={{ padding: compact ? "6px 8px" : "7px 9px", color: C.muted }}>{s.videoCount} / {fmtMB(s.videoMB)}</td>
              <td style={{ padding: compact ? "6px 8px" : "7px 9px" }}><span className="inline-flex items-center gap-1.5"><span className="rounded-full" style={{ backgroundColor: ok ? C.success : C.warning, width: 7, height: 7 }} /><span style={{ color: C.text }}>{ok ? "정상" : `누락 ${s.missing}`}</span></span></td>
            </tr>
          );
        })}</tbody>
      </table>
    </div>
  );
}
function DashboardView({ locals, games, compact }) {
  const tabs = [...locals.map((l) => ({ key: "local-" + l.id, label: l.label, type: "local", local: l })), { key: "masterdb", label: "MasterDB", type: "masterdb" }];
  const [tab, setTab] = useState(tabs[0]?.key);
  useEffect(() => { if (!tabs.find((tb) => tb.key === tab)) setTab(tabs[0]?.key); }, [locals.length]);
  const current = tabs.find((tb) => tb.key === tab) || tabs[0];
  const scoped = current?.type === "local" ? games.filter((g) => g.local === current.local.id) : games;
  const missingRom = scoped.filter((g) => g.status === "누락").length;
  const missingMedia = scoped.filter((g) => g.missingMedia).length;
  const totalMB = computeSystemStats(scoped).reduce((a, s) => a + s.romMB + s.mediaMB + s.videoMB, 0);
  return (
    <div className="flex-1 min-h-0 overflow-y-auto" style={{ padding: compact ? "12px" : "16px 20px" }}>
      <div className="flex gap-1.5 mb-4 flex-wrap">
        {tabs.map((tb) => <button key={tb.key} onClick={() => setTab(tb.key)} className="rounded-lg font-medium transition-colors" style={{ backgroundColor: tab === tb.key ? C.accent : C.card2, color: tab === tb.key ? "#fff" : C.muted, padding: "6px 12px", fontSize: fs(11.5) }}>{tb.label}</button>)}
      </div>
      <div className="rounded-xl mb-4 p-3" style={{ backgroundColor: C.card, border: `1px solid ${C.border}` }}>
        <div className="flex items-center justify-between mb-2">
          <div><div className="font-semibold" style={{ color: C.text, fontSize: fs(12) }}>Library Health</div><div style={{ color: C.muted, fontSize: fs(9) }}>ROM · Metadata · Media 상태</div></div>
          <div className="font-semibold" style={{ color: C.success, fontSize: fs(17) }}>{Math.max(0, Math.round(((scoped.length - missingRom - missingMedia) / Math.max(1, scoped.length)) * 100))}%</div>
        </div>
        <div className="h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: C.card3 }}><div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.round(((scoped.length - missingRom - missingMedia) / Math.max(1, scoped.length)) * 100))}%`, backgroundColor: C.success }} /></div>
        <div className="grid grid-cols-3 gap-2 mt-2">
          <div style={{ color: C.success, fontSize: fs(9) }}>✓ Complete <b>{Math.max(0, scoped.length - missingRom - missingMedia)}</b></div>
          <div style={{ color: C.warning, fontSize: fs(9) }}>◐ Issues <b>{missingMedia}</b></div>
          <div style={{ color: C.danger, fontSize: fs(9) }}>! Missing <b>{missingRom}</b></div>
        </div>
      </div>
      <div className="flex gap-3 mb-4 flex-wrap">
        <MetricCard icon={Gamepad2} label={t("metricTotalRom")} value={scoped.length} color={C.accent} compact={compact} />
        <MetricCard icon={HardDriveDownload} label={t("metricTotalSize")} value={fmtMB(totalMB)} compact={compact} />
        <MetricCard icon={FileWarning} label={t("metricMissingRom")} value={missingRom} color={C.danger} compact={compact} />
        <MetricCard icon={ImageOff} label={t("metricMissingMedia")} value={missingMedia} color={C.warning} compact={compact} />
      </div>
      <div className="font-semibold mb-2" style={{ fontSize: fs(12), color: C.text }}>시스템별 상세 통계</div>
      <SystemStatsTable games={scoped} compact={compact} />
    </div>
  );
}

function SettingsView({ locals, onDeleteLocal, appSettings, onChangeSettings, showToast, forceRerender, onClose }) {
  const [section, setSection] = useState("general");
  const [draft, setDraft] = useState(appSettings);
  const [restoreOpen, setRestoreOpen] = useState(false);
  const sections = [{ key: "general", label: "일반 설정" }, { key: "locals", label: "Local 관리" }, { key: "export", label: "Export 설정" }, { key: "backup", label: "백업 / 복원" }];
  useEffect(() => setDraft(appSettings), [appSettings]);
  function saveGeneral() { onChangeSettings(draft); LANG = draft.lang; applyTheme(draft.theme); forceRerender(); showToast("설정이 저장되었습니다."); }
  function doBackup() { const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14); showToast(`백업 완료: masterdb_backup_${stamp}.zip 생성됨`); }
  const MOCK_BACKUPS = ["masterdb_backup_20260820_093000.zip", "masterdb_backup_20260815_180000.zip"];
  const row = { display: "grid", gridTemplateColumns: "118px 1fr", gap: 10, alignItems: "start", marginBottom: 8 };
  const descStyle = { color: C.muted, fontSize: fs(9), lineHeight: 1.35, paddingTop: 4 };
  return (
    <div className="flex-1 min-h-0 flex">
      <div className="w-32 shrink-0 py-2 px-2 flex flex-col gap-1" style={{ borderRight: `1px solid ${C.border}` }}>
        <div className="px-2.5 pb-2" style={{ borderBottom: `1px solid ${C.border}` }}>
          <div className="flex items-center justify-between">
            <div className="font-bold tracking-tight" style={{ color: C.text, fontSize: fs(13) }}>Settings</div>
            <button onClick={onClose} className="p-1 rounded" title="닫기" style={{ color: C.muted }}><X size={11} /></button>
          </div>
          <Settings size={10} className="mt-1" style={{ color: C.accent }} />
        </div>
        {sections.map((s) => <button key={s.key} onClick={() => setSection(s.key)} className="text-left rounded-md px-2.5 py-1.5 transition-colors" style={{ fontSize: fs(10.5), backgroundColor: section === s.key ? C.card3 : "transparent", color: section === s.key ? C.text : C.muted }}>{s.label}</button>)}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3">
        {section === "general" && (
          <div className="max-w-lg">
            <div className="font-semibold mb-2" style={{ fontSize: fs(11), color: C.text }}>일반 설정</div>
            <div style={row}><div><div className="uppercase tracking-wide mb-1" style={{ fontSize: fs(10), color: C.muted }}>언어</div>
              <select value={draft.lang} onChange={(e) => setDraft({ ...draft, lang: e.target.value })} className="w-full rounded-md px-2 py-1 outline-none" style={{ fontSize: fs(10.5), backgroundColor: C.card2, border: `1px solid ${C.border}`, color: C.text }}>
                <option value="ko">한국어</option><option value="en">English</option>
              </select></div><div style={descStyle}>메뉴/목록 헤더/상태 라벨 등 주요 UI 문자열의 언어를 전환합니다.</div></div>
            <div style={row}><div><div className="uppercase tracking-wide mb-1" style={{ fontSize: fs(10), color: C.muted }}>테마</div>
              <select value={draft.theme} onChange={(e) => setDraft({ ...draft, theme: e.target.value })} className="w-full rounded-md px-2 py-1 outline-none" style={{ fontSize: fs(10.5), backgroundColor: C.card2, border: `1px solid ${C.border}`, color: C.text }}>
                <option value="system">시스템 설정</option><option value="dark">Dark</option><option value="light">Light</option>
              </select></div><div style={descStyle}>시스템 설정을 고르면 OS 다크모드를 따라갑니다.</div></div>
            <div style={row}><div><div className="uppercase tracking-wide mb-1" style={{ fontSize: fs(10), color: C.muted }}>자동 저장 간격</div>
              <select value={draft.saveInterval} onChange={(e) => setDraft({ ...draft, saveInterval: e.target.value })} className="w-full rounded-md px-2 py-1 outline-none" style={{ fontSize: fs(10.5), backgroundColor: C.card2, border: `1px solid ${C.border}`, color: C.text }}>
                <option value="5">5분</option><option value="10">10분</option><option value="30">30분</option><option value="60">1시간</option><option value="0">저장 안 함</option>
              </select></div><div style={descStyle}>설정 주기마다 config.json을 자동 저장합니다.</div></div>
            <IconButton icon={Save} label="설정 저장" primary onClick={saveGeneral} />
          </div>
        )}
        {section === "locals" && (
          <div className="flex flex-col gap-2 max-w-md">
            <div className="font-semibold mb-1" style={{ fontSize: fs(11), color: C.text }}>Local 관리</div>
            {locals.map((l) => (
              <div key={l.id} className="flex items-center justify-between rounded-lg px-3 py-2" style={{ backgroundColor: C.card, border: `1px solid ${C.border}` }}>
                <span className="" style={{ fontSize: fs(11), color: C.text }}>{l.label} ({l.frontend})</span>
                <IconButton icon={Trash2} compact onClick={() => onDeleteLocal(l.id)} />
              </div>
            ))}
          </div>
        )}
        {section === "export" && (
          <div className="max-w-lg">
            <div className="font-semibold mb-2" style={{ fontSize: fs(11), color: C.text }}>Export 설정</div>
            <div className="rounded-lg flex items-start gap-2 mb-3" style={{ backgroundColor: C.card2, padding: 10 }}>
              <Info size={12} style={{ color: C.accent, marginTop: 1, flexShrink: 0 }} />
              <p style={{ color: C.muted, fontSize: fs(10), lineHeight: 1.5 }}>MasterDB의 metadata를 Local로 내보낼 때 처리 방식을 정의합니다.</p>
            </div>
            {[["koreanOnly", "중복 시 한글화 롬만 복사"], ["copyMedia", "Media도 복사"], ["copyVideo", "Video도 복사"], ["forceOverwrite", "강제 덮어쓰기"]].map(([key, label]) => (
              <label key={key} className="flex items-start gap-2 mb-2 cursor-pointer">
                <input type="checkbox" checked={!!draft.exportOptions?.[key]} onChange={(e) => setDraft({ ...draft, exportOptions: { ...draft.exportOptions, [key]: e.target.checked } })} className="accent-purple-500 mt-0.5" />
                <div style={{ color: C.text, fontSize: fs(11) }}>{label}</div>
              </label>
            ))}
            <IconButton icon={Save} label="설정 저장" primary onClick={saveGeneral} />
          </div>
        )}
        {section === "backup" && (
          <div className="max-w-md">
            <div className="font-semibold mb-2" style={{ fontSize: fs(11), color: C.text }}>백업 / 복원</div>
            <div className="flex gap-2 mb-3">
              <IconButton icon={HardDriveDownload} label="지금 백업" primary onClick={doBackup} />
              <IconButton icon={HardDriveUpload} label="복원" onClick={() => setRestoreOpen((v) => !v)} />
            </div>
            {restoreOpen && (
              <div className="rounded-lg overflow-hidden" style={{ border: `1px solid ${C.border}` }}>
                {MOCK_BACKUPS.map((b) => (
                  <button key={b} onClick={() => { setRestoreOpen(false); showToast(`'${b}'으로 복원 완료 — 재시작이 필요합니다.`, "warning"); }}
                    className="w-full text-left px-3 py-2 transition-colors" style={{ fontSize: fs(11.5), color: C.text, backgroundColor: C.card2, borderBottom: `1px solid ${C.border}` }}>{b}</button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function RetroMetadataManagerMockup() {
  const isMobile = useIsMobile();
  const [, bumpRerender] = useState(0);
  const forceRerender = () => bumpRerender((x) => x + 1);
  const [view, setView] = useState("masterdb");
  const [settingsReturnView, setSettingsReturnView] = useState("masterdb");
  const [games, setGames] = useState(GAMES0);
  const [selectedGame, setSelectedGame] = useState(null);
  const [search, setSearch] = useState("");
  const [selectedSystem, setSelectedSystem] = useState("all");
  const [viewMode, setViewMode] = useState("list");
  const [statusFilter, setStatusFilter] = useState(new Set(["all"]));
  const [sortField, setSortField] = useState(null);
  const [sortDir, setSortDir] = useState("asc");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const [locals, setLocals] = useState(LOCALS0);
  const [toast, setToast] = useState(null);
  const [confirmState, setConfirmState] = useState(null);
  const [addLocalOpen, setAddLocalOpen] = useState(false);
  const [appSettings, setAppSettings] = useState({ lang: "ko", theme: "dark", saveInterval: "5", koreanOnly: true, copyMedia: true, copyVideo: true, forceOverwrite: false, exportOptions: { koreanOnly: true, copyMedia: true, copyVideo: true, forceOverwrite: false } });
  const [panelOpen, setPanelOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [fontScale, setFontScale] = useState(1);
  const hideTimer = useRef(null);
  const toastTimer = useRef(null);

  function showToast(msg, type = "success") {
    setToast({ msg, type });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 2600);
  }

  const scopedGames = view.startsWith("local-") ? games.filter((g) => g.local === view.replace("local-", "")) : games;
  const normalizedGames = scopedGames.map((g) => ({ ...g, system: normalizeSystemName(g.system) }));
  const systems = [{ key: "all", label: t("filterAll"), count: normalizedGames.length }, ...Array.from(new Set(normalizedGames.map((g) => g.system))).map((s) => ({ key: s, label: s, count: normalizedGames.filter((g) => g.system === s).length }))];
  const bySystem = normalizedGames.filter((g) => selectedSystem === "all" || g.system === selectedSystem);
  const bySearch = bySystem.filter((g) => g.file.toLowerCase().includes(search.toLowerCase()) || g.title.toLowerCase().includes(search.toLowerCase()));
  const byStatus = bySearch.filter((g) => gameMatchesStatusFilter(g, statusFilter));
  const sorted = [...byStatus].sort((a, b) => {
    if (!sortField) return 0;
    const av = (a[sortField] || "").toString().toLowerCase(), bv = (b[sortField] || "").toString().toLowerCase();
    if (av < bv) return sortDir === "asc" ? -1 : 1;
    if (av > bv) return sortDir === "asc" ? 1 : -1;
    return 0;
  });

  function toggleSort(field) { sortField === field ? setSortDir((d) => (d === "asc" ? "desc" : "asc")) : (setSortField(field), setSortDir("asc")); }
  function toggleStatusFilter(key) {
    setStatusFilter((prev) => {
      if (key === "all") return new Set(["all"]);
      const next = new Set(prev); next.delete("all");
      next.has(key) ? next.delete(key) : next.add(key);
      return next.size === 0 ? new Set(["all"]) : next;
    });
  }
  function openPanelFor(game) {
    setSelectedGame(game);
    if (isMobile) { setMobileDetailOpen(true); return; }
    setPanelOpen(true);
    if (hideTimer.current) clearTimeout(hideTimer.current);
    // [BUG FIX] 취소만 하고 새로 예약을 안 해서, pin이 꺼져있어도 5초 뒤 자동으로 닫히지
    // 않던 문제 - 게임을 새로 선택할 때마다(고정 상태가 아니면) 타이머를 다시 건다.
    if (!pinned) hideTimer.current = setTimeout(() => setPanelOpen(false), AUTO_HIDE_MS);
  }
  function togglePin() {
    setPinned((isPinned) => {
      const next = !isPinned;
      if (hideTimer.current) clearTimeout(hideTimer.current);
      // [BUG FIX] 마찬가지로, Pin을 해제(next===false)하는 순간에도 패널이 열려 있으면
      // 그 시점부터 다시 5초 카운트다운을 걸어줘야 한다.
      if (!next && panelOpen) hideTimer.current = setTimeout(() => setPanelOpen(false), AUTO_HIDE_MS);
      return next;
    });
  }
  useEffect(() => () => { if (hideTimer.current) clearTimeout(hideTimer.current); if (toastTimer.current) clearTimeout(toastTimer.current); }, []);
  useEffect(() => {
    const onWheel = (e) => {
      if (!e.shiftKey) return;
      e.preventDefault();
      setFontScale((v) => Math.max(0.85, Math.min(1.15, +(v + (e.deltaY < 0 ? 0.05 : -0.05)).toFixed(2))));
    };
    window.addEventListener('wheel', onWheel, { passive: false });
    return () => window.removeEventListener('wheel', onWheel);
  }, []);
  useEffect(() => { setSelectedSystem("all"); }, [view]);

  function requestDeleteLocal(local) {
    setConfirmState({
      title: "Local 삭제", danger: true, message: `'${local.label}'을(를) 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.`,
      onConfirm: () => { setLocals((prev) => prev.filter((l) => l.id !== local.id)); if (view === "local-" + local.id) setView("masterdb"); setConfirmState(null); showToast(`${local.label} 삭제됨`, "warning"); },
    });
  }
  function handleRefresh() { showToast("Refresh 완료 — 최신 상태입니다."); }
  function handleCleanup() {
    setConfirmState({
      title: "Reset Metadata (CleanUp)", danger: true, message: "이 Local의 모든 metadata/media가 삭제됩니다. 계속하시겠습니까?",
      onConfirm: () => {
        const scope = view.startsWith("local-") ? view.replace("local-", "") : null;
        setGames((prev) => prev.map((g) => (!scope || g.local === scope) ? { ...g, title: "", desc: "", genre: "", developer: "", publisher: "", release: "", region: "", players: "", rating: "", status: "누락" } : g));
        setConfirmState(null); showToast("CleanUp 완료 — metadata가 초기화되었습니다.", "warning");
      },
    });
  }
  function handlePrune() {
    setConfirmState({
      title: "Orphan Cleanup (Prune Data)", danger: true, message: "ROM이 없는 고아 metadata/media를 삭제합니다. 계속하시겠습니까?",
      onConfirm: () => {
        const scope = view.startsWith("local-") ? view.replace("local-", "") : null;
        const removed = games.filter((g) => (!scope || g.local === scope) && g.status === "누락").length;
        setGames((prev) => prev.filter((g) => !((!scope || g.local === scope) && g.status === "누락")));
        setConfirmState(null); showToast(`Prune 완료 — 고아 항목 ${removed}개 삭제됨.`, "warning");
      },
    });
  }
  function handleExport() {
    const count = sorted.length; const dup = Math.max(0, Math.floor(count * 0.15));
    showToast(`Export to MasterDB 완료 — 성공 ${count - dup}개, 중복 스킵 ${dup}개.`);
  }
  function handleAddLocal({ label, frontend, romPath, metaPath }) {
    const id = "l" + (Date.now() % 100000);
    setLocals((prev) => [...prev, { id, label, frontend, romPath: romPath || "(미지정)", sizeGB: 0, romCount: 0, status: "미설정" }]);
    setAddLocalOpen(false); showToast(`${label} 등록됨`);
  }
  function handleSaveGame(gameId, fields, media) {
    setGames((prev) => prev.map((g) => g.id === gameId ? {
      ...g, title: fields.name, desc: fields.desc, genre: fields.genre, developer: fields.developer, publisher: fields.publisher, release: fields.release, region: fields.region, players: fields.players, rating: fields.rating,
      status: (fields.name && fields.desc) ? "완료" : (fields.name || fields.desc) ? "부분" : "누락",
      ...(media ? { media: { ...(g.media || {}), ...media }, missingMedia: false } : {}),
    } : g));
    setSelectedGame((prev) => prev && prev.id === gameId ? { ...prev, title: fields.name, desc: fields.desc, ...(media ? { media: { ...(prev.media || {}), ...media }, missingMedia: false } : {}) } : prev);
  }

  const goView = (v) => { setView(v); setSidebarOpen(false); };
  const openSettings = () => { setSettingsReturnView(view === "settings" ? "masterdb" : view); setView("settings"); setSidebarOpen(false); };
  const viewTitle = view === "masterdb" ? "MasterDB" : view === "dashboard" ? t("dashboard") : view === "settings" ? t("settings") : locals.find((l) => "local-" + l.id === view)?.label || "Local";
  const isListView = view === "masterdb" || view.startsWith("local-");

  const sidebar = (
    <div className="w-56 shrink-0 h-full flex flex-col py-4 px-3" style={{ backgroundColor: C.bg, borderRight: `1px solid ${C.border}` }}>
      <div className="flex items-center justify-between px-1 mb-5">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ backgroundColor: C.accent, boxShadow: `0 0 16px ${C.accent}55` }}><Gamepad2 size={15} color="#fff" /></div>
          <div><div className="flex items-center gap-1.5"><div className="font-semibold leading-tight whitespace-nowrap" style={{ fontSize: fs(12), color: C.text }}>Retro Metadata Manager</div><button onClick={openSettings} title="앱 설정" className="p-0.5 rounded" style={{ color: C.muted }}><Settings size={12} /></button></div><div className="" style={{ color: C.muted }}>v0.3.0</div></div>
        </div>
        {isMobile && <button onClick={() => setSidebarOpen(false)} style={{ color: C.muted }}><X size={18} /></button>}
      </div>
      <NavItem icon={LayoutDashboard} label={t("dashboard")} active={view === "dashboard"} onClick={() => goView("dashboard")} />
      <div className="font-semibold tracking-wider px-3 mt-4 mb-1.5" style={{ fontSize: fs(9), color: C.muted }}>{t("local")}</div>
      {locals.map((l) => <NavItem key={l.id} label={`${l.label} · ${l.frontend}`} indent small dot={l.status === "정상" ? C.success : l.status === "경고" ? C.warning : C.muted} active={view === "local-" + l.id} onClick={() => goView("local-" + l.id)} />)}
      <NavItem icon={Plus} label={t("addLocal")} indent small onClick={() => setAddLocalOpen(true)} />
      <div className="font-semibold tracking-wider px-3 mt-4 mb-1.5" style={{ fontSize: fs(9), color: C.muted }}>{t("server")}</div>
      <NavItem icon={Database} label="MasterDB" indent small active={view === "masterdb"} onClick={() => goView("masterdb")} />
      {isListView && <>
        <div className="font-semibold tracking-wider px-3 mt-4 mb-1.5" style={{ fontSize: fs(9), color: C.muted }}>GAME SYSTEMS</div>
        {systems.map((s) => <NavItem key={s.key} icon={s.key === "all" ? HardDrive : null} branch={s.key !== "all"} label={`${s.label} · ${s.count}`} indent small active={selectedSystem === s.key} onClick={() => setSelectedSystem(s.key)} />)}
      </>}
      <div className="flex-1" />
    </div>
  );

  const contextBar = (compact) => (
    <div className="flex items-center gap-1.5 shrink-0 overflow-x-auto" style={{ padding: compact ? "5px 12px" : "6px 20px", borderBottom: `1px solid ${C.border}`, backgroundColor: C.card }}>
      <span className="font-bold tracking-wide" style={{ color: C.muted, fontSize: fs(8.5), marginRight: 2 }}>SOURCE</span>
      {locals.map((l) => <TopCard key={l.id} local={l} active={view === "local-" + l.id} onClick={() => goView("local-" + l.id)} compact />)}
      <MasterCard active={view === "masterdb"} onClick={() => goView("masterdb")} compact />
      <button onClick={() => setAddLocalOpen(true)} className="rounded-lg shrink-0" style={{ backgroundColor: C.card2, color: C.muted, border: `1px dashed ${C.border}`, padding: "7px 9px", fontSize: fs(10) }}><Plus size={11} className="inline mr-1" />Local</button>
    </div>
  );

  const filterRow = (compact) => (
    <div className="flex items-center gap-2 flex-wrap shrink-0" style={{ padding: compact ? "8px 12px" : "10px 20px" }}>
      <div className="shrink-0 pr-2" style={{ borderRight: `1px solid ${C.border}` }}>
        <div className="font-bold" style={{ color: C.accent, fontSize: compact ? 8.5 : 9.5, letterSpacing: "0.12em" }}>GAME LIST</div>
        {!compact && <div className="mt-0.5 truncate" style={{ color: C.muted, fontSize: fs(10.5), maxWidth: 132 }}>{viewTitle} 라이브러리</div>}
      </div>
      <div className="flex items-center rounded-lg overflow-hidden shrink-0" style={{ border: `1px solid ${C.border}` }}>
        <button onClick={() => setViewMode("list")} title="List 보기" style={{ backgroundColor: viewMode === "list" ? C.accent : C.card2, color: viewMode === "list" ? "#fff" : C.muted, padding: "6.5px 9px", display: "flex" }}><LayoutList size={13} /></button>
        <button onClick={() => setViewMode("preview")} title="Preview 보기" style={{ backgroundColor: viewMode === "preview" ? C.accent : C.card2, color: viewMode === "preview" ? "#fff" : C.muted, padding: "6.5px 9px", display: "flex" }}><LayoutGrid size={13} /></button>
      </div>
      <Dropdown buttonIcon={ListFilter} buttonLabel={statusFilter.has("all") ? `${t("filterAll")}` : `${statusFilter.size}개 선택`} width={180}>
        {() => (
          <div className="p-1">
            <button onClick={() => toggleStatusFilter("all")} className="w-full text-left px-2 py-1.5 rounded mb-0.5" style={{ fontSize: fs(12), color: statusFilter.has("all") ? "#fff" : C.text, backgroundColor: statusFilter.has("all") ? C.accent : "transparent" }}>{t("filterAll")}</button>
            {STATUS_FILTERS.map((s) => (
              <label key={s.key} className="flex items-center gap-2 px-2 py-1.5 cursor-pointer rounded" style={{ fontSize: fs(12), color: C.text }}>
                <input type="checkbox" checked={statusFilter.has(s.key)} onChange={() => toggleStatusFilter(s.key)} className="accent-purple-500" /><s.icon size={11} style={{ color: C.muted }} />{s.label}
              </label>
            ))}
          </div>
        )}
      </Dropdown>
      <div className="flex-1 flex items-center gap-2 rounded-lg px-2.5 py-1.5" style={{ backgroundColor: C.card2, border: `1px solid ${C.border}`, maxWidth: compact ? "none" : 220 }}>
        <Search size={12} style={{ color: C.muted }} />
        <input placeholder="검색..." value={search} onChange={(e) => setSearch(e.target.value)} className="bg-transparent outline-none flex-1 min-w-0" style={{ fontSize: fs(12), color: C.text }} />
      </div>
      <button onClick={() => setFontScale(1)} title="Shift + 마우스 휠로 글자 크기 조절" className="rounded-lg shrink-0" style={{ backgroundColor: C.card2, border: `1px solid ${C.border}`, color: C.muted, padding: "6px 8px", fontSize: fs(9.5) }}>A {Math.round(fontScale * 100)}%</button>
      {!compact && <IconButton icon={RefreshCw} label={t("refresh")} onClick={handleRefresh} />}
      {!compact && <IconButton icon={Plus} label={t("addLocal")} primary onClick={() => setAddLocalOpen(true)} />}
    </div>
  );

  // [요청 반영] Detail 패널의 세로 시작 위치를 GameList 헤더가 아니라 "SOURCE / GAME LIST"
  // 경계선(=filterRow 상단)에 맞춘다. filterRow와 게임리스트를 하나의 position:relative
  // 래퍼로 묶고, 그 래퍼 기준으로 Detail 패널을 절대배치해서 위쪽으로 더 늘어나게 한다.
  // 동시에 z-index를 GameList 헤더(z-10)보다 높게(20) 줘서 Pin/닫기 버튼이 안 가려지게 한다.
  const gameListOnly = (compact) => (
    <div className="relative flex-1 min-h-0" style={{ padding: compact ? "0 12px 12px" : "0 20px 16px" }}>
      <GameListCard games={sorted} selectedGame={selectedGame} panelOpen={panelOpen} onRowClick={openPanelFor} onSelectAdjacent={openPanelFor} sortField={sortField} sortDir={sortDir} onSort={toggleSort} compact={compact} viewMode={viewMode}
        onRefresh={handleRefresh} onCleanup={handleCleanup} onPrune={handlePrune} onExport={handleExport} />
    </div>
  );

  const listArea = (compact) => (
    <div className="relative flex-1 flex flex-col min-h-0">
      {filterRow(compact)}
      {gameListOnly(compact)}
      <div className="absolute top-0 rounded-xl overflow-hidden shadow-2xl transition-transform duration-300 ease-out"
        style={{ bottom: compact ? 12 : 16, right: compact ? 12 : 20, width: compact ? 300 : 400, zIndex: 20, backgroundColor: C.card, border: `1px solid ${C.border}`, transform: panelOpen ? "translateX(0)" : "translateX(calc(100% + 20px))" }}>
        <DetailPanel game={selectedGame} pinned={pinned} onTogglePin={togglePin} onClose={() => setPanelOpen(false)} onSaveGame={handleSaveGame} showToast={showToast} />
      </div>
    </div>
  );

  const rootStyle = {
    backgroundColor: C.bg, color: C.text, fontFamily: "'Inter','Segoe UI',system-ui,sans-serif", height: APP_HEIGHT,
    backgroundImage: `radial-gradient(circle at 82% -10%, ${C.accent}22, transparent 31%), linear-gradient(135deg, ${C.bg}, ${C.card})`,
    "--font-scale": fontScale,
  };
  const appCss = `
    @keyframes shrinkw { from { width: 100%; } to { width: 0%; } }
    .retro-app { isolation: isolate; }
    .retro-app { --font-scale: 1; }
    .retro-app button { outline: none; }
    .retro-app button:focus-visible, .retro-app input:focus-visible, .retro-app textarea:focus-visible, .retro-app select:focus-visible { box-shadow: 0 0 0 3px ${C.accent}55 !important; }
    .retro-app::after { content: ""; pointer-events: none; position: absolute; inset: 0; z-index: 80; opacity: .13; background: repeating-linear-gradient(0deg, transparent 0, transparent 3px, rgba(255,255,255,.035) 4px); mix-blend-mode: overlay; }
  `;

  if (isMobile) {
    return (
      <div className="retro-app relative flex flex-col w-full rounded-2xl overflow-hidden" style={rootStyle}>
        <style>{appCss}</style>
        <div className="flex items-center justify-between px-3 py-2 shrink-0" style={{ borderBottom: `1px solid ${C.border}` }}>
          <button onClick={() => setSidebarOpen(true)} style={{ color: C.text }}><Menu size={17} /></button>
          <span className="font-semibold" style={{ fontSize: fs(12), color: C.text }}>{viewTitle}</span><span style={{ width: 17 }} />
        </div>
        {isListView && <>{contextBar(true)}{listArea(true)}</>}
        {view === "dashboard" && <DashboardView locals={locals} games={games} compact />}
        {view === "settings" && <SettingsView locals={locals} onDeleteLocal={(id) => requestDeleteLocal(locals.find((l) => l.id === id))} appSettings={appSettings} onChangeSettings={setAppSettings} showToast={showToast} forceRerender={forceRerender} onClose={() => setView(settingsReturnView)} />}
        {sidebarOpen && (
          <div className="absolute inset-0 z-20 flex">
            <div style={{ width: 200 }} className="h-full">{sidebar}</div>
            <div className="flex-1 h-full" style={{ backgroundColor: "rgba(0,0,0,0.5)" }} onClick={() => setSidebarOpen(false)} />
          </div>
        )}
        {mobileDetailOpen && selectedGame && (
          <div className="absolute inset-0 z-10 flex flex-col" style={{ backgroundColor: C.card }}>
            <div className="flex items-center gap-2 px-1 py-1 shrink-0"><button onClick={() => setMobileDetailOpen(false)} className="p-2" style={{ color: C.text }}><ChevronLeft size={18} /></button></div>
            <DetailPanel game={selectedGame} pinned={true} onTogglePin={() => {}} showPin={false} onClose={() => setMobileDetailOpen(false)} onSaveGame={handleSaveGame} showToast={showToast} />
          </div>
        )}
        <Toast toast={toast} />
        <ConfirmDialog open={!!confirmState} {...confirmState} onCancel={() => setConfirmState(null)} />
        {addLocalOpen && <AddLocalModal defaultLabel={`LOCAL ${locals.length + 1}`} onClose={() => setAddLocalOpen(false)} onAdd={handleAddLocal} />}
      </div>
    );
  }

  return (
    <div className="retro-app relative flex w-full rounded-2xl overflow-hidden" style={rootStyle}>
      <style>{appCss}</style>
      {sidebar}
      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        {isListView && contextBar(false)}
        {isListView && listArea(false)}
        {view === "dashboard" && <DashboardView locals={locals} games={games} />}
        {view === "settings" && <SettingsView locals={locals} onDeleteLocal={(id) => requestDeleteLocal(locals.find((l) => l.id === id))} appSettings={appSettings} onChangeSettings={setAppSettings} showToast={showToast} forceRerender={forceRerender} onClose={() => setView(settingsReturnView)} />}
      </div>
      <Toast toast={toast} />
      <ConfirmDialog open={!!confirmState} {...confirmState} onCancel={() => setConfirmState(null)} />
      {addLocalOpen && <AddLocalModal defaultLabel={`LOCAL ${locals.length + 1}`} onClose={() => setAddLocalOpen(false)} onAdd={handleAddLocal} />}
    </div>
  );
}


export default RetroMetadataManagerMockup;
