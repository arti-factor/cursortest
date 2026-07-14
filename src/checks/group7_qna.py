"""Gruppe 7 - Fragen & Antworten (Modus B, Gewicht 5%)."""
from __future__ import annotations

from src.checks.base import CheckContext, nicht_pruefbar, ok, warnung
from src.models import Modus

GRUPPE = "qna"


def _unbeantwortete_fragen(ctx: CheckContext):
    loc_id = ctx.location.id
    if ctx.modus != Modus.B:
        return nicht_pruefbar(
            "qna_unbeantwortete_fragen",
            GRUPPE,
            ctx.modus,
            "Fragen & Antworten sind nur mit Verwaltungszugriff (Modus B) prüfbar.",
            standort_id=loc_id,
        )

    fragen = ctx.profile.questions
    if fragen is None:
        return nicht_pruefbar(
            "qna_unbeantwortete_fragen",
            GRUPPE,
            ctx.modus,
            "Keine Q&A-Daten über die My Business API verfügbar.",
            standort_id=loc_id,
        )
    if not fragen:
        return ok("qna_unbeantwortete_fragen", GRUPPE, ctx.modus, "Keine Fragen vorhanden.", standort_id=loc_id)

    unbeantwortet = [f for f in fragen if not f.get("topAnswers")]
    if unbeantwortet:
        beispiele = "; ".join(f.get("text", "")[:80] for f in unbeantwortet[:3])
        return warnung(
            "qna_unbeantwortete_fragen",
            GRUPPE,
            ctx.modus,
            f"{len(unbeantwortet)} von {len(fragen)} Fragen sind unbeantwortet. Beispiele: {beispiele}",
            "Offene Fragen zeitnah beantworten.",
            punkte=max(0.0, 100.0 * (1 - len(unbeantwortet) / len(fragen))),
            standort_id=loc_id,
        )
    return ok(
        "qna_unbeantwortete_fragen",
        GRUPPE,
        ctx.modus,
        f"Alle {len(fragen)} Fragen sind beantwortet.",
        standort_id=loc_id,
    )


def _anteil_inhaber_antworten(ctx: CheckContext):
    loc_id = ctx.location.id
    if ctx.modus != Modus.B:
        return nicht_pruefbar(
            "qna_anteil_inhaber_antworten",
            GRUPPE,
            ctx.modus,
            "Fragen & Antworten sind nur mit Verwaltungszugriff (Modus B) prüfbar.",
            standort_id=loc_id,
        )

    fragen = ctx.profile.questions
    if not fragen:
        return nicht_pruefbar(
            "qna_anteil_inhaber_antworten",
            GRUPPE,
            ctx.modus,
            "Keine Q&A-Daten mit Antworten zum Auswerten vorhanden.",
            standort_id=loc_id,
        )

    beantwortete = [f for f in fragen if f.get("topAnswers")]
    if not beantwortete:
        return nicht_pruefbar(
            "qna_anteil_inhaber_antworten",
            GRUPPE,
            ctx.modus,
            "Keine beantworteten Fragen zum Auswerten vorhanden.",
            standort_id=loc_id,
        )

    inhaber_anteil = sum(
        1 for f in beantwortete if any(a.get("author", {}).get("type") == "MERCHANT" for a in f.get("topAnswers", []))
    ) / len(beantwortete)

    if inhaber_anteil < 0.5:
        return warnung(
            "qna_anteil_inhaber_antworten",
            GRUPPE,
            ctx.modus,
            f"Nur {inhaber_anteil * 100:.0f}% der beantworteten Fragen wurden vom Inhaber selbst beantwortet.",
            "Fragen aktiv als Inhaber beantworten, statt Community-Antworten stehen zu lassen.",
            punkte=inhaber_anteil * 100,
            standort_id=loc_id,
        )
    return ok(
        "qna_anteil_inhaber_antworten",
        GRUPPE,
        ctx.modus,
        f"{inhaber_anteil * 100:.0f}% der beantworteten Fragen wurden vom Inhaber selbst beantwortet.",
        standort_id=loc_id,
    )


def run(ctx: CheckContext) -> list:
    if ctx.profile is None:
        loc_id = ctx.location.id
        return [
            nicht_pruefbar(cid, GRUPPE, ctx.modus, "Kein GBP-Profil vorhanden - siehe Gruppe 'Existenz'.", standort_id=loc_id)
            for cid in ("qna_unbeantwortete_fragen", "qna_anteil_inhaber_antworten")
        ]
    return [_unbeantwortete_fragen(ctx), _anteil_inhaber_antworten(ctx)]
