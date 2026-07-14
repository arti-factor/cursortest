"""Grobe Ableitung des Bundeslands aus der Postleitzahl (führende Ziffern).

Dient ausschließlich dazu, die richtige `holidays`-Region für die
Feiertagsprüfung (Gruppe 3, Modus B) zu wählen. Deutsche PLZ-Bereiche
überschneiden sich an einigen Grenzen zwischen Bundesländern; da dies nur
eine Heuristik für eine Ja/Nein-Prüfung ist (nicht rechtsverbindlich),
genügt eine Zuordnung nach den ersten beiden Ziffern mit Mehrheitsregel.
Liefert None, wenn keine plausible Zuordnung möglich ist - der Check
meldet dann "nicht prüfbar" statt eine falsche Region zu raten.
"""
from __future__ import annotations

# Sortierte, nicht überlappende Bereiche über die ersten beiden PLZ-Ziffern (00-99).
_RANGES: list[tuple[int, int, str]] = [
    (0, 1, "SN"),
    (2, 2, "SN"),
    (3, 3, "BB"),
    (4, 4, "ST"),
    (6, 6, "TH"),
    (7, 7, "SN"),
    (8, 9, "BY"),
    (10, 14, "BE"),
    (15, 16, "BB"),
    (17, 19, "MV"),
    (20, 25, "HH"),
    (26, 27, "NI"),
    (28, 29, "HB"),
    (30, 31, "NI"),
    (32, 33, "NW"),
    (34, 37, "HE"),
    (38, 39, "NI"),
    (40, 48, "NW"),
    (49, 49, "NI"),
    (50, 53, "NW"),
    (54, 56, "RP"),
    (57, 59, "NW"),
    (60, 65, "HE"),
    (66, 66, "SL"),
    (67, 67, "RP"),
    (68, 69, "BW"),
    (70, 79, "BW"),
    (80, 87, "BY"),
    (88, 89, "BW"),
    (90, 96, "BY"),
    (97, 97, "BY"),
    (98, 99, "TH"),
]

# holidays-Bibliothek erwartet ISO-3166-2-Subdivisions für Deutschland, z.B. "BE", "BY"
_VALID_SUBDIVISIONS = {
    "BW", "BY", "BE", "BB", "HB", "HH", "HE", "MV", "NI", "NW", "RP", "SL", "SN", "ST", "SH", "TH",
}


def bundesland_from_plz(plz: str) -> str | None:
    if not plz or not plz.isdigit() or len(plz) < 2:
        return None
    prefix = int(plz[:2])
    for start, end, land in _RANGES:
        if start <= prefix <= end:
            return land if land in _VALID_SUBDIVISIONS else None
    return None
