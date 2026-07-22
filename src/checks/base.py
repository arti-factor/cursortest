"""Gemeinsame Basis für alle Checks: Kontext-Objekt und Hilfsfunktionen.

Jede Kriteriengruppe lebt in einem eigenen Modul unter src/checks/ und
exportiert eine Funktion `run(ctx: CheckContext) -> list[CheckResult]`.
Das macht den Katalog erweiterbar: eine neue Gruppe hinzufügen bedeutet
"neues Modul schreiben + in GROUPS registrieren", ohne bestehenden Code
anzufassen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.models import CheckResult, CheckStatus, GbpProfile, Location, Modus, PortalCheck


@dataclass
class CheckContext:
    location: Location
    profile: Optional[GbpProfile]
    modus: Modus
    config: dict[str, Any]
    all_locations: list[Location] = field(default_factory=list)
    all_profiles: dict[str, Optional[GbpProfile]] = field(default_factory=dict)
    previous_profile: Optional[GbpProfile] = None  # für Re-Audit-Deltas (Gruppe 9)
    portal_checks: list[PortalCheck] = field(default_factory=list)  # Verzeichnis-Konsistenz (Gruppe 10)

    @property
    def is_multi_location(self) -> bool:
        return len(self.all_locations) > 1

    @property
    def peer_profiles(self) -> list[GbpProfile]:
        """Profile aller *anderen* Standorte desselben Kunden (für Vergleichs-Checks)."""
        return [
            p
            for loc_id, p in self.all_profiles.items()
            if loc_id != self.location.id and p is not None
        ]


def result(
    check_id: str,
    gruppe: str,
    modus: Modus,
    status: CheckStatus,
    punkte: Optional[float],
    befund: str,
    empfehlung: str = "",
    standort_id: str = "",
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        gruppe=gruppe,
        modus=modus,
        status=status,
        punkte=punkte,
        befund=befund,
        empfehlung=empfehlung,
        standort_id=standort_id,
    )


def ok(check_id: str, gruppe: str, modus: Modus, befund: str, standort_id: str = "", punkte: float = 100.0) -> CheckResult:
    return result(check_id, gruppe, modus, CheckStatus.OK, punkte, befund, standort_id=standort_id)


def warnung(
    check_id: str, gruppe: str, modus: Modus, befund: str, empfehlung: str, punkte: float = 50.0, standort_id: str = ""
) -> CheckResult:
    return result(check_id, gruppe, modus, CheckStatus.WARNUNG, punkte, befund, empfehlung, standort_id)


def fehler(
    check_id: str, gruppe: str, modus: Modus, befund: str, empfehlung: str, punkte: float = 0.0, standort_id: str = ""
) -> CheckResult:
    return result(check_id, gruppe, modus, CheckStatus.FEHLER, punkte, befund, empfehlung, standort_id)


def nicht_pruefbar(check_id: str, gruppe: str, modus: Modus, befund: str, standort_id: str = "") -> CheckResult:
    return result(check_id, gruppe, modus, CheckStatus.NICHT_PRUEFBAR, None, befund, standort_id=standort_id)
