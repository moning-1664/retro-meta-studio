"""
app/launch/retroarch.py
========================
RetroArch로 게임을 실행한다.

RetroGameManager `feature/retroarch-launch` 브랜치(launchers/retroarch_launcher.py,
launchers/known_cores.py)에서 실사용으로 다듬어진 것을 옮겨 왔다. 그 브랜치에서 이미
겪고 고친 것들을 그대로 지킨다.

- `retroarch.exe -L <core> <rom>`을 **인자 배열**로 넘긴다(shell 금지) - 경로의 공백·한글·
  괄호가 안전하다.
- 실행 전 검증 순서: 검증 안 된 System → RetroArch 실행 파일 → ROM → Core 설정 → Core 파일.
  exists()가 아니라 is_file()로 본다(폴더를 골라도 통과하던 문제).
- Core는 절대경로가 아니라 **cores 폴더 기준 파일명**으로 저장한다 - RetroArch를 다른
  폴더로 옮겨도 매핑이 깨지지 않는다.
- 게임 세션이 끝날 때까지 기다리지 않는다. 0.6초만 지켜보고 즉시 죽었는지(DLL 누락 등)만 본다.
- 사용자의 retroarch.cfg가 전체화면이어도 창모드로 뜨게 `--appendconfig`로 이번 실행만
  덮어쓴다(창 크기 기억 포함). retroarch.cfg를 직접 열어 고치지 않는다.
- exe가 있는 폴더를 cwd로 둔다 - 포터블 설치가 상대경로로 cores/BIOS를 찾는다.

이 모듈은 파일 경로만 받는다. 어느 Collection의 어느 게임인지는 bridge가 Adapter
layout으로 계산해서 넘긴다.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

#: System별 "무난한 기본 Core" 후보(앞에 있을수록 우선). cores 폴더에 실제로 있는 첫 파일을 쓴다.
#: 본격적인 Core Registry(.info 파싱 등)는 하지 않는다 - 시스템마다 하나씩 고르는 수고만 줄인다.
KNOWN_DEFAULT_CORES = {
    "nes": ["mesen_libretro.dll", "fceumm_libretro.dll", "nestopia_libretro.dll", "quicknes_libretro.dll"],
    "famicom": ["mesen_libretro.dll", "fceumm_libretro.dll", "nestopia_libretro.dll", "quicknes_libretro.dll"],
    "fds": ["mesen_libretro.dll", "fceumm_libretro.dll", "nestopia_libretro.dll"],
    "snes": ["snes9x_libretro.dll", "bsnes_libretro.dll", "snes9x2002_libretro.dll"],
    "sfc": ["snes9x_libretro.dll", "bsnes_libretro.dll", "snes9x2002_libretro.dll"],
    "megadrive": ["genesis_plus_gx_libretro.dll", "genesis_plus_gx_wide_libretro.dll", "picodrive_libretro.dll", "blastem_libretro.dll"],
    "genesis": ["genesis_plus_gx_libretro.dll", "genesis_plus_gx_wide_libretro.dll", "picodrive_libretro.dll", "blastem_libretro.dll"],
    "megacd": ["genesis_plus_gx_libretro.dll", "genesis_plus_gx_wide_libretro.dll", "picodrive_libretro.dll"],
    "segacd": ["genesis_plus_gx_libretro.dll", "genesis_plus_gx_wide_libretro.dll", "picodrive_libretro.dll"],
    "sega32x": ["picodrive_libretro.dll"],
    "mastersystem": ["genesis_plus_gx_libretro.dll", "smsplus_libretro.dll", "picodrive_libretro.dll"],
    "gamegear": ["genesis_plus_gx_libretro.dll", "smsplus_libretro.dll", "picodrive_libretro.dll"],
    "gb": ["gambatte_libretro.dll", "mgba_libretro.dll", "sameboy_libretro.dll"],
    "gbc": ["gambatte_libretro.dll", "mgba_libretro.dll", "sameboy_libretro.dll"],
    "gba": ["mgba_libretro.dll", "gpsp_libretro.dll"],
    "n64": ["mupen64plus_next_libretro.dll", "parallel_n64_libretro.dll"],
    "gc": ["dolphin_libretro.dll"],
    "wii": ["dolphin_libretro.dll"],
    "nds": ["melonds_libretro.dll", "desmume_libretro.dll", "desmume2015_libretro.dll"],
    "n3ds": ["citra_libretro.dll", "citra2018_libretro.dll"],
    "psx": ["mednafen_psx_hw_libretro.dll", "mednafen_psx_libretro.dll", "pcsx_rearmed_libretro.dll", "swanstation_libretro.dll"],
    "ps2": ["pcsx2_libretro.dll", "play_libretro.dll"],
    "psp": ["ppsspp_libretro.dll"],
    "saturn": ["kronos_libretro.dll", "mednafen_saturn_libretro.dll", "yabause_libretro.dll"],
    "dreamcast": ["flycast_libretro.dll"],
    "naomi": ["flycast_libretro.dll"],
    "naomi2": ["flycast_libretro.dll"],
    "pcengine": ["mednafen_pce_fast_libretro.dll", "mednafen_pce_libretro.dll", "mednafen_supergrafx_libretro.dll"],
    "pcenginecd": ["mednafen_pce_fast_libretro.dll", "mednafen_pce_libretro.dll"],
    "supergrafx": ["mednafen_supergrafx_libretro.dll", "mednafen_pce_fast_libretro.dll", "mednafen_pce_libretro.dll"],
    "msx": ["bluemsx_libretro.dll", "fmsx_libretro.dll"],
    "msx1": ["bluemsx_libretro.dll", "fmsx_libretro.dll"],
    "msx2": ["bluemsx_libretro.dll", "fmsx_libretro.dll"],
    "neogeo": ["fbneo_libretro.dll", "fbalpha2012_neogeo_libretro.dll"],
    "neogeocd": ["neocd_libretro.dll"],
    "ngp": ["mednafen_ngp_libretro.dll"],
    "ngpc": ["mednafen_ngp_libretro.dll"],
    "wonderswan": ["mednafen_wswan_libretro.dll"],
    "wonderswancolor": ["mednafen_wswan_libretro.dll"],
    "cps1": ["fbneo_libretro.dll", "fbalpha2012_cps1_libretro.dll"],
    "cps2": ["fbneo_libretro.dll", "fbalpha2012_cps2_libretro.dll"],
    "cps3": ["fbneo_libretro.dll", "fbalpha2012_cps3_libretro.dll"],
    "fba": ["fbneo_libretro.dll", "fbalpha2012_libretro.dll"],
    "fbneo": ["fbneo_libretro.dll"],
    "mame": ["mame2010_libretro.dll", "fbneo_libretro.dll"],
    "mame2003": ["mame2003_plus_libretro.dll", "mame2003_libretro.dll"],
    "arcade": ["fbneo_libretro.dll", "mame2010_libretro.dll"],
    "dos": ["dosbox_pure_libretro.dll", "dosbox_core_libretro.dll"],
    "pc98": ["np2kai_libretro.dll", "nekop2_libretro.dll"],
}

#: Core 후보가 있어도 BIOS·펌웨어·Core 궁합 때문에 기본 설정만으로는 실행이 불안정한 System.
#: 실행 버튼을 비활성으로 두고, 실행 시점에도 다시 막는다. 직접 확인해서 문제없으면 빼면 된다.
#: 반대로 여기 없다고 실행이 보장되는 것은 아니다(알려진 문제가 없다는 뜻일 뿐).
UNVERIFIED_SYSTEMS = frozenset({"ps2", "gc", "wii", "nds", "n3ds", "3ds"})

CORE_SUFFIXES = (".dll", ".so", ".dylib")
STARTUP_CHECK_SEC = 0.6
_WINDOWED_OVERRIDE = Path(tempfile.gettempdir()) / "retro_meta_studio_retroarch_windowed.cfg"


def is_verified(system) -> bool:
    return str(system or "").lower() not in UNVERIFIED_SYSTEMS


@dataclass
class LaunchResult:
    ok: bool
    error: str | None = None
    #: UI가 실패 사유에 따라 다르게 반응하기 위한 안정적인 코드(문구는 바뀌어도 이 값은 유지).
    #: retroarch_missing / rom_missing / core_unset / core_missing / launch_failed
    error_kind: str | None = None
    command: list = field(default_factory=list)


def list_cores(cores_dir) -> list[str]:
    """cores 폴더의 Core 파일명(정렬). 폴더가 없으면 빈 목록."""
    try:
        root = Path(cores_dir)
        if not cores_dir or not root.is_dir():
            return []
        return sorted(p.name for p in root.iterdir() if p.is_file() and p.suffix.lower() in CORE_SUFFIXES)
    except OSError:
        return []


def core_label(filename) -> str:
    """`snes9x_libretro.dll` -> `snes9x`. 화면 표시용."""
    name = Path(str(filename or "")).stem
    return name[: -len("_libretro")] if name.endswith("_libretro") else name


def default_cores_for(systems, available, existing) -> dict[str, str]:
    """systems 중 아직 Core가 없는 것에 알려진 후보를 채운다. **이미 정한 것은 절대 덮어쓰지 않는다.**"""
    available = set(available or [])
    applied = {}
    for system in systems:
        key = str(system or "").lower()
        if not key or key in (existing or {}):
            continue
        for candidate in KNOWN_DEFAULT_CORES.get(key, []):
            if candidate in available:
                applied[key] = candidate
                break
    return applied


def _windowed_override_path() -> str:
    _WINDOWED_OVERRIDE.write_text('video_fullscreen = "false"\nvideo_window_save_positions = "true"\n',
                                  encoding="utf-8")
    return str(_WINDOWED_OVERRIDE)


def launch(exe_path, cores_dir, core_filename, rom_path, system, *, popen=None,
           startup_check_sec=STARTUP_CHECK_SEC) -> LaunchResult:
    """RetroArch를 띄운다. `popen`은 테스트에서 subprocess.Popen 대신 넣는다."""
    # Verification is advisory. An explicitly chosen installed Core may work
    # for a system we have not tested; let RetroArch decide whether it launches.
    if not exe_path or not Path(exe_path).is_file():
        return LaunchResult(False, f"RetroArch 실행 파일을 찾을 수 없습니다: {exe_path or '(미설정)'}",
                            "retroarch_missing")
    rom = Path(rom_path)
    if not rom.is_file():
        return LaunchResult(False, f"ROM 파일을 찾을 수 없습니다: {rom}", "rom_missing")
    if not core_filename:
        return LaunchResult(False, f"'{system}' 시스템에 RetroArch Core가 정해지지 않았습니다.", "core_unset")
    if not cores_dir:
        return LaunchResult(False, "RetroArch Core 폴더가 설정되지 않았습니다.", "core_missing")
    core = Path(cores_dir) / core_filename
    if not core.is_file():
        return LaunchResult(False, f"Core 파일을 찾을 수 없습니다: {core}", "core_missing")

    command = [str(exe_path), "-L", str(core)]
    try:
        command.append(f"--appendconfig={_windowed_override_path()}")
    except OSError:
        pass   # 덮어쓰기 파일을 못 만들면 사용자의 원래 설정대로 실행한다
    command.append(str(rom))

    runner = popen or subprocess.Popen
    kwargs = {"cwd": str(Path(exe_path).parent)}
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        proc = runner(command, **kwargs)
    except Exception as exc:  # noqa: BLE001 - 사용자에게 보여줄 실패로 바꾼다
        return LaunchResult(False, f"RetroArch를 실행할 수 없습니다: {exc}", "launch_failed", command)

    if startup_check_sec:
        time.sleep(startup_check_sec)
    code = proc.poll()
    if code is not None and code != 0:
        return LaunchResult(False, f"RetroArch가 바로 종료됐습니다(exit code {code}).", "launch_failed", command)
    return LaunchResult(True, command=command)
