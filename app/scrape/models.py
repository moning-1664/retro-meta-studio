from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ScrapeIdentity:
    system: str
    filename: str
    path: str | None = None
    size: int | None = None
    crc32: str | None = None
    md5: str | None = None
    sha1: str | None = None
    lookup_alias: dict | None = None

    @property
    def default_query(self) -> str:
        name = Path(self.filename).stem
        # Common dump/region/revision decorations are poor search terms. Keep
        # this deliberately conservative: the editable search key is the real
        # escape hatch for unusual names and translations.
        import re
        cleaned = re.sub(r"\s*[\[(](?:K|KR|KOR|J|JP|JPN|U|US|USA|E|EU|EUR|W|World|Rev[^\])]*|v\d[^\])]*)[\])]\s*",
                         " ", name, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", cleaned).strip() or name

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ScrapeMedia:
    media_type: str
    url: str
    region: str = ""
    language: str = ""
    format: str = ""
    size: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ScrapeCandidate:
    candidate_id: str
    provider: str
    remote_game_id: str
    title: str
    system: str
    fields: dict
    media: tuple[ScrapeMedia, ...] = field(default_factory=tuple)
    alternate_titles: tuple[str, ...] = field(default_factory=tuple)
    evidence: tuple[str, ...] = field(default_factory=tuple)
    confidence: int = 0
    confidence_reason: str = ""
    source_url: str = ""

    def to_dict(self) -> dict:
        value = asdict(self)
        value["media"] = [m.to_dict() for m in self.media]
        value["alternate_titles"] = list(self.alternate_titles)
        value["evidence"] = list(self.evidence)
        return value
