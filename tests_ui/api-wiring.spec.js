// [P2 리뷰 반영] app.js -> api-client.js -> api.py 사이에 메서드 이름이 하나라도
// 어긋나면 UI 버튼은 있는데 실제 기능은 죽는다(이번에 발견된 P0: api.startExportToLocal()
// 이 app.js엔 있는데 api-client.js/api.py 어디에도 없었음). mock의 unknown-call
// fallback이 `ok(true)`라 Playwright UI 테스트로는 이런 누락을 못 잡는다 - 이 테스트는
// 브라우저를 띄우지 않고 두 파일을 정적으로 파싱해서, app.js가 실제로 호출하는
// api.<method>() 전부가 api-client.js의 RMApi 객체에 정의돼 있는지만 확인한다
// (Python 쪽 존재 여부는 test_api_wiring.py에서 별도 확인).
const { test, expect } = require("@playwright/test");
const fs = require("fs");
const path = require("path");

function stripComments(src) {
  // 블록 주석과 줄 주석을 지워서 주석 안의 "api.foo()" 예시가 오탐되지 않게 한다.
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
}

test("app.js가 호출하는 모든 api.<method>()가 api-client.js의 RMApi에 정의돼 있다", async () => {
  const appJsPath = path.join(__dirname, "..", "gui_web", "app.js");
  const apiClientPath = path.join(__dirname, "..", "gui_web", "api-client.js");
  const appJs = stripComments(fs.readFileSync(appJsPath, "utf-8"));
  const apiClientJs = fs.readFileSync(apiClientPath, "utf-8");

  const calledMethods = new Set();
  for (const m of appJs.matchAll(/\bapi\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\(/g)) {
    calledMethods.add(m[1]);
  }
  expect(calledMethods.size).toBeGreaterThan(10); // 파싱 자체가 깨져서 0개 뽑히는 사고 방지

  // RMApi = { ... } 객체 리터럴 블록 안에서 "methodName: (" 또는 "methodName(" 형태로
  // 정의된 이름만 뽑는다(내부 헬퍼인 _call/_mockCall 등 밑줄로 시작하는 것 제외).
  const rmApiBlockMatch = apiClientJs.match(/const RMApi = \{([\s\S]*)\n\s*\};\s*\n\s*window\.RMApi/);
  expect(rmApiBlockMatch, "api-client.js에서 RMApi 객체 리터럴을 못 찾음 - 정규식이 파일 구조와 어긋남").toBeTruthy();
  const rmApiBlock = rmApiBlockMatch[1];
  const definedMethods = new Set();
  for (const m of rmApiBlock.matchAll(/^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*[:(]/gm)) {
    if (!m[1].startsWith("_")) definedMethods.add(m[1]);
  }
  expect(definedMethods.size).toBeGreaterThan(10);

  const missing = [...calledMethods].filter((m) => !definedMethods.has(m)).sort();
  expect(missing, `app.js가 호출하지만 api-client.js RMApi에 없는 메서드: ${missing.join(", ")}`).toEqual([]);
});
