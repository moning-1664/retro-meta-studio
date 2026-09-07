"""
config.py
=========
프로그램 설정(config.json) 로드/저장.
- Local 최대 4개
- Local: rom_path / metadata_path / media_path 분리 저장
- MasterDB 경로
- system_cores (RetroArch core 매핑)
- Export 옵션
- ScreenScraper 인증 정보

설계서 v2 §2.1, §7, §16 참조
"""

import json
import os
import sys
import threading
from pathlib import Path
from datetime import datetime

# [체감 속도 리뷰 반영] save_config()는 여러 스레드(background job/사용자 클릭)에서
# 동시에 호출될 수 있는데, 예전엔 CONFIG_PATH를 곧바로 열어 덮어써서 두 쓰기가
# 겹치면 파일이 깨질 수 있었다. 프로세스 내 호출끼리는 락으로 직렬화하고,
# 디스크에는 임시 파일에 다 쓴 뒤 os.replace()로 원자적으로 바꿔치기한다(중간에
# 죽어도 절반만 쓰인 config.json이 남지 않음).
_SAVE_LOCK = threading.Lock()

# [설계] "실행 파일과 동일 디렉토리"에 config.json을 둔다.
# 개발 중(python main.py)에는 이 파일(config.py)이 있는 폴더가 곧 실행 위치이고,
# 추후 PyInstaller 등으로 패키징(.exe)하면 sys.frozen이 True가 되며 실행 파일 경로 기준으로 바뀐다.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

CONFIG_PATH = BASE_DIR / "config.json"
BACKUP_DIR = BASE_DIR / "backup"  # MasterDB 백업 저장 위치 (설계서 후속 §백업/복원)
MAX_LOCALS = 4

SUPPORTED_FRONTENDS = ["es-de", "daijisho", "pegasus", "emulationstation", "launchbox"]

FRONTEND_LABELS = {
    "es-de": "ES-DE",
    "daijisho": "다이지쇼",
    "pegasus": "Pegasus",
    "emulationstation": "EmulationStation",
    "launchbox": "LaunchBox",
}

# Frontend별 ROM 경로와 Metadata 경로가 동일 디렉토리를 쓰는지 여부
# True인 Frontend는 GUI에서 ROM 경로 필드를 비활성(회색)으로 표시하고 Metadata 경로 값을 미러링한다.
FRONTEND_ROM_METADATA_SAME_DIR = {
    "es-de": False,          # gamelist.xml 위치와 rom_root가 다를 수 있음
    "daijisho": True,
    "pegasus": True,
    "emulationstation": False,
    "launchbox": False,      # LaunchBox는 Data/Platforms/*.xml 별도 위치
}

MEDIA_TYPES = ["3dboxes", "covers", "marquees", "miximages", "screenshots", "videos", "wheel"]
# GUI Media 탭 노출 대상 (video 제외, §12)
MEDIA_TYPES_UI = ["covers", "miximages", "screenshots", "wheel"]
DEFAULT_MEDIA_TAB = "covers"


def default_config():
    return {
        "schema_version": 1,
        "locals": [],  # list of local dicts, max 4
        "masterdb": {
            "root": "",
            "status": "미설정",
        },
        "system_cores": {},  # { system_name: {default_core, is_custom} }
        "export_options": {
            "korean_only_on_conflict": True,
            "copy_media": True,
            "copy_video": True,
            "force_overwrite": False,  # [신규] 충돌 시 확인 대화상자 없이 MasterDB 내용으로 무조건 덮어쓰기
            "selected_media_types": ["screenshots", "3dboxes", "covers", "marquees", "miximages", "wheel"],
            "copy_rom": False,
        },
        "similar_rom": {  # [신규] 유사롬(Comparable ROM) 점수 가중치 + 임계값 (Settings에서 조정)
            "weight_title": 35,
            "weight_filename": 15,
            "weight_developer": 15,
            "weight_year": 15,
            "weight_screenshot": 20,
            "threshold": 60,
        },
        "scraper": {
            "devid": "",
            "devpassword": "",
            "username": "",
            "password": "",
        },
        "ui": {
            "last_selected_media_type": DEFAULT_MEDIA_TAB,
            "language": "ko",
            "theme": "system",
            "ui_scale": 1.0,
            "auto_save_interval_min": 5,
            "restore_last_session": True,
            # [0.4.1.x Settings 체계화] General 섹션에서 조정하는 항목들
            # [수정] 시작 화면은 ArchiveDB가 우선이어야 한다는 요청 반영. S.view의 JS
            # 기본값은 이미 "masterdb"지만, init()이 여기 값이 "dashboard"면 그걸로
            # 덮어써서 신규 설치/설정 초기화 상태에서는 계속 Dashboard가 먼저 떴다.
            "startup_page": "archivedb",  # dashboard | archivedb
            "confirm_destructive_actions": True,
            "logging_enabled": False,
            "default_list_view": "list",  # list | preview
        },
        "window_geometry": "1500x900",
        # v0.5 migration diagnostics: off | shadow | strict
        "database_debug": {"mode": "off"},
        "performance": {
            # [체감 속도] Scan/Import/Export에서 비디오를 뒤로 미루고 커버+메타데이터부터
            # 먼저 끝낸다. 끄면 예전처럼 모든 media 타입을 한 번에 처리한다.
            "defer_video_media": True,
        },
    }


def new_local_entry(local_id, label, frontend):
    return {
        "id": local_id,
        "label": label,
        "frontend": frontend,
        "rom_path": "",
        "metadata_path": "",
        "metadata_format": "",
        "media_path": "",
        "media_format": "es-de",
        "rom_metadata_same_dir": FRONTEND_ROM_METADATA_SAME_DIR.get(frontend, False),
        "status": "미설정",
        "last_scan": None,
        # 시스템 이름 매핑 (설계서 v2 부록B 보강: MasterDB는 ES-DE 계열 system id를 기준으로 삼으므로,
        # Local의 시스템 폴더명이 다를 경우 { local_system_name: canonical_system_name } 형태로 매핑한다.
        # 매핑되지 않은 시스템명은 그대로(동일) 사용된다.
        "system_name_map": {},
        # [v0.5 GameListSet 기반] SQLite game_list_sets.target_capacity_bytes와 짝이 되는 필드.
        # None = 용량 제한 없음. 스키마엔 있었지만 이 필드가 없어서 항상 NULL로 동기화되고
        # 있었음 (memory.md "8~11단계 착수 전 확정 사항" 참고).
        "target_capacity_bytes": None,
        "stats": {
            "rom_count": 0,
            "rom_size_bytes": 0,
            "media_count": 0,
            "media_size_bytes": 0,
            "missing_rom": 0,
            "missing_metadata": 0,
            "missing_media": 0,
        },
    }


# ES-DE platform aliases: these folders represent the same platform in MasterDB.
# Keep the Local/raw system separately; only the MasterDB canonical key is merged.
ESDE_SYSTEM_ALIASES = {
    "msx1": "msx", "msx": "msx",
    "famicom": "nes", "nes": "nes",
    "genesis": "megadrive", "megadrive": "megadrive", "md": "megadrive",
    "sfc": "sfc",
    "pcengine": "pcengine", "turbografx16": "pcengine",
    "pcenginecd": "pcenginecd", "turbografxcd": "pcenginecd",
}
ESDE_IGNORED_SYSTEMS = {"cleanup"}

def canonical_system(local_entry, raw_system):
    """Convert a Local/frontend system name to the MasterDB canonical system.

    ES-DE exposes both ``msx`` and ``msx1`` in some installations even though
    they represent the same MSX platform for metadata purposes. Keep the raw
    system elsewhere for UI/export routing, but use ``msx`` as the canonical
    MasterDB key. Explicit per-local mappings still take precedence.
    """
    raw = str(raw_system or "")
    explicit = local_entry.get("system_name_map", {})
    if raw in explicit:
        return explicit[raw]
    frontend = str(local_entry.get("frontend", "")).lower()
    if frontend == "es-de":
        return ESDE_SYSTEM_ALIASES.get(raw.lower(), raw)
    return raw


def local_system_name(local_entry, canonical_name):
    """canonical 이름으로부터 이 Local의 원본(폴더) 이름을 역으로 조회.
    매핑 테이블에 없으면 canonical_name을 그대로 사용한다 (identity)."""
    mapping = local_entry.get("system_name_map", {})
    for raw, canon in mapping.items():
        if canon == canonical_name:
            return raw
    return canonical_name


class LocalPathError(ValueError):
    """Local의 경로가 설정되지 않았거나 존재하지 않을 때 발생하는 예외."""
    pass


def validate_local_paths(local_entry):
    """
    [안전장치] rom_path/metadata_path/media_path가 비어있거나 존재하지 않으면 예외를 발생시킨다.

    이 검증이 반드시 필요한 이유: Python의 pathlib은 빈 문자열을 "현재 작업 디렉토리"로
    해석한다 (Path("").exists() == True, Path("").resolve() == cwd). 즉 Local의 경로가
    설정되지 않은 채로(rom_path="") 스캔/Import/Export/Reset Metadata/Orphan Cleanup 같은
    파일시스템 작업을 실행하면, 의도와 무관하게 프로그램이 실행된 위치(cwd)를 대상으로
    동작해버릴 수 있다 - 특히 Reset Metadata/Orphan Cleanup은 파일을 **삭제**하므로
    실제 데이터 손실로 이어질 수 있는 위험한 시나리오다.

    따라서 파일시스템에 실제로 접근하는 모든 진입점(scan_local, detect_local_structure,
    reset_metadata, orphan_cleanup 등)은 이 함수를 가장 먼저 호출해야 한다.
    """
    label = local_entry.get("label", "Local")
    # ES-DE is allowed to be metadata-only: ROMs may live elsewhere or be absent.
    fields = [("metadata_path", "Metadata 경로"), ("media_path", "Media 경로")]
    if local_entry.get("frontend") != "es-de":
        fields.insert(0, ("rom_path", "ROM 경로"))
    for field_name, display in fields:
        value = local_entry.get(field_name, "")
        if not value or not str(value).strip():
            raise LocalPathError(f"{label}의 {display}가 설정되지 않았습니다.")
        if not Path(value).exists():
            raise LocalPathError(f"{label}의 {display}를 찾을 수 없습니다: {value}")


def load_config():
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            cfg = default_config()
            _deep_merge(cfg, data)
            return cfg
        except Exception:
            pass
    return default_config()


def _deep_merge(base, override):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def save_config(cfg):
    with _SAVE_LOCK:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CONFIG_PATH)


def can_add_local(cfg):
    return len(cfg.get("locals", [])) < MAX_LOCALS


def add_local(cfg, label, frontend):
    if not can_add_local(cfg):
        raise ValueError(f"Local은 최대 {MAX_LOCALS}개까지 등록할 수 있습니다.")
    idx = len(cfg["locals"]) + 1
    local_id = f"local{idx}"
    entry = new_local_entry(local_id, label, frontend)
    cfg["locals"].append(entry)
    return entry


def remove_local(cfg, local_id):
    cfg["locals"] = [l for l in cfg["locals"] if l["id"] != local_id]


def get_local(cfg, local_id):
    for l in cfg.get("locals", []):
        if l["id"] == local_id:
            return l
    return None


def touch_scan_time(local_entry):
    local_entry["last_scan"] = datetime.now().isoformat(timespec="seconds")
