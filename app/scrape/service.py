from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from app.scrape.models import ScrapeIdentity


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
        return {"id": str(item_id), "system": identity.system, "filename": identity.filename,
                "path": identity.path, "size": identity.size, "query": identity.default_query,
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
        quota = dict(session.get("quota") or provider.account_status())
        request_count = 0
        if progress:
            progress(1, 3, "ROM 식별")
        identity = ScrapeIdentity(item["system"], item["filename"], item.get("path"), item.get("size"))
        candidates = provider.identify(identity)
        if identity.path and Path(identity.path).is_file():
            request_count += 1
        actual_query = str(query or item["query"]).strip()
        if not candidates:
            if progress:
                progress(2, 3, f'"{actual_query}" 검색')
            candidates = provider.search(actual_query, system_hint or item["system"])
            request_count += 1
        candidates = sorted(candidates, key=lambda c: (-c.confidence, c.title.lower()))
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
