"""Tests für die FastAPI-Webanwendung.

Die eigentliche Geschäftslogik (Discovery/Matching/Scoring/Report) ist bereits
in den anderen Testdateien abgedeckt - hier geht es um die Verdrahtung der
Webanwendung: Routen, Weiterleitungen, Job-Status-Seiten, Formulare.
Die entsprechenden src.services-Funktionen werden daher gemockt, damit keine
echten Netzwerkaufrufe nötig sind.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import src.webapp.main as webapp_main
from src.checks.base import ok
from src.matching import MatchCandidate, MatchStatus
from src.models import GbpProfile, Location, Modus
from src.report_html import write_html_report
from src.report_xlsx import write_report
from src.scoring import score_location
from src.services import AmbiguousMatch, DiffRow, MatchRunResult
from src.storage import load_global_config


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GBP_AUDIT_CLIENTS_DIR", str(tmp_path))
    return TestClient(webapp_main.app)


def _wait_done(job_id: str, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = webapp_main.jobs.get(job_id)
        if job and job.status != "running":
            return job
        time.sleep(0.02)
    raise TimeoutError(f"Job {job_id} nicht rechtzeitig fertig geworden")


def _job_id_from_redirect(location: str) -> str:
    # location sieht aus wie /jobs/<id>?next=...
    path = location.split("?")[0]
    return path.rstrip("/").split("/")[-1]


def test_index_ohne_mandanten(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Noch keine Mandanten" in resp.text


def test_client_new_form(client):
    resp = client.get("/clients/new")
    assert resp.status_code == 200
    assert "Discovery starten" in resp.text


def test_discover_und_review_speichert_standort(client, monkeypatch):
    fake_location = Location(
        id="beispiel-12345", name="Beispiel GmbH", street="Musterstraße 1",
        zip="12345", city="Musterstadt", phone="+49 30 1234567",
        website="https://beispiel.de", source_url="https://beispiel.de/kontakt",
        extraction_method="json_ld",
    )
    monkeypatch.setattr(webapp_main, "discover_for_client", lambda url, config: [fake_location])

    resp = client.post("/clients/new", data={"name": "Beispiel GmbH", "url": "https://beispiel.de"}, follow_redirects=False)
    assert resp.status_code == 303
    job_id = _job_id_from_redirect(resp.headers["location"])
    job = _wait_done(job_id)
    assert job.status == "done"
    assert job.result == [fake_location]

    review = client.get(f"/clients/beispiel-gmbh/locations/review?job_id={job_id}")
    assert review.status_code == 200
    assert "Beispiel GmbH" in review.text
    assert "Musterstraße 1" in review.text

    submit = client.post(
        "/clients/beispiel-gmbh/locations/review",
        data={
            "loc_0_name": "Beispiel GmbH",
            "loc_0_street": "Musterstraße 1",
            "loc_0_zip": "12345",
            "loc_0_city": "Musterstadt",
            "loc_0_phone": "+49 30 1234567",
            "loc_0_website": "https://beispiel.de",
            "loc_0_source_url": "https://beispiel.de/kontakt",
            "loc_0_extraction_method": "json_ld",
        },
        follow_redirects=False,
    )
    assert submit.status_code == 303
    assert "gespeichert" in submit.headers["location"]

    detail = client.get("/clients/beispiel-gmbh")
    assert detail.status_code == 200
    assert "Beispiel GmbH" in detail.text
    assert "Musterstadt" in detail.text


def test_match_ohne_mehrdeutigkeit_speichert_automatisch(client, monkeypatch):
    loc = Location(id="a", name="Beispiel GmbH", zip="12345", city="Musterstadt")
    from src.storage import get_client

    c = get_client("matchkunde")
    c.ensure()
    c.save_locations([loc])

    def fake_match_all(locations, config, on_progress=lambda m: None):
        on_progress("Matching für Beispiel GmbH...")
        locations[0].place_id = "ChIJ_test"
        locations[0].match_status = MatchStatus.EINDEUTIG
        return MatchRunResult(locations=locations, ambiguous=[])

    monkeypatch.setattr(webapp_main, "match_all_locations", fake_match_all)

    resp = client.post("/clients/matchkunde/match", follow_redirects=False)
    assert resp.status_code == 303
    job_id = _job_id_from_redirect(resp.headers["location"])
    job = _wait_done(job_id)
    assert job.status == "done"

    saved = c.load_locations()
    assert saved[0].place_id == "ChIJ_test"


def test_match_mit_mehrdeutigkeit_zeigt_review_und_uebernimmt_auswahl(client, monkeypatch):
    loc = Location(id="a", name="Beispiel GmbH", zip="12345", city="Musterstadt")
    from src.storage import get_client

    c = get_client("ambigkunde")
    c.ensure()
    c.save_locations([loc])

    candidate = MatchCandidate(
        place={"id": "ChIJ_kandidat", "displayName": {"text": "Beispiel GmbH"}, "formattedAddress": "Musterstraße 1"},
        confidence=70.0, name_score=90, address_score=50, phone_score=0, domain_score=0,
    )

    def fake_match_all(locations, config, on_progress=lambda m: None):
        return MatchRunResult(
            locations=locations,
            ambiguous=[AmbiguousMatch(location_id="a", location_name="Beispiel GmbH", location_address="12345 Musterstadt", candidates=[candidate])],
        )

    monkeypatch.setattr(webapp_main, "match_all_locations", fake_match_all)
    monkeypatch.setattr(webapp_main, "resolve_ambiguous_match", lambda loc, place_id, config: setattr(loc, "place_id", place_id))

    resp = client.post("/clients/ambigkunde/match", follow_redirects=False)
    job_id = _job_id_from_redirect(resp.headers["location"])
    job = _wait_done(job_id)

    review = client.get(f"/clients/ambigkunde/match/review?job_id={job_id}")
    assert review.status_code == 200
    assert "Beispiel GmbH" in review.text
    assert "ChIJ_kandidat" in review.text

    submit = client.post(
        "/clients/ambigkunde/match/review",
        data={"job_id": job_id, "choice_a": "ChIJ_kandidat"},
        follow_redirects=False,
    )
    assert submit.status_code == 303

    saved = c.load_locations()
    assert saved[0].place_id == "ChIJ_kandidat"


def test_run_und_report_view(client, monkeypatch):
    from src.storage import get_client

    c = get_client("runkunde")
    c.ensure()
    loc = Location(id="a", name="Beispiel GmbH", zip="12345", city="Musterstadt")
    c.save_locations([loc])

    config = load_global_config()
    profile = GbpProfile(place_id="ChIJ_x", display_name="Beispiel GmbH")
    checks = [ok("existenz_gbp_vorhanden", "existenz_auffindbarkeit", Modus.A, "ok", punkte=100.0)]
    result = score_location(loc, profile, Modus.A, checks, config["scoring"])

    from src.models import ClientRun

    def fake_perform_run(client_dirs, cfg, generate_html=False, on_progress=lambda m: None):
        on_progress("Modus: A (Public Audit)")
        run = ClientRun(client_slug=client_dirs.slug, run_date="2026-07-14", modus=Modus.A, results=[result])
        write_report(run, client_dirs.output_dir / "gbp-audit_2026-07-14.xlsx", cfg["report"])
        if generate_html:
            write_html_report(run, client_dirs.output_dir / "gbp-audit_2026-07-14.html")
        return run

    monkeypatch.setattr(webapp_main, "perform_run", fake_perform_run)

    resp = client.post("/clients/runkunde/run", follow_redirects=False)
    job_id = _job_id_from_redirect(resp.headers["location"])
    job = _wait_done(job_id)
    assert job.status == "done"
    assert job.result.run_date == "2026-07-14"

    report = client.get("/clients/runkunde/runs/2026-07-14")
    assert report.status_code == 200
    assert "Excel-Report herunterladen" in report.text
    assert "iframe" in report.text

    download = client.get("/clients/runkunde/runs/2026-07-14/download")
    assert download.status_code == 200

    dashboard = client.get("/clients/runkunde/runs/2026-07-14/dashboard")
    assert dashboard.status_code == 200
    assert "Beispiel GmbH" in dashboard.text


def test_diff_view(client, monkeypatch):
    from src.storage import get_client

    c = get_client("diffkunde")
    c.ensure()
    (c.runs_dir / "2026-06-14").mkdir(parents=True)
    (c.runs_dir / "2026-07-14").mkdir(parents=True)

    monkeypatch.setattr(
        webapp_main,
        "perform_diff",
        lambda client_dirs, cfg, r1, r2: [DiffRow(location_name="Beispiel GmbH", score_alt=70.0, score_neu=85.0, delta=15.0)],
    )

    resp = client.get("/clients/diffkunde/diff?run1=2026-06-14&run2=2026-07-14")
    assert resp.status_code == 200
    assert "Beispiel GmbH" in resp.text
    assert "+15.0" in resp.text


def test_unbekannter_mandant_redirect(client):
    resp = client.get("/clients/gibts-nicht", follow_redirects=False)
    assert resp.status_code == 303
    assert "existiert+nicht" in resp.headers["location"]


def test_auth_start_ohne_client_secret_gibt_verstaendlichen_fehler(client, monkeypatch):
    from src.storage import get_client

    c = get_client("authkunde")
    c.ensure()
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET_FILE", raising=False)

    resp = client.get("/clients/authkunde/auth/start", follow_redirects=False)
    assert resp.status_code == 303
    assert "flash_kind=error" in resp.headers["location"]
