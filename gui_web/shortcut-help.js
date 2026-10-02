/* Shortcut help uses the same modal and buttons as the rest of the app. */
window.RMSShortcutHelp = {
  open({h, msg, showModal, closeModal}) {
    const shortcuts = [
      ["Ctrl+F", "search"], ["Ctrl+A", "selectAll"], ["Ctrl+V", "paste"],
      ["Ctrl+Z", "undo"], ["Ctrl+Y", "redo"], ["F2", "rename"],
      ["F5", "refresh"], ["Ctrl+S", "save"], ["Esc", "close"],
      ["↑ / ↓ · Shift", "focus"],
    ];
    const body = h("div", {class: "shortcut-help-body"}, [
      h("p", {class: "stg-help"}, [msg("ui.help.scope")]),
      ...shortcuts.map(([keys, action]) => h("div", {class: "shortcut-help-row"}, [
        h("kbd", {}, [keys]), h("span", {}, [msg(`ui.help.${action}`)]),
      ])),
    ]);
    const card = showModal(msg("ui.help.title"), body,
      [h("button", {class: "btn", onClick: closeModal}, ["닫기"])]);
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-label", window.RMSI18n.t("ui.help.title"));
    card.querySelector("button").focus();
  },
};
