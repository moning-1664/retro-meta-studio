"""
bridge/media_server.py
=======================
영상 파일을 WebView에 흘려 주는 로컬 전용 HTTP 서버.

화면은 pywebview 내장 서버가 `gui_web` 폴더만 서빙한다. Collection의 영상은 그 밖(사용자
디스크 어디든)에 있어서 페이지가 경로로 가리킬 수 없고, 수~수십 MB 영상을 브릿지로 base64
문자열에 실어 보내는 것은 현실적이지 않다(이미지는 그렇게 한다). 그래서 영상만 여기로 돌린다.

- 127.0.0.1에만 묶는다. 포트는 운영체제가 고른다.
- **경로를 URL에 싣지 않는다.** 앱이 허락한 파일마다 추측할 수 없는 토큰을 발급하고, 토큰에
  없는 요청은 404다 - 같은 PC의 다른 프로그램이 이 포트로 임의 파일을 읽을 수 없다.
- Range 요청(206)을 지원한다. `<video>`는 탐색·반복 재생 때 부분 요청을 보낸다.
- 처음 쓸 때 켠다. 영상을 한 번도 안 보면 서버도 뜨지 않는다.
"""

from __future__ import annotations

import mimetypes
import secrets
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

#: WebView(Chromium)가 재생할 수 있는 컨테이너만 내준다. .avi/.mkv는 재생되지 않으므로
#: URL을 주지 않고 화면이 Screenshot을 그대로 두게 한다.
PLAYABLE = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".ogv": "video/ogg",
            ".mov": "video/mp4"}
MAX_TOKENS = 256
CHUNK = 256 * 1024


def playable(path) -> bool:
    return Path(str(path)).suffix.lower() in PLAYABLE


class MediaServer:
    def __init__(self):
        self._server = None
        self._thread = None
        self._lock = threading.Lock()
        self._files: OrderedDict[str, Path] = OrderedDict()

    # ------------------------------------------------------------------
    def url_for(self, path) -> str | None:
        """이 파일을 재생할 URL. 재생할 수 없는 형식이거나 파일이 없으면 None."""
        path = Path(str(path))
        if not playable(path) or not path.is_file():
            return None
        self._ensure_started()
        with self._lock:
            # 같은 파일은 같은 토큰을 다시 쓴다 - 게임을 오갈 때마다 브라우저 캐시가 살아 있게.
            token = next((t for t, p in self._files.items() if p == path), None)
            if token is None:
                token = secrets.token_urlsafe(18)
                self._files[token] = path
                while len(self._files) > MAX_TOKENS:
                    self._files.popitem(last=False)
            else:
                self._files.move_to_end(token)
        return f"http://127.0.0.1:{self._server.server_address[1]}/v/{token}{path.suffix.lower()}"

    def resolve(self, token) -> Path | None:
        with self._lock:
            return self._files.get(token)

    def stop(self):
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()

    # ------------------------------------------------------------------
    def _ensure_started(self):
        with self._lock:
            if self._server is not None:
                return
            owner = self

            class Handler(_Handler):
                media = owner

            self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            self._server.daemon_threads = True
            self._thread = threading.Thread(target=self._server.serve_forever, name="media-server", daemon=True)
            self._thread.start()


class _Handler(BaseHTTPRequestHandler):
    media: MediaServer = None

    def log_message(self, *args):   # 콘솔을 요청 로그로 채우지 않는다
        pass

    def do_HEAD(self):
        self._serve(head=True)

    def do_GET(self):
        self._serve(head=False)

    def _serve(self, head):
        parts = self.path.split("?", 1)[0].strip("/").split("/")
        token = parts[1].split(".", 1)[0] if len(parts) == 2 and parts[0] == "v" else ""
        path = self.media.resolve(token) if token else None
        if path is None or not path.is_file():
            self.send_error(404)
            return
        size = path.stat().st_size
        start, end = 0, size - 1
        status = 200
        header = self.headers.get("Range")
        if header and header.startswith("bytes="):
            try:
                first, last = header[len("bytes="):].split(",", 1)[0].split("-", 1)
                if first:
                    start = int(first)
                    end = int(last) if last else size - 1
                else:                      # bytes=-N : 끝에서 N바이트
                    start = max(0, size - int(last))
                end = min(end, size - 1)
                if start > end or start >= size:
                    raise ValueError
                status = 206
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        self.send_response(status)
        mime = PLAYABLE.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_header("Content-Type", mime)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "private, max-age=3600")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head:
            return
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = handle.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass   # 게임을 넘기면 브라우저가 연결을 끊는다 - 정상이다
