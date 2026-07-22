"""Registry der Verzeichnis-Portale für die Verzeichnis-Konsistenz-Prüfung.

Drei Portale (Google, Foursquare, Yelp) haben offizielle Such-APIs und werden
automatisch geprüft. Google läuft über die bestehende GBP-Matching-Logik
(siehe matching.py/services.py) und taucht hier bewusst nicht auf - diese
Registry deckt nur die zusätzlichen Verzeichnis-Portale ab.

Alle übrigen Portale haben keine öffentliche Such-API. Für sie generiert
`build_search_url` einen direkten Such-Link; der Nutzer öffnet ihn, findet den
Eintrag und markiert die NAP-Angaben, die dann per Bookmarklet erfasst werden
(siehe src/webapp/main.py, Abschnitt "Verzeichnis-Erfassung").
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from src.models import PortalCheckType

API_PORTAL_IDS = ("foursquare", "yelp")


@dataclass(frozen=True)
class Portal:
    id: str
    label: str
    check_type: PortalCheckType


def api_portals() -> list[Portal]:
    return [
        Portal(id="foursquare", label="Foursquare", check_type=PortalCheckType.API),
        Portal(id="yelp", label="Yelp Deutschland", check_type=PortalCheckType.API),
    ]


def bookmarklet_portals(config: dict[str, Any]) -> list[Portal]:
    eintraege = (config.get("verzeichnis_portale", {}) or {}).get("bookmarklet_portale", {}) or {}
    return [
        Portal(id=portal_id, label=daten.get("label", portal_id), check_type=PortalCheckType.BOOKMARKLET)
        for portal_id, daten in eintraege.items()
    ]


def all_portals(config: dict[str, Any]) -> list[Portal]:
    """Alle Portale der Verzeichnis-Konsistenz-Prüfung (ohne Google)."""
    return api_portals() + bookmarklet_portals(config)


def get_portal(portal_id: str, config: dict[str, Any]) -> Portal:
    for portal in all_portals(config):
        if portal.id == portal_id:
            return portal
    raise ValueError(f"Unbekanntes Portal: '{portal_id}'")


def build_search_url(portal_id: str, standort_name: str, standort_ort: str, config: dict[str, Any]) -> str:
    eintraege = (config.get("verzeichnis_portale", {}) or {}).get("bookmarklet_portale", {}) or {}
    vorlage = (eintraege.get(portal_id) or {}).get("such_url_vorlage", "")
    if not vorlage:
        raise ValueError(f"Keine Such-URL-Vorlage für Portal '{portal_id}' konfiguriert.")
    return vorlage.format(name=quote(standort_name), ort=quote(standort_ort))
