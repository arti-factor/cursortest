import json
from pathlib import Path

import pytest

from src.matching import find_duplicates, match_location, normalize_phone
from src.models import Location, MatchStatus
from src.storage import load_global_config

FIXTURES = Path(__file__).parent / "fixtures" / "json"


def _read(name: str):
    with open(FIXTURES / name, "r", encoding="utf-8") as f:
        return json.load(f)


class FakePlacesClient:
    """Duck-typed Ersatz für PlacesClient - liefert vordefinierte Fixture-Antworten
    statt echte HTTP-Aufrufe zu machen."""

    def __init__(self, text_search_results=None, nearby_results=None):
        self._text_search_results = text_search_results or []
        self._nearby_results = nearby_results or []

    def text_search(self, query, max_results=5):
        return self._text_search_results

    def search_nearby(self, lat, lng, radius_meters, included_types=None):
        return self._nearby_results


@pytest.fixture
def matching_config():
    return load_global_config()["matching"]


def test_match_location_eindeutig(matching_config):
    location = Location(
        id="beispiel-gmbh-musterstadt-12345",
        name="Beispiel GmbH Musterstadt",
        street="Musterstraße 12",
        zip="12345",
        city="Musterstadt",
        phone="+49 30 1234567",
        website="https://beispiel-gmbh.de/musterstadt",
    )
    client = FakePlacesClient(text_search_results=_read("places_eindeutig.json"))

    result = match_location(location, client, matching_config)

    assert result.status == MatchStatus.EINDEUTIG
    assert result.chosen is not None
    assert result.chosen.place["id"] == "ChIJ_eindeutig123"
    assert result.chosen.confidence >= matching_config["auto_accept_threshold"]


def test_match_location_mehrdeutig(matching_config):
    location = Location(
        id="fitcorp-studio-berlin-10115",
        name="FitCorp Studio Berlin",
        street="",
        zip="10115",
        city="Berlin",
        phone="",
        website="",
    )
    client = FakePlacesClient(text_search_results=_read("places_mehrdeutig.json"))

    result = match_location(location, client, matching_config)

    assert result.status == MatchStatus.MEHRDEUTIG
    assert len(result.candidates) == 2
    assert result.chosen is None


def test_match_location_kein_treffer(matching_config):
    location = Location(
        id="praxis-weber-50667",
        name="Praxis Dr. Weber",
        street="Bahnhofstraße 3",
        zip="50667",
        city="Köln",
        phone="+49 221 5566778",
        website="",
    )
    client = FakePlacesClient(text_search_results=_read("places_kein_treffer.json"))

    result = match_location(location, client, matching_config)

    assert result.status == MatchStatus.KEIN_TREFFER
    assert result.chosen is None


def test_find_duplicates_erkennt_verwaisten_alteintrag(matching_config):
    nearby = _read("places_nearby_duplikat.json")
    chosen_place = nearby[0]
    client = FakePlacesClient(nearby_results=nearby)

    duplicates = find_duplicates(chosen_place, client, matching_config)

    assert "ChIJ_alteintrag_verwaist" in duplicates
    assert "ChIJ_unrelated_shop" not in duplicates
    assert chosen_place["id"] not in duplicates


def test_normalize_phone_gleiche_nummer_unterschiedliches_format():
    a = normalize_phone("+49 30 1234567")
    b = normalize_phone("030 1234567")
    assert a == b
    assert a.startswith("+49")
