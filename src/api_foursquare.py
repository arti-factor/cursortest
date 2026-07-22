"""Client für die Foursquare Places API (v3).

Eine von drei Portalen, die automatisch per offizieller API geprüft werden
(zusammen mit Google und Yelp) - die übrigen Verzeichnisse haben keine
öffentliche Such-API und werden per Bookmarklet manuell erfasst (siehe
src/portals.py).
"""
from __future__ import annotations

from typing import Any, Optional

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


class FoursquareApiError(RuntimeError):
    pass


class FoursquareApiQuotaError(FoursquareApiError):
    """Foursquare meldet fehlende Berechtigung (ungültiger/gesperrter API-Key)."""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, httpx.TransportError)


class FoursquareClient:
    def __init__(self, api_key: str, config: dict[str, Any], client: Optional[httpx.Client] = None):
        if not api_key:
            raise FoursquareApiError(
                "Kein FOURSQUARE_API_KEY gesetzt. Siehe README.md, Abschnitt "
                "'Einrichtung', für die Erstellung eines Foursquare-API-Keys."
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

    def __enter__(self) -> "FoursquareClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def search(self, query: str, near: str, limit: int = 5) -> list[dict[str, Any]]:
        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=self.backoff_base, min=self.backoff_base, max=30),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )
        def _call() -> httpx.Response:
            resp = self._client.get(
                f"{self.base_url}/search",
                params={"query": query, "near": near, "limit": limit},
                headers={"Authorization": self.api_key, "Accept": "application/json"},
            )
            resp.raise_for_status()
            return resp

        try:
            resp = _call()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise FoursquareApiQuotaError(
                    "Foursquare API verweigert den Zugriff (401/403). API-Key im "
                    "Foursquare Developer Portal (foursquare.com/developers) prüfen."
                ) from exc
            raise FoursquareApiError(f"Foursquare API Fehler: {exc.response.status_code} {exc.response.text}") from exc
        except httpx.TransportError as exc:
            raise FoursquareApiError(f"Foursquare API nicht erreichbar: {exc}") from exc
        return resp.json().get("results", [])


def foursquare_result_to_nap(result: dict[str, Any]) -> dict[str, str]:
    """Mappt ein Foursquare-Suchergebnis auf einheitliche NAP-Felder."""
    location = result.get("location", {}) or {}
    return {
        "external_id": result.get("fsq_id", ""),
        "name": result.get("name", ""),
        "address": location.get("formatted_address", "") or ", ".join(
            p for p in (location.get("address", ""), location.get("postcode", ""), location.get("locality", "")) if p
        ),
        "phone": result.get("tel", ""),
        "website": result.get("website", ""),
    }
