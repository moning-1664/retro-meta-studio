from __future__ import annotations

import threading
import time
import uuid
import re
import logging
import sqlite3
from dataclasses import replace
from pathlib import Path

from app.scrape.providers.screenscraper import ARCADE_SYSTEMS, _system_id

log = logging.getLogger(__name__)
MISS_TTL_SECONDS = 10 * 60
MAX_NAME_REQUESTS = 5

from app.scrape.models import ScrapeIdentity


def _query_fallbacks(query: str) -> list[str]:
    """Bounded punctuation and subtitle variants for weak searches."""
    value = re.sub(r"\s+", " ", str(query or "")).strip()
    value = value.replace("：", ":")
    variants = []
    if ":" in value:
        main, subtitle = value.split(":", 1)
        if main.strip() and subtitle.strip():
            variants.extend((f"{main.strip()}:{subtitle.strip()}" if subtitle.startswith(" ")
                             else f"{main.strip()}: {subtitle.strip()}", main.strip(), subtitle.strip()))
    else:
        parts = re.split(r"\s+[-–—]\s+", value, maxsplit=1)
        if len(parts) == 2 and all(part.strip() for part in parts):
            variants.extend((f"{parts[0].strip()}: {parts[1].strip()}",
                             parts[0].strip(), parts[1].strip()))
        else:
            parenthesized = re.fullmatch(r"(.+?)\s+\([^()]+\)", value)
            if parenthesized:
                variants.append(parenthesized.group(1).strip())
    # "Neon Genesis Evangelion 2" may only be indexed as
    # "Shinseiki Evangelion 2". Keep a number-bearing distinctive suffix as a
    # bounded suggestion; never auto-confirm a candidate returned by it.
    tokens = value.split()
    if len(tokens) >= 4 and re.search(r"\d", tokens[-1]):
        variants.append(" ".join(tokens[-2:]))
    return list(dict.fromkeys(candidate for candidate in variants
                              if candidate and candidate.casefold() != value.casefold()))[:3]


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
    def __init__(self, provider_factory, sessions: ScrapeSessionStore | None = None,
                 dat_catalog=None):
        self.provider_factory = provider_factory
        self.sessions = sessions or ScrapeSessionStore()
        self.dat_catalog = dat_catalog
        self._failed_queries: dict[tuple[str, str], float] = {}
        self._failed_lock = threading.Lock()

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
                "originalQuery": query,
                "fields": dict(fields or {}), "status": "pending", "candidates": [],
                "selectedCandidateId": None, "selectedFields": [], "selectedMedia": []}

    def search_item(self, session_id: str, item_id: str, query: str | None,
                    system_hint: str | None, progress=None, force_search=False) -> dict:
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
        actual_query = str(query or item["query"]).strip()
        item["requestedQuery"] = actual_query
        dat_hint = None
        if (self.dat_catalog is not None and not force_search
                and actual_query.casefold() == item["originalQuery"].casefold()):
            try:
                dat_hint = self.dat_catalog.lookup(
                    selected_system, item["filename"], item.get("path"), item.get("size"))
            except (OSError, ValueError, sqlite3.Error):
                log.exception("DAT lookup failed system=%s filename=%s",
                              selected_system, item["filename"])
        item["datHint"] = dat_hint
        confirmed_id = item.get("confirmedGameId")
        confirmed_lookup = getattr(provider, "confirmed_game", None)
        use_confirmed = (not force_search and confirmed_id and callable(confirmed_lookup)
                         and actual_query.casefold() == item["originalQuery"].casefold()
                         and _system_id(selected_system) == _system_id(item["system"])
                         and _system_id(selected_system) is not None)
        candidates = confirmed_lookup(confirmed_id, selected_system) if use_confirmed else []
        if use_confirmed:
            request_count += 1
            log.info("Scraper confirmed lookup system=%s filename=%s gameId=%s found=%d",
                     selected_system, item["filename"], confirmed_id, len(candidates))
        alias_id = item.get("aliasGameId") if not force_search and not candidates else None
        if alias_id and callable(confirmed_lookup):
            candidates = [replace(candidate, confidence=85,
                                  confidence_reason="이전에 확정한 검색어 별칭")
                          for candidate in confirmed_lookup(alias_id, selected_system)]
            request_count += 1
        if not candidates:
            candidates = provider.identify(identity)
        identified = bool(candidates)
        if not candidates and (selected_system and not identity.is_modified_rom and
                (selected_system.lower() in ARCADE_SYSTEMS
                or (identity.path and Path(identity.path).is_file()
                    and getattr(getattr(provider, "config", None), "use_hashes", True)))):
            request_count += 1
        best_query = actual_query
        by_id = {candidate.candidate_id: candidate for candidate in candidates}
        weak_arcade_identity = (identified and selected_system.lower() in ARCADE_SYSTEMS
                                and max((c.confidence for c in candidates), default=0) < 45)
        name_requests = 0

        def best_confidence() -> int:
            return max((candidate.confidence for candidate in by_id.values()), default=0)

        def search_with(search_query: str, source: str):
            nonlocal request_count, best_query, name_requests
            if name_requests >= MAX_NAME_REQUESTS:
                return
            miss_key = (selected_system.casefold(), search_query.casefold())
            with self._failed_lock:
                last_miss = self._failed_queries.get(miss_key)
            if (last_miss is not None and not force_search
                    and time.monotonic() - last_miss < MISS_TTL_SECONDS):
                log.info("Scraper recent miss cache system=%s query=%s",
                         selected_system, search_query)
                return
            if progress:
                progress(2, 3, f'"{search_query}" 검색')
            found = provider.search(search_query, selected_system)
            name_requests += 1
            request_count += 1
            with self._failed_lock:
                if found:
                    self._failed_queries.pop(miss_key, None)
                else:
                    self._failed_queries[miss_key] = time.monotonic()
                    if len(self._failed_queries) > 1024:
                        oldest = min(self._failed_queries, key=self._failed_queries.get)
                        self._failed_queries.pop(oldest, None)
            log.info("Scraper search source=%s system=%s query=%s candidates=%d",
                     source, selected_system or "all", search_query, len(found))
            before = best_confidence()
            for candidate in found:
                previous = by_id.get(candidate.candidate_id)
                if previous is None:
                    by_id[candidate.candidate_id] = candidate
                else:
                    evidence = tuple(dict.fromkeys((*previous.evidence, *candidate.evidence)))
                    chosen = candidate if candidate.confidence > previous.confidence else previous
                    by_id[candidate.candidate_id] = replace(chosen, evidence=evidence)
            if best_confidence() > before:
                best_query = search_query

        if (dat_hint and dat_hint["title"].casefold() != actual_query.casefold()
                and best_confidence() < 80):
            search_with(dat_hint["title"], "user-dat")
        if best_confidence() < 80:
            search_with(actual_query, "filename-or-manual")
        # A weak first result must not block a better spelling. Bound extra
        # requests and stop once a strong candidate is available for review.
        if best_confidence() < 80:
            for alternative in _query_fallbacks(actual_query):
                search_with(alternative, "punctuation")
                if best_confidence() >= 80:
                    break
        if (weak_arcade_identity or best_confidence() < 80) and actual_query == item["query"]:
            known_title = str((item.get("fields") or {}).get("name") or "").strip()
            if (len(known_title) > 3 and re.search(r"[A-Za-z]", known_title)
                    and known_title.casefold() not in
                    {actual_query.casefold(), *[v.casefold() for v in _query_fallbacks(actual_query)]}):
                search_with(known_title, "existing-title")
        candidates = list(by_id.values())
        actual_query = best_query
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
