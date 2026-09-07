"""
app/model/constants.py
=======================
Frontend/Media/System 이름에 대한 상수와 정규화.

이전 `config.py`에서 살아남은 부분만 옮겼다. `config.json` 로드/저장과 Local 등록
기능은 registry.db(`app/store/registry.py`)가 대체하므로 함께 사라졌다 - 두 곳에서
동시에 저장하다 파일이 깨지던 문제도 그래서 없어졌다.

System 이름 정규화는 계속 필요하다. 같은 플랫폼을 Collection마다 다른 폴더명으로
쓰는 경우가 실제로 있고(ES-DE의 `msx` / `msx1`), Collection 간 복사·비교는 그
차이를 넘어서 같은 것으로 봐야 한다. 다만 **폴더명 자체는 절대 바꾸지 않는다** -
정규화된 이름은 매칭에만 쓰고, 파일을 읽고 쓸 때는 각 Collection의 원본 이름을
그대로 쓴다.
"""

from __future__ import annotations

MEDIA_TYPES = ("3dboxes", "covers", "marquees", "miximages", "screenshots", "videos", "wheel")
#: Detail 패널 Media 탭에 기본 노출하는 타입(비디오 제외)
MEDIA_TYPES_UI = ("covers", "miximages", "screenshots", "wheel")
DEFAULT_MEDIA_TAB = "covers"

FRONTEND_LABELS = {
    "es-de": "ES-DE",
    "pegasus": "Pegasus",
    "emulationstation": "EmulationStation",
    "launchbox": "LaunchBox",
}

# 같은 플랫폼을 가리키는 ES-DE 폴더명들. 매칭용 정규화에만 쓴다.
ESDE_SYSTEM_ALIASES = {
    "msx1": "msx", "msx": "msx",
    "famicom": "nes", "nes": "nes",
    "genesis": "megadrive", "megadrive": "megadrive", "md": "megadrive",
    "sfc": "sfc",
    "pcengine": "pcengine", "turbografx16": "pcengine",
    "pcenginecd": "pcenginecd", "turbografxcd": "pcenginecd",
}

# ES-DE가 만들지만 게임 시스템이 아닌 폴더
ESDE_IGNORED_SYSTEMS = {"cleanup"}


def normalize_system(frontend, raw_system, overrides=None) -> str:
    """매칭에 쓸 정규화된 System 이름. 사용자가 지정한 override가 항상 우선한다."""
    raw = str(raw_system or "")
    if overrides and raw in overrides:
        return overrides[raw]
    if str(frontend or "").lower() == "es-de":
        return ESDE_SYSTEM_ALIASES.get(raw.lower(), raw)
    return raw


def denormalize_system(normalized, overrides=None) -> str:
    """정규화된 이름으로부터 이 Collection의 실제 폴더명을 되찾는다."""
    for raw, canon in (overrides or {}).items():
        if canon == normalized:
            return raw
    return normalized
