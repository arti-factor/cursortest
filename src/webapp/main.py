"""FastAPI-Webanwendung für gbp-audit.

Eigenständige Webanwendung (kein eigenes Login) - gedacht zum Verlinken/
Einbetten aus einer bestehenden Agenturverwaltung heraus. Nutzt dieselbe
Geschäftslogik wie die CLI (src/services.py).

Start (Entwicklung):
    uvicorn src.webapp.main:app --reload --port 8000

Start (produktiv, im lokalen Netz erreichbar):
    uvicorn src.webapp.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.api_gbp import GbpApiError, build_web_oauth_flow
from src.api_places import PlacesApiError
from src.models import Location
from src.services import (
    discover_for_client,
    match_all_locations,
    perform_diff,
    perform_run,
    resolve_ambiguous_match,
)
from src.storage import ClientDirs, get_client, list_clients, slugify
from src.webapp.jobs import Job, jobs

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="gbp-audit")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# state -> client-slug, für den OAuth-Web-Flow (siehe unten). In-Memory reicht,
# da der Flow innerhalb weniger Minuten im selben Prozess abgeschlossen wird.
_oauth_states: dict[str, str] = {}


def render(request: Request, template: str, **ctx):
    flash = request.query_params.get("flash")
    flash_kind = request.query_params.get("flash_kind", "info")
    return templates.TemplateResponse(
        request, template, {"flash_message": flash, "flash_kind": flash_kind, **ctx}
    )


def redirect_with_flash(url: str, message: str, kind: str = "info") -> RedirectResponse:
    sep = "&" if "?" in url else "?"
    return RedirectResponse(f"{url}{sep}{urlencode({'flash': message, 'flash_kind': kind})}", status_code=303)


def _require_client(slug: str) -> ClientDirs:
    client = get_client(slug)
    if not client.exists():
        raise LookupError(f"Mandant '{slug}' existiert nicht.")
    return client


AMPEL_CLASS = {"gruen": "gruen", "gelb": "gelb", "rot": "rot", "n/a": "na"}


# --- Mandanten-Übersicht ---


@app.get("/", response_class=HTMLResponse, name="index")
def index(request: Request):
    rows = []
    for slug in list_clients():
        cd = ClientDirs(slug)
        locations = cd.load_locations()
        runs = cd.list_runs()
        rows.append(
            {
                "slug": slug,
                "anzahl_standorte": len(locations),
                "letzter_lauf": runs[-1] if runs else None,
                "modus_b": cd.token_path.exists(),
            }
        )
    return render(request, "index.html", clients=rows)


@app.get("/clients/new", response_class=HTMLResponse, name="client_new_form")
def client_new_form(request: Request):
    return render(request, "client_new.html")


def _discover_job(job: Job, url: str, client: ClientDirs) -> list[Location]:
    job.append_log(f"Durchsuche {url}...")
    config = client.load_config()
    locations = discover_for_client(url, config)
    job.append_log(f"{len(locations)} Standort(e) gefunden.")
    return locations


@app.post("/clients/new", name="client_new_submit")
def client_new_submit(request: Request, name: str = Form(...), url: str = Form(...)):
    slug = slugify(name)
    client = get_client(slug)
    if client.exists():
        return redirect_with_flash(
            str(request.url_for("client_detail", slug=slug)),
            f"Mandant '{slug}' existiert bereits.",
            "error",
        )
    client.ensure()
    job = jobs.start("discover", lambda job: _discover_job(job, url, client), meta={"slug": slug, "url": url})
    return RedirectResponse(
        str(request.url_for("job_status", job_id=job.id)) + f"?next=locations_review&slug={slug}",
        status_code=303,
    )


# --- Job-Status (Polling-Seite für Hintergrundvorgänge) ---


@app.get("/jobs/{job_id}", response_class=HTMLResponse, name="job_status")
def job_status(request: Request, job_id: str, next: Optional[str] = None, slug: Optional[str] = None):
    job = jobs.get(job_id)
    if job is None:
        return redirect_with_flash(str(request.url_for("index")), "Unbekannter Vorgang.", "error")

    redirect_url = None
    if job.status == "done" and next:
        redirect_url = _resolve_next_url(request, next, slug, job)

    return render(
        request,
        "job_status.html",
        job=job,
        redirect_url=redirect_url,
        slug=slug,
    )


def _resolve_next_url(request: Request, next: str, slug: Optional[str], job: Job) -> Optional[str]:
    if next == "locations_review" and slug:
        return str(request.url_for("locations_review_form", slug=slug)) + f"?job_id={job.id}"
    if next == "match_review" and slug:
        if job.result and job.result.ambiguous:
            return str(request.url_for("match_review_form", slug=slug)) + f"?job_id={job.id}"
        return str(request.url_for("client_detail", slug=slug)) + "?" + urlencode(
            {"flash": "Matching abgeschlossen.", "flash_kind": "success"}
        )
    if next == "report" and slug and job.result is not None:
        return str(request.url_for("report_view", slug=slug, run_date=job.result.run_date))
    return None


# --- Standort-Review (nach Discovery) ---


@app.get("/clients/{slug}/locations/review", response_class=HTMLResponse, name="locations_review_form")
def locations_review_form(request: Request, slug: str, job_id: Optional[str] = None):
    try:
        client = _require_client(slug)
    except LookupError as exc:
        return redirect_with_flash(str(request.url_for("index")), str(exc), "error")

    locations = None
    if job_id:
        job = jobs.get(job_id)
        if job and job.status == "done":
            locations = job.result
        elif job and job.status == "error":
            return redirect_with_flash(
                str(request.url_for("client_detail", slug=slug)), f"Discovery fehlgeschlagen: {job.error}", "error"
            )
    if locations is None:
        locations = client.load_locations()

    return render(request, "locations_review.html", slug=slug, locations=locations)


@app.post("/clients/{slug}/locations/review", name="locations_review_submit")
async def locations_review_submit(request: Request, slug: str):
    try:
        client = _require_client(slug)
    except LookupError as exc:
        return redirect_with_flash(str(request.url_for("index")), str(exc), "error")

    form = await request.form()
    indices = sorted({key.split("_", 2)[1] for key in form.keys() if key.startswith("loc_")})

    locations: list[Location] = []
    for i in indices:
        if form.get(f"loc_{i}_removed"):
            continue
        name = (form.get(f"loc_{i}_name") or "").strip()
        if not name:
            continue
        street = (form.get(f"loc_{i}_street") or "").strip()
        zip_code = (form.get(f"loc_{i}_zip") or "").strip()
        city = (form.get(f"loc_{i}_city") or "").strip()
        phone = (form.get(f"loc_{i}_phone") or "").strip()
        website = (form.get(f"loc_{i}_website") or "").strip()
        source_url = (form.get(f"loc_{i}_source_url") or "").strip()
        loc_id = re.sub(r"[^a-z0-9]+", "-", f"{name}-{zip_code}".lower()).strip("-") or f"standort-{i}"
        locations.append(
            Location(
                id=loc_id,
                name=name,
                street=street,
                zip=zip_code,
                city=city,
                phone=phone,
                website=website,
                source_url=source_url,
                extraction_method=form.get(f"loc_{i}_extraction_method") or "manuell",
                manuell_ergaenzt=bool(form.get(f"loc_{i}_manuell")),
            )
        )

    client.save_locations(locations)
    return redirect_with_flash(
        str(request.url_for("client_detail", slug=slug)),
        f"{len(locations)} Standort(e) gespeichert.",
        "success",
    )


# --- Mandanten-Detailseite ---


@app.get("/clients/{slug}", response_class=HTMLResponse, name="client_detail")
def client_detail(request: Request, slug: str):
    try:
        client = _require_client(slug)
    except LookupError as exc:
        return redirect_with_flash(str(request.url_for("index")), str(exc), "error")

    locations = client.load_locations()
    runs = list(reversed(client.list_runs()))
    return render(
        request,
        "client_detail.html",
        slug=slug,
        locations=locations,
        runs=runs,
        modus_b=client.token_path.exists(),
        has_locations=bool(locations),
    )


@app.post("/clients/{slug}/discover", name="client_discover")
def client_discover(request: Request, slug: str, url: str = Form(...)):
    try:
        client = _require_client(slug)
    except LookupError as exc:
        return redirect_with_flash(str(request.url_for("index")), str(exc), "error")

    job = jobs.start("discover", lambda job: _discover_job(job, url, client), meta={"slug": slug})
    return RedirectResponse(
        str(request.url_for("job_status", job_id=job.id)) + f"?next=locations_review&slug={slug}",
        status_code=303,
    )


# --- Matching ---


def _match_job(job: Job, client: ClientDirs):
    config = client.load_config()
    locations = client.load_locations()
    result = match_all_locations(locations, config, on_progress=job.append_log)
    if not result.ambiguous:
        client.save_locations(result.locations)
        job.append_log("Alle Standorte eindeutig zugeordnet und gespeichert.")
    return result


@app.post("/clients/{slug}/match", name="client_match")
def client_match(request: Request, slug: str):
    try:
        client = _require_client(slug)
    except LookupError as exc:
        return redirect_with_flash(str(request.url_for("index")), str(exc), "error")

    if not client.load_locations():
        return redirect_with_flash(
            str(request.url_for("client_detail", slug=slug)), "Keine Standorte vorhanden.", "error"
        )

    job = jobs.start("match", lambda job: _match_job(job, client), meta={"slug": slug})
    return RedirectResponse(
        str(request.url_for("job_status", job_id=job.id)) + f"?next=match_review&slug={slug}",
        status_code=303,
    )


@app.get("/clients/{slug}/match/review", response_class=HTMLResponse, name="match_review_form")
def match_review_form(request: Request, slug: str, job_id: str):
    job = jobs.get(job_id)
    if job is None or job.status != "done":
        return redirect_with_flash(
            str(request.url_for("client_detail", slug=slug)), "Matching-Vorgang nicht gefunden.", "error"
        )
    return render(request, "match_review.html", slug=slug, job_id=job_id, ambiguous=job.result.ambiguous)


@app.post("/clients/{slug}/match/review", name="match_review_submit")
async def match_review_submit(request: Request, slug: str, job_id: str = Form(...)):
    try:
        client = _require_client(slug)
    except LookupError as exc:
        return redirect_with_flash(str(request.url_for("index")), str(exc), "error")

    job = jobs.get(job_id)
    if job is None or job.status != "done":
        return redirect_with_flash(
            str(request.url_for("client_detail", slug=slug)), "Matching-Vorgang nicht gefunden.", "error"
        )

    form = await request.form()
    config = client.load_config()
    locations_by_id = {loc.id: loc for loc in job.result.locations}

    for amb in job.result.ambiguous:
        chosen_place_id = form.get(f"choice_{amb.location_id}") or None
        loc = locations_by_id[amb.location_id]
        try:
            resolve_ambiguous_match(loc, chosen_place_id, config)
        except PlacesApiError as exc:
            return redirect_with_flash(
                str(request.url_for("client_detail", slug=slug)), f"Fehler beim Zuordnen: {exc}", "error"
            )

    client.save_locations(job.result.locations)
    return redirect_with_flash(
        str(request.url_for("client_detail", slug=slug)), "Matching abgeschlossen und gespeichert.", "success"
    )


# --- Audit-Lauf + Report ---


def _run_job(job: Job, client: ClientDirs):
    config = client.load_config()
    return perform_run(client, config, generate_html=True, on_progress=job.append_log)


@app.post("/clients/{slug}/run", name="client_run")
def client_run(request: Request, slug: str):
    try:
        client = _require_client(slug)
    except LookupError as exc:
        return redirect_with_flash(str(request.url_for("index")), str(exc), "error")

    if not client.load_locations():
        return redirect_with_flash(
            str(request.url_for("client_detail", slug=slug)), "Keine Standorte vorhanden.", "error"
        )

    job = jobs.start("run", lambda job: _run_job(job, client), meta={"slug": slug})
    return RedirectResponse(
        str(request.url_for("job_status", job_id=job.id)) + f"?next=report&slug={slug}",
        status_code=303,
    )


@app.get("/clients/{slug}/runs/{run_date}", response_class=HTMLResponse, name="report_view")
def report_view(request: Request, slug: str, run_date: str):
    try:
        client = _require_client(slug)
    except LookupError as exc:
        return redirect_with_flash(str(request.url_for("index")), str(exc), "error")

    xlsx_path = client.output_dir / f"gbp-audit_{run_date}.xlsx"
    html_path = client.output_dir / f"gbp-audit_{run_date}.html"
    if not xlsx_path.exists():
        return redirect_with_flash(
            str(request.url_for("client_detail", slug=slug)), f"Lauf '{run_date}' nicht gefunden.", "error"
        )

    return render(
        request,
        "report_view.html",
        slug=slug,
        run_date=run_date,
        has_dashboard=html_path.exists(),
        ampel_class=AMPEL_CLASS,
    )


@app.get("/clients/{slug}/runs/{run_date}/download", name="report_download_xlsx")
def report_download_xlsx(slug: str, run_date: str):
    client = get_client(slug)
    path = client.output_dir / f"gbp-audit_{run_date}.xlsx"
    if not path.exists():
        return HTMLResponse("Nicht gefunden", status_code=404)
    return FileResponse(path, filename=path.name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/clients/{slug}/runs/{run_date}/dashboard", name="report_dashboard_html")
def report_dashboard_html(slug: str, run_date: str):
    client = get_client(slug)
    path = client.output_dir / f"gbp-audit_{run_date}.html"
    if not path.exists():
        return HTMLResponse("Nicht gefunden", status_code=404)
    return FileResponse(path, media_type="text/html")


# --- Diff ---


@app.get("/clients/{slug}/diff", response_class=HTMLResponse, name="diff_form")
def diff_form(request: Request, slug: str, run1: Optional[str] = None, run2: Optional[str] = None):
    try:
        client = _require_client(slug)
    except LookupError as exc:
        return redirect_with_flash(str(request.url_for("index")), str(exc), "error")

    runs = client.list_runs()
    rows = None
    if run1 and run2:
        try:
            rows = perform_diff(client, client.load_config(), run1, run2)
        except FileNotFoundError:
            return redirect_with_flash(
                str(request.url_for("diff_form", slug=slug)), "Einer der Läufe wurde nicht gefunden.", "error"
            )

    return render(request, "diff_view.html", slug=slug, runs=runs, run1=run1, run2=run2, rows=rows)


# --- Modus B: OAuth-Web-Flow ---


@app.get("/clients/{slug}/auth/start", name="auth_start")
def auth_start(request: Request, slug: str):
    try:
        client = _require_client(slug)
    except LookupError as exc:
        return redirect_with_flash(str(request.url_for("index")), str(exc), "error")

    config = client.load_config()
    client_secret_file = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_FILE", "")
    redirect_uri = str(request.url_for("auth_callback", slug=slug))
    try:
        flow = build_web_oauth_flow(client_secret_file, config["gbp_api"]["oauth_scopes"], redirect_uri)
    except GbpApiError as exc:
        return redirect_with_flash(str(request.url_for("client_detail", slug=slug)), str(exc), "error")

    auth_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    _oauth_states[state] = slug
    return RedirectResponse(auth_url, status_code=303)


@app.get("/clients/{slug}/auth/callback", name="auth_callback")
def auth_callback(request: Request, slug: str, code: str, state: str):
    if _oauth_states.pop(state, None) != slug:
        return redirect_with_flash(
            str(request.url_for("client_detail", slug=slug)), "Ungültiger OAuth-Status (state mismatch).", "error"
        )

    try:
        client = _require_client(slug)
    except LookupError as exc:
        return redirect_with_flash(str(request.url_for("index")), str(exc), "error")

    config = client.load_config()
    client_secret_file = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_FILE", "")
    redirect_uri = str(request.url_for("auth_callback", slug=slug))
    try:
        flow = build_web_oauth_flow(client_secret_file, config["gbp_api"]["oauth_scopes"], redirect_uri)
        flow.fetch_token(code=code)
    except GbpApiError as exc:
        return redirect_with_flash(str(request.url_for("client_detail", slug=slug)), str(exc), "error")

    client.token_path.parent.mkdir(parents=True, exist_ok=True)
    client.token_path.write_text(flow.credentials.to_json(), encoding="utf-8")
    return redirect_with_flash(
        str(request.url_for("client_detail", slug=slug)),
        "Modus B (Full Audit) eingerichtet.",
        "success",
    )


def run_dev_server() -> None:
    import uvicorn

    uvicorn.run("src.webapp.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    run_dev_server()
