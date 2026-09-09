"""E2E 하네스 - **실제 파이썬 Api**를 HTTP로 노출하고 gui_web을 함께 서빙한다.

기존 Playwright 62개는 `api-client.js`의 목업 위에서 돈다. 화면 로직은 검증하지만
**"화면이 성공이라고 말한 것"과 "실제로 파일이 그렇게 됐는가"는 구별하지 못한다.**
목업은 파일을 건드리지 않기 때문이다.

여기서는 그 사슬을 끝까지 잇는다.

    브라우저 -> api-client.js -> HTTP -> bridge.api.Api -> FileOperationEngine
             -> 실제 파일 -> Cache/DB -> 다시 화면

테스트(Node)는 같은 기계에서 돌므로 `fs`로 **실제 파일을 직접 확인**한다. 그것이 이
하네스의 존재 이유다 - 화면의 토스트 문구를 믿지 않는다.

작업 공간은 매번 새 임시 폴더에 만든다. 사용자의 실제 자료는 건드리지 않는다.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bridge.api import Api   # noqa: E402

GUI_DIR = ROOT / "gui_web"

GAMELIST = """<?xml version="1.0"?>
<alternativeEmulator>
\t<label>PCSX2</label>
</alternativeEmulator>
<gameList>
\t<game>
\t\t<path>./FFX.iso</path>
\t\t<name>Final Fantasy X</name>
\t\t<genre>RPG</genre>
\t\t<developer>Square</developer>
\t\t<playcount>17</playcount>
\t</game>
\t<game>
\t\t<path>./MGS2.iso</path>
\t\t<name>Metal Gear Solid 2</name>
\t\t<genre>Action</genre>
\t</game>
</gameList>
"""


def build_workspace(base: Path) -> dict:
    """ROM/media/gamelist가 실제로 있는 Collection 두 개를 만든다.

    source에는 게임 둘, target은 비어 있다 - "가져오기"가 실제로 파일을 옮기는지
    보려면 받는 쪽이 비어 있어야 한다.
    """
    source = base / "source"
    (source / "gamelists" / "ps2").mkdir(parents=True)
    (source / "gamelists" / "ps2" / "gamelist.xml").write_text(GAMELIST, encoding="utf-8")
    (source / "ps2").mkdir(parents=True)
    (source / "ps2" / "FFX.iso").write_bytes(b"FFX-ROM" * 200)
    (source / "ps2" / "MGS2.iso").write_bytes(b"MGS2-ROM" * 150)
    covers = source / "downloaded_media" / "ps2" / "covers"
    covers.mkdir(parents=True)
    (covers / "FFX.png").write_bytes(b"FFX-COVER" * 40)
    (source / "downloaded_media" / "ps2" / "videos").mkdir(parents=True)

    target = base / "target"
    (target / "gamelists" / "ps2").mkdir(parents=True)
    (target / "gamelists" / "ps2" / "gamelist.xml").write_text(
        '<?xml version="1.0"?>\n<gameList/>\n', encoding="utf-8")
    (target / "ps2").mkdir(parents=True)
    (target / "downloaded_media" / "ps2" / "covers").mkdir(parents=True)

    # --- Import 검증용: 메타데이터 폴더와 ROM 폴더를 **떨어뜨려** 둔다 -------
    # 사용자의 실제 배치(ES-DE 백업과 C:\Games\ROMs가 서로 다른 곳)를 그대로 흉내낸다.
    # 여기는 API로 미리 Collection을 만들지 않는다 - 실제 Import 다이얼로그가
    # 이 두 경로를 따로 받아 하나의 Collection으로 합치는지가 검증 대상이다.
    fresh_meta = base / "fresh_meta"
    (fresh_meta / "gamelists" / "snes").mkdir(parents=True)
    (fresh_meta / "gamelists" / "snes" / "gamelist.xml").write_text(
        '<?xml version="1.0"?>\n<gameList>\n'
        '  <game><path>./Zelda.sfc</path><name>Zelda</name><genre>Action</genre></game>\n'
        '</gameList>\n', encoding="utf-8")
    fresh_roms = base / "fresh_roms"
    (fresh_roms / "snes").mkdir(parents=True)
    (fresh_roms / "snes" / "Zelda.sfc").write_bytes(b"ZELDA-ROM" * 100)
    # gba는 메타데이터가 없다 - ROM 폴더에만 있는 System도 딸려 오는지 함께 본다.
    (fresh_roms / "gba").mkdir(parents=True)
    (fresh_roms / "gba" / "Metroid.gba").write_bytes(b"METROID-ROM" * 80)

    # --- Storage 이동 검증용: System 하나 + 빈 External 폴더 -----------------
    storage_root = base / "storagetest"
    (storage_root / "gamelists" / "snes").mkdir(parents=True)
    (storage_root / "gamelists" / "snes" / "gamelist.xml").write_text(
        '<?xml version="1.0"?>\n<gameList/>\n', encoding="utf-8")
    (storage_root / "snes").mkdir(parents=True)
    (storage_root / "snes" / "Zelda.sfc").write_bytes(b"ZELDA-ROM" * 100)
    storage_external = base / "storage_external"
    storage_external.mkdir(parents=True)

    return {"source": source, "target": target, "fresh_meta": fresh_meta,
            "fresh_roms": fresh_roms, "storage_root": storage_root,
            "storage_external": storage_external}


class Harness:
    def __init__(self):
        self.base = Path(tempfile.mkdtemp(prefix="rms_e2e_"))
        self.roots = build_workspace(self.base)
        self.api = Api(registry_path=self.base / "registry.db", cache_dir=self.base / "cache")
        self.ids = {}
        for name in ("source", "target"):
            result = self.api.create_collection(
                name.capitalize(), "es-de", str(self.roots[name]))
            self.ids[name] = result["data"]["id"]
            job = self.api.start_scan(self.ids[name], True)["data"]["jobId"]
            self._wait(job)

        # Storage 이동 검증용 - Internal에 System 하나, External은 미리 붙여만 두고
        # 비운다. 드래그 자체가 실제로 파일을 옮기는지가 검증 대상이다.
        storage_result = self.api.create_collection(
            "Storagetest", "es-de", str(self.roots["storage_root"]))
        self.ids["storagetest"] = storage_result["data"]["id"]
        self._wait(self.api.start_scan(self.ids["storagetest"], True)["data"]["jobId"])
        ext = self.api.add_external_storage(
            self.ids["storagetest"], "SD", str(self.roots["storage_external"]))
        self.external_storage_id = ext["data"]

    def _wait(self, job_id, timeout=30.0):
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            progress = self.api.get_job_progress(job_id)["data"]
            if progress.get("done"):
                return progress
            time.sleep(0.02)
        raise TimeoutError(f"작업이 끝나지 않았다: {job_id}")

    def info(self) -> dict:
        return {
            "base": str(self.base),
            "sourceRoot": str(self.roots["source"]),
            "targetRoot": str(self.roots["target"]),
            "sourceId": self.ids["source"],
            "targetId": self.ids["target"],
            "freshMetaRoot": str(self.roots["fresh_meta"]),
            "freshRomsRoot": str(self.roots["fresh_roms"]),
            "storageRoot": str(self.roots["storage_root"]),
            "storageExternalRoot": str(self.roots["storage_external"]),
            "storagetestId": self.ids["storagetest"],
            "externalStorageId": self.external_storage_id,
        }

    def close(self):
        try:
            self.api.close()
        finally:
            shutil.rmtree(self.base, ignore_errors=True)


def make_handler(harness: Harness):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(GUI_DIR), **kwargs)

        def log_message(self, *_args):
            pass        # 요청 로그가 Playwright 출력을 덮는다

        def _json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/__workspace"):
                return self._json(harness.info())
            return super().do_GET()

        def do_POST(self):
            if not self.path.startswith("/__api/"):
                return self._json({"ok": False, "error": "알 수 없는 경로"}, 404)
            name = self.path[len("/__api/"):].split("?")[0]
            length = int(self.headers.get("Content-Length") or 0)
            args = json.loads(self.rfile.read(length) or "[]")

            method = getattr(harness.api, name, None)
            if method is None or name.startswith("_"):
                return self._json({"ok": False, "error": f"없는 호출: {name}"})
            try:
                return self._json(method(*args))
            except Exception as exc:                      # noqa: BLE001
                # Api는 보통 @guarded로 감싸져 있어 여기까지 오지 않는다. 와도
                # 서버가 죽지 않아야 테스트가 원인을 볼 수 있다.
                return self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    return Handler


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4174
    harness = Harness()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(harness))
    print(f"E2E 하네스: http://127.0.0.1:{port}/index.html?bridge=http", flush=True)
    print(json.dumps(harness.info(), ensure_ascii=False), flush=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        harness.close()


if __name__ == "__main__":
    main()
