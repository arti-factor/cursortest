"""Gruppe 1 - Basisdaten & NAP (Modus A, Gewicht 15%)."""
from __future__ import annotations

from collections import Counter

from rapidfuzz import fuzz

from src.checks.base import CheckContext, fehler, nicht_pruefbar, ok, warnung
from src.matching import normalize_phone

GRUPPE = "basisdaten_nap"


def _feld_vorhanden(check_id: str, ctx: CheckContext, wert: str, feldname: str):
    loc_id = ctx.location.id
    if wert and wert.strip():
        return ok(check_id, GRUPPE, ctx.modus, f"{feldname} im Profil vorhanden.", standort_id=loc_id)
    return fehler(
        check_id,
        GRUPPE,
        ctx.modus,
        f"{feldname} fehlt im Google-Unternehmensprofil.",
        f"{feldname} im Profil ergänzen.",
        standort_id=loc_id,
    )


def _nap_abgleich(ctx: CheckContext):
    loc_id = ctx.location.id
    profile = ctx.profile
    abweichungen = []

    name_sim = fuzz.token_sort_ratio(ctx.location.name.lower(), (profile.display_name or "").lower())
    if name_sim < 85:
        abweichungen.append(f"Name weicht ab (Website: '{ctx.location.name}' vs. Profil: '{profile.display_name}')")

    addr_sim = fuzz.token_set_ratio(
        ctx.location.address.lower(), (profile.formatted_address or "").lower()
    )
    if ctx.location.zip and ctx.location.zip not in (profile.formatted_address or ""):
        abweichungen.append(
            f"Adresse weicht ab (Website: '{ctx.location.address}' vs. Profil: '{profile.formatted_address}')"
        )
    elif addr_sim < 60:
        abweichungen.append(
            f"Adresse weicht ab (Website: '{ctx.location.address}' vs. Profil: '{profile.formatted_address}')"
        )

    if ctx.location.phone and profile.phone:
        if normalize_phone(ctx.location.phone) != normalize_phone(profile.phone):
            abweichungen.append(f"Telefonnummer weicht ab (Website: '{ctx.location.phone}' vs. Profil: '{profile.phone}')")

    if abweichungen:
        return warnung(
            "nap_abgleich",
            GRUPPE,
            ctx.modus,
            "NAP-Abgleich Website <-> Profil: " + "; ".join(abweichungen),
            "Angaben zwischen Website und Google-Unternehmensprofil angleichen.",
            punkte=max(0.0, 100.0 - 30.0 * len(abweichungen)),
            standort_id=loc_id,
        )
    return ok("nap_abgleich", GRUPPE, ctx.modus, "NAP-Daten stimmen zwischen Website und Profil überein.", standort_id=loc_id)


def _einheitliches_namensschema(ctx: CheckContext):
    """Nur bei Mehrstandort-Kunden: prüft, ob alle Profile demselben Namensmuster folgen
    (z.B. 'Marke Stadtteil' vs. 'Marke - Stadtteil' vs. 'Stadtteil Marke')."""
    loc_id = ctx.location.id
    if not ctx.is_multi_location:
        return nicht_pruefbar(
            "nap_einheitliches_namensschema",
            GRUPPE,
            ctx.modus,
            "Nur bei Mehrstandort-Kunden relevant (dieser Kunde hat einen Standort).",
            standort_id=loc_id,
        )

    def separator_pattern(name: str) -> str:
        for sep in (" - ", " | ", ", ", " – "):
            if sep in name:
                return sep
        return "<leerzeichen>"

    all_names = [ctx.profile.display_name] + [p.display_name for p in ctx.peer_profiles if p.display_name]
    all_names = [n for n in all_names if n]
    patterns = Counter(separator_pattern(n) for n in all_names)
    haeufigstes_muster, _ = patterns.most_common(1)[0]
    eigenes_muster = separator_pattern(ctx.profile.display_name)

    if eigenes_muster != haeufigstes_muster and len(patterns) > 1:
        return warnung(
            "nap_einheitliches_namensschema",
            GRUPPE,
            ctx.modus,
            f"Namensschema weicht vom kundenweiten Muster ab (häufigstes Muster: '{haeufigstes_muster}').",
            "Profilnamen über alle Standorte an ein einheitliches Schema angleichen.",
            punkte=60.0,
            standort_id=loc_id,
        )
    return ok(
        "nap_einheitliches_namensschema",
        GRUPPE,
        ctx.modus,
        "Namensschema entspricht dem kundenweit üblichen Muster.",
        standort_id=loc_id,
    )


def _website_link_korrekt(ctx: CheckContext):
    loc_id = ctx.location.id
    profile_url = (ctx.profile.website_uri or "").rstrip("/")
    erwartete_url = (ctx.location.website or ctx.location.source_url or "").rstrip("/")

    if not profile_url:
        return fehler(
            "nap_website_link",
            GRUPPE,
            ctx.modus,
            "Kein Website-Link im Profil hinterlegt.",
            "Website-Link im Profil ergänzen.",
            standort_id=loc_id,
        )

    if not erwartete_url:
        return nicht_pruefbar(
            "nap_website_link",
            GRUPPE,
            ctx.modus,
            "Keine erwartete Ziel-URL aus der Discovery bekannt.",
            standort_id=loc_id,
        )

    if profile_url == erwartete_url:
        return ok("nap_website_link", GRUPPE, ctx.modus, "Website-Link zeigt auf die korrekte Seite.", standort_id=loc_id)

    from urllib.parse import urlparse

    profile_path = urlparse(profile_url).path.strip("/")
    if ctx.is_multi_location and not profile_path:
        return warnung(
            "nap_website_link",
            GRUPPE,
            ctx.modus,
            "Website-Link zeigt auf die Startseite statt auf die spezifische Standortseite.",
            "Bei Mehrstandort-Profilen auf die jeweilige Standort-/Filialseite verlinken.",
            punkte=50.0,
            standort_id=loc_id,
        )

    return warnung(
        "nap_website_link",
        GRUPPE,
        ctx.modus,
        f"Website-Link weicht von der erwarteten Zielseite ab (Profil: '{profile_url}', erwartet: '{erwartete_url}').",
        "Website-Link im Profil korrigieren.",
        punkte=50.0,
        standort_id=loc_id,
    )


def run(ctx: CheckContext) -> list:
    if ctx.profile is None:
        loc_id = ctx.location.id
        return [
            nicht_pruefbar(cid, GRUPPE, ctx.modus, "Kein GBP-Profil vorhanden - siehe Gruppe 'Existenz'.", standort_id=loc_id)
            for cid in (
                "nap_name_vorhanden",
                "nap_adresse_vorhanden",
                "nap_telefon_vorhanden",
                "nap_website_vorhanden",
                "nap_abgleich",
                "nap_einheitliches_namensschema",
                "nap_website_link",
            )
        ]

    results = [
        _feld_vorhanden("nap_name_vorhanden", ctx, ctx.profile.display_name, "Name"),
        _feld_vorhanden("nap_adresse_vorhanden", ctx, ctx.profile.formatted_address, "Adresse"),
        _feld_vorhanden("nap_telefon_vorhanden", ctx, ctx.profile.phone, "Telefonnummer"),
        _feld_vorhanden("nap_website_vorhanden", ctx, ctx.profile.website_uri, "Website"),
        _nap_abgleich(ctx),
        _einheitliches_namensschema(ctx),
        _website_link_korrekt(ctx),
    ]
    return results
