"""Gruppe 6 - Bewertungen (Modus A eingeschränkt, voll in Modus B, Gewicht 15%)."""
from __future__ import annotations

import datetime as dt
import statistics
from collections import Counter

from src.checks.base import CheckContext, fehler, nicht_pruefbar, ok, warnung
from src.models import Modus

GRUPPE = "bewertungen"


def _anzahl_und_durchschnitt(ctx: CheckContext):
    loc_id = ctx.location.id
    rating = ctx.profile.rating
    count = ctx.profile.user_rating_count

    if rating is None or count is None:
        return nicht_pruefbar(
            "bewertungen_anzahl_durchschnitt",
            GRUPPE,
            ctx.modus,
            "Keine Bewertungsdaten (Anzahl/Durchschnitt) verfügbar.",
            standort_id=loc_id,
        )

    if ctx.is_multi_location:
        peer_ratings = [p.rating for p in ctx.peer_profiles if p.rating is not None]
        alle_ratings = peer_ratings + [rating]
        kunden_durchschnitt = statistics.mean(alle_ratings)
        abweichung = kunden_durchschnitt - rating
        if abweichung > 0.4:
            return warnung(
                "bewertungen_anzahl_durchschnitt",
                GRUPPE,
                ctx.modus,
                f"{count} Bewertungen, Ø {rating:.1f} - liegt {abweichung:.1f} Punkte unter dem "
                f"kundenweiten Durchschnitt ({kunden_durchschnitt:.1f}).",
                "Ursachen für unterdurchschnittliche Bewertungen analysieren (Service, Reaktion auf Kritik).",
                punkte=max(0.0, 100.0 - abweichung * 50),
                standort_id=loc_id,
            )
        return ok(
            "bewertungen_anzahl_durchschnitt",
            GRUPPE,
            ctx.modus,
            f"{count} Bewertungen, Ø {rating:.1f} - im Bereich des kundenweiten Durchschnitts ({kunden_durchschnitt:.1f}).",
            standort_id=loc_id,
        )

    benchmark = ctx.config.get("checks", {}).get("bewertungen_branchen_benchmark", 4.3)
    if rating < benchmark - 0.3:
        return warnung(
            "bewertungen_anzahl_durchschnitt",
            GRUPPE,
            ctx.modus,
            f"{count} Bewertungen, Ø {rating:.1f} - liegt unter dem Branchen-Benchmark ({benchmark:.1f}).",
            "Bewertungsmanagement verbessern (aktiv um Bewertungen bitten, auf Kritik reagieren).",
            punkte=max(0.0, 100.0 - (benchmark - rating) * 50),
            standort_id=loc_id,
        )
    return ok(
        "bewertungen_anzahl_durchschnitt",
        GRUPPE,
        ctx.modus,
        f"{count} Bewertungen, Ø {rating:.1f} - im oder über dem Branchen-Benchmark ({benchmark:.1f}).",
        standort_id=loc_id,
    )


def _antwortquote_indiz_modus_a(ctx: CheckContext):
    loc_id = ctx.location.id
    sample = ctx.profile.reviews_sample or []

    if ctx.modus == Modus.B:
        return nicht_pruefbar(
            "bewertungen_antwortquote_indiz",
            GRUPPE,
            ctx.modus,
            "Wird im Modus B durch die vollständige Antwortquote ersetzt.",
            standort_id=loc_id,
        )
    if not sample:
        return nicht_pruefbar(
            "bewertungen_antwortquote_indiz",
            GRUPPE,
            ctx.modus,
            "Kein Bewertungs-Ausschnitt über die Places API verfügbar.",
            standort_id=loc_id,
        )

    # Die Places API (New) liefert i.d.R. keine Inhaber-Antworten je Review; ist das
    # Feld nicht vorhanden, kann dieser Indiz-Check nicht ausgewertet werden.
    reviews_mit_reply_feld = [r for r in sample if "reviewReply" in r or "owner_reply" in r]
    if not reviews_mit_reply_feld:
        return nicht_pruefbar(
            "bewertungen_antwortquote_indiz",
            GRUPPE,
            ctx.modus,
            "Antwortstatus einzelner Bewertungen ist über die Places API nicht auswertbar.",
            standort_id=loc_id,
        )

    beantwortet = sum(1 for r in reviews_mit_reply_feld if r.get("reviewReply") or r.get("owner_reply"))
    quote = beantwortet / len(reviews_mit_reply_feld)
    if quote < 0.5:
        return warnung(
            "bewertungen_antwortquote_indiz",
            GRUPPE,
            ctx.modus,
            f"Im sichtbaren Ausschnitt sind nur {beantwortet}/{len(reviews_mit_reply_feld)} Bewertungen beantwortet (Indiz).",
            "Auf mehr Bewertungen antworten.",
            punkte=quote * 100,
            standort_id=loc_id,
        )
    return ok(
        "bewertungen_antwortquote_indiz",
        GRUPPE,
        ctx.modus,
        f"Im sichtbaren Ausschnitt sind {beantwortet}/{len(reviews_mit_reply_feld)} Bewertungen beantwortet (Indiz).",
        standort_id=loc_id,
    )


def _modus_b_guard(check_id: str, ctx: CheckContext):
    if ctx.modus != Modus.B:
        return nicht_pruefbar(
            check_id,
            GRUPPE,
            ctx.modus,
            "Nur mit Verwaltungszugriff (Modus B) vollständig prüfbar.",
            standort_id=ctx.location.id,
        )
    return None


def _parse_time(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _vollstaendige_antwortquote(ctx: CheckContext, heute: dt.datetime | None = None):
    guard = _modus_b_guard("bewertungen_antwortquote_vollstaendig", ctx)
    if guard:
        return guard

    loc_id = ctx.location.id
    reviews = ctx.profile.reviews_full or []
    if not reviews:
        return nicht_pruefbar(
            "bewertungen_antwortquote_vollstaendig",
            GRUPPE,
            ctx.modus,
            "Keine Bewertungen über die My Business API verfügbar.",
            standort_id=loc_id,
        )

    heute = heute or dt.datetime.now(dt.timezone.utc)
    letzte_90_tage = heute - dt.timedelta(days=90)

    def beantwortet(r: dict) -> bool:
        return bool(r.get("reviewReply"))

    gesamt_quote = sum(1 for r in reviews if beantwortet(r)) / len(reviews)

    aktuelle = [r for r in reviews if (_parse_time(r.get("createTime")) or heute) >= letzte_90_tage]
    quote_90 = (sum(1 for r in aktuelle if beantwortet(r)) / len(aktuelle)) if aktuelle else None

    text = f"Antwortquote gesamt: {gesamt_quote * 100:.0f}%"
    if quote_90 is not None:
        text += f", letzte 90 Tage: {quote_90 * 100:.0f}%"

    if gesamt_quote < 0.7:
        return warnung(
            "bewertungen_antwortquote_vollstaendig",
            GRUPPE,
            ctx.modus,
            text,
            "Antwortquote erhöhen, insbesondere bei negativen Bewertungen zeitnah reagieren.",
            punkte=gesamt_quote * 100,
            standort_id=loc_id,
        )
    return ok("bewertungen_antwortquote_vollstaendig", GRUPPE, ctx.modus, text, standort_id=loc_id)


def _median_reaktionszeit(ctx: CheckContext):
    guard = _modus_b_guard("bewertungen_reaktionszeit", ctx)
    if guard:
        return guard

    loc_id = ctx.location.id
    reviews = ctx.profile.reviews_full or []
    zeiten = []
    for r in reviews:
        reply = r.get("reviewReply")
        created = _parse_time(r.get("createTime"))
        replied = _parse_time(reply.get("updateTime")) if reply else None
        if created and replied and replied >= created:
            zeiten.append((replied - created).total_seconds() / 3600)

    if not zeiten:
        return nicht_pruefbar(
            "bewertungen_reaktionszeit",
            GRUPPE,
            ctx.modus,
            "Keine beantworteten Bewertungen mit auswertbaren Zeitstempeln vorhanden.",
            standort_id=loc_id,
        )

    median_stunden = statistics.median(zeiten)
    if median_stunden > 72:
        return warnung(
            "bewertungen_reaktionszeit",
            GRUPPE,
            ctx.modus,
            f"Median-Reaktionszeit auf Bewertungen: {median_stunden:.0f} Stunden.",
            "Schneller auf Bewertungen reagieren (Ziel: innerhalb 72 Stunden).",
            punkte=max(0.0, 100.0 - (median_stunden - 72) / 2),
            standort_id=loc_id,
        )
    return ok(
        "bewertungen_reaktionszeit",
        GRUPPE,
        ctx.modus,
        f"Median-Reaktionszeit auf Bewertungen: {median_stunden:.0f} Stunden.",
        standort_id=loc_id,
    )


def _keyword_analyse(ctx: CheckContext):
    guard = _modus_b_guard("bewertungen_keyword_analyse", ctx)
    if guard:
        return guard

    loc_id = ctx.location.id
    keywords = (ctx.config.get("bewertungen", {}) or {}).get("keywords", [])
    if not keywords:
        return nicht_pruefbar(
            "bewertungen_keyword_analyse",
            GRUPPE,
            ctx.modus,
            "Keine Begriffsliste für die Bewertungsanalyse in der Kundenkonfiguration hinterlegt.",
            standort_id=loc_id,
        )

    reviews = ctx.profile.reviews_full or []
    texte = " ".join((r.get("comment") or "") for r in reviews).lower()
    treffer = Counter(kw for kw in keywords if kw.lower() in texte)

    if not treffer:
        return warnung(
            "bewertungen_keyword_analyse",
            GRUPPE,
            ctx.modus,
            f"Keiner der {len(keywords)} konfigurierten Begriffe kommt in den Bewertungen vor.",
            "Prüfen, ob die erwarteten Stärken/Leistungen tatsächlich wahrgenommen werden.",
            punkte=50.0,
            standort_id=loc_id,
        )
    top = ", ".join(f"'{k}' ({n}x)" for k, n in treffer.most_common(5))
    return ok(
        "bewertungen_keyword_analyse",
        GRUPPE,
        ctx.modus,
        f"Häufigste Treffer aus der Begriffsliste in Bewertungen: {top}.",
        standort_id=loc_id,
    )


def run(ctx: CheckContext, heute: dt.datetime | None = None) -> list:
    if ctx.profile is None:
        loc_id = ctx.location.id
        return [
            nicht_pruefbar(cid, GRUPPE, ctx.modus, "Kein GBP-Profil vorhanden - siehe Gruppe 'Existenz'.", standort_id=loc_id)
            for cid in (
                "bewertungen_anzahl_durchschnitt",
                "bewertungen_antwortquote_indiz",
                "bewertungen_antwortquote_vollstaendig",
                "bewertungen_reaktionszeit",
                "bewertungen_keyword_analyse",
            )
        ]
    return [
        _anzahl_und_durchschnitt(ctx),
        _antwortquote_indiz_modus_a(ctx),
        _vollstaendige_antwortquote(ctx, heute=heute),
        _median_reaktionszeit(ctx),
        _keyword_analyse(ctx),
    ]
