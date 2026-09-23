from __future__ import annotations

from abc import ABC, abstractmethod

from app.scrape.models import ScrapeCandidate, ScrapeIdentity


class ScrapeProvider(ABC):
    provider_id = ""

    @abstractmethod
    def account_status(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def identify(self, identity: ScrapeIdentity) -> list[ScrapeCandidate]:
        raise NotImplementedError

    @abstractmethod
    def search(self, query: str, system_hint: str = "") -> list[ScrapeCandidate]:
        raise NotImplementedError
