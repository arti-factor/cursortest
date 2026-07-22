"""Ordnet extrahierte Website-Standorte den passenden Google-Unternehmensprofilen zu.

Drei mögliche Ausgänge je Standort:
- EINDEUTIG: Konfidenz >= auto_accept_threshold -> automatisch übernommen
- MEHRDEUTIG: mehrere Kandidaten zwischen review_threshold und auto_accept_threshold
  -> Nutzer wählt interaktiv (siehe cli.py)
- KEIN_TREFFER: kein Kandidat über review_threshold -> zentraler Audit-Befund
  ("Standort ohne Google-Unternehmensprofil")

Zusätzlich: Umkreissuche nach möglichen Duplikaten/verwaisten Alteinträgen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

import phonenumbers
from rapidfuzz import fuzz

from src.api_places import PlacesClient
from src.models import Location, MatchStatus


def normalize_phone(raw: str, region: str = "DE") -> str:
    if not raw:
        return ""
    try:
        parsed = phonenumbers.parse(raw, region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    # Fallback: nur Ziffern vergleichen, wenn die Nummer nicht sauber parsbar ist
    return "".join(ch for ch in raw if ch.isdigit())


def _domain(url: str) -> str:
    if not url:
        return ""
    if "://" not in url:
        url = f"//{url}"
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


@dataclass
class MatchCandidate:
    place: dict[str, Any]
    confidence: float
    name_score: float
    address_score: float
    phone_score: float
    domain_score: float


@dataclass
class MatchResult:
    status: MatchStatus
    candidates: list[MatchCandidate] = field(default_factory=list)
    chosen: Optional[MatchCandidate] = None


def _place_name(place: dict[str, Any]) -> str:
    dn = place.get("displayName", {})
    return dn.get("text", "") if isinstance(dn, dict) else str(dn or "")


def _place_phone(place: dict[str, Any]) -> str:
    return place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber", "")


def nap_similarity(
    location: Location,
    candidate_name: str,
    candidate_address: str,
    candidate_phone: str,
    candidate_website: str,
    weights: dict[str, float],
) -> dict[str, float]:
    """Portal-unabhängiger NAP-Ähnlichkeitsvergleich (Name/Adresse/Telefon/Website-Domain).

    Nutzt dieselbe Logik wie das Google-Places-Matching, aber auf einfachen
    Strings statt eines Places-API-spezifischen JSON-Objekts - so nutzbar für
    beliebige Portale (Foursquare, Yelp, erfasster Bookmarklet-Rohtext, ...).
    """
    name_score = fuzz.token_sort_ratio(location.name.lower(), (candidate_name or "").lower())

    addr_text = f"{location.street} {location.zip} {location.city}".strip().lower()
    cand_addr = (candidate_address or "").lower()
    address_score = fuzz.token_set_ratio(addr_text, cand_addr) if addr_text and cand_addr else 0.0
    if location.zip and location.zip in cand_addr:
        address_score = max(address_score, 90.0)

    loc_phone = normalize_phone(location.phone)
    cand_phone = normalize_phone(candidate_phone)
    phone_score = 100.0 if loc_phone and cand_phone and loc_phone == cand_phone else 0.0

    loc_domain = _domain(location.website)
    cand_domain = _domain(candidate_website)
    domain_score = 100.0 if loc_domain and cand_domain and loc_domain == cand_domain else 0.0

    confidence = (
        weights.get("name", 0.4) * name_score
        + weights.get("address", 0.3) * address_score
        + weights.get("phone", 0.2) * phone_score
        + weights.get("website_domain", 0.1) * domain_score
    )
    return {
        "name_score": name_score,
        "address_score": address_score,
        "phone_score": phone_score,
        "domain_score": domain_score,
        "confidence": round(confidence, 1),
    }


def compute_confidence(location: Location, place: dict[str, Any], weights: dict[str, float]) -> MatchCandidate:
    scores = nap_similarity(
        location, _place_name(place), place.get("formattedAddress") or "", _place_phone(place), place.get("websiteUri", ""), weights
    )
    return MatchCandidate(
        place=place,
        confidence=scores["confidence"],
        name_score=scores["name_score"],
        address_score=scores["address_score"],
        phone_score=scores["phone_score"],
        domain_score=scores["domain_score"],
    )


def match_location(location: Location, places_client: PlacesClient, matching_config: dict[str, Any]) -> MatchResult:
    query = f"{location.name}, {location.address}".strip(", ")
    raw_candidates = places_client.text_search(query, max_results=5)

    weights = matching_config.get("weights", {})
    scored = [compute_confidence(location, place, weights) for place in raw_candidates]
    scored.sort(key=lambda c: c.confidence, reverse=True)

    auto_accept = matching_config.get("auto_accept_threshold", 90)
    review = matching_config.get("review_threshold", 60)

    if not scored or scored[0].confidence < review:
        return MatchResult(status=MatchStatus.KEIN_TREFFER, candidates=scored)

    if scored[0].confidence >= auto_accept and (len(scored) == 1 or scored[0].confidence - scored[1].confidence >= 10):
        return MatchResult(status=MatchStatus.EINDEUTIG, candidates=scored, chosen=scored[0])

    plausible = [c for c in scored if c.confidence >= review]
    if len(plausible) == 1:
        return MatchResult(status=MatchStatus.EINDEUTIG, candidates=scored, chosen=plausible[0])

    return MatchResult(status=MatchStatus.MEHRDEUTIG, candidates=plausible)


def find_duplicates(
    chosen_place: dict[str, Any],
    places_client: PlacesClient,
    matching_config: dict[str, Any],
) -> list[str]:
    """Sucht im Umkreis des gewählten Treffers nach möglichen Duplikaten (ähnlicher Name)."""
    location_data = chosen_place.get("location") or {}
    lat, lng = location_data.get("latitude"), location_data.get("longitude")
    if lat is None or lng is None:
        return []

    radius = matching_config.get("duplicate_search_radius_meters", 500)
    nearby = places_client.search_nearby(lat, lng, radius)

    chosen_id = chosen_place.get("id")
    chosen_name = _place_name(chosen_place).lower()
    duplicates = []
    for place in nearby:
        if place.get("id") == chosen_id:
            continue
        similarity = fuzz.token_sort_ratio(chosen_name, _place_name(place).lower())
        if similarity >= 80:
            duplicates.append(place.get("id"))
    return duplicates
