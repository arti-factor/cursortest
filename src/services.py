"""Geteilte Geschäftslogik für Discovery/Matching/Run/Diff.

Enthält reine Funktionen ohne Ausgabe-Logik (kein console.print/Rich), damit
sowohl die CLI (src/cli.py) als auch die Webanwendung (src/webapp/) dieselbe
Logik nutzen, ohne sie zu duplizieren. Fortschritts-/Statusmeldungen werden
über einen optionalen `on_progress`-Callback nach außen gereicht.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Optional

from src.api_gbp import GbpApiClient, GbpApiError, load_credentials
from src.api_places import PlacesApiError, PlacesClient, place_to_gbp_profile
from src.checks import run_all_checks
from src.checks.base import CheckContext
from src.discovery import CrawlConfig, discover_locations
from src.matching import MatchCandidate, MatchStatus, find_duplicates, match_location
from src.models import ClientRun, GbpProfile, Location, Modus
from src.report_html import write_html_report
from src.report_xlsx import write_report
from src.scoring import score_location
from src.storage import ClientDirs

ProgressFn = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


def places_client(config: dict[str, Any]) -> PlacesClient:
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    return PlacesClient(api_key, config["places_api"])


def discover_for_client(url: str, config: dict[str, Any]) -> list[Location]:
    crawl_config = CrawlConfig.from_dict(config["discovery"])
    return discover_locations(url, crawl_config)


@dataclass
class AmbiguousMatch:
    location_id: str
    location_name: str
    location_address: str
    candidates: list[MatchCandidate] = field(default_factory=list)


@dataclass
class MatchRunResult:
    locations: list[Location]
    ambiguous: list[AmbiguousMatch]


def apply_chosen_match(
    loc: Location, chosen: MatchCandidate, places: PlacesClient, matching_config: dict[str, Any]
) -> None:
    loc.place_id = chosen.place["id"]
    loc.match_status = MatchStatus.EINDEUTIG
    loc.match_confidence = chosen.confidence
    loc.duplicate_place_ids = find_duplicates(chosen.place, places, matching_config)


def match_all_locations(
    locations: list[Location], config: dict[str, Any], on_progress: ProgressFn = _noop
) -> MatchRunResult:
    """Führt Matching für alle Standorte durch.

    Eindeutige Treffer werden sofort übernommen. Mehrdeutige Standorte werden
    mit ihren Kandidaten zurückgegeben, damit ein Aufrufer (CLI-Prompt oder
    Web-Review-Seite) den Nutzer entscheiden lassen kann.
    """
    ambiguous: list[AmbiguousMatch] = []

    with places_client(config) as places:
        for loc in locations:
            on_progress(f"Matching für {loc.name} ({loc.address})...")
            try:
                result = match_location(loc, places, config["matching"])
            except PlacesApiError as exc:
                on_progress(f"  Fehler: {exc}")
                continue

            if result.status == MatchStatus.EINDEUTIG:
                apply_chosen_match(loc, result.chosen, places, config["matching"])
                on_progress(f"  Eindeutiger Treffer (Konfidenz {result.chosen.confidence:.0f}%).")
            elif result.status == MatchStatus.MEHRDEUTIG:
                ambiguous.append(
                    AmbiguousMatch(
                        location_id=loc.id,
                        location_name=loc.name,
                        location_address=loc.address,
                        candidates=result.candidates,
                    )
                )
                on_progress(f"  {len(result.candidates)} mögliche Treffer - Auswahl nötig.")
            else:
                loc.place_id = None
                loc.match_status = MatchStatus.KEIN_TREFFER
                on_progress("  Kein Google-Unternehmensprofil gefunden.")

    return MatchRunResult(locations=locations, ambiguous=ambiguous)


def resolve_ambiguous_match(
    loc: Location, chosen_place_id: Optional[str], config: dict[str, Any]
) -> None:
    """Wendet die Nutzerauswahl für einen zuvor mehrdeutigen Standort an.

    Holt die Platzdetails frisch über die Places API (statt die Kandidatenliste
    aus dem ursprünglichen Matching-Lauf zu serialisieren) - einfacher und
    robuster, insbesondere für die Duplikatssuche (benötigt Lat/Lng).
    """
    if not chosen_place_id:
        loc.place_id = None
        loc.match_status = MatchStatus.KEIN_TREFFER
        return

    with places_client(config) as places:
        place = places.get_place_details(chosen_place_id)
        loc.place_id = place["id"]
        loc.match_status = MatchStatus.EINDEUTIG
        loc.match_confidence = None
        loc.duplicate_place_ids = find_duplicates(place, places, config["matching"])


def _fetch_profile_modus_a(loc: Location, places: PlacesClient) -> Optional[GbpProfile]:
    if not loc.place_id:
        return None
    place = places.get_place_details(loc.place_id)
    return place_to_gbp_profile(place)


def _merge_modus_b(profile: GbpProfile, gbp_client: GbpApiClient, config: dict[str, Any], account_id: str, location_id: str, on_progress: ProgressFn) -> None:
    """Reichert ein GbpProfile mit Modus-B-Daten an (mutiert das Objekt)."""
    read_mask = "title,storefrontAddress,phoneNumbers,websiteUri,categories,regularHours,specialHours,profile,attributes,serviceItems"
    gbp_location = gbp_client.get_location(f"locations/{location_id}", read_mask)
    profile.description = (gbp_location.get("profile") or {}).get("description")
    profile.attributes = {a.get("attributeId"): a for a in gbp_location.get("attributes", [])}
    profile.service_items = gbp_location.get("serviceItems", [])
    profile.special_hours = gbp_location.get("specialHours", {})

    profile.reviews_full = gbp_client.list_reviews(account_id, location_id)
    profile.questions = gbp_client.list_questions(account_id, location_id)
    profile.owner_photos = gbp_client.list_media(account_id, location_id)

    lookback_days = config["gbp_api"].get("performance_lookback_days", 365)
    today = date.today()
    start = today.replace(year=today.year - 1) if lookback_days >= 365 else today
    try:
        perf = gbp_client.fetch_daily_metrics_time_series(
            f"locations/{location_id}",
            config["gbp_api"]["performance_metrics"],
            {"year": start.year, "month": start.month, "day": start.day},
            {"year": today.year, "month": today.month, "day": today.day},
        )
        totals: dict[str, int] = {}
        for series in perf.get("multiDailyMetricTimeSeries", []):
            for m in series.get("dailyMetricTimeSeries", []):
                metric = m.get("dailyMetric")
                total = sum(int(v.get("value", 0)) for v in m.get("timeSeries", {}).get("datedValues", []))
                totals[metric] = total
        profile.performance_metrics = totals
    except GbpApiError as exc:
        on_progress(f"  Performance-Daten nicht verfügbar: {exc}")

    profile.modus = Modus.B


def perform_run(
    client: ClientDirs, config: dict[str, Any], generate_html: bool = False, on_progress: ProgressFn = _noop
) -> ClientRun:
    """Datenabruf + Checks + Scoring + Report-Erstellung in einem Durchlauf."""
    locations = client.load_locations()
    if not locations:
        raise ValueError("Keine Standorte vorhanden. Zuerst Discovery und Matching durchführen.")

    run_date = date.today().isoformat()
    previous_runs = client.list_runs()
    previous_run_date = (
        previous_runs[-1]
        if previous_runs and previous_runs[-1] != run_date
        else (previous_runs[-2] if len(previous_runs) > 1 else None)
    )

    modus = Modus.B if client.token_path.exists() else Modus.A
    on_progress(f"Modus: {modus.value} ({'Full Audit' if modus == Modus.B else 'Public Audit'})")

    profiles: dict[str, Optional[GbpProfile]] = {}
    gbp_client: Optional[GbpApiClient] = None
    account_id = None

    with places_client(config) as places:
        if modus == Modus.B:
            try:
                creds = load_credentials(client.token_path, config["gbp_api"]["oauth_scopes"])
                gbp_client = GbpApiClient(creds, config["gbp_api"])
                accounts = gbp_client.list_accounts()
                account_id = accounts[0]["name"].split("/")[-1] if accounts else None
            except GbpApiError as exc:
                on_progress(f"Modus B nicht verfügbar, falle auf Modus A zurück: {exc}")
                modus = Modus.A
                gbp_client = None

        for loc in locations:
            on_progress(f"Rufe Daten ab für {loc.name}...")
            try:
                profile = _fetch_profile_modus_a(loc, places)
            except PlacesApiError as exc:
                on_progress(f"  Fehler: {exc}")
                profile = None

            if profile and modus == Modus.B and gbp_client and account_id:
                try:
                    _merge_modus_b(profile, gbp_client, config, account_id, loc.place_id, on_progress)
                except GbpApiError as exc:
                    on_progress(f"  Modus-B-Daten nicht verfügbar: {exc}")

            profiles[loc.id] = profile

    if gbp_client:
        gbp_client.close()

    client.save_run_json(run_date, "profiles.json", {lid: (p.to_dict() if p else None) for lid, p in profiles.items()})

    previous_profiles: dict[str, Optional[GbpProfile]] = {}
    if previous_run_date:
        try:
            raw = client.load_run_json(previous_run_date, "profiles.json")
            previous_profiles = {lid: (GbpProfile.from_dict(p) if p else None) for lid, p in raw.items()}
        except FileNotFoundError:
            pass

    portal_checks = client.load_portal_checks()

    results = []
    for loc in locations:
        ctx = CheckContext(
            location=loc,
            profile=profiles.get(loc.id),
            modus=modus,
            config=config,
            all_locations=locations,
            all_profiles=profiles,
            previous_profile=previous_profiles.get(loc.id),
            portal_checks=portal_checks,
        )
        checks = run_all_checks(ctx)
        results.append(score_location(loc, profiles.get(loc.id), modus, checks, config["scoring"]))

    client_run = ClientRun(client_slug=client.slug, run_date=run_date, modus=modus, results=results)

    xlsx_path = client.output_dir / f"gbp-audit_{run_date}.xlsx"
    write_report(client_run, xlsx_path, config["report"])
    on_progress(f"Excel-Report gespeichert: {xlsx_path}")

    if generate_html:
        html_path = client.output_dir / f"gbp-audit_{run_date}.html"
        write_html_report(client_run, html_path)
        on_progress(f"HTML-Dashboard gespeichert: {html_path}")

    return client_run


@dataclass
class DiffRow:
    location_name: str
    score_alt: Optional[float]
    score_neu: Optional[float]
    delta: Optional[float]


def perform_diff(client: ClientDirs, config: dict[str, Any], run1: str, run2: str) -> list[DiffRow]:
    alt = client.load_run_json(run1, "profiles.json")
    neu = client.load_run_json(run2, "profiles.json")

    locations = {loc.id: loc for loc in client.load_locations()}
    portal_checks = client.load_portal_checks()
    rows: list[DiffRow] = []

    for loc_id, loc in locations.items():
        alt_profile = GbpProfile.from_dict(alt[loc_id]) if alt.get(loc_id) else None
        neu_profile = GbpProfile.from_dict(neu[loc_id]) if neu.get(loc_id) else None

        alt_profiles = {k: (GbpProfile.from_dict(v) if v else None) for k, v in alt.items()}
        neu_profiles = {k: (GbpProfile.from_dict(v) if v else None) for k, v in neu.items()}

        ctx_alt = CheckContext(
            location=loc,
            profile=alt_profile,
            modus=alt_profile.modus if alt_profile else Modus.A,
            config=config,
            all_locations=list(locations.values()),
            all_profiles=alt_profiles,
            portal_checks=portal_checks,
        )
        ctx_neu = CheckContext(
            location=loc,
            profile=neu_profile,
            modus=neu_profile.modus if neu_profile else Modus.A,
            config=config,
            all_locations=list(locations.values()),
            all_profiles=neu_profiles,
            portal_checks=portal_checks,
        )

        score_alt = score_location(loc, alt_profile, ctx_alt.modus, run_all_checks(ctx_alt), config["scoring"]).gesamtscore
        score_neu = score_location(loc, neu_profile, ctx_neu.modus, run_all_checks(ctx_neu), config["scoring"]).gesamtscore

        delta = round(score_neu - score_alt, 1) if score_alt is not None and score_neu is not None else None
        rows.append(DiffRow(location_name=loc.name, score_alt=score_alt, score_neu=score_neu, delta=delta))

    return rows
