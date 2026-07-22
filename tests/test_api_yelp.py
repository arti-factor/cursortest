import httpx
import pytest

from src.api_yelp import YelpApiQuotaError, YelpClient, yelp_result_to_nap
from src.storage import load_global_config


@pytest.fixture
def config():
    return load_global_config()["yelp_api"]


def test_search_ohne_api_key_gibt_verstaendlichen_fehler(config):
    with pytest.raises(Exception, match="YELP_API_KEY"):
        YelpClient("", config)


def test_search_liefert_ergebnisse(config):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "businesses": [
                    {
                        "id": "xyz789",
                        "name": "Beispiel GmbH",
                        "location": {"display_address": ["Musterstraße 1", "12345 Musterstadt"]},
                        "phone": "+49301234567",
                        "url": "https://yelp.de/biz/beispiel-gmbh",
                    }
                ]
            },
        )

    client = YelpClient("test-key", config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    results = client.search("Beispiel GmbH", "Musterstadt")

    assert len(results) == 1
    nap = yelp_result_to_nap(results[0])
    assert nap["name"] == "Beispiel GmbH"
    assert nap["external_id"] == "xyz789"
    assert "Musterstraße" in nap["address"]


def test_403_wird_als_quota_fehler_gemeldet(config):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "invalid key"})

    client = YelpClient("bad-key", config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(YelpApiQuotaError):
        client.search("Beispiel GmbH", "Musterstadt")
