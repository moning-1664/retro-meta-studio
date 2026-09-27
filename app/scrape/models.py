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
        # Strip recognized dump tags, but retain meaningful parenthesized
        # subtitles (e.g. "Game (Special Edition)").
        import re
        tag = (r"(?:K|KR|KOR|J|JP|JPN|U|US|USA|E|EU|EUR|W|World|Japan|Korea|Europe|"
               r"Rev(?:ision)?\s*[\w.-]+|v\d[\w.-]*|!|"
               r"(?:En|Fr|De|Es|It|Ja|Ko)(?:\s*,\s*(?:En|Fr|De|Es|It|Ja|Ko))+)" )
        cleaned = re.sub(rf"\s*[\[(]{tag}[\])]\s*", " ", name, flags=re.IGNORECASE)
        cleaned = re.sub(r"[_]+", " ", cleaned)
        trailing_article = re.fullmatch(r"(.+),\s*(The|A|An)", cleaned.strip(), re.IGNORECASE)
        if trailing_article:
            cleaned = f"{trailing_article.group(2)} {trailing_article.group(1)}"
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
