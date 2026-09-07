// Playwright UI 회귀 테스트 설정.
// gui_web/은 순수 vanilla HTML/CSS/JS이고, api-client.js는 window.pywebview가 없으면
// 자동으로 내장 mock 모드로 전환된다 (RMApi._mockMode) - 그 특성을 이용해 실제
// pywebview/Windows 없이도 정적 서버 + 헤드리스 브라우저로 클릭/드래그/키보드
// 시나리오를 검증한다. pywebview 고유 동작(네이티브 폴더 대화상자, 실제 파일시스템
// 드래그, WebView2 렌더링 버그)은 여전히 Windows 실기 확인이 필요하다.
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests_ui",
  timeout: 30_000,
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    headless: true,
    // 이 sandbox에는 @playwright/test가 기대하는 빌드 번호와 다른 Chromium이
    // 미리 설치되어 있음 (chromium-1194) - 재다운로드 대신 그 바이너리를 직접 지정한다.
    launchOptions: { executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" },
  },
  webServer: {
    command: "python3 -m http.server 4173 --directory gui_web",
    url: "http://127.0.0.1:4173/index.html",
    reuseExistingServer: !process.env.CI,
    timeout: 15_000,
  },
});
