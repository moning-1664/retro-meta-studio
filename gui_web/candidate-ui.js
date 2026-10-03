/* Shared metadata layout for scraper, revision and conflict previews. */
(function () {
  "use strict";
  const LABELS = {
    name: "제목", desc: "설명", developer: "개발사", publisher: "배급사",
    genre: "장르", region: "지역", releasedate: "출시일", rating: "평점",
    players: "플레이어", lang: "언어", language: "언어", favorite: "즐겨찾기",
  };
  const valueText = (value) => Array.isArray(value) ? value.join(", ") : String(value ?? "");

  function fields(h, values, options = {}) {
    const grid = h("div", { class: "candidate-details-grid" });
    Object.entries(values || {}).forEach(([key, raw]) => {
      const text = valueText(raw);
      if (!text && !options.includeEmpty) return;
      const row = h(options.selected ? "label" : "div", {
        class: "candidate-detail-field" + (key === "desc" || key === "name" ? " wide" : "")
          + (options.differing?.has(key) ? " changed" : ""),
      });
      if (options.selected) {
        const checkbox = h("input", { type: "checkbox", value: key });
        checkbox.checked = options.selected.has(key);
        checkbox.addEventListener("change", () => options.onChange?.(key, checkbox.checked));
        row.appendChild(checkbox);
      }
      const content = h("div", { class: "candidate-detail-content" }, [
        h("span", { class: "candidate-detail-label" }, [LABELS[key] || key]),
      ]);
      if (options.current) {
        const current = valueText(options.current[key]);
        content.appendChild(h("span", { class: "candidate-detail-current", title: window.RMSI18n.raw(current) },
          [h("span", { class: "candidate-detail-label" }, ["기존"]), " · ",
            current ? window.RMSI18n.raw(current) : window.RMSI18n.t("ui.common.empty")]));
      }
      content.appendChild(h("span", { class: "candidate-detail-value", title: window.RMSI18n.raw(text) },
        [text ? window.RMSI18n.raw(text) : "없음"]));
      row.appendChild(content);
      grid.appendChild(row);
    });
    return grid;
  }

  function facts(h, values, toggle = null, extra = null) {
    const year = String(values?.releasedate || "").match(/\d{4}/)?.[0];
    const entries = [["연도", year], ["장르", values?.genre], ["개발사", values?.developer],
      ["배급사", values?.publisher], ["플레이어", values?.players], ["평점", values?.rating]];
    if (extra) entries.push(extra);
    const filled = entries.filter(([, value]) => value);
    const split = filled.length > 3 ? Math.ceil(filled.length / 2) : filled.length;
    const groups = split ? [filled.slice(0, split), filled.slice(split)].filter(group => group.length) : [[]];
    const rows = groups.map(group => h("div", { class: "scrape-fact-row" }, group
      .map(([label, value]) => h("span", { class: "scrape-fact", title: window.RMSI18n.message("ui.candidate.factTooltip", {label:window.RMSI18n.t(label), value:valueText(value)}) },
        [document.createTextNode(valueText(value))]))));
    if (toggle) rows.at(-1).appendChild(toggle);
    return h("div", { class: "scrape-candidate-facts" }, rows);
  }
  window.RMSCandidateUI = { fields, facts };
})();
