// 실제 파일시스템 E2E 설정.
//
// `playwright.config.js`(tests_ui/)와 **분리한 이유**: 저쪽은 목업 위에서 도는 빠른 UI
// 회귀라 병렬로 돌려도 되지만, 이쪽은 실제 Api 인스턴스 하나와 실제 파일을 공유한다.
// 한 파일 안에서 순서대로 돌아야 "붙여넣고 실행한 결과를 다음 테스트가 다시 읽는"
// 시나리오가 성립한다.
//
// 테스트 개수를 늘리는 것이 목적이 아니다. 목업이 절대 답할 수 없는 질문 -
// "화면이 성공이라고 말한 것이 실제 파일에도 일어났는가" - 만 여기 둔다.
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests_e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,               // Api 인스턴스와 임시 작업 공간을 공유한다
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4174",
    headless: true,
  },
  webServer: {
    command: "python tests_e2e/server.py 4174",
    url: "http://127.0.0.1:4174/__workspace",
    reuseExistingServer: false,   // 매번 깨끗한 임시 작업 공간에서 시작한다
    timeout: 60_000,
  },
});
