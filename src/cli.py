"""CLI-Einstiegspunkt für gbp-audit.

Befehle:
  gbp-audit client add <name> --url https://beispiel-gmbh.de
  gbp-audit client list
  gbp-audit discover <kunde>
  gbp-audit match <kunde>
  gbp-audit auth <kunde>
  gbp-audit run <kunde> [--html]
  gbp-audit diff <kunde> RUN1 RUN2

Die eigentliche Geschäftslogik liegt in src/services.py und wird auch von der
Webanwendung (src/webapp/) genutzt - dieses Modul kümmert sich nur um
Ein-/Ausgabe (Prompts, Tabellen).
"""
from __future__ import annotations

import os
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from src.api_gbp import GbpApiError, run_oauth_flow
from src.api_places import PlacesApiError
from src.models import ClientRun, Location
from src.services import (
    discover_for_client,
    match_all_locations,
    perform_diff,
    perform_run,
    resolve_ambiguous_match,
)
from src.storage import ClientDirs, get_client, list_clients

load_dotenv()

app = typer.Typer(help="Mandantenfähige CLI für Google-Unternehmensprofil-Audits.")
client_app = typer.Typer(help="Mandanten verwalten.")
app.add_typer(client_app, name="client")

console = Console()


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
    locations = discover_for_client(url, config)

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
        result = match_all_locations(locations, config, on_progress=lambda msg: console.print(msg))
    except PlacesApiError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1)

    for amb in result.ambiguous:
        table = Table(title=f"Mehrdeutig: {amb.location_name} ({amb.location_address})")
        table.add_column("#")
        table.add_column("Name")
        table.add_column("Adresse")
        table.add_column("Konfidenz")
        for i, cand in enumerate(amb.candidates, start=1):
            table.add_row(str(i), cand.place.get("displayName", {}).get("text", ""), cand.place.get("formattedAddress", ""), f"{cand.confidence:.0f}%")
        console.print(table)
        auswahl = typer.prompt("Welcher Treffer ist korrekt? (0 = keiner)", type=int, default=0)
        loc = next(l for l in result.locations if l.id == amb.location_id)
        chosen_place_id = amb.candidates[auswahl - 1].place["id"] if 1 <= auswahl <= len(amb.candidates) else None
        resolve_ambiguous_match(loc, chosen_place_id, config)

    client.save_locations(result.locations)
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
    try:
        client_run = perform_run(client, config, generate_html=html, on_progress=lambda msg: console.print(msg))
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1)
    except PlacesApiError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1)

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

    config = client.load_config()
    try:
        rows = perform_diff(client, config, run1, run2)
    except FileNotFoundError as exc:
        console.print(f"[red]Lauf nicht gefunden: {exc}[/]")
        raise typer.Exit(code=1)

    table = Table(title=f"Diff {run1} -> {run2}")
    table.add_column("Standort")
    table.add_column(f"Score {run1}")
    table.add_column(f"Score {run2}")
    table.add_column("Delta")
    for row in rows:
        table.add_row(
            row.location_name,
            str(row.score_alt) if row.score_alt is not None else "n/a",
            str(row.score_neu) if row.score_neu is not None else "n/a",
            f"{row.delta:+.1f}" if row.delta is not None else "n/a",
        )
    console.print(table)


if __name__ == "__main__":
    app()
