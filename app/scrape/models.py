from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re


# Only explicit translation/hack markers suppress a useful original-ROM hash.
_PATCH_TAG = re.compile(
    r"\s*[\[(][^\])]*(?:T[-_ ]?(?:Kor|Korean|Eng|English|En|Kr)|"
    r"Translat(?:ed|ion)|Hack|Patch|한글(?:화)?|번역|패치)[^\])]*[\])]",
    re.IGNORECASE,
)
_PATCH_SUFFIX = re.compile(r"\s+(?:한글(?:화)?\s*패치|번역판|번역\s*패치)\s*$", re.IGNORECASE)
_PATCH_BARE = re.compile(r"(?<!\S)T[-_ ]?(?:Korean|English|Kor|Eng|En|Kr)(?!\S)", re.IGNORECASE)


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
    def is_modified_rom(self) -> bool:
        name = Path(self.filename).stem
        return bool(_PATCH_TAG.search(name) or _PATCH_SUFFIX.search(name)
                    or _PATCH_BARE.search(name))

    @property
    def default_query(self) -> str:
        name = Path(self.filename).stem
        # Strip recognized dump tags, but retain meaningful parenthesized
        # subtitles (e.g. "Game (Special Edition)").
        tag = (r"(?:K|KR|KOR|J|JP|JPN|U|US|USA|E|EU|EUR|W|World|Japan|Korea|Europe|"
               r"Rev(?:ision)?\s*[\w.-]+|v\d[\w.-]*|!|"
               r"(?:En|Fr|De|Es|It|Ja|Ko)(?:\s*,\s*(?:En|Fr|De|Es|It|Ja|Ko))+)" )
        cleaned = _PATCH_SUFFIX.sub("", _PATCH_BARE.sub(" ", _PATCH_TAG.sub(" ", name)))
        cleaned = re.sub(rf"\s*[\[(]{tag}[\])]\s*", " ", cleaned, flags=re.IGNORECASE)
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
