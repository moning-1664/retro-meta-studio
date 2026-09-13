/* Dashboard UX v3: theme-safe target controls with human capacity snapping. */
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const MB = 1024 * 1024, GB = 1024 * MB, TB = 1024 * GB, MAX = 4 * TB;
  const SNAP = [32*GB,64*GB,128*GB,256*GB,512*GB,1*TB,2*TB,3*TB,4*TB];
  function formatCapacity(bytes) { bytes=Math.max(MB,Math.round(bytes/MB)*MB); if(bytes>=TB)return `${(bytes/TB).toFixed(bytes%TB?1:0)} TB`; return `${Math.round(bytes/GB)} GB`; }
  function parseCapacity(text) { const m=String(text||"").trim().replace(/,/g,"").match(/^([0-9]+(?:\.[0-9]+)?)\s*(mb|m|gb|g|tb|t)?$/i); if(!m)return null; const n=Number(m[1]),u=(m[2]||"mb").toLowerCase(),mult=(u==="tb"||u==="t")?TB:(u==="gb"||u==="g")?GB:MB; return Math.max(MB,Math.min(MAX,Math.round(n*mult/MB)*MB)); }
  function nearestSnap(bytes, ratio=.035) { let best=null,d=Infinity; for(const p of SNAP){const x=Math.abs(bytes-p);if(x<d){d=x;best=p;}} return best!=null&&d<=Math.max(GB,best*ratio)?best:bytes; }
  let collectionId=null, busy=false;
  async function enhance(){
    if(busy)return;
    const rows=$$(".rms-dash-target-row").filter(r=>!r.dataset.rmsV3Target);
    if(!rows.length||!window.api?.listCollections||!window.pywebview?.api?.dashboard_stats)return;
    busy=true;
    try{
      const name=$(".ctab.active .ctab-name")?.textContent.trim(), cr=await window.api.listCollections();
      const c=(cr?.data||[]).find(x=>x.name===name); if(!c)return; collectionId=c.id;
      const r=await window.pywebview.api.dashboard_stats(c.id), storages=r?.ok?(r.data?.storages||[]):[];
      rows.forEach((row,i)=>install(row,storages[i]));
    } finally {busy=false;}
  }
  function install(row,storage){
    const range=row.querySelector('input[type="range"]'),old=row.querySelector(".rms-dash-target-value"),line=row.querySelector(".rms-dash-target-line");
    if(!range||!old||!line)return; row.dataset.rmsV3Target="1";
    const key=storage?.id!=null?`rms.dashboard.target.${collectionId}.${storage.id}`:null;
    let current=Math.max(MB,Math.min(MAX,(Number(range.value)||4096)*MB));
    if(key){const saved=Number(localStorage.getItem(key));if(Number.isFinite(saved)&&saved>0)current=Math.max(MB,Math.min(MAX,saved));}
    range.min=String(MB);range.max=String(MAX);range.step=String(MB);range.value=String(current);
    const input=document.createElement("input");input.type="text";input.className="rms-dash-target-input";input.inputMode="decimal";input.title="예: 512 GB, 1 TB, 2048 MB";
    const spin=document.createElement("div");spin.className="rms-dash-target-spin";
    const up=document.createElement("button"),down=document.createElement("button");up.type=down.type="button";up.className=down.className="rms-dash-target-spin-btn";up.title="용량 증가";down.title="용량 감소";up.textContent="▲";down.textContent="▼";spin.append(up,down);
    function render(v,persist=true){current=Math.max(MB,Math.min(MAX,Math.round(v/MB)*MB));range.value=String(current);input.value=formatCapacity(current);if(persist&&key)localStorage.setItem(key,String(current));}
    function step(v){return v<TB?GB:v<2*TB?8*GB:16*GB;}
    function change(delta){render(nearestSnap(current+delta,.02));}
    range.addEventListener("input",()=>render(nearestSnap(Number(range.value)),false));
    range.addEventListener("change",()=>render(nearestSnap(Number(range.value)),true));
    input.addEventListener("change",()=>{const v=parseCapacity(input.value);if(v==null){input.value=formatCapacity(current);return;}render(nearestSnap(v,.02));});
    input.addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();input.dispatchEvent(new Event("change"));input.blur();}else if(e.key==="ArrowUp"){e.preventDefault();change(step(current));}else if(e.key==="ArrowDown"){e.preventDefault();change(-step(current));}});
    up.addEventListener("click",()=>change(step(current)));down.addEventListener("click",()=>change(-step(current)));
    old.replaceWith(input);line.appendChild(spin);render(current,false);
  }
  const observer=new MutationObserver(enhance);
  function init(){enhance();observer.observe(document.body,{childList:true,subtree:true});}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});else init();
})();
