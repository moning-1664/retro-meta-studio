/* ==========================================================================
   dashboard.js — Collection Dashboard (Navigator의 Dashboard로 중앙 영역을 전환)

   구성은 ui/stitch-v2-redesign의 Dashboard를 따른다: 요약 카드, Storage 사용량,
   목표 용량, Metadata Health, System 통계 표. 달라진 점:

   - 값의 주인은 app.js다. 이 모듈은 받은 데이터를 그리고 ctx 콜백으로만 알린다 -
     그 브랜치처럼 탭 이름으로 Collection을 찾거나 브릿지를 직접 부르지 않는다.
   - 목표 용량은 localStorage가 아니라 그 Collection의 ui_state에 저장한다.
   - 차트 규칙: 사용량 막대는 상위 7개 + 기타(회색), 조각 사이 2px 틈, 범례 필수,
     글자는 데이터 색을 입지 않고 옆의 색 표시가 정체를 말한다. 상태는 아이콘+글자.
     아래의 System 표가 차트의 표 보기 역할을 한다(모든 값을 거기서 읽을 수 있다).
   ========================================================================== */
(function () {
  "use strict";

  const MB = 1024 * 1024;
  const GB = 1024 * MB;
  const TB = 1024 * GB;
  const TARGET_MAX = 8 * TB;
  //: 사람이 실제로 쓰는 용량 눈금(프리셋). 슬라이더는 연속으로 움직이다가 이 값 **근처에 오면
  //: 자석처럼 붙는다**(사용자 결정). 텍스트 입력은 자유롭고, 여기 가까우면(snap()) 이 값에 붙는다.
  const SNAP = [32 * GB, 64 * GB, 128 * GB, 256 * GB, 512 * GB, 1 * TB, 2 * TB, 3 * TB, 4 * TB, 8 * TB];
  //: 눈금 아래에 글자로 적는 프리셋 - 로그 눈금에서 고르게(0/25/50/75/100%) 떨어진 값이다.
  const TICK_LABELS = new Set([32 * GB, 128 * GB, 512 * GB, 2 * TB, 8 * TB]);
  //: 슬라이더는 32GB~8TB를 **로그 눈금**으로 편다(32→64와 4→8TB가 같은 거리). 1000칸.
  const SLIDER_MIN = SNAP[0];
  const SLIDER_STEPS = 1000;
  //: 프리셋에서 이 칸 수 안이면 그 값에 붙는다(트랙 길이의 ±1.4%).
  const SNAP_RANGE = 14;
  //: 사용량 막대에 따로 칠하는 System 수. 나머지는 "기타"로 묶는다(색이 8개를 넘으면
  //: 구분이 안 된다).
  const TOP_SYSTEMS = 7;

  function parseCapacity(text) {
    const m = String(text || "").trim().replace(/,/g, "")
      .match(/^([0-9]+(?:\.[0-9]+)?)\s*(mb|m|gb|g|tb|t)?$/i);
    if (!m) return null;
    const unit = (m[2] || "gb").toLowerCase();
    const mult = unit[0] === "t" ? TB : unit[0] === "m" ? MB : GB;
    return Math.max(GB, Math.min(TARGET_MAX, Math.round(Number(m[1]) * mult)));
  }

  function formatCapacity(bytes) {
    if (!bytes) return "";
    if (bytes >= TB) return `${+(bytes / TB).toFixed(bytes % TB ? 1 : 0)} TB`;
    return `${Math.round(bytes / GB)} GB`;
  }

  function snap(bytes) {
    const nearest = SNAP.reduce((best, p) => (Math.abs(p - bytes) < Math.abs(best - bytes) ? p : best), SNAP[0]);
    return Math.abs(nearest - bytes) <= Math.max(GB, nearest * 0.03) ? nearest : bytes;
  }

  /** 보여줄 수 있는 단위로 반올림한다 - 1TB 미만은 1GB, 그 이상은 0.1TB. */
  function roundCapacity(bytes) {
    if (bytes >= TB) return Math.round(Math.round(bytes / (TB / 10)) * (TB / 10));
    return Math.max(GB, Math.round(bytes / GB) * GB);
  }

  //: 프리셋 사이의 다음/이전 프리셋. 키보드(슬라이더의 ←→)가 쓴다.
  const nextPreset = (bytes) => SNAP.find((v) => v > bytes) ?? SNAP[SNAP.length - 1];
  const prevPreset = (bytes) => [...SNAP].reverse().find((v) => v < bytes) ?? SNAP[0];

  //: ▲/▼의 세밀한 한 칸(사용자 결정 - 프리셋만 건너뛰지 않는다). 크기에 비례해 커지고,
  //: 프리셋을 넘어가지는 않는다(그 사이에 프리셋이 있으면 거기서 멈춘다).
  const fineStep = (bytes) => (bytes >= TB ? TB / 10 : bytes >= 256 * GB ? 16 * GB : bytes >= 64 * GB ? 8 * GB : 2 * GB);
  const stepUp = (bytes) => (!bytes ? SNAP[0]
    : Math.min(TARGET_MAX, roundCapacity(bytes + fineStep(bytes)), nextPreset(bytes) > bytes ? nextPreset(bytes) : TARGET_MAX));
  const stepDown = (bytes) => {
    const below = [...SNAP].reverse().find((v) => v < bytes);
    return Math.max(GB, roundCapacity(bytes - fineStep(bytes - 1)), below ?? GB);
  };

  const LOG_MIN = Math.log(SLIDER_MIN);
  const LOG_SPAN = Math.log(TARGET_MAX) - LOG_MIN;
  const toPos = (bytes) => Math.round(
    ((Math.log(Math.min(TARGET_MAX, Math.max(SLIDER_MIN, bytes))) - LOG_MIN) / LOG_SPAN) * SLIDER_STEPS);
  /** 슬라이더 위치 → 값. 프리셋 근처면 그 프리셋과 그 자리(pos)를 돌려준다. */
  function sliderValueAt(pos) {
    const preset = SNAP.find((p) => Math.abs(toPos(p) - pos) <= SNAP_RANGE);
    if (preset) return { bytes: preset, pos: toPos(preset), snapped: true };
    return { bytes: roundCapacity(Math.exp(LOG_MIN + (pos / SLIDER_STEPS) * LOG_SPAN)), pos, snapped: false };
  }

  function render(host, data, ctx) {
    const { h, icon, formatBytes, formatCount } = ctx;
    while (host.firstChild) host.removeChild(host.firstChild);

    const t = data.totals;
    const health = data.health;
    const storageById = Object.fromEntries(data.storages.map((s) => [s.id, s]));
    const pct = (part, whole) => (whole ? Math.round((part / whole) * 100) : 0);

    // 툴팁은 하나를 돌려 쓴다. 값은 툴팁에서만 볼 수 있는 것이 없다 - 범례와 표에도 있다.
    const tip = h("div", { class: "dsb-tip", role: "tooltip" });
    tip.hidden = true;
    const showTip = (event, lines) => {
      while (tip.firstChild) tip.removeChild(tip.firstChild);
      lines.forEach((line, i) => tip.appendChild(h("div", { class: i ? "dsb-tip-sub" : "dsb-tip-main" }, [line])));
      tip.hidden = false;
      const x = Math.min(event.clientX + 12, window.innerWidth - tip.offsetWidth - 8);
      tip.style.left = `${x}px`;
      tip.style.top = `${event.clientY + 14}px`;
    };
    const hideTip = () => { tip.hidden = true; };

    // ---------------------------------------------------------- 머리 + Validate 결과
    const validateBtn = h("button", { class: "btn compact dsb-validate" },
      [icon("check", 12), h("span", {}, ["Validate Collection"])]);
    const validation = h("div", { class: "dsb-validation", "aria-live": "polite" });
    const ISSUE_LABEL = { missingRom: "ROM 없음", missingMetadata: "이름 없음" };

    // 결과는 ctx에 둔다 - 표 정렬로 화면을 다시 그려도 사라지지 않고, ✕로만 지운다(사용자 요구).
    // 세부 목록은 접힌 채로 시작하고 ▼로 펼친다. 펼치면 전부 보여주되 칸 안에서 스크롤한다.
    function drawValidation() {
      while (validation.firstChild) validation.removeChild(validation.firstChild);
      const r = ctx.validation;
      if (!r) return;
      if (r.running) { validation.appendChild(h("div", { class: "dsb-muted" }, ["Metadata 파일을 검사하는 중…"])); return; }

      const clearBtn = h("button", { class: "icon-btn dsb-validate-clear", title: "결과 지우기" }, [icon("x", 10)]);
      clearBtn.addEventListener("click", () => { ctx.validation = null; ctx.validationOpen = false; drawValidation(); });

      if (!r.ok) {
        validation.appendChild(h("div", { class: "dsb-validate-head" }, [
          statusLine("bad", r.error || "검사하지 못했습니다."), h("span", { class: "dsb-validate-spacer" }), clearBtn]));
        return;
      }
      const { checked, invalid, duplicates, issues, statuses } = r.data;
      const problems = invalid.length + duplicates.length + issues.length;

      // 네 가지 상태를 늘 보여준다(사용자 요구) - Metadata Health 카드와 같은 기준이다
      // (app/dashboard.py::validate_collection).
      const summary = h("div", { class: "dsb-validate-summary" }, [
        statusLine("good", `Complete ${formatCount(statuses.complete)}`),
        statuses.missingMedia ? statusLine("warn", `Missing Media ${formatCount(statuses.missingMedia)}`) : null,
        statuses.missingDescription
          ? statusLine("warn", `Missing Description ${formatCount(statuses.missingDescription)}`) : null,
        statuses.invalidXml ? statusLine("bad", `Invalid XML ${formatCount(statuses.invalidXml)}`)
          : statusLine("good", "Invalid XML 0"),
        problems ? null : statusLine("good", `Metadata 파일 ${formatCount(checked)}개 확인 · 문제 없음`),
      ]);
      const head = h("div", { class: "dsb-validate-head" }, [summary, h("span", { class: "dsb-validate-spacer" })]);
      if (problems) {
        const toggle = h("button", { class: "btn compact dsb-validate-toggle", "aria-expanded": String(!!ctx.validationOpen) },
          [`세부 문제 ${formatCount(problems)}개 `, ctx.validationOpen ? "▲" : "▼"]);
        toggle.addEventListener("click", () => { ctx.validationOpen = !ctx.validationOpen; drawValidation(); });
        head.appendChild(toggle);
      }
      head.appendChild(clearBtn);
      validation.appendChild(head);
      if (!problems) return;

      const details = h("div", { class: "dsb-validate-details" });
      details.hidden = !ctx.validationOpen;
      const issueSection = (title, items, line) => {
        if (!items.length) return;
        details.appendChild(h("div", { class: "dsb-validate-section-title" }, [title]));
        details.appendChild(h("ul", { class: "dsb-invalid" }, items.map(line)));
      };
      issueSection(`읽을 수 없는 파일 ${formatCount(invalid.length)}개`, invalid, (item) =>
        h("li", { title: item.error }, [h("b", {}, [String(item.system).toUpperCase()]), ` ${item.path}`]));
      issueSection(`중복된 Metadata ${formatCount(duplicates.length)}개`, duplicates, (item) =>
        h("li", {}, [h("b", {}, [String(item.system).toUpperCase()]), ` ${item.filename} · ${formatCount(item.count)}개`]));
      issueSection(`ROM 연결·이름 문제 ${formatCount(issues.length)}개`, issues, (item) =>
        h("li", {}, [h("b", {}, [String(item.system).toUpperCase()]),
          ` ${item.filename} · ${item.issues.map((k) => ISSUE_LABEL[k] || k).join(", ")}`]));
      validation.appendChild(details);
    }

    validateBtn.addEventListener("click", async () => {
      validateBtn.disabled = true;
      ctx.validation = { running: true };
      drawValidation();
      const r = await ctx.onValidate();
      validateBtn.disabled = false;
      ctx.validation = r;
      ctx.validationOpen = false;
      drawValidation();
    });

    host.appendChild(h("div", { class: "dsb-head" }, [
      h("div", {}, [
        h("div", { class: "dsb-eyebrow" }, ["DASHBOARD"]),
        h("div", { class: "dsb-title" }, [data.collectionName || "Collection"]),
      ]),
      validateBtn,
    ]));
    host.appendChild(validation);
    drawValidation();

    // ---------------------------------------------------------- 요약 카드
    const tiles = h("div", { class: "dsb-tiles" });
    const tile = (label, value, sub) => tiles.appendChild(h("div", { class: "dsb-tile" }, [
      h("div", { class: "dsb-tile-label" }, [label]),
      h("div", { class: "dsb-tile-value" }, [value]),
      sub ? h("div", { class: "dsb-tile-sub" }, [sub]) : null,
    ]));
    tile("Games", formatCount(t.games), `${formatCount(health.present)}개에 ROM 있음`);
    tile("ROM", formatBytes(t.romBytes), `${formatCount(t.romCount)}개 파일`);
    tile("Media", formatBytes(t.mediaBytes), `${formatCount(t.mediaCount)}개 파일`);
    tile("Metadata", formatCount(health.metadata), `전체 ${formatCount(health.total)}개 중`);
    data.storages.forEach((s) => tile(s.label, formatBytes(s.romBytes + s.mediaBytes),
      `ROM ${formatCount(s.romCount)}개 · ${s.kind === "external" ? "External" : "Internal"}`));
    host.appendChild(tiles);

    const grid = h("div", { class: "dsb-grid" });
    host.appendChild(grid);

    // ---------------------------------------------------------- 사용량 (전체 대비 System 비율)
    const usage = card("Storage usage · ROM + Media");
    const ranked = data.systems
      .map((s) => ({ system: s.system, bytes: s.romBytes + s.mediaBytes }))
      .filter((s) => s.bytes > 0)
      .sort((a, b) => b.bytes - a.bytes);
    const total = ranked.reduce((sum, s) => sum + s.bytes, 0);
    if (!total) {
      usage.appendChild(h("div", { class: "dsb-empty" }, ["아직 스캔된 파일이 없습니다."]));
    } else {
      const parts = ranked.slice(0, TOP_SYSTEMS).map((s, i) => ({ ...s, name: s.system.toUpperCase(), color: `var(--series-${i + 1})` }));
      const rest = ranked.slice(TOP_SYSTEMS);
      if (rest.length) {
        parts.push({ name: `기타 ${rest.length}개`, bytes: rest.reduce((sum, s) => sum + s.bytes, 0), color: "var(--series-other)" });
      }
      const stack = h("div", { class: "dsb-stack", role: "img",
        "aria-label": parts.map((p) => `${p.name} ${pct(p.bytes, total)}%`).join(", ") });
      parts.forEach((p) => {
        const seg = h("div", { class: "dsb-seg", style: { flexGrow: String(p.bytes), background: p.color } });
        seg.addEventListener("mousemove", (e) => showTip(e, [p.name, `${formatBytes(p.bytes)} · ${pct(p.bytes, total)}%`]));
        seg.addEventListener("mouseleave", hideTip);
        stack.appendChild(seg);
      });
      usage.appendChild(stack);
      const legend = h("div", { class: "dsb-legend" });
      parts.forEach((p) => legend.appendChild(h("div", { class: "dsb-legend-item" }, [
        h("span", { class: "dsb-swatch", style: { background: p.color } }),
        h("span", { class: "dsb-legend-name" }, [p.name]),
        h("span", { class: "dsb-legend-value" }, [`${formatBytes(p.bytes)} · ${pct(p.bytes, total)}%`]),
      ])));
      usage.appendChild(legend);
    }
    grid.appendChild(usage);

    // ---------------------------------------------------------- 목표 용량
    const targets = card("Storage target");
    data.storages.forEach((s) => targets.appendChild(targetRow(s)));
    grid.appendChild(targets);

    function targetRow(s) {
      const used = s.romBytes + s.mediaBytes;
      const target = ctx.targets[s.id] || s.capacityBytes || null;
      const ratio = target ? used / target : 0;
      const level = !target ? "none" : ratio > 1 ? "over" : ratio >= 0.9 ? "warn" : "ok";

      const input = h("input", { class: "dsb-target-input", value: formatCapacity(target),
        placeholder: "예: 512 GB", title: "예: 512 GB, 1 TB", "aria-label": `${s.label} 목표 용량` });
      const commit = (bytes) => {
        if (!bytes) { input.value = formatCapacity(target); return; }
        // 슬라이더를 키보드로 움직이는 중이면 새로 그린 뒤에도 슬라이더에 초점을 남긴다.
        const keepFocus = document.activeElement === slider;
        ctx.onTargetChange(s.id, snap(bytes));
        const next = targetRow(s);
        row.replaceWith(next);
        if (keepFocus) next.querySelector(".dsb-target-slider").focus();
      };
      // ▲/▼(버튼과 텍스트 칸의 화살표 키)는 세밀하게 한 칸씩 움직이고 프리셋에서는 멈춘다.
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); commit(parseCapacity(input.value)); }
        else if (e.key === "ArrowUp") { e.preventDefault(); commit(stepUp(target || 0)); }
        else if (e.key === "ArrowDown") { e.preventDefault(); if (target) commit(stepDown(target)); }
      });
      input.addEventListener("change", () => commit(parseCapacity(input.value)));
      const up = h("button", { class: "dsb-spin", title: "조금 크게" }, ["▲"]);
      const down = h("button", { class: "dsb-spin", title: "조금 작게" }, ["▼"]);
      up.addEventListener("click", () => commit(stepUp(target || 0)));
      down.addEventListener("click", () => { if (target) commit(stepDown(target)); });

      // Slider - 로그 눈금 위를 연속으로 움직이고, 프리셋 근처에 오면 그 값에 딱 붙는다
      // (눈금이 켜지고 값 글자가 강조된다). 끄는 동안은 미리보기만 바꾸고(row를 새로 만들면
      // 드래그가 끊긴다), 손을 뗀 순간(change)에만 반영한다. 키보드 ←→는 프리셋 단위로 움직인다.
      const initial = target ? sliderValueAt(toPos(target)) : null;
      let current = target ? { bytes: target, snapped: SNAP.includes(target) } : null;
      const sliderValue = h("span", { class: "dsb-slider-value" + (current && current.snapped ? " snapped" : "") },
        [target ? formatCapacity(target) : "—"]);
      const slider = h("input", {
        type: "range", class: "dsb-target-slider", min: "0", max: String(SLIDER_STEPS), step: "1",
        value: String(target ? toPos(target) : 0), "aria-label": `${s.label} 목표 용량`,
        "aria-valuetext": target ? formatCapacity(target) : "목표 없음",
      });
      const ticks = h("div", { class: "dsb-slider-ticks", "aria-hidden": "true" }, SNAP.map((p) => h("span", {
        class: "dsb-tick" + (initial && initial.snapped && initial.bytes === p && target === p ? " on" : "")
          + (TICK_LABELS.has(p) ? " labeled" : ""),
        "data-bytes": String(p),
        style: { left: `calc(8px + (100% - 16px) * ${toPos(p) / SLIDER_STEPS})` },
      }, [TICK_LABELS.has(p) ? formatCapacity(p).replace(" ", "") : ""])));
      const markTicks = () => ticks.querySelectorAll(".dsb-tick").forEach((tick) =>
        tick.classList.toggle("on", !!current && current.snapped && Number(tick.dataset.bytes) === current.bytes));
      slider.addEventListener("input", () => {
        current = sliderValueAt(Number(slider.value));
        if (current.snapped) slider.value = String(current.pos);
        sliderValue.textContent = formatCapacity(current.bytes);
        sliderValue.classList.toggle("snapped", current.snapped);
        slider.setAttribute("aria-valuetext", formatCapacity(current.bytes));
        markTicks();
      });
      slider.addEventListener("change", () => { if (current) commit(current.bytes); });
      slider.addEventListener("keydown", (e) => {
        const base = target || 0;
        const to = { ArrowRight: nextPreset(base), ArrowUp: nextPreset(base),
          ArrowLeft: prevPreset(base), ArrowDown: prevPreset(base),
          Home: SNAP[0], End: SNAP[SNAP.length - 1] }[e.key];
        if (!to) return;
        e.preventDefault();
        commit(to);
      });

      const summary = !target
        ? "목표를 정하지 않았습니다"
        : `사용 ${formatBytes(used)} / 목표 ${formatCapacity(target)} · ${pct(used, target)}%`;
      const row = h("div", { class: "dsb-target", "data-storage": s.id }, [
        h("div", { class: "dsb-target-head" }, [
          h("span", { class: "dsb-target-name" }, [s.label]),
          h("span", { class: "dsb-target-kind" }, [s.kind === "external" ? "External" : "Internal"]),
          h("span", { class: "dsb-target-controls" }, [input, h("span", { class: "dsb-spins" }, [up, down])]),
        ]),
        h("div", { class: "dsb-target-slider-row" }, [
          h("div", { class: "dsb-slider-track" }, [slider, ticks]),
          sliderValue,
        ]),
        h("div", { class: "dsb-meter " + level }, [
          h("div", { class: "dsb-meter-fill", style: { width: `${Math.min(100, ratio * 100)}%` } }),
        ]),
        h("div", { class: "dsb-target-foot" }, [
          h("span", {}, [summary]),
          level === "over" ? statusLine("warn", `목표 초과 ${formatBytes(used - target)}`) : null,
          s.freeBytes != null ? h("span", { class: "dsb-muted" }, [`디스크 여유 ${formatBytes(s.freeBytes)}`]) : null,
        ]),
      ]);
      return row;
    }

    // ---------------------------------------------------------- Metadata Health
    const healthCard = card("Metadata health");
    [["Metadata", health.metadata], ["Media", health.media],
     ["Description", health.description], ["Cover", health.cover]].forEach(([label, value]) => {
      healthCard.appendChild(h("div", { class: "dsb-bar" }, [
        h("div", { class: "dsb-bar-head" }, [
          h("span", {}, [label]),
          h("span", { class: "dsb-muted" }, [`${formatCount(value)} / ${formatCount(health.total)} · ${pct(value, health.total)}%`]),
        ]),
        h("div", { class: "dsb-meter ok" }, [
          h("div", { class: "dsb-meter-fill", style: { width: `${pct(value, health.total)}%` } }),
        ]),
      ]));
    });
    const statuses = h("div", { class: "dsb-statuses" }, [statusLine("good", `Complete ${formatCount(health.complete)}`)]);
    [["Missing ROM", health.missingRom], ["Missing Media", health.missingMedia],
     ["Missing Description", health.missingDescription], ["Missing Cover", health.missingCover]]
      .filter(([, n]) => n > 0)
      .forEach(([label, n]) => statuses.appendChild(statusLine("warn", `${label} ${formatCount(n)}`)));
    healthCard.appendChild(statuses);
    grid.appendChild(healthCard);

    // ---------------------------------------------------------- System 통계 표
    const tableCard = card("System statistics");
    tableCard.classList.add("dsb-wide");
    const sort = ctx.sort || (ctx.sort = { key: "size", desc: true });
    const statusOf = (s) => (s.games === 0 ? ["muted", "Empty"]
      : s.missingMedia > 0 ? ["warn", `Media 없음 ${formatCount(s.missingMedia)}`]
      : s.missingMetadata > 0 ? ["warn", `Metadata 없음 ${formatCount(s.missingMetadata)}`]
      : ["good", "정상"]);
    const storageName = (s) => (storageById[s.storageId] || {}).label || s.storageId;
    //: [key, 머리글, 정렬 값, 칸 내용, 숫자 칸인지]
    const COLS = [
      ["system", "System", (s) => s.system, (s) => s.system.toUpperCase(), false],
      ["storage", "Storage", storageName, storageName, false],
      ["games", "Games", (s) => s.games, (s) => formatCount(s.games), true],
      ["size", "ROM size", (s) => s.romBytes, (s) => formatBytes(s.romBytes), true],
      ["media", "Media size", (s) => s.mediaBytes, (s) => formatBytes(s.mediaBytes), true],
      ["total", "Total size", (s) => s.romBytes + s.mediaBytes, (s) => formatBytes(s.romBytes + s.mediaBytes), true],
      ["status", "Status", (s) => statusOf(s)[1], null, false],
    ];
    const table = h("table", { class: "dsb-table" });
    const thead = h("thead");
    const tbody = h("tbody");
    const headRow = h("tr");
    COLS.forEach(([key, label, , , numeric]) => {
      const btn = h("button", { class: "dsb-sort" + (sort.key === key ? " on" : "") },
        [label, sort.key === key ? (sort.desc ? " ↓" : " ↑") : ""]);
      btn.addEventListener("click", () => {
        if (sort.key === key) sort.desc = !sort.desc;
        else { sort.key = key; sort.desc = numeric; }
        render(host, data, ctx);
      });
      headRow.appendChild(h("th", { class: numeric ? "num" : "",
        "aria-sort": sort.key === key ? (sort.desc ? "descending" : "ascending") : "none" }, [btn]));
    });
    thead.appendChild(headRow);
    const pick = COLS.find(([key]) => key === sort.key)[2];
    data.systems.slice().sort((a, b) => {
      const av = pick(a), bv = pick(b);
      const c = typeof av === "number" ? av - bv : String(av).localeCompare(String(bv));
      return sort.desc ? -c : c;
    }).forEach((s) => {
      const [level, label] = statusOf(s);
      const tr = h("tr", { tabindex: "0", title: `${s.system.toUpperCase()} 목록 열기`, "data-system": s.system },
        COLS.map(([key, , , cell, numeric]) => h("td", {
          class: key === "system" ? "dsb-sys" : key === "total" ? "num dsb-total" : numeric ? "num" : "",
        }, [cell ? cell(s) : statusLine(level, label)])));
      const open = () => ctx.onOpenSystem(s.system);
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
      tbody.appendChild(tr);
    });
    table.appendChild(thead);
    table.appendChild(tbody);
    tableCard.appendChild(h("div", { class: "dsb-table-wrap" }, [table]));
    grid.appendChild(tableCard);

    host.appendChild(tip);

    function card(title) {
      return h("section", { class: "dsb-card" }, [h("div", { class: "dsb-card-title" }, [title])]);
    }
    function statusLine(level, text) {
      const mark = { good: "✓", warn: "⚠", bad: "✕", muted: "–" }[level];
      return h("span", { class: `dsb-status ${level}` }, [h("span", { class: "dsb-status-icon", "aria-hidden": "true" }, [mark]), text]);
    }
  }

  window.RMSDashboard = { render, parseCapacity, formatCapacity, sliderValueAt, toPos, stepUp, stepDown };
})();
