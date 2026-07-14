import datetime as dt

from src.checks import (
    group4_beschreibung,
    group5_fotos,
    group6_bewertungen,
    group7_qna,
    group8_leistungen,
    group9_performance,
)
from src.checks.base import CheckContext
from src.models import CheckStatus, GbpProfile, Location, Modus


def _location(**overrides) -> Location:
    base = dict(id="loc-a", name="Beispiel GmbH", zip="12345", city="Musterstadt")
    base.update(overrides)
    return Location(**base)


def _profile(**overrides) -> GbpProfile:
    base = dict(place_id="ChIJ_test", display_name="Beispiel GmbH", rating=4.5, user_rating_count=100)
    base.update(overrides)
    return GbpProfile(**base)


def _ctx(location=None, profile=None, modus=Modus.B, config=None, **kwargs) -> CheckContext:
    return CheckContext(
        location=location or _location(),
        profile=profile,
        modus=modus,
        config=config or {},
        **kwargs,
    )


def _status(results, check_id) -> CheckStatus:
    return next(r for r in results if r.check_id == check_id).status


# --- Gruppe 4: Beschreibung & Attribute ---


def test_gruppe4_modus_a_alles_nicht_pruefbar():
    ctx = _ctx(profile=_profile(), modus=Modus.A)
    results = group4_beschreibung.run(ctx)
    assert all(r.status == CheckStatus.NICHT_PRUEFBAR for r in results)


def test_gruppe4_beschreibung_fehlt():
    ctx = _ctx(profile=_profile(description=""))
    results = group4_beschreibung.run(ctx)
    assert _status(results, "beschreibung_laenge") == CheckStatus.FEHLER


def test_gruppe4_beschreibung_zu_kurz():
    ctx = _ctx(profile=_profile(description="Kurzer Text."))
    results = group4_beschreibung.run(ctx)
    assert _status(results, "beschreibung_laenge") == CheckStatus.WARNUNG


def test_gruppe4_beschreibung_ausreichend_lang():
    ctx = _ctx(profile=_profile(description="X" * 300))
    results = group4_beschreibung.run(ctx)
    assert _status(results, "beschreibung_laenge") == CheckStatus.OK


def test_gruppe4_duplikat_erkannt_bei_mehrstandort():
    text = "Wir sind Ihr Ansprechpartner vor Ort und bieten erstklassigen Service seit vielen Jahren." * 2
    loc = _location(id="a")
    profile = _profile(description=text)
    peer = _profile(description=text)
    ctx = _ctx(
        location=loc,
        profile=profile,
        all_locations=[loc, _location(id="b")],
        all_profiles={"a": profile, "b": peer},
    )
    results = group4_beschreibung.run(ctx)
    assert _status(results, "beschreibung_duplikat") == CheckStatus.WARNUNG


def test_gruppe4_erwartete_attribute_fehlen():
    config = {"beschreibung_attribute": {"erwartete_attribute": ["wheelchair_accessible", "wifi"]}}
    ctx = _ctx(profile=_profile(attributes={"wifi": True}), config=config)
    results = group4_beschreibung.run(ctx)
    assert _status(results, "beschreibung_attribute") == CheckStatus.WARNUNG


# --- Gruppe 5: Fotos ---


def test_gruppe5_modus_a_keine_fotos():
    ctx = _ctx(profile=_profile(photo_count=0), modus=Modus.A)
    results = group5_fotos.run(ctx)
    assert _status(results, "fotos_anzahl_indiz") == CheckStatus.FEHLER


def test_gruppe5_modus_a_ausreichend_fotos():
    ctx = _ctx(profile=_profile(photo_count=20), modus=Modus.A)
    results = group5_fotos.run(ctx)
    assert _status(results, "fotos_anzahl_indiz") == CheckStatus.OK


def test_gruppe5_modus_b_mindestanzahl_erreicht():
    fotos = [{"createTime": "2026-06-01T00:00:00Z", "locationAssociation": {"category": "EXTERIOR"}}] * 5
    fotos += [{"createTime": "2026-06-01T00:00:00Z", "locationAssociation": {"category": "INTERIOR"}}] * 5
    ctx = _ctx(profile=_profile(owner_photos=fotos))
    results = group5_fotos.run(ctx, heute=dt.date(2026, 7, 1))
    assert _status(results, "fotos_mindestanzahl") == CheckStatus.OK
    assert _status(results, "fotos_aussen_innen") == CheckStatus.OK
    assert _status(results, "fotos_aktualitaet") == CheckStatus.OK


def test_gruppe5_modus_b_veraltete_fotos():
    fotos = [{"createTime": "2020-01-01T00:00:00Z"}] * 10
    ctx = _ctx(profile=_profile(owner_photos=fotos))
    results = group5_fotos.run(ctx, heute=dt.date(2026, 7, 1))
    assert _status(results, "fotos_aktualitaet") == CheckStatus.WARNUNG


# --- Gruppe 6: Bewertungen ---


def test_gruppe6_modus_a_unter_branchenbenchmark():
    config = {"checks": {"bewertungen_branchen_benchmark": 4.5}}
    ctx = _ctx(profile=_profile(rating=3.8, user_rating_count=50), modus=Modus.A, config=config)
    results = group6_bewertungen.run(ctx)
    assert _status(results, "bewertungen_anzahl_durchschnitt") == CheckStatus.WARNUNG


def test_gruppe6_mehrstandort_ausreisser_erkannt():
    loc = _location(id="a")
    profile = _profile(rating=3.5)
    peer1 = _profile(rating=4.6)
    peer2 = _profile(rating=4.7)
    ctx = _ctx(
        location=loc,
        profile=profile,
        modus=Modus.A,
        all_locations=[loc, _location(id="b"), _location(id="c")],
        all_profiles={"a": profile, "b": peer1, "c": peer2},
    )
    results = group6_bewertungen.run(ctx)
    assert _status(results, "bewertungen_anzahl_durchschnitt") == CheckStatus.WARNUNG


def test_gruppe6_antwortquote_indiz_ohne_reply_feld_nicht_pruefbar():
    ctx = _ctx(profile=_profile(reviews_sample=[{"rating": 5, "text": "Super!"}]), modus=Modus.A)
    results = group6_bewertungen.run(ctx)
    assert _status(results, "bewertungen_antwortquote_indiz") == CheckStatus.NICHT_PRUEFBAR


def test_gruppe6_vollstaendige_antwortquote_modus_b():
    reviews = [
        {"createTime": "2026-06-01T00:00:00Z", "reviewReply": {"updateTime": "2026-06-02T00:00:00Z"}},
        {"createTime": "2026-06-01T00:00:00Z"},
    ]
    ctx = _ctx(profile=_profile(reviews_full=reviews))
    results = group6_bewertungen.run(ctx, heute=dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc))
    assert _status(results, "bewertungen_antwortquote_vollstaendig") == CheckStatus.WARNUNG  # 50% < 70%


def test_gruppe6_keyword_analyse():
    config = {"bewertungen": {"keywords": ["freundlich", "schnell"]}}
    reviews = [{"comment": "Sehr freundlicher Service, danke!"}]
    ctx = _ctx(profile=_profile(reviews_full=reviews), config=config)
    results = group6_bewertungen.run(ctx)
    assert _status(results, "bewertungen_keyword_analyse") == CheckStatus.OK


# --- Gruppe 7: Q&A ---


def test_gruppe7_modus_a_nicht_pruefbar():
    ctx = _ctx(profile=_profile(), modus=Modus.A)
    results = group7_qna.run(ctx)
    assert all(r.status == CheckStatus.NICHT_PRUEFBAR for r in results)


def test_gruppe7_unbeantwortete_fragen():
    fragen = [{"text": "Gibt es Parkplätze?", "topAnswers": []}, {"text": "Öffnungszeiten?", "topAnswers": [{"author": {"type": "MERCHANT"}}]}]
    ctx = _ctx(profile=_profile(questions=fragen))
    results = group7_qna.run(ctx)
    assert _status(results, "qna_unbeantwortete_fragen") == CheckStatus.WARNUNG


def test_gruppe7_anteil_inhaber_antworten():
    fragen = [
        {"text": "Q1", "topAnswers": [{"author": {"type": "MERCHANT"}}]},
        {"text": "Q2", "topAnswers": [{"author": {"type": "REGULAR_USER"}}]},
        {"text": "Q3", "topAnswers": [{"author": {"type": "REGULAR_USER"}}]},
    ]
    ctx = _ctx(profile=_profile(questions=fragen))
    results = group7_qna.run(ctx)
    assert _status(results, "qna_anteil_inhaber_antworten") == CheckStatus.WARNUNG


# --- Gruppe 8: Leistungen ---


def test_gruppe8_modus_a_nicht_pruefbar():
    ctx = _ctx(profile=_profile(), modus=Modus.A)
    results = group8_leistungen.run(ctx)
    assert _status(results, "leistungen_serviceitems") == CheckStatus.NICHT_PRUEFBAR


def test_gruppe8_zu_wenige_leistungen():
    config = {"checks": {"leistungen_mindestanzahl": 3}}
    ctx = _ctx(profile=_profile(service_items=[{"name": "Beratung"}]), config=config)
    results = group8_leistungen.run(ctx)
    assert _status(results, "leistungen_serviceitems") == CheckStatus.WARNUNG


def test_gruppe8_ausreichend_leistungen():
    config = {"checks": {"leistungen_mindestanzahl": 2}}
    ctx = _ctx(profile=_profile(service_items=[{"name": "A"}, {"name": "B"}]), config=config)
    results = group8_leistungen.run(ctx)
    assert _status(results, "leistungen_serviceitems") == CheckStatus.OK


# --- Gruppe 9: Performance ---


def test_gruppe9_modus_a_nicht_pruefbar():
    ctx = _ctx(profile=_profile(), modus=Modus.A)
    results = group9_performance.run(ctx)
    assert all(r.status == CheckStatus.NICHT_PRUEFBAR for r in results)


def test_gruppe9_kennzahlen_ohne_bewertung():
    metrics = {
        "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": 1000,
        "BUSINESS_IMPRESSIONS_DESKTOP_MAPS": 500,
        "BUSINESS_IMPRESSIONS_MOBILE_SEARCH": 2000,
        "BUSINESS_IMPRESSIONS_MOBILE_MAPS": 1500,
        "BUSINESS_DIRECTION_REQUESTS": 50,
        "CALL_CLICKS": 30,
        "WEBSITE_CLICKS": 80,
    }
    ctx = _ctx(profile=_profile(performance_metrics=metrics))
    results = group9_performance.run(ctx)
    kennzahlen = next(r for r in results if r.check_id == "performance_kennzahlen")
    assert kennzahlen.status == CheckStatus.OK
    assert kennzahlen.punkte is None  # Datenerhebung, keine Bewertung


def test_gruppe9_quartil_schwaechste_10_prozent():
    def metrics_for(direction_requests):
        return {
            "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": 1000,
            "BUSINESS_IMPRESSIONS_DESKTOP_MAPS": 0,
            "BUSINESS_IMPRESSIONS_MOBILE_SEARCH": 0,
            "BUSINESS_IMPRESSIONS_MOBILE_MAPS": 0,
            "BUSINESS_DIRECTION_REQUESTS": direction_requests,
        }

    loc = _location(id="a")
    profile = _profile(performance_metrics=metrics_for(1))  # sehr wenige Wegbeschreibungen
    peers = {f"peer{i}": _profile(performance_metrics=metrics_for(50 + i)) for i in range(9)}
    all_profiles = {"a": profile, **peers}
    ctx = _ctx(
        location=loc,
        profile=profile,
        all_locations=[loc] + [_location(id=k) for k in peers],
        all_profiles=all_profiles,
    )
    results = group9_performance.run(ctx)
    assert _status(results, "performance_quartil") == CheckStatus.WARNUNG


def test_gruppe9_delta_zum_vorlauf():
    alt_metrics = {"BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": 1000, "BUSINESS_IMPRESSIONS_DESKTOP_MAPS": 0, "BUSINESS_IMPRESSIONS_MOBILE_SEARCH": 0, "BUSINESS_IMPRESSIONS_MOBILE_MAPS": 0}
    neu_metrics = {"BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": 1500, "BUSINESS_IMPRESSIONS_DESKTOP_MAPS": 0, "BUSINESS_IMPRESSIONS_MOBILE_SEARCH": 0, "BUSINESS_IMPRESSIONS_MOBILE_MAPS": 0}
    previous_profile = _profile(performance_metrics=alt_metrics)
    ctx = _ctx(profile=_profile(performance_metrics=neu_metrics), previous_profile=previous_profile)
    results = group9_performance.run(ctx)
    delta = next(r for r in results if r.check_id == "performance_delta")
    assert delta.status == CheckStatus.OK
    assert "50%" in delta.befund
