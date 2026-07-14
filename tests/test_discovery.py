from pathlib import Path

from src.discovery import (
    dedupe_locations,
    extract_heuristic_locations,
    extract_locations_from_html,
    extract_json_ld_locations,
)

FIXTURES = Path(__file__).parent / "fixtures" / "html"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_json_ld_standort_wird_erkannt():
    html = _read("jsonld_standort.html")
    locations = extract_locations_from_html(html, "https://beispiel-gmbh.de/kontakt")

    assert len(locations) == 1
    loc = locations[0]
    assert loc.extraction_method == "json_ld"
    assert loc.name == "Beispiel GmbH Musterstadt"
    assert loc.street == "Musterstraße 12"
    assert loc.zip == "12345"
    assert loc.city == "Musterstadt"
    assert "1234567" in loc.phone.replace(" ", "")
    assert loc.website == "https://beispiel-gmbh.de/musterstadt"


def test_html_only_adresse_heuristik():
    html = _read("html_only_adresse.html")
    locations = extract_locations_from_html(html, "https://handwerk-schneider.de/kontakt")

    assert len(locations) == 1
    loc = locations[0]
    assert loc.extraction_method == "heuristik"
    assert loc.zip == "80331"
    assert loc.city == "München"
    assert "Gartenweg" in loc.street
    assert loc.phone  # irgendeine Telefonnummer wurde gefunden


def test_impressum_einzelstandort():
    html = _read("impressum_einzelstandort.html")
    locations = extract_locations_from_html(html, "https://praxis-weber.de/impressum")

    assert len(locations) == 1
    loc = locations[0]
    assert loc.zip == "50667"
    assert loc.city == "Köln"
    assert "Bahnhofstraße" in loc.street


def test_standortliste_50plus_alle_gefunden():
    html = _read("standortliste_50plus.html")
    locations = extract_json_ld_locations(html, "https://fitcorp-beispiel.de/standorte")

    assert len(locations) == 55
    zips = {loc.zip for loc in locations}
    assert len(zips) > 1  # mehrere Städte vertreten
    assert all(loc.name.startswith("FitCorp Studio") for loc in locations)
    assert all(loc.extraction_method == "json_ld" for loc in locations)
    # Standort-IDs müssen eindeutig sein, auch bei vielen Standorten
    assert len({loc.id for loc in locations}) == len(locations)


def test_dedupe_locations_merged_ueber_seiten():
    html1 = (
        '<html><body><script type="application/ld+json">'
        '{"@type":"LocalBusiness","name":"Cafe Sonne","address":{"@type":"PostalAddress",'
        '"postalCode":"10115","addressLocality":"Berlin"}}'
        "</script></body></html>"
    )
    html2 = (
        '<html><body><script type="application/ld+json">'
        '{"@type":"LocalBusiness","name":"Cafe Sonne","address":{"@type":"PostalAddress",'
        '"streetAddress":"Sonnenallee 1","postalCode":"10115","addressLocality":"Berlin"},'
        '"telephone":"+49 30 999999"}'
        "</script></body></html>"
    )
    locs = extract_json_ld_locations(html1, "https://cafe-sonne.de/kontakt")
    locs += extract_json_ld_locations(html2, "https://cafe-sonne.de/impressum")

    merged = dedupe_locations(locs)
    assert len(merged) == 1
    assert merged[0].street == "Sonnenallee 1"
    assert merged[0].phone


def test_html_kontakt_seite_mit_generischem_h1_nutzt_firmenname_aus_title():
    """Regressionstest: <h1>Kontakt</h1> darf nicht als Firmenname übernommen werden -
    sonst ergeben Kontakt-/Impressum-/Startseite derselben Firma fälschlich mehrere
    'Standorte', weil die Namen (Kontakt vs. Impressum vs. echter Firmenname) nicht
    zusammengeführt werden."""
    html = _read("kontakt_generischer_h1.html")
    locations = extract_locations_from_html(html, "https://musterfirma.de/kontakt")

    assert len(locations) == 1
    assert locations[0].name == "Musterfirma GmbH"


def test_extract_heuristic_locations_ohne_treffer_liefert_leere_liste():
    html = "<html><body><h1>Über uns</h1><p>Wir sind ein tolles Team.</p></body></html>"
    assert extract_heuristic_locations(html, "https://example.de/ueber-uns") == []
