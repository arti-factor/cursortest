"""Client für die Google Places API (New).

Deckt Text Search (Matching), Place Details (Datenabruf Modus A) und Nearby
Search (Duplikat-Erkennung) ab. Retries mit exponentiellem Backoff über
`tenacity`, damit transiente Fehler/Rate-Limits nicht sofort zum Abbruch führen.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


class PlacesApiError(RuntimeError):
    """Fehler bei einer Places-API-Anfrage, die auch nach Retries fehlschlägt."""


class PlacesApiQuotaError(PlacesApiError):
    """Places API meldet fehlende Berechtigung/Quota (z.B. Abrechnung nicht aktiviert)."""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, httpx.TransportError)


class PlacesClient:
    def __init__(
        self,
        api_key: str,
        config: dict[str, Any],
        client: Optional[httpx.Client] = None,
    ):
        if not api_key:
            raise PlacesApiError(
                "Kein GOOGLE_PLACES_API_KEY gesetzt. Siehe README.md, Abschnitt "
                "'Einrichtung', für die Erstellung eines Places-API-Keys mit "
                "aktivierter Abrechnung."
            )
        self.api_key = api_key
        self.base_url = config["base_url"].rstrip("/")
        self.text_search_field_mask = ",".join(config["text_search_field_mask"])
        self.details_field_mask = ",".join(config["details_field_mask"])
        self.max_retries = config.get("max_retries", 5)
        self.backoff_base = config.get("backoff_base_seconds", 1.0)
        self._client = client or httpx.Client(timeout=15.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "PlacesClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _post(self, path: str, json_body: dict[str, Any], field_mask: str) -> dict[str, Any]:
        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=self.backoff_base, min=self.backoff_base, max=30),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )
        def _call() -> httpx.Response:
            resp = self._client.post(
                f"{self.base_url}{path}",
                json=json_body,
                headers={
                    "X-Goog-Api-Key": self.api_key,
                    "X-Goog-FieldMask": field_mask,
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            return resp

        try:
            resp = _call()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise PlacesApiQuotaError(
                    "Places API verweigert den Zugriff (401/403). Prüfen Sie, ob "
                    "'Places API (New)' aktiviert und ein Abrechnungskonto verknüpft "
                    "ist, und ob der API-Key auf diese API eingeschränkt ist."
                ) from exc
            raise PlacesApiError(f"Places API Fehler: {exc.response.status_code} {exc.response.text}") from exc
        except httpx.TransportError as exc:
            raise PlacesApiError(f"Places API nicht erreichbar: {exc}") from exc
        return resp.json()

    def text_search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """`places:searchText` - liefert Kandidaten für das Matching."""
        body = {"textQuery": query, "maxResultCount": max_results}
        data = self._post(":searchText", body, self.text_search_field_mask)
        return data.get("places", [])

    def search_nearby(
        self, lat: float, lng: float, radius_meters: float, included_types: Optional[list[str]] = None
    ) -> list[dict[str, Any]]:
        """`places:searchNearby` - für die Duplikatssuche im Umkreis eines Treffers."""
        body = {
            "locationRestriction": {
                "circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius_meters}
            },
            "maxResultCount": 20,
        }
        if included_types:
            body["includedTypes"] = included_types
        data = self._post(":searchNearby", body, self.text_search_field_mask)
        return data.get("places", [])

    def get_place_details(self, place_id: str) -> dict[str, Any]:
        clean_id = place_id.split("/")[-1]

        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=self.backoff_base, min=self.backoff_base, max=30),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )
        def _call() -> httpx.Response:
            resp = self._client.get(
                f"{self.base_url}/places/{clean_id}",
                headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": self.details_field_mask},
            )
            resp.raise_for_status()
            return resp

        try:
            resp = _call()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise PlacesApiQuotaError(
                    "Places API verweigert den Zugriff auf Place Details (401/403). "
                    "Abrechnung/API-Aktivierung im Google Cloud Projekt prüfen."
                ) from exc
            raise PlacesApiError(f"Places API Fehler: {exc.response.status_code} {exc.response.text}") from exc
        except httpx.TransportError as exc:
            raise PlacesApiError(f"Places API nicht erreichbar: {exc}") from exc
        return resp.json()


def place_to_gbp_profile(place: dict[str, Any]):
    """Mappt eine Places-API-Antwort (Text Search oder Details) auf GbpProfile."""
    from src.models import GbpProfile, Modus

    display_name = place.get("displayName", {})
    name = display_name.get("text", "") if isinstance(display_name, dict) else str(display_name or "")
    photos = place.get("photos") or []
    reviews = place.get("reviews") or []

    return GbpProfile(
        place_id=place.get("id", ""),
        display_name=name,
        formatted_address=place.get("formattedAddress", ""),
        phone=place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber", ""),
        website_uri=place.get("websiteUri", ""),
        primary_type=place.get("primaryType", ""),
        types=place.get("types", []),
        business_status=place.get("businessStatus", ""),
        rating=place.get("rating"),
        user_rating_count=place.get("userRatingCount"),
        regular_opening_hours=place.get("regularOpeningHours", {}) or {},
        reviews_sample=reviews,
        photo_count=len(photos) if photos else None,
        modus=Modus.A,
    )
