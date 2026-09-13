/* RetroMeta Studio — Dashboard. Keeps app.js layout/state intact. */
(function(){
  "use strict";
  const $=(s,r=document)=>r.querySelector(s);
  const clear=e=>{while(e&&e.firstChild)e.removeChild(e.firstChild);};
  const el=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e;};
  const fmt=n=>Number(n||0).toLocaleString();
  const size=n=>{n=Number(n||0);if(!n)return "0 B";const u=["B","KB","MB","GB","TB"];let i=0;while(n>=1024&&i<4){n/=1024;i++;}return (n>=100||i===0?Math.round(n):n.toFixed(1))+" "+u[i];};
  const colors=["#3b82f6","#22c55e","#f59e0b","#ef4444","#a855f7","#14b8a6","#f97316","#ec4899","#84cc16","#06b6d4","#8b5cf6","#eab308"];
  let dashboardActive=false, renderToken=0;

  function activeCollectionId(){
    const tab=$(".ctab.active .ctab-name");
    if(!tab||tab.textContent.trim()==="Archive")return null;
    return window.api?.listCollections?.().then(r=>{const a=Array.isArray(r?.data)?r.data:[];return a.find(c=>c.name===tab.textContent.trim())?.id||null;});
  }
  function bridge(name,...args){const f=window.pywebview?.api?.[name];return f?Promise.resolve(f(...args)):Promise.resolve({ok:false,error:name+" bridge 없음"});}

  function hideAppCenterContent(hide){
    const center=$("#center");if(!center)return;
    ["#collection-header","#filter-bar","#list-wrap"].forEach(s=>{const x=$(s,center);if(x)x.style.display=hide?"none":"";});
    center.classList.toggle("rms-dashboard-mode",hide);
  }
  function leave(){
    dashboardActive=false;
    const host=$("#rms-dashboard-host");if(host)host.remove();
    hideAppCenterContent(false);
    const detail=$("#detail-panel");if(detail)detail.style.display="";
  }
  function makeBarRow(label,value,total,sub,cls){
    const row=el("div","rms-dash-bar-row "+(cls||""));
    const top=el("div","rms-dash-bar-top");top.append(el("span","rms-dash-bar-label",label),el("span","rms-dash-bar-value",(total?Math.round(value/total*100):0)+"%"));
    const track=el("div","rms-dash-bar-track"),fill=el("div","rms-dash-bar-fill");fill.style.width=(total?Math.min(100,value/total*100):0)+"%";track.appendChild(fill);row.append(top,track);if(sub)row.appendChild(el("div","rms-dash-bar-sub",sub));return row;
  }
  function metric(label,value,sub){const m=el("div","rms-dash-metric");m.append(el("div","rms-dash-metric-label",label),el("div","rms-dash-metric-value",value));if(sub)m.appendChild(el("div","rms-dash-metric-sub",sub));return m;}

  function renderSystemTable(card,systems){
    const wrap=el("div","rms-dash-table-wrap"),table=el("table","rms-dash-table"),thead=el("thead"),tr=el("tr"),tbody=el("tbody");
    const cols=[
      ["system","SYSTEM","text"],["romCount","ROM","num"],["romBytes","ROM SIZE","size"],["mediaBytes","MEDIA SIZE","size"],["status","STATUS","text"]
    ];
    let sortKey="romBytes",desc=true;
    const statusOf=s=>Number(s.romCount||0)===0?"Empty":Number(s.mediaBytes||0)===0?"Media missing":"Healthy";
    function draw(){
      [...tbody.children].forEach(x=>x.remove());
      const rows=systems.map(s=>({...s,status:statusOf(s)}));
      rows.sort((a,b)=>{let av=a[sortKey],bv=b[sortKey];if(sortKey.endsWith("Bytes")||sortKey==="romCount"){av=Number(av||0);bv=Number(bv||0);}else{av=String(av).toLowerCase();bv=String(bv).toLowerCase();}const c=av>bv?1:av<bv?-1:0;return desc?-c:c;});
      rows.forEach((s,i)=>{const r=el("tr");const dot=el("span","rms-dash-color-dot");dot.style.background=colors[i%colors.length];const sys=el("td","rms-dash-system");sys.append(dot,document.createTextNode(String(s.system||"").toUpperCase()));r.append(sys,el("td","rms-dash-num",fmt(s.romCount)),el("td","rms-dash-size",size(s.romBytes)),el("td","rms-dash-size",size(s.mediaBytes)));const st=el("td","rms-dash-status "+(s.status==="Healthy"?"ok":"warn"),s.status);r.appendChild(st);tbody.appendChild(r);});
    }
    cols.forEach(c=>{const th=el("th","",c[1]);th.addEventListener("click",()=>{if(sortKey===c[0])desc=!desc;else{sortKey=c[0];desc=false;}draw();});tr.appendChild(th);});
    thead.appendChild(tr);table.append(thead,tbody);wrap.appendChild(table);card.appendChild(wrap);draw();
  }

  function render(x){
    const center=$("#center");if(!center)return;
    let host=$("#rms-dashboard-host");if(!host){host=el("div","rms-dashboard");host.id="rms-dashboard-host";center.appendChild(host);}else clear(host);
    const head=el("div","rms-dashboard-header");head.appendChild(el("div","rms-dashboard-title",x.collectionName||"Collection"));
    const actions=el("div","rms-dash-header-actions"),validate=el("button","rms-dash-validate","Validate Collection"),result=el("span","rms-dash-validate-result");
    validate.onclick=async()=>{validate.disabled=true;result.textContent="검사 중…";const r=await bridge("validate_collection",x.collectionId);validate.disabled=false;result.textContent=r.ok?`${fmt(r.data?.checked)} metadata files checked · ${fmt(r.data?.invalidCount)} invalid`:(r.error||"Validation 실패");};actions.append(validate,result);head.appendChild(actions);host.appendChild(head);
    const sum=el("div","rms-dash-grid rms-dash-summary");sum.append(metric("TOTAL ROM",fmt(x.totalRomCount),size(x.totalRomBytes)));sum.append(metric("METADATA",fmt(x.metadataCount)));sum.append(metric("MEDIA",fmt(x.totalMediaCount),size(x.totalMediaBytes)));
    (x.storages||[]).filter(s=>s.kind==="internal").forEach(s=>sum.append(metric("INTERNAL ROM",fmt(s.romCount),size(s.romBytes))));
    (x.storages||[]).filter(s=>s.kind==="external").forEach(s=>sum.append(metric("EXTERNAL ROM",fmt(s.romCount),size(s.romBytes))));host.appendChild(sum);

    const total=(x.systems||[]).reduce((a,s)=>a+Number(s.romBytes||0)+Number(s.mediaBytes||0),0);
    const usage=el("section","rms-dash-card rms-dash-usage");usage.appendChild(el("div","rms-dash-card-title","STORAGE USAGE · ROM + MEDIA"));
    const track=el("div","rms-dash-usage-track");(x.systems||[]).slice().sort((a,b)=>(Number(b.romBytes||0)+Number(b.mediaBytes||0))-(Number(a.romBytes||0)+Number(a.mediaBytes||0))).forEach((s,i)=>{const v=Number(s.romBytes||0)+Number(s.mediaBytes||0),seg=document.createElement("div");seg.className="rms-dash-usage-segment";seg.style.width=(total?v/total*100:0)+"%";seg.style.background=colors[i%colors.length];seg.title=`${String(s.system).toUpperCase()} · ${size(v)}`;track.appendChild(seg);});usage.appendChild(track);host.appendChild(usage);

    const stats=el("section","rms-dash-card rms-dash-stats");stats.appendChild(el("div","rms-dash-card-title","SYSTEM STATISTICS"));renderSystemTable(stats,x.systems||[]);host.appendChild(stats);

    const targets=el("section","rms-dash-card rms-dash-targets");targets.appendChild(el("div","rms-dash-card-title","STORAGE TARGET"));
    (x.storages||[]).forEach(s=>{const used=Number(s.romBytes||0)+Number(s.mediaBytes||0),key=`rms.dashboard.target.${x.collectionId}.${s.id}`,stored=Number(localStorage.getItem(key)||s.capacityBytes||0),max=4096*1024*1024,value=Math.max(1,Math.min(max,stored||max));const row=el("div","rms-dash-target-row"),label=el("div","rms-dash-target-label",`${s.label} · ${s.kind==="external"?"External":"Internal"}`),line=el("div","rms-dash-target-line"),range=document.createElement("input"),out=el("span","rms-dash-target-value");range.type="range";range.min="1";range.max="4096";range.step="1";range.value=Math.round(value/1048576);out.textContent=fmt(range.value)+" MB";range.addEventListener("input",()=>{out.textContent=fmt(range.value)+" MB";});range.addEventListener("change",()=>localStorage.setItem(key,String(Number(range.value)*1048576)));line.append(range,out);row.append(label,line);targets.appendChild(row);});host.appendChild(targets);

    const health=el("section","rms-dash-card rms-dash-health");health.appendChild(el("div","rms-dash-card-title","METADATA HEALTH / VALIDATION"));const h=x.health||{};health.append(makeBarRow("Metadata",h.metadata,h.total,`${fmt(h.metadata)} / ${fmt(h.total)}`),makeBarRow("Media",h.media,h.total,`${fmt(h.media)} / ${fmt(h.total)}`),makeBarRow("Description",h.description,h.total,`${fmt(h.description)} / ${fmt(h.total)}`),makeBarRow("Cover",h.cover,h.total,`${fmt(h.cover)} / ${fmt(h.total)}`));const hs=el("div","rms-dash-health-status");hs.append(el("span","ok",`✓ Complete ${fmt(h.complete)}`),el("span","warn",`⚠ Missing Media ${fmt(h.missingMedia)}`),el("span","warn",`⚠ Missing Description ${fmt(h.missingDescription)}`),el("span","warn",`⚠ Missing Cover ${fmt(h.missingCover)}`));health.appendChild(hs);host.appendChild(health);
  }

  async function open(){
    if(dashboardActive)return;dashboardActive=true;hideAppCenterContent(true);const center=$("#center");if(!center)return;
    const token=++renderToken;let host=$("#rms-dashboard-host");if(!host){host=el("div","rms-dashboard","Dashboard 불러오는 중…");host.id="rms-dashboard-host";center.appendChild(host);}
    const id=await activeCollectionId();if(token!==renderToken||!dashboardActive)return;if(!id){clear(host);host.appendChild(el("div","rms-dash-error","Collection을 먼저 선택하세요."));return;}
    const r=await bridge("dashboard_stats",id);if(token!==renderToken||!dashboardActive)return;if(!r.ok){clear(host);host.appendChild(el("div","rms-dash-error",r.error||"Dashboard 데이터를 읽을 수 없습니다."));return;}render(r.data);
  }

  document.addEventListener("click",e=>{
    if(e.target?.closest?.(".nav-dashboard")){e.preventDefault();e.stopImmediatePropagation();open();return;}
    if(dashboardActive && !e.target?.closest?.("#rms-dashboard-host")){leave();}
  },true);
  window.addEventListener("rms-dashboard-leave",leave);
})();

/* Load optional Dashboard/metadata UX layers without changing app.js boot order. */
(function(){
  ["dashboard-theme.css","dashboard-v3.css"].forEach(href=>{if(!document.querySelector(`link[href="${href}"]`)){const l=document.createElement("link");l.rel="stylesheet";l.href=href;document.head.appendChild(l);}});
  ["p1-detail-filename.js","dashboard-v3.js"].forEach(src=>{if(!document.querySelector(`script[src="${src}"]`)){const s=document.createElement("script");s.src=src;s.async=false;document.body.appendChild(s);}});
})();
