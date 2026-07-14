import httpx
import pytest

from src.api_places import PlacesApiQuotaError, PlacesClient
from src.storage import load_global_config


@pytest.fixture
def places_config():
    return load_global_config()["places_api"]


def _client_with(handler, places_config) -> PlacesClient:
    return PlacesClient("dummy-key", places_config, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_text_search_trifft_die_korrekte_google_url(places_config):
    """Regressionstest: die echte Places API (New) erwartet POST /v1/places:searchText,
    nicht /v1:searchText - ein fehlendes '/places' führte hier zu einem echten 404."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"places": []})

    client = _client_with(handler, places_config)
    client.text_search("Testfirma, Musterstadt")

    assert captured["url"] == "https://places.googleapis.com/v1/places:searchText"


def test_search_nearby_trifft_die_korrekte_google_url(places_config):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"places": []})

    client = _client_with(handler, places_config)
    client.search_nearby(52.5, 13.4, 500)

    assert captured["url"] == "https://places.googleapis.com/v1/places:searchNearby"


def test_get_place_details_trifft_die_korrekte_google_url(places_config):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"id": "ChIJ_x"})

    client = _client_with(handler, places_config)
    client.get_place_details("ChIJ_x")

    assert captured["url"] == "https://places.googleapis.com/v1/places/ChIJ_x"


def test_403_wird_als_quota_fehler_gemeldet(places_config):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"status": "PERMISSION_DENIED"}})

    client = _client_with(handler, places_config)
    with pytest.raises(PlacesApiQuotaError):
        client.text_search("Testfirma")
