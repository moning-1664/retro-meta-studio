/* Metadata detail filename copy action. Keep filename copy out of GameList. */
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  function copyText(text) {
    if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
    return new Promise((resolve, reject) => {
      const input = document.createElement("textarea");
      input.value = text; input.setAttribute("readonly", "");
      input.style.position = "fixed"; input.style.opacity = "0";
      document.body.appendChild(input); input.select();
      try { document.execCommand("copy") ? resolve() : reject(new Error("copy failed")); }
      catch (e) { reject(e); }
      input.remove();
    });
  }
  function addDetailButton() {
    const filename = $("#detail-panel .detail-filename");
    if (!filename || filename.closest(".rms-detail-filename-row")) return;
    const row = document.createElement("div"); row.className = "rms-detail-filename-row";
    filename.parentNode.insertBefore(row, filename); row.appendChild(filename);
    const button = document.createElement("button");
    button.type = "button"; button.className = "icon-btn rms-detail-file-copy";
    button.title = "파일명 복사"; button.setAttribute("aria-label", "파일명 복사");
    button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
    button.addEventListener("click", async (e) => {
      e.preventDefault(); e.stopPropagation();
      const text = filename.textContent.trim(); if (!text) return;
      try { await copyText(text); button.classList.add("copied"); button.title = "복사됨"; setTimeout(() => { button.classList.remove("copied"); button.title = "파일명 복사"; }, 900); }
      catch (_) { button.title = "클립보드 복사 실패"; }
    });
    row.appendChild(button);
  }
  function init() {
    const style = document.createElement("style");
    style.textContent = ".rms-file-copy{display:none!important}.rms-detail-filename-row .detail-filename{user-select:text;-webkit-user-select:text;cursor:text}";
    document.head.appendChild(style);
    addDetailButton();
    new MutationObserver(addDetailButton).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
