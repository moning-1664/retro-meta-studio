from __future__ import annotations

import hashlib
import logging
import re
import time
import zlib
import zipfile
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # 앱의 나머지 기능은 선택 의존성 누락과 무관하게 열려야 한다.
    requests = None

_REQUEST_ERROR = requests.RequestException if requests is not None else OSError

from app.scrape.models import ScrapeCandidate, ScrapeIdentity, ScrapeMedia
from app.scrape.providers.base import ScrapeProvider


API_BASE = "https://api.screenscraper.fr/api2"
log = logging.getLogger(__name__)
MAX_AUTO_HASH_BYTES = 64 * 1024 * 1024
ARCADE_SYSTEMS = frozenset({"arcade", "mame", "mame2003", "mame2003plus",
                           "mame2010", "fbneo", "fbern", "fba", "cps1", "cps2", "cps3"})


class ScreenScraperError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "provider"):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class ScreenScraperConfig:
    dev_id: str
    dev_password: str
    soft_name: str
    user_id: str = ""
    user_password: str = ""
    timeout: float = 20.0
    use_hashes: bool = True
    media_types: tuple[str, ...] | None = None

    def validate(self):
        if not self.dev_id or not self.dev_password or not self.soft_name:
            raise ScreenScraperError("ScreenScraper 개발자 정보를 먼저 설정하세요.", kind="auth")


def hashes_of_file(path: str, chunk_size: int = 1024 * 1024) -> dict:
    crc = 0
    md5 = hashlib.md5()  # noqa: S324 - upstream matching identifier, not security
    sha1 = hashlib.sha1()  # noqa: S324 - upstream matching identifier, not security
    size = 0
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            size += len(chunk)
            crc = zlib.crc32(chunk, crc)
            md5.update(chunk)
            sha1.update(chunk)
    return {"size": size, "crc32": f"{crc & 0xffffffff:08X}",
            "md5": md5.hexdigest(), "sha1": sha1.hexdigest()}


def lookup_hashes(path: str) -> dict:
    """Hash a small raw ROM, or use a single ZIP member's stored CRC/size.

    A multi-member arcade set has no one game CRC. Never hash its ZIP container
    and present that as the ROM hash. Large files stay on the name fallback so
    a network drive is not read in full just to open the candidate dialog.
    """
    source = Path(path)
    if source.suffix.casefold() == ".zip":
        with zipfile.ZipFile(source) as archive:
            members = [entry for entry in archive.infolist() if not entry.is_dir()
                       and not entry.filename.startswith("__MACOSX/")]
            if len(members) != 1:
                return {}
            member = members[0]
            # ScreenScraper's romtaille is the submitted archive file size;
            # the member CRC is available from the ZIP directory without
            # decompressing its payload.
            return {"size": source.stat().st_size, "crc32": f"{member.CRC:08X}"}
    if source.stat().st_size > MAX_AUTO_HASH_BYTES:
        return {}
    return hashes_of_file(path)


def _list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("text") or value.get("nom") or "")
    return str(value or "")


def _integer(value: Any) -> int:
    """ScreenScraper occasionally returns counters as formatted strings."""
    text = _text(value).strip().replace(" ", "")
    try:
        return int(text or 0)
    except (TypeError, ValueError):
        return 0


def _localized(items: Any, languages=("ko", "kr", "en"), regions=("kr", "wor", "us", "eu", "jp")) -> str:
    if isinstance(items, dict) and not any(key in items for key in ("text", "nom", "langue", "region")):
        # The API also publishes JSON fields as nom_us/synopsis_en/date_jp.
        for suffix in (*languages, *regions):
            found = next((str(value) for key, value in items.items()
                          if str(key).lower().endswith("_" + suffix) and value), "")
            if found:
                return found
        return next((str(value) for value in items.values() if isinstance(value, str) and value), "")
    values = _list(items)
    for language in languages:
        found = next((_text(v) for v in values if isinstance(v, dict)
                      and str(v.get("langue") or "").lower() == language and _text(v)), "")
        if found:
            return found
    for region in regions:
        found = next((_text(v) for v in values if isinstance(v, dict)
                      and str(v.get("region") or "").lower() == region and _text(v)), "")
        if found:
            return found
    return next((_text(v) for v in values if _text(v)), "")


MEDIA_TYPES = {
    "box-2d": "covers", "box-3d": "3dboxes", "ss": "screenshots",
    "sstitle": "titlescreens", "wheel": "wheel", "marquee": "marquees",
    "fanart": "fanart", "manuel": "manuals", "video": "videos",
    "mixrbv1": "miximages", "mixrbv2": "miximages",
}

# Frontend folder names -> ScreenScraper systemesListe IDs. Unknown names must
# not silently turn a system-scoped search into an all-platform search.
# IDs follow ScreenScraper's published system list (also used by EmulationStation).
SYSTEM_IDS = {
    "3do": 29, "amiga": 64, "arcade": 75, "fbneo": 75, "fbern": 75,
    "cps1": 75, "cps2": 75, "cps3": 75, "mame": 75, "fba": 75,
    "mame2003": 75, "mame2003plus": 75, "mame2010": 75,
    "dos": 135, "dreamcast": 23, "gamegear": 21, "gb": 9,
    "gba": 12, "gbc": 10, "gc": 13, "megadrive": 1,
    "genesis": 1, "msx": 113, "msx1": 113, "msx2": 116,
    "msx2+": 117, "n64": 14, "naomi": 56, "nes": 3,
    "nds": 15, "n3ds": 17, "3ds": 17, "wii": 16, "wiiu": 18,
    "switch": 225, "psvita": 62, "vita": 62, "ps3": 59, "ps4": 60,
    "famicom": 3, "pcengine": 31, "ps2": 58, "psp": 61,
    "psx": 57, "ps1": 57, "saturn": 22, "sfc": 4,
    "snes": 4, "supergrafx": 105,
}


def _system_id(hint: str) -> str | None:
    value = str(hint or "").strip().casefold()
    if not value:
        return None
    if value.isdigit() and int(value) > 0:
        return str(int(value))
    system_id = SYSTEM_IDS.get(value)
    if system_id is None:
        raise ScreenScraperError(
            f"ScreenScraper 시스템 ID를 알 수 없습니다: {hint}. 숫자 System ID를 입력하세요.",
            kind="system")
    return str(system_id)


def _game_system_id(game: dict) -> str | None:
    system = game.get("systeme") or {}
    value = system.get("id") if isinstance(system, dict) else system
    return str(value) if value is not None and str(value).isdigit() else None


class ScreenScraperClient(ScrapeProvider):
    provider_id = "screenscraper"

    def __init__(self, config: ScreenScraperConfig, session=None):
        config.validate()
        if session is None and requests is None:
            raise ScreenScraperError("ScreenScraper 연결 모듈(requests)이 설치되지 않았습니다.",
                                     kind="network")
        self.config = config
        self.http = session or requests.Session()

    def _params(self) -> dict:
        return {"devid": self.config.dev_id, "devpassword": self.config.dev_password,
                "softname": self.config.soft_name, "ssid": self.config.user_id,
                "sspassword": self.config.user_password, "output": "json"}

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        query = self._params()
        query.update(params or {})
        started = time.perf_counter()
        try:
            response = self.http.get(f"{API_BASE}/{endpoint}", params=query,
                                     timeout=self.config.timeout)
        except _REQUEST_ERROR as exc:
            # requests exceptions can include the full URL with credentials.
            # Never surface that string in the UI or application log.
            log.warning("ScreenScraper %s network failure: %s after %.2fs",
                        endpoint, type(exc).__name__, time.perf_counter() - started)
            raise ScreenScraperError(f"ScreenScraper 연결 실패 ({type(exc).__name__})", kind="network") from exc
        log.info("ScreenScraper %s HTTP %s in %.2fs", endpoint, response.status_code,
                 time.perf_counter() - started)
        if response.status_code == 401:
            raise ScreenScraperError("ScreenScraper 서버가 혼잡해 요청을 받지 않습니다. 잠시 후 다시 시도하세요.",
                                     kind="busy")
        if response.status_code == 403:
            raise ScreenScraperError("ScreenScraper 인증에 실패했습니다.", kind="auth")
        if response.status_code == 404:
            raise ScreenScraperError("ScreenScraper 검색 결과가 없습니다.", kind="not_found")
        if response.status_code == 429:
            raise ScreenScraperError("ScreenScraper 동시 요청 제한에 걸렸습니다. 잠시 후 다시 시도하세요.",
                                     kind="rate")
        if response.status_code in (430, 431):
            raise ScreenScraperError("ScreenScraper 일일 스크랩 한도에 도달했습니다.", kind="quota")
        if response.status_code in (423, 426):
            raise ScreenScraperError(f"ScreenScraper 서비스를 사용할 수 없습니다 ({response.status_code}).",
                                     kind="unavailable")
        if response.status_code != 200:
            raise ScreenScraperError(f"ScreenScraper 응답 오류 ({response.status_code})")
        try:
            payload = response.json()
        except ValueError as exc:
            message = response.text.strip()[:240]
            raise ScreenScraperError(message or "ScreenScraper 응답을 읽을 수 없습니다.") from exc
        if not isinstance(payload, dict):
            raise ScreenScraperError("ScreenScraper 응답 형식이 올바르지 않습니다.")
        return payload

    def account_status(self) -> dict:
        payload = self._get("ssuserInfos.php")
        user = (payload.get("response") or {}).get("ssuser") or {}
        return {
            "provider": self.provider_id,
            "user": _text(user.get("id") or self.config.user_id),
            "level": _text(user.get("niveau")),
            "maxThreads": _integer(user.get("maxthreads")),
            "requestsToday": _integer(user.get("requeststoday")),
            "requestsLimit": _integer(user.get("maxrequestsperday")),
            "requestsMinute": _integer(user.get("requestspermin")),
            "requestsMinuteLimit": _integer(user.get("maxrequestspermin")),
        }

    def identify(self, identity: ScrapeIdentity) -> list[ScrapeCandidate]:
        alias = identity.lookup_alias or {}
        arcade = str(identity.system).lower() in ARCADE_SYSTEMS
        hashes = {}
        if self.config.use_hashes and identity.path and Path(identity.path).is_file():
            hash_started = time.perf_counter()
            try:
                hashes = lookup_hashes(identity.path)
            except (OSError, zipfile.BadZipFile) as exc:
                log.info("ScreenScraper ROM hash unavailable type=%s", type(exc).__name__)
            log.info("ScreenScraper ROM lookup system=%s type=%s hashFields=%s seconds=%.3f",
                     identity.system, Path(identity.path).suffix.lower(), sorted(hashes),
                     time.perf_counter() - hash_started)
        params = {"romnom": identity.filename, "romtype": "rom"}
        for source, target in (("size", "romtaille"), ("crc32", "crc"),
                               ("md5", "md5"), ("sha1", "sha1")):
            value = alias.get(source) or hashes.get(source)
            if value:
                params[target] = value
        if "romtaille" not in params and identity.size:
            params["romtaille"] = identity.size
        if (not arcade and not any(key in params for key in ("crc", "md5", "sha1"))
                and (not identity.path or not Path(identity.path).is_file())):
            return []
        system_id = _system_id(str(alias.get("systemId") or identity.system))
        if system_id:
            params["systemeid"] = system_id
        game = None
        names = [identity.filename]
        if arcade and Path(identity.filename).stem != identity.filename:
            names.append(Path(identity.filename).stem)
        for rom_name in names:
            try:
                game = (self._get("jeuInfos.php", {**params, "romnom": rom_name})
                        .get("response") or {}).get("jeu")
            except ScreenScraperError as exc:
                # Only an unknown ROM should try the next spelling. A network,
                # quota or authentication error must remain visible.
                if exc.kind != "not_found":
                    raise
            if game:
                break
        if game and system_id and _game_system_id(game) not in (None, system_id):
            return []
        evidence = ("원본 별칭으로 조회" if alias and any(k in params for k in ("crc", "md5", "sha1"))
                    else "ROM 해시로 조회" if any(k in params for k in ("crc", "md5", "sha1"))
                    else "Arcade ROM-set 파일명으로 조회")
        # jeuInfos may also fall back to romnom on its side. Without a returned
        # checksum we cannot claim that the response is a verified hash match.
        return [self._candidate(game, evidence=(evidence,), confidence=90)] if game else []

    def search(self, query: str, system_hint: str = "") -> list[ScrapeCandidate]:
        query = str(query or "").strip()
        if not query:
            return []
        params = {"recherche": query}
        system_id = _system_id(system_hint)
        if system_id:
            params["systemeid"] = system_id
        try:
            response = self._get("jeuRecherche.php", params).get("response") or {}
        except ScreenScraperError as exc:
            if exc.kind == "not_found":
                return []
            raise
        games = response.get("jeux") or response.get("jeu") or []
        if isinstance(games, dict) and "jeu" in games:
            games = games["jeu"]
        candidates = []
        other_systems = low_similarity = 0
        for game in _list(games):
            if not isinstance(game, dict):
                continue
            # The request was already scoped by systemeid. Some search rows
            # omit systeme; reject only an explicit contradictory ID.
            if system_id and _game_system_id(game) not in (None, system_id):
                other_systems += 1
                continue
            candidate = self._candidate(game, evidence=(f'검색어 "{query}"',), confidence=55)
            score = _title_similarity(query, candidate.title, candidate.alternate_titles)
            # jeuRecherche는 관련 없는 단일 결과를 정상 응답으로 돌려주기도 한다. 제목이
            # 거의 겹치지 않으면 선택을 강요하지 않고 "후보 없음"으로 처리한다.
            if score < 0.45:
                low_similarity += 1
                continue
            confidence = max(45, min(95, round(score * 100)))
            candidates.append(replace(
                candidate, confidence=confidence,
                confidence_reason=f"제목 유사도 {confidence}%"))
        log.info("ScreenScraper search system=%s returned=%d kept=%d otherSystem=%d lowSimilarity=%d",
                 system_id or "all", len(_list(games)), len(candidates), other_systems, low_similarity)
        return candidates

    def _candidate(self, game: dict, *, evidence: tuple[str, ...], confidence: int) -> ScrapeCandidate:
        remote_id = str(game.get("id") or game.get("jeu_id") or "")
        raw_names = game.get("noms")
        names = ([str(value) for value in raw_names.values() if isinstance(value, str) and value]
                 if isinstance(raw_names, dict) and not any(k in raw_names for k in ("text", "nom"))
                 else [_text(item) for item in _list(raw_names) if _text(item)])
        title = _localized(game.get("noms")) or _text(game.get("nom")) or (names[0] if names else "")
        system = game.get("systeme") or {}
        system_name = (_text(system.get("nom_eu")) or _text(system.get("nom"))
                       or _text(game.get("systeme_nom")))
        genres = []
        for genre in _list(game.get("genres")):
            name = _localized(genre.get("noms") if isinstance(genre, dict) else genre)
            if name and name not in genres:
                genres.append(name)
        fields = {
            "name": title,
            "desc": _localized(game.get("synopsis")),
            "genre": "/".join(genres),
            "developer": _text(game.get("developpeur")),
            "publisher": _text(game.get("editeur")),
            "releasedate": _localized(game.get("dates")),
            "players": _text(game.get("joueurs")),
            "rating": _text(game.get("note")),
        }
        media = []
        allowed = set(MEDIA_TYPES.values() if self.config.media_types is None
                      else self.config.media_types)
        seen_media_types = set()
        for item in _list(game.get("medias")):
            if not isinstance(item, dict) or not item.get("url"):
                continue
            media_type = MEDIA_TYPES.get(str(item.get("type") or "").lower())
            # 같은 종류의 지역/언어 변형을 모두 보여주면 카드가 수십 장이 된다.
            # API 응답의 우선순위가 높은 첫 항목 하나만 후보로 보낸다.
            if media_type and media_type in allowed and media_type not in seen_media_types:
                media.append(ScrapeMedia(media_type, str(item["url"]),
                                         str(item.get("region") or ""),
                                         str(item.get("langue") or ""),
                                         str(item.get("format") or ""),
                                         int(item["size"]) if str(item.get("size") or "").isdigit() else None))
                seen_media_types.add(media_type)
        source_url = f"https://www.screenscraper.fr/gameinfos.php?gameid={remote_id}" if remote_id else ""
        return ScrapeCandidate(
            candidate_id=f"screenscraper:{remote_id or abs(hash((title, system_name)))}",
            provider=self.provider_id, remote_game_id=remote_id, title=title,
            system=system_name, fields={k: v for k, v in fields.items() if v not in (None, "")},
            media=tuple(media), alternate_titles=tuple(dict.fromkeys(
                [*names, _text(game.get("nom"))])), evidence=evidence,
            confidence=confidence, confidence_reason=evidence[0] if evidence else "",
            source_url=source_url)


def _title_similarity(query: str, title: str, alternate_titles=()) -> float:
    def clean(value):
        return re.sub(r"[^0-9a-z가-힣]+", " ", str(value or "").casefold()).strip()

    wanted = clean(query)
    if not wanted:
        return 0.0
    scores = []
    for value in (title, *(alternate_titles or ())):
        candidate = clean(value)
        if not candidate:
            continue
        if candidate == wanted:
            return 1.0
        ratio = SequenceMatcher(None, wanted, candidate).ratio()
        wanted_tokens, candidate_tokens = set(wanted.split()), set(candidate.split())
        overlap = len(wanted_tokens & candidate_tokens) / max(1, len(wanted_tokens | candidate_tokens))
        scores.append(max(ratio, overlap))
    return max(scores, default=0.0)
