// Playwright UI 회귀 테스트 설정.
//
// gui_web/은 순수 vanilla HTML/CSS/JS이고, api-client.js는 window.pywebview가 없으면
// 자동으로 내장 mock으로 폴백한다(`api.isMock()`) - 그 특성을 이용해 pywebview 없이
// 정적 서버 + 헤드리스 브라우저로 클릭/입력/스크롤 시나리오를 검증한다.
//
// [이 PC 기준으로 고친 것] 이 설정은 이전 프로젝트(RetroGameManager)에서 가져왔는데,
// 거기 값은 리눅스 샌드박스 전용이라 여기서는 한 줄도 동작하지 않았다:
//   - `executablePath: /opt/pw-browsers/...` : 존재하지 않는 경로 -> 브라우저 못 띄움.
//     제거해서 `npx playwright install chromium`이 받아둔 것을 쓰게 했다.
//   - `python3` : Windows 파이썬 런처는 `python`이다.
// 목업이 다루지 못하는 것(네이티브 폴더 대화상자, 실제 파일 I/O, WebView2 고유 렌더링)은
// 여전히 실기 확인이 필요하다.
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests_ui",
  timeout: 30_000,
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    headless: true,
  },
  webServer: {
    command: "python -m http.server 4173 --directory gui_web",
    url: "http://127.0.0.1:4173/index.html",
    reuseExistingServer: !process.env.CI,
    timeout: 20_000,
  },
});
