import httpx
import pytest

from src.api_foursquare import FoursquareApiQuotaError, FoursquareClient, foursquare_result_to_nap
from src.storage import load_global_config


@pytest.fixture
def config():
    return load_global_config()["foursquare_api"]


def test_search_ohne_api_key_gibt_verstaendlichen_fehler(config):
    with pytest.raises(Exception, match="FOURSQUARE_API_KEY"):
        FoursquareClient("", config)


def test_search_liefert_ergebnisse(config):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "test-key"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "fsq_id": "abc123",
                        "name": "Beispiel GmbH",
                        "location": {"formatted_address": "Musterstraße 1, 12345 Musterstadt"},
                        "tel": "+49 30 1234567",
                        "website": "https://beispiel.de",
                    }
                ]
            },
        )

    client = FoursquareClient("test-key", config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    results = client.search("Beispiel GmbH", "Musterstadt")

    assert len(results) == 1
    nap = foursquare_result_to_nap(results[0])
    assert nap["name"] == "Beispiel GmbH"
    assert nap["external_id"] == "abc123"
    assert "Musterstraße" in nap["address"]


def test_403_wird_als_quota_fehler_gemeldet(config):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "invalid key"})

    client = FoursquareClient("bad-key", config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(FoursquareApiQuotaError):
        client.search("Beispiel GmbH", "Musterstadt")
