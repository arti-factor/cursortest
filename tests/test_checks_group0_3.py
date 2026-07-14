import datetime as dt

from src.checks import group0_existenz, group1_basisdaten, group2_kategorien, group3_oeffnungszeiten
from src.checks.base import CheckContext
from src.models import CheckStatus, GbpProfile, Location, Modus


def _location(**overrides) -> Location:
    base = dict(
        id="beispiel-gmbh-12345",
        name="Beispiel GmbH Musterstadt",
        street="Musterstraße 12",
        zip="12345",
        city="Musterstadt",
        phone="+49 30 1234567",
        website="https://beispiel-gmbh.de/musterstadt",
        source_url="https://beispiel-gmbh.de/kontakt",
    )
    base.update(overrides)
    return Location(**base)


def _profile(**overrides) -> GbpProfile:
    base = dict(
        place_id="ChIJ_test",
        display_name="Beispiel GmbH Musterstadt",
        formatted_address="Musterstraße 12, 12345 Musterstadt, Deutschland",
        phone="+49 30 1234567",
        website_uri="https://beispiel-gmbh.de/musterstadt",
        primary_type="corporate_office",
        business_status="OPERATIONAL",
    )
    base.update(overrides)
    return GbpProfile(**base)


def _ctx(location=None, profile=None, modus=Modus.A, config=None, **kwargs) -> CheckContext:
    return CheckContext(
        location=location or _location(),
        profile=profile,
        modus=modus,
        config=config or {},
        **kwargs,
    )


def _status(results, check_id) -> CheckStatus:
    return next(r for r in results if r.check_id == check_id).status


# --- Gruppe 0: Existenz & Auffindbarkeit ---


def test_gruppe0_kein_profil_ist_fehler():
    ctx = _ctx(profile=None)
    results = group0_existenz.run(ctx)
    assert _status(results, "existenz_gbp_vorhanden") == CheckStatus.FEHLER
    assert len(results) == 1  # Folgechecks werden ohne Profil nicht ausgewertet


def test_gruppe0_profil_vorhanden_ohne_duplikate():
    ctx = _ctx(profile=_profile())
    results = group0_existenz.run(ctx)
    assert _status(results, "existenz_gbp_vorhanden") == CheckStatus.OK
    assert _status(results, "existenz_keine_duplikate") == CheckStatus.OK
    assert _status(results, "existenz_betriebsstatus") == CheckStatus.OK


def test_gruppe0_duplikat_warnung():
    loc = _location(duplicate_place_ids=["ChIJ_alt"])
    ctx = _ctx(location=loc, profile=_profile())
    results = group0_existenz.run(ctx)
    assert _status(results, "existenz_keine_duplikate") == CheckStatus.WARNUNG


def test_gruppe0_dauerhaft_geschlossen_ist_fehler():
    ctx = _ctx(profile=_profile(business_status="CLOSED_PERMANENTLY"))
    results = group0_existenz.run(ctx)
    assert _status(results, "existenz_betriebsstatus") == CheckStatus.FEHLER


# --- Gruppe 1: Basisdaten & NAP ---


def test_gruppe1_alle_felder_ok():
    ctx = _ctx(profile=_profile())
    results = group1_basisdaten.run(ctx)
    for cid in ("nap_name_vorhanden", "nap_adresse_vorhanden", "nap_telefon_vorhanden", "nap_website_vorhanden"):
        assert _status(results, cid) == CheckStatus.OK
    assert _status(results, "nap_abgleich") == CheckStatus.OK
    assert _status(results, "nap_website_link") == CheckStatus.OK


def test_gruppe1_fehlendes_telefon_ist_fehler():
    ctx = _ctx(profile=_profile(phone=""))
    results = group1_basisdaten.run(ctx)
    assert _status(results, "nap_telefon_vorhanden") == CheckStatus.FEHLER


def test_gruppe1_nap_abweichung_erkannt():
    ctx = _ctx(profile=_profile(phone="+49 30 9999999"))
    results = group1_basisdaten.run(ctx)
    assert _status(results, "nap_abgleich") == CheckStatus.WARNUNG


def test_gruppe1_einzelstandort_namensschema_nicht_pruefbar():
    ctx = _ctx(profile=_profile())
    results = group1_basisdaten.run(ctx)
    assert _status(results, "nap_einheitliches_namensschema") == CheckStatus.NICHT_PRUEFBAR


def test_gruppe1_mehrstandort_abweichendes_namensschema():
    loc = _location(id="a", name="FitCorp - Berlin")
    peer1 = _profile(display_name="FitCorp - Hamburg")
    peer2 = _profile(display_name="FitCorp - Köln")
    profile = _profile(display_name="FitCorp Berlin")  # anderes Muster als Peers
    ctx = _ctx(
        location=loc,
        profile=profile,
        all_locations=[loc, _location(id="b"), _location(id="c")],
        all_profiles={"a": profile, "b": peer1, "c": peer2},
    )
    results = group1_basisdaten.run(ctx)
    assert _status(results, "nap_einheitliches_namensschema") == CheckStatus.WARNUNG


def test_gruppe1_website_link_zeigt_auf_startseite_bei_mehrstandort():
    loc = _location(id="a", website="https://fitcorp-beispiel.de/berlin")
    profile = _profile(website_uri="https://fitcorp-beispiel.de")
    ctx = _ctx(
        location=loc,
        profile=profile,
        all_locations=[loc, _location(id="b")],
        all_profiles={"a": profile, "b": _profile()},
    )
    results = group1_basisdaten.run(ctx)
    assert _status(results, "nap_website_link") == CheckStatus.WARNUNG


# --- Gruppe 2: Kategorien ---


def test_gruppe2_keine_soll_kategorie_konfiguriert():
    ctx = _ctx(profile=_profile())
    results = group2_kategorien.run(ctx)
    assert _status(results, "kategorien_hauptkategorie") == CheckStatus.NICHT_PRUEFBAR


def test_gruppe2_hauptkategorie_entspricht_soll():
    config = {"kategorien": {"soll_hauptkategorie": "corporate_office"}}
    ctx = _ctx(profile=_profile(), config=config)
    results = group2_kategorien.run(ctx)
    assert _status(results, "kategorien_hauptkategorie") == CheckStatus.OK


def test_gruppe2_hauptkategorie_weicht_ab():
    config = {"kategorien": {"soll_hauptkategorie": "gym"}}
    ctx = _ctx(profile=_profile(primary_type="corporate_office"), config=config)
    results = group2_kategorien.run(ctx)
    assert _status(results, "kategorien_hauptkategorie") == CheckStatus.WARNUNG


def test_gruppe2_mehrstandort_abweichung_vom_haeufigsten_set():
    loc = _location(id="a")
    profile = _profile(primary_type="restaurant")
    peer1 = _profile(primary_type="gym")
    peer2 = _profile(primary_type="gym")
    ctx = _ctx(
        location=loc,
        profile=profile,
        all_locations=[loc, _location(id="b"), _location(id="c")],
        all_profiles={"a": profile, "b": peer1, "c": peer2},
    )
    results = group2_kategorien.run(ctx)
    assert _status(results, "kategorien_mehrstandort_konsistenz") == CheckStatus.WARNUNG


# --- Gruppe 3: Öffnungszeiten ---


def test_gruppe3_keine_zeiten_ist_fehler():
    ctx = _ctx(profile=_profile(regular_opening_hours={}))
    results = group3_oeffnungszeiten.run(ctx)
    assert _status(results, "oeffnungszeiten_regulaer") == CheckStatus.FEHLER


def test_gruppe3_vollstaendige_zeiten_ok():
    periods = [{"open": {"day": d}} for d in range(7)]
    ctx = _ctx(profile=_profile(regular_opening_hours={"periods": periods}))
    results = group3_oeffnungszeiten.run(ctx)
    assert _status(results, "oeffnungszeiten_regulaer") == CheckStatus.OK


def test_gruppe3_feiertage_modus_a_nicht_pruefbar():
    ctx = _ctx(profile=_profile(), modus=Modus.A)
    results = group3_oeffnungszeiten.run(ctx)
    assert _status(results, "oeffnungszeiten_feiertage") == CheckStatus.NICHT_PRUEFBAR


def test_gruppe3_feiertage_modus_b_fehlende_sonderzeiten():
    loc = _location(zip="80331")  # München -> Bayern
    profile = _profile(special_hours={"specialHourPeriods": []})
    ctx = _ctx(location=loc, profile=profile, modus=Modus.B)
    results = group3_oeffnungszeiten.run(ctx, heute=dt.date(2026, 12, 20))
    assert _status(results, "oeffnungszeiten_feiertage") == CheckStatus.WARNUNG


def test_gruppe3_feiertage_modus_b_gepflegt():
    import holidays as holidays_lib

    heute = dt.date(2026, 12, 20)
    horizont_ende = heute + dt.timedelta(days=60)
    anstehende = sorted(
        d for d in holidays_lib.Germany(subdiv="BY", years=[heute.year, horizont_ende.year]) if heute <= d <= horizont_ende
    )

    loc = _location(zip="80331")  # München -> Bayern
    special_hours = {
        "specialHourPeriods": [
            {"startDate": {"year": d.year, "month": d.month, "day": d.day}} for d in anstehende
        ]
    }
    profile = _profile(special_hours=special_hours)
    ctx = _ctx(location=loc, profile=profile, modus=Modus.B)
    results = group3_oeffnungszeiten.run(ctx, heute=heute)
    assert _status(results, "oeffnungszeiten_feiertage") == CheckStatus.OK
