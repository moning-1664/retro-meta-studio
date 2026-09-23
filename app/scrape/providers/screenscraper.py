from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass
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
        try:
            response = self.http.get(f"{API_BASE}/{endpoint}", params=query,
                                     timeout=self.config.timeout)
        except _REQUEST_ERROR as exc:
            raise ScreenScraperError(f"ScreenScraper 연결 실패: {exc}", kind="network") from exc
        if response.status_code in (401, 403):
            raise ScreenScraperError("ScreenScraper 인증에 실패했습니다.", kind="auth")
        if response.status_code == 429:
            raise ScreenScraperError("ScreenScraper 요청 제한에 도달했습니다.", kind="quota")
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
        if not identity.path or not Path(identity.path).is_file():
            return []
        hashes = hashes_of_file(identity.path)
        params = {"romnom": identity.filename, "romtaille": hashes["size"],
                  "crc": hashes["crc32"], "md5": hashes["md5"], "sha1": hashes["sha1"]}
        alias = identity.lookup_alias or {}
        for source, target in (("crc32", "crc"), ("md5", "md5"), ("sha1", "sha1"), ("size", "romtaille")):
            if alias.get(source):
                params[target] = alias[source]
        if alias.get("systemId"):
            params["systemeid"] = alias["systemId"]
        try:
            game = (self._get("jeuInfos.php", params).get("response") or {}).get("jeu")
        except ScreenScraperError as exc:
            # A normal unknown-ROM response is often a textual provider error.
            # Authentication/quota/network failures must remain visible.
            if exc.kind in ("auth", "quota", "network"):
                raise
            return []
        return [self._candidate(game, evidence=("원본 별칭 해시 일치" if alias else "ROM 해시 일치",),
                                confidence=100)] if game else []

    def search(self, query: str, system_hint: str = "") -> list[ScrapeCandidate]:
        query = str(query or "").strip()
        if not query:
            return []
        params = {"recherche": query}
        if str(system_hint or "").isdigit():
            params["systemeid"] = str(system_hint)
        response = self._get("jeuRecherche.php", params).get("response") or {}
        games = response.get("jeux") or response.get("jeu") or []
        if isinstance(games, dict) and "jeu" in games:
            games = games["jeu"]
        return [self._candidate(game, evidence=(f'검색어 "{query}"',), confidence=55)
                for game in _list(games) if isinstance(game, dict)]

    def _candidate(self, game: dict, *, evidence: tuple[str, ...], confidence: int) -> ScrapeCandidate:
        remote_id = str(game.get("id") or game.get("jeu_id") or "")
        names = [_text(item) for item in _list(game.get("noms")) if _text(item)]
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
        for item in _list(game.get("medias")):
            if not isinstance(item, dict) or not item.get("url"):
                continue
            media_type = MEDIA_TYPES.get(str(item.get("type") or "").lower())
            if media_type:
                media.append(ScrapeMedia(media_type, str(item["url"]),
                                         str(item.get("region") or ""),
                                         str(item.get("langue") or ""),
                                         str(item.get("format") or ""),
                                         int(item["size"]) if str(item.get("size") or "").isdigit() else None))
        source_url = f"https://www.screenscraper.fr/gameinfos.php?gameid={remote_id}" if remote_id else ""
        return ScrapeCandidate(
            candidate_id=f"screenscraper:{remote_id or abs(hash((title, system_name)))}",
            provider=self.provider_id, remote_game_id=remote_id, title=title,
            system=system_name, fields={k: v for k, v in fields.items() if v not in (None, "")},
            media=tuple(media), alternate_titles=tuple(dict.fromkeys(names)), evidence=evidence,
            confidence=confidence, confidence_reason=evidence[0] if evidence else "",
            source_url=source_url)
