"""Tests für die Verzeichnis-Konsistenz-Routen der Webanwendung.

Deckt: Verzeichnisse-Seite rendert, Bookmarklet-Href wird gebaut, manuelle
Erfassung (Übernehmen/Kein Eintrag), Bookmarklet-Capture-Flow (Prüfen starten
-> Fetch vom Portal aus simuliert -> Submit), API-Portal-Prüfung (Foursquare/
Yelp, gemockt) inkl. Fehlerbehandlung ohne API-Key.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import src.webapp.main as webapp_main
from src.models import Location, PortalCheckStatus
from src.storage import get_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GBP_AUDIT_CLIENTS_DIR", str(tmp_path))
    webapp_main._active_capture = None
    return TestClient(webapp_main.app)


@pytest.fixture
def kunde_mit_standort(client):
    c = get_client("verzeichniskunde")
    c.ensure()
    c.save_locations(
        [Location(id="a", name="Beispiel GmbH", street="Musterstraße 1", zip="12345", city="Musterstadt", phone="+49301234567")]
    )
    return c


def test_portale_view_rendert(client, kunde_mit_standort):
    resp = client.get("/clients/verzeichniskunde/portale")
    assert resp.status_code == 200
    assert "Gelbe Seiten" in resp.text
    assert "gbp-audit erfassen" in resp.text
    assert "javascript:" in resp.text


def test_manuelle_erfassung_uebernehmen(client, kunde_mit_standort):
    resp = client.post(
        "/clients/verzeichniskunde/portale/a/gelbe_seiten/manuell",
        data={"erfasster_text": "Beispiel GmbH\nMusterstraße 1\n12345 Musterstadt\nTelefon: 030 1234567"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    checks = kunde_mit_standort.load_portal_checks()
    assert len(checks) == 1
    assert checks[0].status == PortalCheckStatus.GEFUNDEN_NAP_OK


def test_manuelle_erfassung_kein_eintrag(client, kunde_mit_standort):
    resp = client.post(
        "/clients/verzeichniskunde/portale/a/wer_liefert_was/manuell",
        data={"erfasster_text": "", "kein_eintrag": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    checks = kunde_mit_standort.load_portal_checks()
    assert checks[0].status == PortalCheckStatus.NICHT_VORHANDEN


def test_bookmarklet_capture_flow(client, kunde_mit_standort):
    start = client.post("/clients/verzeichniskunde/portale/a/das_oertliche/pruefen", follow_redirects=False)
    assert start.status_code == 303
    assert "dasoertliche.de" in start.headers["location"]

    submit = client.post(
        "/api/portal-capture/submit",
        json={
            "action": "uebernehmen",
            "selected_text": "Beispiel GmbH\nMusterstraße 1\n12345 Musterstadt\nTelefon: 030 1234567",
            "source_url": "https://www.dasoertliche.de/xyz",
        },
    )
    assert submit.status_code == 200
    checks = kunde_mit_standort.load_portal_checks()
    assert len(checks) == 1
    assert checks[0].status == PortalCheckStatus.GEFUNDEN_NAP_OK
    assert checks[0].quelladresse == "https://www.dasoertliche.de/xyz"


def test_bookmarklet_capture_ohne_aktive_pruefung_gibt_409(client, kunde_mit_standort):
    resp = client.post(
        "/api/portal-capture/submit",
        json={"action": "uebernehmen", "selected_text": "irgendwas", "source_url": "https://example.de"},
    )
    assert resp.status_code == 409


def test_bookmarklet_kein_eintrag(client, kunde_mit_standort):
    client.post("/clients/verzeichniskunde/portale/a/cylex/pruefen", follow_redirects=False)
    submit = client.post("/api/portal-capture/submit", json={"action": "kein_eintrag", "selected_text": "", "source_url": "https://cylex.de/x"})
    assert submit.status_code == 200
    checks = kunde_mit_standort.load_portal_checks()
    assert checks[0].status == PortalCheckStatus.NICHT_VORHANDEN


def test_api_portal_pruefen_foursquare_gemockt(client, kunde_mit_standort, monkeypatch):
    monkeypatch.setenv("FOURSQUARE_API_KEY", "dummy-key")

    class FakeFoursquareClient:
        def __init__(self, api_key, config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def search(self, name, near):
            return [
                {
                    "fsq_id": "abc",
                    "name": "Beispiel GmbH",
                    "location": {"formatted_address": "Musterstraße 1 12345 Musterstadt"},
                    "tel": "+49301234567",
                    "website": "",
                }
            ]

    monkeypatch.setattr(webapp_main, "FoursquareClient", FakeFoursquareClient)

    resp = client.post("/clients/verzeichniskunde/portale/a/foursquare/pruefen-api", follow_redirects=False)
    assert resp.status_code == 303
    checks = kunde_mit_standort.load_portal_checks()
    assert checks[0].status == PortalCheckStatus.GEFUNDEN_NAP_OK


def test_api_portal_pruefen_ohne_api_key_zeigt_fehler(client, kunde_mit_standort):
    resp = client.post("/clients/verzeichniskunde/portale/a/foursquare/pruefen-api", follow_redirects=False)
    assert resp.status_code == 303
    assert "flash_kind=error" in resp.headers["location"]
    assert kunde_mit_standort.load_portal_checks() == []


def test_unbekanntes_portal_bei_pruefen_start_gibt_fehler(client, kunde_mit_standort):
    resp = client.post("/clients/verzeichniskunde/portale/a/nicht-vorhanden/pruefen", follow_redirects=False)
    assert resp.status_code == 303
    assert "flash_kind=error" in resp.headers["location"]
