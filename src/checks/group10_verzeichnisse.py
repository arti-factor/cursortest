"""Gruppe 10 - Verzeichnis-Konsistenz (Modus A, Gewicht konfigurierbar).

Unabhängig vom monatlichen GBP-Audit-Zyklus: prüft, ob der Standort auf
weiteren Verzeichnis-Portalen (neben Google) gelistet ist und ob die NAP-Daten
dort übereinstimmen. Die Ergebnisse kommen aus clients/<kunde>/portale.yaml -
befüllt über die Weboberfläche (Foursquare/Yelp automatisch per API, alle
anderen Portale per Bookmarklet manuell erfasst, siehe src/portals.py) - nicht
aus einem Live-Aufruf während dieses Checks. Ein Portal, das noch nie geprüft
wurde, ist "nicht prüfbar" und fließt (wie bei allen anderen Gruppen) nicht in
den Score ein, bis der erste Check durchgeführt wurde.
"""
from __future__ import annotations

from src.checks.base import CheckContext, fehler, nicht_pruefbar, ok, warnung
from src.models import PortalCheckStatus
from src.portals import all_portals

GRUPPE = "verzeichnis_konsistenz"


def run(ctx: CheckContext) -> list:
    portale = all_portals(ctx.config)
    checks_by_portal = {pc.portal_id: pc for pc in ctx.portal_checks if pc.standort_id == ctx.location.id}

    ergebnisse = []
    for portal in portale:
        check_id = f"verzeichnis_{portal.id}"
        pc = checks_by_portal.get(portal.id)

        if pc is None or pc.status == PortalCheckStatus.NICHT_GEPRUEFT:
            ergebnisse.append(
                nicht_pruefbar(
                    check_id,
                    GRUPPE,
                    ctx.modus,
                    f"{portal.label}: noch nicht geprüft.",
                    standort_id=ctx.location.id,
                )
            )
        elif pc.status == PortalCheckStatus.NICHT_VORHANDEN:
            ergebnisse.append(
                fehler(
                    check_id,
                    GRUPPE,
                    ctx.modus,
                    f"{portal.label}: kein Unternehmenseintrag gefunden.",
                    f"Unternehmenseintrag auf {portal.label} anlegen.",
                    standort_id=ctx.location.id,
                )
            )
        elif pc.status == PortalCheckStatus.GEFUNDEN_NAP_OK:
            ergebnisse.append(
                ok(
                    check_id,
                    GRUPPE,
                    ctx.modus,
                    f"{portal.label}: gefunden, NAP-Daten stimmen überein.",
                    standort_id=ctx.location.id,
                )
            )
        elif pc.status == PortalCheckStatus.GEFUNDEN_NAP_ABWEICHUNG:
            punkte = pc.aehnlichkeit_prozent if pc.aehnlichkeit_prozent is not None else 50.0
            fundstelle = pc.gefundener_name or (pc.erfasster_text[:60] if pc.erfasster_text else "")
            ergebnisse.append(
                warnung(
                    check_id,
                    GRUPPE,
                    ctx.modus,
                    f"{portal.label}: gefunden, NAP-Daten weichen ab ({fundstelle}).",
                    f"NAP-Daten auf {portal.label} korrigieren/angleichen.",
                    punkte=punkte,
                    standort_id=ctx.location.id,
                )
            )
        else:  # GEFUNDEN_NICHT_EINDEUTIG
            ergebnisse.append(
                warnung(
                    check_id,
                    GRUPPE,
                    ctx.modus,
                    f"{portal.label}: erfasst, automatischer Abgleich nicht eindeutig.",
                    "Erfassten Rohtext in der Verzeichnisse-Ansicht manuell mit den Standort-Daten vergleichen.",
                    punkte=50.0,
                    standort_id=ctx.location.id,
                )
            )
    return ergebnisse
