from src.checks import group10_verzeichnisse
from src.checks.base import CheckContext
from src.models import CheckStatus, GbpProfile, Location, Modus, PortalCheck, PortalCheckStatus
from src.storage import load_global_config


def _location() -> Location:
    return Location(id="a", name="Beispiel GmbH", street="Musterstraße 1", zip="12345", city="Musterstadt", phone="+49301234567")


def _ctx(portal_checks=None, config=None) -> CheckContext:
    return CheckContext(
        location=_location(),
        profile=GbpProfile(place_id="ChIJ_x", display_name="Beispiel GmbH"),
        modus=Modus.A,
        config=config or load_global_config(),
        portal_checks=portal_checks or [],
    )


def _status(results, check_id) -> CheckStatus:
    return next(r for r in results if r.check_id == check_id).status


def test_noch_nie_geprueftes_portal_ist_nicht_pruefbar():
    results = group10_verzeichnisse.run(_ctx())
    assert all(r.status == CheckStatus.NICHT_PRUEFBAR for r in results)
    assert len(results) == 11  # 2 API + 9 Bookmarklet-Portale


def test_nicht_vorhanden_ist_fehler():
    checks = [PortalCheck(standort_id="a", portal_id="gelbe_seiten", status=PortalCheckStatus.NICHT_VORHANDEN)]
    results = group10_verzeichnisse.run(_ctx(portal_checks=checks))
    assert _status(results, "verzeichnis_gelbe_seiten") == CheckStatus.FEHLER


def test_gefunden_nap_ok_ist_ok():
    checks = [PortalCheck(standort_id="a", portal_id="foursquare", status=PortalCheckStatus.GEFUNDEN_NAP_OK, aehnlichkeit_prozent=95.0)]
    results = group10_verzeichnisse.run(_ctx(portal_checks=checks))
    assert _status(results, "verzeichnis_foursquare") == CheckStatus.OK


def test_gefunden_nap_abweichung_ist_warnung():
    checks = [
        PortalCheck(
            standort_id="a", portal_id="yelp", status=PortalCheckStatus.GEFUNDEN_NAP_ABWEICHUNG,
            aehnlichkeit_prozent=55.0, gefundener_name="Beispiel GmbH Filiale",
        )
    ]
    results = group10_verzeichnisse.run(_ctx(portal_checks=checks))
    result = next(r for r in results if r.check_id == "verzeichnis_yelp")
    assert result.status == CheckStatus.WARNUNG
    assert result.punkte == 55.0


def test_nicht_eindeutig_ist_warnung_mit_hinweis():
    checks = [PortalCheck(standort_id="a", portal_id="cylex", status=PortalCheckStatus.GEFUNDEN_NICHT_EINDEUTIG)]
    results = group10_verzeichnisse.run(_ctx(portal_checks=checks))
    result = next(r for r in results if r.check_id == "verzeichnis_cylex")
    assert result.status == CheckStatus.WARNUNG
    assert "manuell" in result.empfehlung.lower()


def test_checks_anderer_standorte_werden_ignoriert():
    checks = [PortalCheck(standort_id="anderer-standort", portal_id="gelbe_seiten", status=PortalCheckStatus.NICHT_VORHANDEN)]
    results = group10_verzeichnisse.run(_ctx(portal_checks=checks))
    assert _status(results, "verzeichnis_gelbe_seiten") == CheckStatus.NICHT_PRUEFBAR
