import pytest

from src.models import PortalCheck, PortalCheckStatus, PortalCheckType
from src.portals import all_portals, api_portals, bookmarklet_portals, build_search_url, get_portal
from src.storage import ClientDirs, load_global_config


@pytest.fixture
def config():
    return load_global_config()


def test_api_portals_enthaelt_foursquare_und_yelp_nicht_google(config):
    portale = api_portals()
    ids = {p.id for p in portale}
    assert ids == {"foursquare", "yelp"}
    assert all(p.check_type == PortalCheckType.API for p in portale)


def test_bookmarklet_portals_enthaelt_konfigurierte_portale(config):
    portale = bookmarklet_portals(config)
    ids = {p.id for p in portale}
    assert "gelbe_seiten" in ids
    assert "branchenbuch_deutschland" in ids
    assert "cylex" in ids
    assert "meinestadt" in ids
    assert all(p.check_type == PortalCheckType.BOOKMARKLET for p in portale)


def test_all_portals_ohne_google(config):
    ids = {p.id for p in all_portals(config)}
    assert "google" not in ids
    assert len(ids) == 11  # 2 API + 9 Bookmarklet


def test_get_portal_unbekannt_wirft_fehler(config):
    with pytest.raises(ValueError):
        get_portal("nicht-vorhanden", config)


def test_build_search_url_ersetzt_platzhalter(config):
    url = build_search_url("gelbe_seiten", "Beispiel GmbH & Co. KG", "Musterstadt", config)
    assert url.startswith("https://www.gelbeseiten.de/Suche/")
    assert "Musterstadt" in url


def test_build_search_url_unbekanntes_portal_wirft_fehler(config):
    with pytest.raises(ValueError):
        build_search_url("nicht-vorhanden", "Beispiel GmbH", "Musterstadt", config)


def test_portal_check_persistenz_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("GBP_AUDIT_CLIENTS_DIR", str(tmp_path))
    client = ClientDirs("testkunde")
    client.ensure()

    check = PortalCheck(
        standort_id="a",
        portal_id="gelbe_seiten",
        status=PortalCheckStatus.GEFUNDEN_NAP_OK,
        erfasster_text="Beispiel GmbH\nMusterstraße 1\n12345 Musterstadt",
        quelladresse="https://www.gelbeseiten.de/Suche/Beispiel/Musterstadt",
        zeitstempel="2026-07-14T10:00:00+00:00",
    )
    client.upsert_portal_check(check)

    geladen = client.load_portal_checks()
    assert len(geladen) == 1
    assert geladen[0].status == PortalCheckStatus.GEFUNDEN_NAP_OK
    assert geladen[0].erfasster_text.startswith("Beispiel GmbH")


def test_upsert_portal_check_ersetzt_bestehenden_eintrag(tmp_path, monkeypatch):
    monkeypatch.setenv("GBP_AUDIT_CLIENTS_DIR", str(tmp_path))
    client = ClientDirs("testkunde2")
    client.ensure()

    client.upsert_portal_check(PortalCheck(standort_id="a", portal_id="gelbe_seiten", status=PortalCheckStatus.NICHT_VORHANDEN))
    client.upsert_portal_check(PortalCheck(standort_id="a", portal_id="gelbe_seiten", status=PortalCheckStatus.GEFUNDEN_NAP_OK))

    geladen = client.load_portal_checks()
    assert len(geladen) == 1
    assert geladen[0].status == PortalCheckStatus.GEFUNDEN_NAP_OK
