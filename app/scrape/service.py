from __future__ import annotations

import threading
import time
import uuid
import re
import logging
from pathlib import Path

from app.scrape.providers.screenscraper import ARCADE_SYSTEMS

log = logging.getLogger(__name__)

from app.scrape.models import ScrapeIdentity


def _query_fallbacks(query: str) -> list[str]:
    """At most two specific spelling variants after the original search misses."""
    value = re.sub(r"\s+", " ", str(query or "")).strip()
    variants = []
    if ":" in value:
        main, subtitle = value.split(":", 1)
        if main.strip() and subtitle.strip():
            variants.extend((f"{main.strip()}:{subtitle.strip()}" if subtitle.startswith(" ")
                             else f"{main.strip()}: {subtitle.strip()}", main.strip()))
    else:
        parts = re.split(r"\s+[-–—]\s+", value, maxsplit=1)
        if len(parts) == 2 and all(part.strip() for part in parts):
            variants.extend((f"{parts[0].strip()}: {parts[1].strip()}", parts[0].strip()))
        else:
            parenthesized = re.fullmatch(r"(.+?)\s+\([^()]+\)", value)
            if parenthesized:
                variants.append(parenthesized.group(1).strip())
    return list(dict.fromkeys(candidate for candidate in variants
                              if candidate and candidate.casefold() != value.casefold()))[:2]


class ScrapeSessionStore:
    """Short-lived review state. Nothing is applied until the explicit final step."""

    def __init__(self):
        self._sessions: dict[str, dict] = {}
        self._lock = threading.RLock()

    def create(self, target: str, collection_id: str | None, items: list[dict]) -> dict:
        session_id = str(uuid.uuid4())
        session = {"id": session_id, "target": target, "collectionId": collection_id,
                   "createdAt": time.time(), "items": items, "quota": None}
        with self._lock:
            self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> dict:
        with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None:
                raise KeyError("스크랩 세션을 찾을 수 없습니다.")
            return session

    def close(self, session_id: str):
        with self._lock:
            return self._sessions.pop(str(session_id), None) is not None


class ScrapeService:
    def __init__(self, provider_factory, sessions: ScrapeSessionStore | None = None):
        self.provider_factory = provider_factory
        self.sessions = sessions or ScrapeSessionStore()

    @staticmethod
    def item(item_id, system, filename, fields, *, path=None, size=None) -> dict:
        identity = ScrapeIdentity(system=str(system or ""), filename=str(filename or ""),
                                  path=str(path) if path else None,
                                  size=int(size) if size is not None else None)
        # Search from the ROM filename, even when an existing localized
        # gamelist title is present. The user can still edit the key manually.
        query = identity.default_query
        return {"id": str(item_id), "system": identity.system, "filename": identity.filename,
                "path": identity.path, "size": identity.size, "query": query,
                "fields": dict(fields or {}), "status": "pending", "candidates": [],
                "selectedCandidateId": None, "selectedFields": [], "selectedMedia": []}

    def search_item(self, session_id: str, item_id: str, query: str | None,
                    system_hint: str | None, progress=None) -> dict:
        session = self.sessions.get(session_id)
        item = next((row for row in session["items"] if row["id"] == str(item_id)), None)
        if item is None:
            raise KeyError("스크랩할 항목을 찾을 수 없습니다.")
        provider = self.provider_factory()
        if progress:
            progress(0, 3, "계정 사용량 확인")
        # Account status is a separate network round trip. A slow quota call
        # must not delay the actual game search or turn its timeout into a
        # failed match. The UI refreshes quota independently.
        quota = dict(session.get("quota") or {})
        request_count = 0
        if progress:
            progress(1, 3, "ROM 식별")
        selected_system = item["system"] if system_hint is None else str(system_hint)
        identity = ScrapeIdentity(selected_system, item["filename"],
                                  item.get("path"), item.get("size"))
        candidates = provider.identify(identity)
        if (selected_system and not identity.is_modified_rom and
                (selected_system.lower() in ARCADE_SYSTEMS
                or (identity.path and Path(identity.path).is_file()
                    and getattr(getattr(provider, "config", None), "use_hashes", True)))):
            request_count += 1
        actual_query = str(query or item["query"]).strip()
        if not candidates:
            if progress:
                progress(2, 3, f'"{actual_query}" 검색')
            candidates = provider.search(actual_query, selected_system)
            request_count += 1
        if not candidates:
            for alternative in _query_fallbacks(actual_query):
                if progress:
                    progress(2, 3, f'"{alternative}" 검색')
                log.info("Scraper query fallback system=%s original=%s alternative=%s",
                         selected_system or "all", actual_query, alternative)
                candidates = provider.search(alternative, selected_system)
                request_count += 1
                if candidates:
                    actual_query = alternative
                    break
        if (not candidates and selected_system.lower() in ARCADE_SYSTEMS
                and actual_query == item["query"]):
            known_title = str((item.get("fields") or {}).get("name") or "").strip()
            # A pre-existing human title can rescue an unknown short ROM-set
            # code; localized Hangul titles are poor ScreenScraper search keys.
            if (len(known_title) > 3 and re.search(r"[A-Za-z]", known_title)
                    and known_title.casefold() != actual_query.casefold()):
                if progress:
                    progress(2, 3, f'기존 제목 "{known_title}" 검색')
                candidates = provider.search(known_title, selected_system)
                request_count += 1
                if candidates:
                    actual_query = known_title
        # Python's stable sort preserves provider rank among equally scored
        # short-name results, where title alphabetization loses search order.
        candidates = sorted(candidates, key=lambda c: -c.confidence)
        if not candidates:
            log.info("Scraper unmatched system=%s filename=%s query=%s",
                     selected_system or "all", item["filename"], actual_query)
        item.update({"query": actual_query, "status": "review" if candidates else "not_found",
                     "candidates": [candidate.to_dict() for candidate in candidates],
                     "selectedCandidateId": None, "selectedFields": [], "selectedMedia": []})
        if request_count:
            quota["requestsToday"] = int(quota.get("requestsToday") or 0) + request_count
            quota["estimated"] = True
        session["quota"] = quota
        if progress:
            progress(3, 3, "후보 준비 완료")
        return {"sessionId": session_id, "item": item, "quota": quota}

    def select(self, session_id: str, item_id: str, candidate_id: str,
               selected_fields: list[str] | None = None,
               selected_media: list[int] | None = None) -> dict:
        session = self.sessions.get(session_id)
        item = next((row for row in session["items"] if row["id"] == str(item_id)), None)
        if item is None:
            raise KeyError("스크랩할 항목을 찾을 수 없습니다.")
        candidate = next((row for row in item["candidates"]
                          if row["candidate_id"] == candidate_id), None)
        if candidate is None:
            raise KeyError("선택한 후보를 찾을 수 없습니다.")
        available = set(candidate.get("fields") or {})
        requested = available if selected_fields is None else selected_fields
        chosen = [key for key in requested if key in available]
        media = candidate.get("media") or []
        media_indexes = [int(index) for index in (selected_media or [])
                         if str(index).isdigit() and 0 <= int(index) < len(media)]
        item.update({"selectedCandidateId": candidate_id, "selectedFields": chosen,
                     "selectedMedia": media_indexes, "status": "selected"})
        return item

    def skip(self, session_id: str, item_id: str) -> dict:
        session = self.sessions.get(session_id)
        item = next((row for row in session["items"] if row["id"] == str(item_id)), None)
        if item is None:
            raise KeyError("스크랩할 항목을 찾을 수 없습니다.")
        item.update({"selectedCandidateId": None, "selectedFields": [],
                     "selectedMedia": [], "status": "skipped"})
        return item

    @staticmethod
    def proposal(item: dict) -> dict | None:
        candidate = next((row for row in item.get("candidates") or []
                          if row["candidate_id"] == item.get("selectedCandidateId")), None)
        if candidate is None:
            return None
        fields = candidate.get("fields") or {}
        media = candidate.get("media") or []
        return {"itemId": item["id"],
                "fields": {key: fields[key] for key in item.get("selectedFields") or [] if key in fields},
                "media": [media[index] for index in item.get("selectedMedia") or []
                          if 0 <= index < len(media)],
                "provenance": {"provider": candidate["provider"],
                               "remoteGameId": candidate["remote_game_id"],
                               "sourceUrl": candidate.get("source_url") or "",
                               "evidence": candidate.get("evidence") or []}}
