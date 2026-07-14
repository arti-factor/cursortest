"""Client für die Google-Business-Profile-APIs (Modus B / "Full Audit").

Bündelt drei offizielle APIs plus die ältere My Business API v4 (für
Bewertungen/Q&A/Medien, die in den neueren APIs fehlen):

- Account Management API   (mybusinessaccountmanagement.googleapis.com)
- Business Information API (mybusinessbusinessinformation.googleapis.com)
- Business Profile Performance API (businessprofileperformance.googleapis.com)
- My Business API v4       (mybusiness.googleapis.com/v4) - reviews/questions/media

Erfordert vom Kunden freigeschaltete GBP-API-Quota (Standard-Quota ist 0).
Bei Quota=0 liefert Google typischerweise 403 PERMISSION_DENIED - das wird
hier in eine verständliche Fehlermeldung übersetzt (siehe GbpApiQuotaError).

Read-only: es werden ausschließlich lesende Endpunkte verwendet, es wird
niemals in ein GBP-Profil geschrieben (siehe "Nicht-Ziele" im Projektauftrag).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Optional

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


class GbpApiError(RuntimeError):
    pass


class GbpApiQuotaError(GbpApiError):
    """Der Kunde/das Google-Cloud-Projekt hat keine (oder Quota=0) für die GBP-APIs."""


class GbpAuthRequiredError(GbpApiError):
    """Für diesen Mandanten wurde noch kein OAuth-Flow (gbp-audit auth <kunde>) durchgeführt."""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, httpx.TransportError)


def run_oauth_flow(client_secret_file: str, scopes: list[str], token_path: Path) -> Credentials:
    """Führt den OAuth-Desktop-Flow interaktiv aus und speichert den Token unter token_path."""
    if not client_secret_file or not Path(client_secret_file).exists():
        raise GbpApiError(
            "Keine gültige OAuth-Client-Secret-Datei gefunden. In der Google Cloud "
            "Console unter 'APIs & Dienste -> Zugangsdaten' eine OAuth-Client-ID vom "
            "Typ 'Desktop-App' anlegen, JSON herunterladen und den Pfad in "
            "GOOGLE_OAUTH_CLIENT_SECRET_FILE (.env) eintragen."
        )
    flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, scopes=scopes)
    creds = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def load_credentials(token_path: Path, scopes: list[str]) -> Credentials:
    if not token_path.exists():
        raise GbpAuthRequiredError(
            f"Kein OAuth-Token unter {token_path} gefunden. Zuerst 'gbp-audit auth <kunde>' ausführen."
        )
    creds = Credentials.from_authorized_user_info(json.loads(token_path.read_text(encoding="utf-8")), scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


class GbpApiClient:
    def __init__(self, credentials: Credentials, config: dict[str, Any], client: Optional[httpx.Client] = None):
        self.credentials = credentials
        self.config = config
        self.max_retries = config.get("max_retries", 5)
        self.backoff_base = config.get("backoff_base_seconds", 1.0)
        self._client = client or httpx.Client(timeout=30.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "GbpApiClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _auth_header(self) -> dict[str, str]:
        if self.credentials.expired and self.credentials.refresh_token:
            self.credentials.refresh(Request())
        return {"Authorization": f"Bearer {self.credentials.token}"}

    def _get(self, url: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=self.backoff_base, min=self.backoff_base, max=30),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )
        def _call() -> httpx.Response:
            resp = self._client.get(url, params=params, headers=self._auth_header())
            resp.raise_for_status()
            return resp

        try:
            resp = _call()
        except httpx.HTTPStatusError as exc:
            self._raise_mapped(exc)
        except httpx.TransportError as exc:
            raise GbpApiError(f"GBP-API nicht erreichbar: {exc}") from exc
        return resp.json()

    def _raise_mapped(self, exc: httpx.HTTPStatusError) -> None:
        status = exc.response.status_code
        body = exc.response.text
        if status == 403 and ("PERMISSION_DENIED" in body or "quota" in body.lower()):
            raise GbpApiQuotaError(
                "Kein Zugriff auf die GBP-APIs (403 PERMISSION_DENIED). Das Google-Cloud-"
                "Projekt hat vermutlich Quota=0 für die Business-Profile-APIs. Zugang über "
                "das GBP-API-Antragsformular beantragen: "
                "https://developers.google.com/my-business/content/prereqs#request-access. "
                f"Original-Fehler: {body[:300]}"
            ) from exc
        if status == 401:
            raise GbpAuthRequiredError(
                "OAuth-Token abgelaufen/ungültig. 'gbp-audit auth <kunde>' erneut ausführen."
            ) from exc
        raise GbpApiError(f"GBP-API Fehler {status}: {body[:500]}") from exc

    # --- Account Management API ---

    def list_accounts(self) -> list[dict[str, Any]]:
        url = f"{self.config['account_management_base_url']}/accounts"
        accounts: list[dict[str, Any]] = []
        page_token = None
        while True:
            params = {"pageToken": page_token} if page_token else {}
            data = self._get(url, params=params)
            accounts.extend(data.get("accounts", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return accounts

    # --- Business Information API ---

    def list_locations(self, account_name: str, read_mask: str) -> list[dict[str, Any]]:
        """account_name: 'accounts/{accountId}'."""
        url = f"{self.config['business_information_base_url']}/{account_name}/locations"
        locations: list[dict[str, Any]] = []
        page_token = None
        while True:
            params = {"readMask": read_mask, "pageSize": 100}
            if page_token:
                params["pageToken"] = page_token
            data = self._get(url, params=params)
            locations.extend(data.get("locations", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return locations

    def get_location(self, location_name: str, read_mask: str) -> dict[str, Any]:
        """location_name: 'locations/{locationId}'."""
        url = f"{self.config['business_information_base_url']}/{location_name}"
        return self._get(url, params={"readMask": read_mask})

    # --- Business Profile Performance API ---

    def fetch_daily_metrics_time_series(
        self, location_name: str, metrics: list[str], start_date: dict[str, int], end_date: dict[str, int]
    ) -> dict[str, Any]:
        """location_name: 'locations/{locationId}'. start/end_date: {"year", "month", "day"}."""
        url = f"{self.config['performance_base_url']}/{location_name}:fetchMultiDailyMetricsTimeSeries"
        params: dict[str, Any] = {
            "dailyMetrics": metrics,
            "dailyRange.startDate.year": start_date["year"],
            "dailyRange.startDate.month": start_date["month"],
            "dailyRange.startDate.day": start_date["day"],
            "dailyRange.endDate.year": end_date["year"],
            "dailyRange.endDate.month": end_date["month"],
            "dailyRange.endDate.day": end_date["day"],
        }
        return self._get(url, params=params)

    # --- My Business API v4 (legacy) - reviews / questions / media ---

    def list_reviews(self, account_id: str, location_id: str) -> list[dict[str, Any]]:
        url = (
            f"{self.config['legacy_v4_base_url']}/accounts/{account_id}"
            f"/locations/{location_id}/reviews"
        )
        reviews: list[dict[str, Any]] = []
        page_token = None
        while True:
            params = {"pageToken": page_token} if page_token else {}
            data = self._get(url, params=params)
            reviews.extend(data.get("reviews", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return reviews

    def list_questions(self, account_id: str, location_id: str) -> list[dict[str, Any]]:
        url = (
            f"{self.config['legacy_v4_base_url']}/accounts/{account_id}"
            f"/locations/{location_id}/questions"
        )
        questions: list[dict[str, Any]] = []
        page_token = None
        while True:
            params = {"pageToken": page_token} if page_token else {}
            data = self._get(url, params=params)
            questions.extend(data.get("questions", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return questions

    def list_media(self, account_id: str, location_id: str) -> list[dict[str, Any]]:
        url = f"{self.config['legacy_v4_base_url']}/accounts/{account_id}/locations/{location_id}/media"
        media: list[dict[str, Any]] = []
        page_token = None
        while True:
            params = {"pageToken": page_token} if page_token else {}
            data = self._get(url, params=params)
            media.extend(data.get("mediaItems", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return media
