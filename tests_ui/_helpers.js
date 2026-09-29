// GUI 테스트 공용 헬퍼.
//
// 이전 프로젝트에서는 모든 spec이 같은 `beforeEach(goto + 첫 렌더 대기)`를 각자
// 복사해 갖고 있었다. 여기서는 한 곳에 둔다 - 초기화 타이밍이 바뀌면 고칠 곳도 하나다.
//
// [타이밍 주의] app.js는 pywebview가 없을 때 `pywebviewready`를 받지 못하므로
// 400ms 타이머로 init()을 늦게 부른다. 그래서 첫 렌더는 즉시 오지 않는다 -
// 반드시 expect()의 auto-wait로 기다려야 하고, 고정 sleep을 넣으면 안 된다.
const { expect } = require("@playwright/test");

async function openApp(page, { archiveUnconfigured = false } = {}) {
  await page.goto(archiveUnconfigured ? "/index.html" : "/index.html?archive=on");
  // 목업 모드로 떴는지부터 확인한다 - 실수로 실제 브릿지에 붙으면 테스트가
  // 조용히 다른 것을 검증하게 된다.
  await expect.poll(() => page.evaluate(() => window.api && window.api.isMock())).toBe(true);
  // init()이 끝나 첫 Collection 탭이 열릴 때까지.
  await expect(page.locator(".ctab").first()).toBeVisible();
  await expect(page.locator(".lrow").first()).toBeVisible();
}

/** 모달의 "저장"/"추가" 같은 확정 버튼. */
function modalButton(page, label) {
  return page.locator(".modal-actions .btn", { hasText: label });
}

module.exports = { openApp, modalButton };
