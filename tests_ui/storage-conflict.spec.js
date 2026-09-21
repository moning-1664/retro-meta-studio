// External Storage 정체성 - 같은 System 폴더가 두 Storage에 있으면 충돌(빨간 !, 쓰기 막힘),
// 한쪽 이름 바꾸기/삭제로 해결, Storage 설정(Android Storage ID), ES-DE XML 결과, External 추가 시 연결.
const { test, expect } = require("@playwright/test");
const { openApp, modalButton } = require("./_helpers");

const CONFLICT = {
  ps2: [
    { storageId: "internal", label: "Internal", path: "D:\\ES-DE\\ps2", name: "ps2" },
    { storageId: "ext-1", label: "External SD", path: "E:\\ROMs\\ps2", name: "ps2" },
  ],
};
const withConflict = async (page) => {
  await page.addInitScript((c) => { window.__RMS_MOCK_CONFLICTS = c; }, CONFLICT);
  await openApp(page);
};
const ps2Row = (page) => page.locator(".nav-system", { hasText: "PS2" });

test.describe("충돌 표시와 쓰기 막힘", () => {
  test.beforeEach(async ({ page }) => { await withConflict(page); });

  test("충돌한 System에 빨간 !와 두 경로가 보인다", async ({ page }) => {
    const badge = ps2Row(page).locator(".nav-conflict");
    await expect(badge).toHaveText("!");
    await expect(badge).toHaveAttribute("title", /D:\\ES-DE\\ps2/);
    await expect(badge).toHaveAttribute("title", /E:\\ROMs\\ps2/);
    await expect(ps2Row(page)).toHaveClass(/conflict/);
    await expect(page.locator(".nav-system", { hasText: "SNES" }).locator(".nav-conflict")).toHaveCount(0);
  });

  test("Detail의 저장 버튼이 막힌다", async ({ page }) => {
    await page.locator(".lrow", { hasText: "FFX.iso" }).locator(".lc-file").click();
    await expect(page.locator(".detail-save")).toBeDisabled();
    await expect(page.locator(".detail-save")).toContainText("쓰기 막힘");
  });

  test("우클릭 메뉴에 양쪽의 이름 바꾸기/삭제가 있다", async ({ page }) => {
    await ps2Row(page).click({ button: "right" });
    for (const label of ["Internal 폴더 이름 바꾸기…", "Internal 폴더 삭제…", "External SD 폴더 이름 바꾸기…", "External SD 폴더 삭제…"]) {
      await expect(page.locator(".ctx-menu .ctx-item", { hasText: label })).toBeEnabled();
    }
    await expect(page.locator(".ctx-menu .ctx-item", { hasText: "System 이름 바꾸기…" })).toBeDisabled();
  });

  test("한쪽 이름을 바꾸면 요청하고, 충돌 표시가 사라진다", async ({ page }) => {
    await page.evaluate(() => {
      window.__renamed = [];
      const original = window.api.renameSystemFolder;
      window.api.renameSystemFolder = (...args) => { window.__renamed.push(args); return original(...args); };
    });
    await ps2Row(page).click({ button: "right" });
    await page.locator(".ctx-menu .ctx-item", { hasText: "External SD 폴더 이름 바꾸기…" }).click();
    await page.locator(".rename-system-input").fill("ps2sd");
    await page.locator(".rename-system-save").click();
    await expect.poll(() => page.evaluate(() => window.__renamed)).toEqual([["c1", "ps2", "ext-1", "ps2sd"]]);
    await expect(page.locator(".nav-conflict")).toHaveCount(0);
  });

  test("한쪽 폴더 삭제는 확인을 체크해야 되고, 끝나면 충돌이 풀린다", async ({ page }) => {
    await ps2Row(page).click({ button: "right" });
    await page.locator(".ctx-menu .ctx-item", { hasText: "External SD 폴더 삭제…" }).click();
    await expect(page.locator(".sysdel-warning")).toContainText("ROM 폴더만");
    await expect(page.locator(".sysdel-kept")).toContainText("Internal");
    await expect(modalButton(page, "확인")).toBeDisabled();
    await page.locator(".sysdel-ack-input").check();
    await modalButton(page, "확인").click();
    await expect(page.locator(".nav-conflict")).toHaveCount(0);
  });
});

test.describe("External Storage 설정과 연결", () => {
  test.beforeEach(async ({ page }) => { await openApp(page); });

  test("External 그룹의 설정에서 기기 경로(전체 경로)를 저장한다", async ({ page }) => {
    await page.evaluate(() => {
      window.__updated = [];
      const original = window.api.updateStorage;
      window.api.updateStorage = (...args) => { window.__updated.push(args); return original(...args); };
    });
    const head = page.locator(".nav-group-head", { hasText: "EXTERNAL SD" });
    await head.locator(".storage-settings-btn").click();
    // Storage ID 칸은 없다 - 전체 경로 하나만 받는다(사용자 결정).
    await expect(page.locator(".storage-device-id")).toHaveCount(0);
    await page.locator(".storage-device-root").fill("/storage/1234-ABCD/Roms");
    await page.locator(".storage-settings-save").click();
    await expect(page.locator(".toast-msg")).toHaveText("Storage 설정을 저장했습니다.");
    const args = await page.evaluate(() => window.__updated[0]);
    expect([args[0], args[1], args[5]]).toEqual(["c1", "ext-1", "/storage/1234-ABCD/Roms"]);
  });

  // 실사용 피드백 - "Internal의 옵션에 들어있는 Android Storage ID, Storage
  // 경로는 의미없다." write_custom_systems()가 Internal을 애초에 건너뛰므로
  // (Android는 %ROMPATH%를 쓴다) 그 필드를 채워도 아무 데도 쓰이지 않는다.
  test("Internal 설정에는 Android Storage ID/경로 칸이 아예 없다", async ({ page }) => {
    const head = page.locator(".nav-group-head", { hasText: "INTERNAL" });
    await head.locator(".storage-settings-btn").click();
    await expect(page.locator(".modal-title")).toContainText("설정");
    await expect(page.locator(".storage-device-id")).toHaveCount(0);
    await expect(page.locator(".storage-device-root")).toHaveCount(0);
    await expect(page.locator(".modal-body")).not.toContainText("Android Storage ID");
    // 이름은 여전히 바꿀 수 있다 - Internal도 이름 자체는 뜻이 있다.
    await expect(page.locator(".storage-label")).toBeVisible();
  });

  test("Internal 설정 저장은 device_id/device_root를 건드리지 않는다", async ({ page }) => {
    await page.evaluate(() => {
      window.__updated = [];
      const original = window.api.updateStorage;
      window.api.updateStorage = (...args) => { window.__updated.push(args); return original(...args); };
    });
    await page.locator(".nav-group-head", { hasText: "INTERNAL" }).locator(".storage-settings-btn").click();
    await page.locator(".storage-settings-save").click();
    const args = await page.evaluate(() => window.__updated[0]);
    expect(args[4]).toBeNull();   // deviceId
    expect(args[5]).toBeNull();   // deviceRoot
  });

  test("/로 시작하지 않는 기기 경로는 저장하지 않고 알린다", async ({ page }) => {
    await page.evaluate(() => {
      window.api.updateStorage = async () => ({ ok: false, error: "기기 경로는 /로 시작해야 합니다(예: /storage/1234-ABCD/ROMs)." });
    });
    await page.locator(".nav-group-head", { hasText: "EXTERNAL SD" }).locator(".storage-settings-btn").click();
    await page.locator(".storage-device-root").fill("storage/x");
    await page.locator(".storage-settings-save").click();
    await expect(page.locator(".toast-msg")).toContainText("/로 시작");
    await expect(page.locator(".storage-device-root")).toBeVisible();
  });

  test("ES-DE XML 결과에 기기 경로가 없어 빠진 System을 알려준다", async ({ page }) => {
    // XML 생성은 이제 Storage 설정 안에 있다(사용자 결정 - 그룹 머리의 아이콘이었을
    // 때는 External이 여럿이면 "어느 그룹에서 눌러도 전체를 다시 쓴다"가 안 보였다).
    await page.evaluate(() => {
      window.api.runAdapterAction = async () => ({ ok: true, data: {
        path: "D:\\ES-DE\\custom_systems\\es_systems.xml", platform: "android", systems: [], written: false,
        needsDeviceId: ["ps2"], noTemplate: [], kept: [] } });
    });
    await page.locator(".nav-group-head", { hasText: "EXTERNAL SD" }).locator(".storage-settings-btn").click();
    await page.locator(".modal-actions .btn", { hasText: "ES-DE XML 생성" }).click();
    const row = page.locator(".xml-row", { hasText: "ps2" });
    await expect(row).toHaveClass(/warn/);
    await expect(row).toContainText("기기 경로 없음");
  });

  test("External Storage를 지우고 다시 추가하면 그 밑의 System을 연결한다", async ({ page }) => {
    // Add External Storage는 External이 없을 때만 보인다(사용자 결정) - 이미
    // 있는 것을 먼저 지운다.
    await page.locator(".nav-group-head", { hasText: "EXTERNAL SD" }).locator(".storage-remove-btn").click();
    await modalButton(page, "확인").click();
    await expect(page.locator(".nav-action", { hasText: "Add External Storage" })).toBeVisible();

    await page.evaluate(() => {
      window.__attached = [];
      window.api.attachStorageSystems = async (id, storageId) => {
        window.__attached.push([id, storageId]);
        return { ok: true, data: { added: [], moved: [], conflicts: ["ps2"] } };
      };
    });
    await page.locator(".nav-action", { hasText: "Add External Storage" }).click();
    await page.locator(".modal-body input.field-input").nth(1).fill("F:\\ROMs");
    await modalButton(page, "추가").click();
    await expect.poll(() => page.evaluate(() => window.__attached.length)).toBe(1);
    await expect(page.locator(".toast-msg")).toContainText("충돌 1개 (ps2)");
  });
});
