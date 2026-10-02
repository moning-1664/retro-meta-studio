"""
version.py
==========
RetroMeta Studio 버전 정보 (MAJOR.MINOR.PATCH).

- 시작 버전: 0.1.0.
- build_web.bat 실행 시 패키징 직전에 PATCH를 증가한다. 실패한 빌드 번호도 재사용하지 않는다.
- 사용자가 버전을 올리라고 요청하면 MINOR를 증가하고 PATCH를 0으로 초기화한다.
- python version.py --bump minor: 사용자 요청에 따른 버전 증가.
- python version.py --sync: 번호 증가 없이 UI 버전 파일 동기화.
"""

__version__ = "0.1.1"


def version_tuple():
    return tuple(int(x) for x in __version__.split("."))


def update_version(bump=None):
    """Synchronize the UI version; builds bump patch, releases bump minor."""
    import json
    import os
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent
    path = root / "version.py"
    source = path.read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"$', source, re.MULTILINE)
    if match is None:
        raise ValueError("Expected a three-part application version")
    major, minor, patch = map(int, match.groups())
    if bump == "patch":
        patch += 1
    elif bump == "minor":
        minor, patch = minor + 1, 0
    current = f"{major}.{minor}.{patch}"

    def write_atomic(target, content):
        temporary = target.with_name(target.name + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)

    write_atomic(root / "gui_web" / "version.js",
                 "// Generated from version.py; do not edit separately.\n"
                 + f"window.RMS_APP_VERSION = {json.dumps(current)};\n")
    if bump:
        source = source[:match.start()] + f'__version__ = "{current}"' + source[match.end():]
        write_atomic(path, source)
    return current


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage the application version")
    parser.add_argument("--bump", choices=("patch", "minor"))
    parser.add_argument("--sync", action="store_true")
    args = parser.parse_args()
    print(update_version(args.bump) if args.bump or args.sync else __version__)
