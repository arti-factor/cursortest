"""Registry des Prüfkatalogs.

GROUPS bildet die Reihenfolge/Zuordnung aus config.yaml (scoring.group_weights)
auf die jeweilige Check-Implementierung ab. Eine neue Kriteriengruppe
hinzuzufügen bedeutet: neues Modul unter src/checks/ + Eintrag hier.
"""
from __future__ import annotations

from src.checks import (
    group0_existenz,
    group1_basisdaten,
    group2_kategorien,
    group3_oeffnungszeiten,
    group4_beschreibung,
    group5_fotos,
    group6_bewertungen,
    group7_qna,
    group8_leistungen,
    group9_performance,
    group10_verzeichnisse,
)
from src.checks.base import CheckContext

GROUPS: list[tuple[str, object]] = [
    ("existenz_auffindbarkeit", group0_existenz),
    ("basisdaten_nap", group1_basisdaten),
    ("kategorien", group2_kategorien),
    ("oeffnungszeiten", group3_oeffnungszeiten),
    ("beschreibung_attribute", group4_beschreibung),
    ("fotos", group5_fotos),
    ("bewertungen", group6_bewertungen),
    ("qna", group7_qna),
    ("leistungen", group8_leistungen),
    ("performance", group9_performance),
    ("verzeichnis_konsistenz", group10_verzeichnisse),
]


def run_all_checks(ctx: CheckContext) -> list:
    """Führt alle registrierten Kriteriengruppen für einen Standort aus."""
    results = []
    for _, module in GROUPS:
        results.extend(module.run(ctx))
    return results
