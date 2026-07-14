import httpx
import pytest
from google.oauth2.credentials import Credentials

from src.api_gbp import GbpApiClient, GbpApiQuotaError, GbpAuthRequiredError
from src.storage import load_global_config


@pytest.fixture
def gbp_config():
    return load_global_config()["gbp_api"]


def _fake_creds() -> Credentials:
    return Credentials(token="fake-access-token")


def test_quota_zero_raises_verstaendliche_fehlermeldung(gbp_config):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"status": "PERMISSION_DENIED", "message": "quota"}})

    client = GbpApiClient(_fake_creds(), gbp_config, client=httpx.Client(transport=httpx.MockTransport(handler)))

    with pytest.raises(GbpApiQuotaError, match="Antragsformular"):
        client.list_accounts()


def test_401_raised_as_auth_required(gbp_config):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"status": "UNAUTHENTICATED"}})

    client = GbpApiClient(_fake_creds(), gbp_config, client=httpx.Client(transport=httpx.MockTransport(handler)))

    with pytest.raises(GbpAuthRequiredError):
        client.list_accounts()


def test_list_locations_paginiert_korrekt(gbp_config):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if "pageToken" not in request.url.params:
            return httpx.Response(200, json={"locations": [{"name": "locations/1"}], "nextPageToken": "p2"})
        return httpx.Response(200, json={"locations": [{"name": "locations/2"}]})

    client = GbpApiClient(_fake_creds(), gbp_config, client=httpx.Client(transport=httpx.MockTransport(handler)))

    locations = client.list_locations("accounts/123", read_mask="title,storefrontAddress")

    assert [loc["name"] for loc in locations] == ["locations/1", "locations/2"]
    assert calls["n"] == 2
