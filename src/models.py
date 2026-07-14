"""Zentrale Datenmodelle für gbp-audit.

Bewusst als einfache dataclasses gehalten (keine ORM-/Pydantic-Abhängigkeit
nötig) mit expliziten to_dict/from_dict-Methoden für die YAML/JSON-Persistenz
unter clients/<kunde>/.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class Modus(str, Enum):
    A = "A"  # Public Audit (nur Places API)
    B = "B"  # Full Audit (OAuth Business-Profile-APIs)


class CheckStatus(str, Enum):
    OK = "ok"
    WARNUNG = "warnung"
    FEHLER = "fehler"
    NICHT_PRUEFBAR = "nicht_pruefbar"


class MatchStatus(str, Enum):
    EINDEUTIG = "eindeutig"
    MEHRDEUTIG = "mehrdeutig"
    KEIN_TREFFER = "kein_treffer"


@dataclass
class Location:
    """Ein aus der Kunden-Website extrahierter Standort."""

    id: str  # stabiler Slug, z.B. aus Name+PLZ abgeleitet
    name: str
    street: str = ""
    zip: str = ""
    city: str = ""
    phone: str = ""
    website: str = ""  # Ziel-URL, auf die das GBP-Profil verlinken sollte
    source_url: str = ""  # Seite, von der die Daten extrahiert wurden
    extraction_method: str = ""  # "json_ld" | "microdata" | "heuristik" | "manuell"
    manuell_ergaenzt: bool = False
    place_id: Optional[str] = None
    match_status: Optional[MatchStatus] = None
    match_confidence: Optional[float] = None
    duplicate_place_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["match_status"] = self.match_status.value if self.match_status else None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Location":
        d = dict(d)
        ms = d.get("match_status")
        d["match_status"] = MatchStatus(ms) if ms else None
        d["duplicate_place_ids"] = d.get("duplicate_place_ids") or []
        return cls(**d)

    @property
    def address(self) -> str:
        parts = [self.street, f"{self.zip} {self.city}".strip()]
        return ", ".join(p for p in parts if p)


@dataclass
class GbpProfile:
    """Konsolidierte GBP-Daten eines Standorts, egal ob aus Modus A oder B."""

    place_id: str
    display_name: str = ""
    formatted_address: str = ""
    phone: str = ""
    website_uri: str = ""
    primary_type: str = ""
    types: list[str] = field(default_factory=list)
    business_status: str = ""
    rating: Optional[float] = None
    user_rating_count: Optional[int] = None
    regular_opening_hours: dict[str, Any] = field(default_factory=dict)
    special_hours: dict[str, Any] = field(default_factory=dict)
    reviews_sample: list[dict[str, Any]] = field(default_factory=list)
    photo_count: Optional[int] = None
    # Modus B - nur gefüllt, wenn OAuth eingerichtet ist
    description: Optional[str] = None
    attributes: dict[str, Any] = field(default_factory=dict)
    service_items: list[dict[str, Any]] = field(default_factory=list)
    reviews_full: Optional[list[dict[str, Any]]] = None
    questions: Optional[list[dict[str, Any]]] = None
    owner_photos: Optional[list[dict[str, Any]]] = None
    performance_metrics: Optional[dict[str, Any]] = None
    modus: Modus = Modus.A

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["modus"] = self.modus.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GbpProfile":
        d = dict(d)
        d["modus"] = Modus(d.get("modus", "A"))
        return cls(**d)


@dataclass
class CheckResult:
    check_id: str
    gruppe: str
    modus: Modus
    status: CheckStatus
    punkte: Optional[float]  # 0-100, None bei NICHT_PRUEFBAR
    befund: str
    empfehlung: str = ""
    standort_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["modus"] = self.modus.value
        d["status"] = self.status.value
        return d


@dataclass
class GroupScore:
    gruppe: str
    punkte: Optional[float]
    gewicht_prozent: float
    checks: list[CheckResult] = field(default_factory=list)
    lauffaehig: bool = True  # False = keine Checks dieser Gruppe im aktuellen Modus lauffähig


@dataclass
class LocationAuditResult:
    location: Location
    profile: Optional[GbpProfile]
    modus: Modus
    gesamtscore: Optional[float]
    ampel: str  # "gruen" | "gelb" | "rot" | "n/a"
    gruppen: list[GroupScore] = field(default_factory=list)


@dataclass
class ClientRun:
    client_slug: str
    run_date: str
    modus: Modus
    results: list[LocationAuditResult] = field(default_factory=list)
