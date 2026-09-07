"""
scraper/screenscraper.py
==========================
ScreenScraper.fr API 연동 (설계서 v2 §10, §18).

- 해시(CRC32/MD5) 기반 매칭 우선, 실패 시 이름 검색 폴백
- 단건 조회(jeuInfos.php) / 일괄 스크랩(rate limit 대응 큐)
- 결과는 db.META_FIELD_KEYS 형식으로 변환하여 반환 (import_engine/db와 동일 스키마 재사용)

API 문서: https://api.screenscraper.fr/webapi2.php
※ 실제 API 키(devid/devpassword)와 사용자 계정 필요. Settings에서 입력받는다.
"""

import time
import hashlib
import zlib
import requests

API_BASE = "https://api.screenscraper.fr/api2"
SOFTNAME = "RetroMetadataManager"

# ScreenScraper region id -> 표시용 region 텍스트 (일부만 예시로 매핑)
REGION_MAP = {
    "us": "USA (NTSC)", "eu": "Europe (PAL)", "jp": "Japan (NTSC-J)",
    "wor": "World", "kr": "Korea",
}


class ScreenScraperError(Exception):
    pass


def _crc32_of_file(path):
    crc = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            crc = zlib.crc32(chunk, crc)
    return f"{crc & 0xFFFFFFFF:08X}"


def _md5_of_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _auth_params(cfg_scraper):
    return {
        "devid": cfg_scraper.get("devid", ""),
        "devpassword": cfg_scraper.get("devpassword", ""),
        "softname": SOFTNAME,
        "ssid": cfg_scraper.get("username", ""),
        "sspassword": cfg_scraper.get("password", ""),
        "output": "json",
    }


def search_by_hash(cfg_scraper, rom_path, system_id=None, timeout=15):
    """
    ROM 파일의 CRC32/MD5 해시로 ScreenScraper 조회 (jeuInfos.php).
    반환: (fields_dict, match_method) 또는 (None, None) (매칭 실패 시)
    """
    params = _auth_params(cfg_scraper)
    params["crc"] = _crc32_of_file(rom_path)
    params["md5"] = _md5_of_file(rom_path)
    if system_id:
        params["systemeid"] = system_id

    resp = requests.get(f"{API_BASE}/jeuInfos.php", params=params, timeout=timeout)
    if resp.status_code != 200:
        return None, None

    try:
        data = resp.json()
    except ValueError:
        return None, None

    jeu = data.get("response", {}).get("jeu")
    if not jeu:
        return None, None

    return _parse_jeu(jeu), "해시"


def search_by_name(cfg_scraper, game_name, system_id=None, timeout=15):
    """이름 기반 검색 (해시 매칭 실패 시 폴백). romnom 파라미터 사용."""
    params = _auth_params(cfg_scraper)
    params["romnom"] = game_name
    if system_id:
        params["systemeid"] = system_id

    resp = requests.get(f"{API_BASE}/jeuInfos.php", params=params, timeout=timeout)
    if resp.status_code != 200:
        return None, None

    try:
        data = resp.json()
    except ValueError:
        return None, None

    jeu = data.get("response", {}).get("jeu")
    if not jeu:
        return None, None

    return _parse_jeu(jeu), "이름검색"


def _parse_jeu(jeu):
    """ScreenScraper의 jeu 응답을 db.META_FIELD_KEYS 형식으로 변환."""

    def first_text(items, lang_priority=("ko", "en", "kr")):
        if not items:
            return ""
        if isinstance(items, str):
            return items
        for lang in lang_priority:
            for item in items:
                if item.get("langue") == lang:
                    return item.get("text", "")
        return items[0].get("text", "") if items else ""

    names = jeu.get("noms", [])
    name = first_text(names) if names else jeu.get("nom", "")

    synopsis = jeu.get("synopsis", [])
    desc = first_text(synopsis)

    genres = jeu.get("genres", [])
    genre_names = []
    for g in genres:
        gn = g.get("noms", [])
        t = first_text(gn)
        if t:
            genre_names.append(t)
    genre = "/".join(genre_names)

    developer = (jeu.get("developpeur") or {}).get("text", "")
    publisher = (jeu.get("editeur") or {}).get("text", "")

    dates = jeu.get("dates", [])
    release = first_text(dates) if dates else ""

    players = (jeu.get("joueurs") or {}).get("text", "")
    rating = (jeu.get("note") or {}).get("text", "")

    medias = jeu.get("medias", [])
    media_urls = {}
    media_type_map = {
        "box-2D": "covers", "box-3D": "3dboxes",
        "ss": "screenshots", "wheel": "wheel",
        "mixrbv1": "miximages", "mixrbv2": "miximages",
        "video": "videos", "marquee": "marquees",
    }
    for m in medias:
        mtype = media_type_map.get(m.get("type"))
        url = m.get("url")
        if mtype and url:
            media_urls.setdefault(mtype, []).append(url)

    fields = {
        "name": name,
        "desc": desc,
        "genre": genre,
        "developer": developer,
        "publisher": publisher,
        "releasedate": release,
        "region": "",
        "players": players,
        "rating": rating,
        "tags": genre_names,
    }
    return {"fields": fields, "media_urls": media_urls}


def download_media(url, dest_path, timeout=20):
    resp = requests.get(url, timeout=timeout, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)


# ---------------------------------------------------------------------------
# 일괄 스크랩 (Rate limit 대응)
# ---------------------------------------------------------------------------

DEFAULT_REQUEST_DELAY_SEC = 1.2  # ScreenScraper 무료 계정 rate limit 고려 기본 딜레이


def batch_scrape(cfg_scraper, rom_list, progress_cb=None, delay=DEFAULT_REQUEST_DELAY_SEC):
    """
    rom_list: [{"system": str, "filename": str, "path": str}, ...]
    반환: [{"system", "filename", "result": {...}|None, "match_method": str|None,
            "status": "완료"|"확인필요"|"실패"}, ...]
    """
    results = []
    total = len(rom_list)

    for idx, rom in enumerate(rom_list, start=1):
        if progress_cb:
            progress_cb(idx, total, rom["filename"])

        entry = {"system": rom["system"], "filename": rom["filename"],
                  "result": None, "match_method": None, "status": "실패"}
        try:
            parsed, method = search_by_hash(cfg_scraper, rom["path"])
            if not parsed:
                time.sleep(delay)
                parsed, method = search_by_name(cfg_scraper, rom["filename"])

            if parsed:
                entry["result"] = parsed
                entry["match_method"] = method
                entry["status"] = "완료" if method == "해시" else "확인필요"
        except requests.RequestException as e:
            entry["error"] = str(e)

        results.append(entry)
        time.sleep(delay)

    return results
