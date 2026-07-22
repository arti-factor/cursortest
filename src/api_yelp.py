"""Client für die Yelp Fusion API.

Eine von drei Portalen, die automatisch per offizieller API geprüft werden
(zusammen mit Google und Foursquare). Achtung: Yelps Datenabdeckung für
Deutschland ist deutlich dünner als in den USA - ein "kein Treffer" kann
schlicht bedeuten, dass Yelp den Betrieb (noch) nicht kennt.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


class YelpApiError(RuntimeError):
    pass


class YelpApiQuotaError(YelpApiError):
    """Yelp meldet fehlende Berechtigung (ungültiger/gesperrter API-Key)."""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, httpx.TransportError)


class YelpClient:
    def __init__(self, api_key: str, config: dict[str, Any], client: Optional[httpx.Client] = None):
        if not api_key:
            raise YelpApiError(
                "Kein YELP_API_KEY gesetzt. Siehe README.md, Abschnitt 'Einrichtung', "
                "für die Erstellung eines Yelp-Fusion-API-Keys."
            )
        self.api_key = api_key
        self.base_url = config["base_url"].rstrip("/")
        self.max_retries = config.get("max_retries", 5)
        self.backoff_base = config.get("backoff_base_seconds", 1.0)
        self._client = client or httpx.Client(timeout=15.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "YelpClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def search(self, term: str, location: str, limit: int = 5) -> list[dict[str, Any]]:
        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=self.backoff_base, min=self.backoff_base, max=30),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )
        def _call() -> httpx.Response:
            resp = self._client.get(
                f"{self.base_url}/businesses/search",
                params={"term": term, "location": location, "limit": limit},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()
            return resp

        try:
            resp = _call()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise YelpApiQuotaError(
                    "Yelp Fusion API verweigert den Zugriff (401/403). API-Key im "
                    "Yelp-Developer-Portal (yelp.com/developers) prüfen."
                ) from exc
            raise YelpApiError(f"Yelp API Fehler: {exc.response.status_code} {exc.response.text}") from exc
        except httpx.TransportError as exc:
            raise YelpApiError(f"Yelp API nicht erreichbar: {exc}") from exc
        return resp.json().get("businesses", [])


def yelp_result_to_nap(result: dict[str, Any]) -> dict[str, str]:
    """Mappt ein Yelp-Suchergebnis auf einheitliche NAP-Felder."""
    location = result.get("location", {}) or {}
    address = ", ".join(location.get("display_address", []) or []) or ", ".join(
        p for p in (location.get("address1", ""), location.get("zip_code", ""), location.get("city", "")) if p
    )
    return {
        "external_id": result.get("id", ""),
        "name": result.get("name", ""),
        "address": address,
        "phone": result.get("phone", ""),
        "website": result.get("url", ""),
    }
