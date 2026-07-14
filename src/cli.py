"""CLI-Einstiegspunkt für gbp-audit.

Befehle:
  gbp-audit client add <name> --url https://beispiel-gmbh.de
  gbp-audit client list
  gbp-audit discover <kunde>
  gbp-audit match <kunde>
  gbp-audit auth <kunde>
  gbp-audit run <kunde> [--html]
  gbp-audit diff <kunde> RUN1 RUN2
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from src.api_gbp import GbpApiClient, GbpApiError, load_credentials, run_oauth_flow
from src.api_places import PlacesApiError, PlacesClient, place_to_gbp_profile
from src.checks import GROUPS, run_all_checks
from src.checks.base import CheckContext
from src.discovery import CrawlConfig, discover_locations
from src.matching import MatchStatus, find_duplicates, match_location
from src.models import ClientRun, GbpProfile, Location, Modus
from src.report_html import write_html_report
from src.report_xlsx import write_report
from src.scoring import score_location
from src.storage import ClientDirs, get_client, list_clients

load_dotenv()

app = typer.Typer(help="Mandantenfähige CLI für Google-Unternehmensprofil-Audits.")
client_app = typer.Typer(help="Mandanten verwalten.")
app.add_typer(client_app, name="client")

console = Console()


def _places_client(config: dict) -> PlacesClient:
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    return PlacesClient(api_key, config["places_api"])


def _print_locations_table(locations: list[Location]) -> None:
    table = Table(title="Gefundene Standorte")
    table.add_column("#", justify="right")
    table.add_column("Name")
    table.add_column("Adresse")
    table.add_column("Telefon")
    table.add_column("Quelle", overflow="fold")
    table.add_column("Methode")
    for i, loc in enumerate(locations, start=1):
        table.add_row(str(i), loc.name, loc.address, loc.phone, loc.source_url, loc.extraction_method)
    console.print(table)


@client_app.command("add")
def client_add(
    name: str = typer.Argument(..., help="Name/Slug des Kunden, z.B. 'beispiel-gmbh'"),
    url: str = typer.Option(..., "--url", help="Domain oder direkte Kontakt-/Standortseiten-URL des Kunden"),
):
    """Legt einen neuen Mandanten an: Discovery + Matching in einem Durchlauf."""
    client = get_client(name)
    if client.exists():
        console.print(f"[yellow]Mandant '{client.slug}' existiert bereits - verwende 'discover'/'match' zum Aktualisieren.[/]")
        raise typer.Exit(code=1)

    client.ensure()
    console.print(f"[bold]Discovery für {url}...[/]")
    _run_discovery(client, url)
    console.print("[bold]Starte GBP-Matching...[/]")
    _run_matching(client)


@client_app.command("list")
def client_list():
    """Zeigt alle angelegten Mandanten."""
    clients = list_clients()
    if not clients:
        console.print("Noch keine Mandanten angelegt. Mit 'gbp-audit client add' beginnen.")
        return
    table = Table(title="Mandanten")
    table.add_column("Slug")
    table.add_column("Standorte")
    table.add_column("Letzter Lauf")
    for slug in clients:
        cd = ClientDirs(slug)
        locations = cd.load_locations()
        runs = cd.list_runs()
        table.add_row(slug, str(len(locations)), runs[-1] if runs else "-")
    console.print(table)


def _run_discovery(client: ClientDirs, url: str) -> list[Location]:
    config = client.load_config()
    crawl_config = CrawlConfig.from_dict(config["discovery"])
    locations = discover_locations(url, crawl_config)

    if not locations:
        console.print("[red]Keine Standorte gefunden. URL prüfen oder Standorte manuell in locations.yaml ergänzen.[/]")
        return []

    _print_locations_table(locations)
    if typer.confirm(f"{len(locations)} Standort(e) übernehmen?", default=True):
        client.save_locations(locations)
        console.print(f"[green]{len(locations)} Standort(e) gespeichert unter {client.locations_path}[/]")
    return locations


@app.command()
def discover(kunde: str, url: Optional[str] = typer.Option(None, "--url", help="Abweichende URL statt der gespeicherten")):
    """Extrahiert Standorte erneut von der Kunden-Website."""
    client = get_client(kunde)
    if not client.exists():
        console.print(f"[red]Mandant '{client.slug}' existiert nicht. Zuerst 'gbp-audit client add' ausführen.[/]")
        raise typer.Exit(code=1)
    if url is None:
        existing = client.load_locations()
        if not existing:
            console.print("[red]Keine bekannte URL - bitte --url angeben.[/]")
            raise typer.Exit(code=1)
        url = existing[0].source_url
    _run_discovery(client, url)


def _run_matching(client: ClientDirs) -> None:
    config = client.load_config()
    locations = client.load_locations()
    if not locations:
        console.print("[red]Keine Standorte vorhanden. Zuerst 'gbp-audit discover' ausführen.[/]")
        return

    try:
        places = _places_client(config)
    except PlacesApiError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1)

    with places:
        for loc in locations:
            console.print(f"Matching für [bold]{loc.name}[/] ({loc.address})...")
            try:
                result = match_location(loc, places, config["matching"])
            except PlacesApiError as exc:
                console.print(f"  [red]{exc}[/]")
                continue

            if result.status == MatchStatus.EINDEUTIG:
                loc.place_id = result.chosen.place["id"]
                loc.match_status = MatchStatus.EINDEUTIG
                loc.match_confidence = result.chosen.confidence
                console.print(f"  [green]Eindeutiger Treffer (Konfidenz {result.chosen.confidence:.0f}%).[/]")
                loc.duplicate_place_ids = find_duplicates(result.chosen.place, places, config["matching"])
            elif result.status == MatchStatus.MEHRDEUTIG:
                table = Table()
                table.add_column("#")
                table.add_column("Name")
                table.add_column("Adresse")
                table.add_column("Konfidenz")
                for i, cand in enumerate(result.candidates, start=1):
                    table.add_row(str(i), cand.place.get("displayName", {}).get("text", ""), cand.place.get("formattedAddress", ""), f"{cand.confidence:.0f}%")
                console.print(table)
                auswahl = typer.prompt("Welcher Treffer ist korrekt? (0 = keiner)", type=int, default=0)
                if 1 <= auswahl <= len(result.candidates):
                    chosen = result.candidates[auswahl - 1]
                    loc.place_id = chosen.place["id"]
                    loc.match_status = MatchStatus.EINDEUTIG
                    loc.match_confidence = chosen.confidence
                    loc.duplicate_place_ids = find_duplicates(chosen.place, places, config["matching"])
                else:
                    loc.place_id = None
                    loc.match_status = MatchStatus.KEIN_TREFFER
            else:
                console.print("  [red]Kein Google-Unternehmensprofil gefunden.[/]")
                loc.place_id = None
                loc.match_status = MatchStatus.KEIN_TREFFER

    client.save_locations(locations)
    console.print("[green]Matching abgeschlossen und gespeichert.[/]")


@app.command()
def match(kunde: str):
    """Führt das GBP-Matching (erneut) durch."""
    client = get_client(kunde)
    if not client.exists():
        console.print(f"[red]Mandant '{client.slug}' existiert nicht.[/]")
        raise typer.Exit(code=1)
    _run_matching(client)


@app.command()
def auth(kunde: str):
    """Richtet OAuth für Modus B (Full Audit) ein."""
    client = get_client(kunde)
    if not client.exists():
        console.print(f"[red]Mandant '{client.slug}' existiert nicht.[/]")
        raise typer.Exit(code=1)

    config = client.load_config()
    client_secret_file = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_FILE", "")
    try:
        run_oauth_flow(client_secret_file, config["gbp_api"]["oauth_scopes"], client.token_path)
    except GbpApiError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1)
    console.print(f"[green]OAuth für '{client.slug}' eingerichtet. Modus B ist ab sofort verfügbar.[/]")


def _fetch_profile_modus_a(loc: Location, places: PlacesClient) -> Optional[GbpProfile]:
    if not loc.place_id:
        return None
    place = places.get_place_details(loc.place_id)
    return place_to_gbp_profile(place)


def _merge_modus_b(profile: GbpProfile, gbp_client: GbpApiClient, config: dict, account_id: str, location_id: str) -> None:
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
        console.print(f"  [yellow]Performance-Daten nicht verfügbar: {exc}[/]")

    profile.modus = Modus.B


@app.command()
def run(
    kunde: str,
    html: bool = typer.Option(False, "--html", help="Zusätzlich ein HTML-Dashboard erzeugen"),
):
    """Führt Datenabruf, Checks und Report-Erstellung in einem Durchlauf aus."""
    client = get_client(kunde)
    if not client.exists():
        console.print(f"[red]Mandant '{client.slug}' existiert nicht. Zuerst 'gbp-audit client add' ausführen.[/]")
        raise typer.Exit(code=1)

    config = client.load_config()
    locations = client.load_locations()
    if not locations:
        console.print("[red]Keine Standorte vorhanden. Zuerst 'gbp-audit discover' und 'gbp-audit match' ausführen.[/]")
        raise typer.Exit(code=1)

    run_date = date.today().isoformat()
    previous_runs = client.list_runs()
    previous_run_date = previous_runs[-1] if previous_runs and previous_runs[-1] != run_date else (
        previous_runs[-2] if len(previous_runs) > 1 else None
    )

    modus_b_verfuegbar = client.token_path.exists()
    modus = Modus.B if modus_b_verfuegbar else Modus.A
    console.print(f"[bold]Modus: {modus.value}[/] ({'Full Audit' if modus == Modus.B else 'Public Audit'})")

    profiles: dict[str, Optional[GbpProfile]] = {}
    gbp_client: Optional[GbpApiClient] = None
    account_id = None

    try:
        places = _places_client(config)
    except PlacesApiError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1)

    with places:
        if modus == Modus.B:
            try:
                creds = load_credentials(client.token_path, config["gbp_api"]["oauth_scopes"])
                gbp_client = GbpApiClient(creds, config["gbp_api"])
                accounts = gbp_client.list_accounts()
                account_id = accounts[0]["name"].split("/")[-1] if accounts else None
            except GbpApiError as exc:
                console.print(f"[yellow]Modus B nicht verfügbar, falle auf Modus A zurück: {exc}[/]")
                modus = Modus.A
                gbp_client = None

        for loc in locations:
            console.print(f"Rufe Daten ab für [bold]{loc.name}[/]...")
            try:
                profile = _fetch_profile_modus_a(loc, places)
            except PlacesApiError as exc:
                console.print(f"  [red]{exc}[/]")
                profile = None

            if profile and modus == Modus.B and gbp_client and account_id:
                try:
                    _merge_modus_b(profile, gbp_client, config, account_id, loc.place_id)
                except GbpApiError as exc:
                    console.print(f"  [yellow]Modus-B-Daten nicht verfügbar: {exc}[/]")

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
        )
        checks = run_all_checks(ctx)
        results.append(score_location(loc, profiles.get(loc.id), modus, checks, config["scoring"]))

    client_run = ClientRun(client_slug=client.slug, run_date=run_date, modus=modus, results=results)

    xlsx_path = client.output_dir / f"gbp-audit_{run_date}.xlsx"
    write_report(client_run, xlsx_path, config["report"])
    console.print(f"[green]Excel-Report gespeichert: {xlsx_path}[/]")

    if html:
        html_path = client.output_dir / f"gbp-audit_{run_date}.html"
        write_html_report(client_run, html_path)
        console.print(f"[green]HTML-Dashboard gespeichert: {html_path}[/]")

    _print_summary(client_run)


def _print_summary(client_run: ClientRun) -> None:
    table = Table(title=f"Zusammenfassung {client_run.client_slug} ({client_run.run_date})")
    table.add_column("Standort")
    table.add_column("Score")
    table.add_column("Ampel")
    for r in sorted(client_run.results, key=lambda r: (r.gesamtscore is None, r.gesamtscore or 0)):
        table.add_row(r.location.name, str(r.gesamtscore) if r.gesamtscore is not None else "n/a", r.ampel)
    console.print(table)


@app.command()
def diff(kunde: str, run1: str, run2: str):
    """Vergleicht zwei Läufe eines Mandanten (Score-Entwicklung je Standort)."""
    client = get_client(kunde)
    if not client.exists():
        console.print(f"[red]Mandant '{client.slug}' existiert nicht.[/]")
        raise typer.Exit(code=1)

    try:
        alt = client.load_run_json(run1, "profiles.json")
        neu = client.load_run_json(run2, "profiles.json")
    except FileNotFoundError as exc:
        console.print(f"[red]Lauf nicht gefunden: {exc}[/]")
        raise typer.Exit(code=1)

    locations = {loc.id: loc for loc in client.load_locations()}
    config = client.load_config()

    table = Table(title=f"Diff {run1} -> {run2}")
    table.add_column("Standort")
    table.add_column(f"Score {run1}")
    table.add_column(f"Score {run2}")
    table.add_column("Delta")

    for loc_id, loc in locations.items():
        alt_profile = GbpProfile.from_dict(alt[loc_id]) if alt.get(loc_id) else None
        neu_profile = GbpProfile.from_dict(neu[loc_id]) if neu.get(loc_id) else None

        ctx_alt = CheckContext(location=loc, profile=alt_profile, modus=alt_profile.modus if alt_profile else Modus.A, config=config, all_locations=list(locations.values()), all_profiles={k: (GbpProfile.from_dict(v) if v else None) for k, v in alt.items()})
        ctx_neu = CheckContext(location=loc, profile=neu_profile, modus=neu_profile.modus if neu_profile else Modus.A, config=config, all_locations=list(locations.values()), all_profiles={k: (GbpProfile.from_dict(v) if v else None) for k, v in neu.items()})

        score_alt = score_location(loc, alt_profile, ctx_alt.modus, run_all_checks(ctx_alt), config["scoring"]).gesamtscore
        score_neu = score_location(loc, neu_profile, ctx_neu.modus, run_all_checks(ctx_neu), config["scoring"]).gesamtscore

        delta = None
        if score_alt is not None and score_neu is not None:
            delta = round(score_neu - score_alt, 1)

        table.add_row(loc.name, str(score_alt) if score_alt is not None else "n/a", str(score_neu) if score_neu is not None else "n/a", f"{delta:+.1f}" if delta is not None else "n/a")

    console.print(table)


if __name__ == "__main__":
    app()
