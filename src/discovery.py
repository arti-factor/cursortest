"""Standort-Discovery: Crawlt die Website eines Kunden und extrahiert NAP-Daten
(Name, Adresse, Telefon) je Standort.

Die Extraktion ist bewusst als reine, netzwerkfreie Funktion `extract_locations_from_html`
implementiert, damit sie sich isoliert mit HTML-Fixtures testen lässt. Das Crawlen
(HTTP, robots.txt, Sitemap, Linkfolgen) ist in `WebsiteCrawler` gekapselt.
"""
from __future__ import annotations

import re
import urllib.robotparser
from dataclasses import dataclass
from typing import Any, Iterable, Optional
from urllib.parse import urljoin, urlparse

import extruct
import httpx
from selectolax.parser import HTMLParser
from w3lib.html import get_base_url

from src.models import Location

# --- Heuristische Muster für deutsche Adressen/Telefonnummern ---

# "Musterstraße 12" oder "Musterstr. 12a" etc.
_STREET_RE = re.compile(
    r"(?P<street>[A-ZÄÖÜ][a-zäöüß\.\-]+(?:straße|strasse|str\.|weg|allee|platz|gasse|ring)\s?"
    r"\d+[a-zA-Z]?(?:\s*[-/]\s*\d+[a-zA-Z]?)?)",
    re.IGNORECASE,
)
# 5-stellige PLZ + Ort (deutsches Format). Die Stadt darf nicht über Zeilenumbrüche
# hinausreichen, daher [ \t] statt \s als Wort-Trenner innerhalb des Städtenamens.
_PLZ_ORT_RE = re.compile(
    r"(?P<zip>\b\d{5}\b)[ \t]+"
    r"(?P<city>[A-ZÄÖÜ][a-zA-ZäöüÄÖÜß\-]*(?:[ \t]+[A-ZÄÖÜ][a-zA-Zäöüß\-]*){0,2})"
)
# Telefonnummern: großzügig, deckt +49, 0-Vorwahl, Trennzeichen ab
_PHONE_RE = re.compile(
    r"(?:Tel\.?:?|Telefon:?|Fon:?)?\s*"
    r"(?P<phone>(?:\+49[\s\-/]?|0)\(?\d{2,5}\)?[\s\-/]?\d{3,}[\s\-/]?\d{0,10})",
    re.IGNORECASE,
)


@dataclass
class CrawlConfig:
    max_crawl_depth: int = 2
    max_pages: int = 60
    request_timeout_seconds: float = 15.0
    user_agent: str = "gbp-audit-bot/0.1"
    respect_robots_txt: bool = True
    candidate_paths: list[str] = None
    anchor_keywords: list[str] = None

    def __post_init__(self):
        if self.candidate_paths is None:
            self.candidate_paths = ["/kontakt", "/impressum", "/standorte", "/filialen"]
        if self.anchor_keywords is None:
            self.anchor_keywords = ["kontakt", "impressum", "standort", "filiale"]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CrawlConfig":
        return cls(
            max_crawl_depth=d.get("max_crawl_depth", 2),
            max_pages=d.get("max_pages", 60),
            request_timeout_seconds=d.get("request_timeout_seconds", 15.0),
            user_agent=d.get("user_agent", "gbp-audit-bot/0.1"),
            respect_robots_txt=d.get("respect_robots_txt", True),
            candidate_paths=d.get("candidate_paths"),
            anchor_keywords=d.get("anchor_keywords"),
        )


def _make_slug(name: str, zip_code: str) -> str:
    base = f"{name}-{zip_code}".lower()
    base = re.sub(r"[^a-z0-9]+", "-", base)
    return base.strip("-") or "standort"


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _normalize_phone(raw: str) -> str:
    return re.sub(r"[\s\-/()]", "", raw or "")


# --- JSON-LD / Mikrodaten Extraktion ---

_LOCAL_BUSINESS_TYPES = {
    "LocalBusiness",
    "Organization",
    "Store",
    "Restaurant",
    "MedicalBusiness",
    "ProfessionalService",
    "Dentist",
    "AutoRepair",
}


def _address_from_jsonld(addr: Any) -> tuple[str, str, str]:
    if isinstance(addr, dict):
        street = _clean_text(addr.get("streetAddress", ""))
        zip_code = _clean_text(str(addr.get("postalCode", "")))
        city = _clean_text(addr.get("addressLocality", ""))
        return street, zip_code, city
    if isinstance(addr, str):
        m = _PLZ_ORT_RE.search(addr)
        zip_code, city = (m.group("zip"), _clean_text(m.group("city"))) if m else ("", "")
        sm = _STREET_RE.search(addr)
        street = _clean_text(sm.group("street")) if sm else ""
        return street, zip_code, city
    return "", "", ""


def _phone_from_jsonld(node: dict[str, Any]) -> str:
    return _clean_text(str(node.get("telephone", "")))


def _iter_jsonld_business_nodes(item: Any) -> Iterable[dict[str, Any]]:
    if isinstance(item, dict):
        node_type = item.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if any(t in _LOCAL_BUSINESS_TYPES for t in types if t):
            yield item
        # verschachtelte Standorte, z.B. Organization.department oder @graph
        for key in ("department", "@graph", "subOrganization", "location"):
            nested = item.get(key)
            if isinstance(nested, list):
                for n in nested:
                    yield from _iter_jsonld_business_nodes(n)
            elif isinstance(nested, dict):
                yield from _iter_jsonld_business_nodes(nested)
    elif isinstance(item, list):
        for n in item:
            yield from _iter_jsonld_business_nodes(n)


def extract_json_ld_locations(html: str, url: str) -> list[Location]:
    base_url = get_base_url(html.encode("utf-8"), url)
    data = extruct.extract(html, base_url=base_url, syntaxes=["json-ld"], errors="ignore")
    locations: list[Location] = []
    for item in data.get("json-ld", []):
        for node in _iter_jsonld_business_nodes(item):
            name = _clean_text(node.get("name", ""))
            if not name:
                continue
            street, zip_code, city = _address_from_jsonld(node.get("address"))
            phone = _phone_from_jsonld(node)
            website = _clean_text(node.get("url", "")) or url
            locations.append(
                Location(
                    id=_make_slug(name, zip_code),
                    name=name,
                    street=street,
                    zip=zip_code,
                    city=city,
                    phone=phone,
                    website=website,
                    source_url=url,
                    extraction_method="json_ld",
                )
            )
    return locations


def extract_microdata_locations(html: str, url: str) -> list[Location]:
    base_url = get_base_url(html.encode("utf-8"), url)
    data = extruct.extract(html, base_url=base_url, syntaxes=["microdata", "rdfa"], errors="ignore")
    locations: list[Location] = []
    for syntax in ("microdata", "rdfa"):
        for item in data.get(syntax, []):
            item_type = item.get("type", "") or ""
            if not any(t in item_type for t in _LOCAL_BUSINESS_TYPES):
                continue
            props = item.get("properties", {}) or {}
            name = _clean_text(_first(props.get("name")))
            if not name:
                continue
            addr = props.get("address")
            if isinstance(addr, list) and addr:
                addr = addr[0]
            addr_props = addr.get("properties", {}) if isinstance(addr, dict) else {}
            street = _clean_text(_first(addr_props.get("streetAddress")))
            zip_code = _clean_text(_first(addr_props.get("postalCode")))
            city = _clean_text(_first(addr_props.get("addressLocality")))
            phone = _clean_text(_first(props.get("telephone")))
            locations.append(
                Location(
                    id=_make_slug(name, zip_code),
                    name=name,
                    street=street,
                    zip=zip_code,
                    city=city,
                    phone=phone,
                    website=url,
                    source_url=url,
                    extraction_method="microdata",
                )
            )
    return locations


def _first(value: Any) -> str:
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


# --- Heuristische HTML-Extraktion (Fallback) ---


def extract_heuristic_locations(html: str, url: str) -> list[Location]:
    tree = HTMLParser(html)
    for tag in tree.css("script, style, nav, footer[aria-hidden]"):
        tag.decompose()
    raw_text = tree.body.text(separator="\n") if tree.body else tree.root.text(separator="\n")
    # Zeilenumbrüche bewusst erhalten (statt zu einer Zeile zu kollabieren), damit
    # PLZ/Ort-Erkennung nicht versehentlich in die nächste Zeile "durchrutscht".
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw_text.split("\n")]
    text = "\n".join(line for line in lines if line)

    tel_links = [
        _normalize_phone(node.attributes.get("href", "").replace("tel:", ""))
        for node in tree.css("a[href^='tel:']")
    ]

    locations: list[Location] = []
    zip_matches = list(_PLZ_ORT_RE.finditer(text))
    if not zip_matches:
        return locations

    for m in zip_matches:
        zip_code, city = m.group("zip"), _clean_text(m.group("city"))
        window_start = max(0, m.start() - 120)
        window = text[window_start : m.end() + 40]
        street_match = _STREET_RE.search(window)
        street = _clean_text(street_match.group("street")) if street_match else ""

        phone = ""
        phone_match = _PHONE_RE.search(window)
        if phone_match:
            phone = _normalize_phone(phone_match.group("phone"))
        elif tel_links:
            phone = tel_links[0]

        title_node = tree.css_first("h1") or tree.css_first("title")
        name = _clean_text(title_node.text()) if title_node else city or "Standort"

        locations.append(
            Location(
                id=_make_slug(name, zip_code),
                name=name,
                street=street,
                zip=zip_code,
                city=city,
                phone=phone,
                website=url,
                source_url=url,
                extraction_method="heuristik",
            )
        )
    return locations


def extract_locations_from_html(html: str, url: str) -> list[Location]:
    """Extrahiert Standorte nach Prioritätsreihenfolge JSON-LD > Mikrodaten/RDFa > Heuristik.

    Liefert die Ergebnisse der ersten Methode, die etwas findet - eine Seite
    mit sauberem JSON-LD-Markup wird nicht zusätzlich heuristisch durchsucht,
    um Duplikate/Rauschen zu vermeiden.
    """
    locations = extract_json_ld_locations(html, url)
    if locations:
        return locations
    locations = extract_microdata_locations(html, url)
    if locations:
        return locations
    return extract_heuristic_locations(html, url)


def dedupe_locations(locations: Iterable[Location]) -> list[Location]:
    """Führt Standorte über mehrere Seiten hinweg anhand von PLZ+Namensähnlichkeit zusammen."""
    from rapidfuzz import fuzz

    result: list[Location] = []
    for loc in locations:
        match = None
        for existing in result:
            if existing.zip and existing.zip == loc.zip:
                if fuzz.token_sort_ratio(existing.name.lower(), loc.name.lower()) >= 85:
                    match = existing
                    break
            elif not existing.zip and not loc.zip and existing.name.lower() == loc.name.lower():
                match = existing
                break
        if match:
            # fehlende Felder aus dem neuen Fund ergänzen, ohne Bestehendes zu überschreiben
            for field_name in ("street", "zip", "city", "phone"):
                if not getattr(match, field_name) and getattr(loc, field_name):
                    setattr(match, field_name, getattr(loc, field_name))
        else:
            result.append(loc)
    return result


# --- Crawling (Netzwerk) ---


class WebsiteCrawler:
    def __init__(self, base_url: str, config: CrawlConfig):
        if not base_url.startswith("http"):
            base_url = f"https://{base_url}"
        self.base_url = base_url.rstrip("/")
        self.domain = urlparse(self.base_url).netloc
        self.config = config
        self._robot_parser: Optional[urllib.robotparser.RobotFileParser] = None

    def _load_robots(self, client: httpx.Client) -> None:
        if not self.config.respect_robots_txt:
            return
        rp = urllib.robotparser.RobotFileParser()
        try:
            resp = client.get(urljoin(self.base_url + "/", "robots.txt"))
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp.allow_all = True
        except httpx.HTTPError:
            rp.allow_all = True
        self._robot_parser = rp

    def _can_fetch(self, url: str) -> bool:
        if not self.config.respect_robots_txt or self._robot_parser is None:
            return True
        return self._robot_parser.can_fetch(self.config.user_agent, url)

    def _sitemap_urls(self, client: httpx.Client) -> list[str]:
        urls: list[str] = []
        for sitemap_path in ("/sitemap.xml", "/sitemap_index.xml"):
            try:
                resp = client.get(urljoin(self.base_url + "/", sitemap_path))
            except httpx.HTTPError:
                continue
            if resp.status_code != 200:
                continue
            locs = re.findall(r"<loc>(.*?)</loc>", resp.text)
            urls.extend(locs)
        return urls

    def _is_candidate(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return any(cp.rstrip("/") in path for cp in self.config.candidate_paths)

    def _anchor_is_candidate(self, anchor_text: str, href: str) -> bool:
        text = (anchor_text or "").lower()
        href = (href or "").lower()
        return any(kw in text or kw in href for kw in self.config.anchor_keywords)

    def discover_urls(self, client: httpx.Client) -> list[str]:
        self._load_robots(client)
        seen: set[str] = set()
        queue: list[str] = [self.base_url + "/"]
        candidates: list[str] = []

        for path in self.config.candidate_paths:
            queue.append(urljoin(self.base_url + "/", path.lstrip("/")))

        for sitemap_url in self._sitemap_urls(client):
            if urlparse(sitemap_url).netloc == self.domain:
                if self._is_candidate(sitemap_url):
                    candidates.append(sitemap_url)
                else:
                    queue.append(sitemap_url)

        depth = 0
        frontier = queue
        while frontier and depth <= self.config.max_crawl_depth and len(seen) < self.config.max_pages:
            next_frontier: list[str] = []
            for url in frontier:
                if url in seen or len(seen) >= self.config.max_pages:
                    continue
                if urlparse(url).netloc not in (self.domain, ""):
                    continue
                if not self._can_fetch(url):
                    continue
                seen.add(url)
                if self._is_candidate(url):
                    candidates.append(url)
                    continue
                try:
                    resp = client.get(url)
                except httpx.HTTPError:
                    continue
                if resp.status_code != 200 or "text/html" not in resp.headers.get("content-type", ""):
                    continue
                if depth < self.config.max_crawl_depth:
                    tree = HTMLParser(resp.text)
                    for a in tree.css("a[href]"):
                        href = a.attributes.get("href") or ""
                        abs_url = urljoin(url, href).split("#")[0]
                        if abs_url not in seen and self._anchor_is_candidate(a.text(), href):
                            next_frontier.append(abs_url)
            frontier = next_frontier
            depth += 1

        # dedupe, Kandidaten zuerst
        ordered = list(dict.fromkeys(candidates + [self.base_url + "/"]))
        return ordered[: self.config.max_pages]

    def crawl(self) -> list[Location]:
        all_locations: list[Location] = []
        with httpx.Client(
            headers={"User-Agent": self.config.user_agent},
            timeout=self.config.request_timeout_seconds,
            follow_redirects=True,
        ) as client:
            urls = self.discover_urls(client)
            for url in urls:
                if not self._can_fetch(url):
                    continue
                try:
                    resp = client.get(url)
                except httpx.HTTPError:
                    continue
                if resp.status_code != 200:
                    continue
                all_locations.extend(extract_locations_from_html(resp.text, url))
        return dedupe_locations(all_locations)


def discover_locations(base_url_or_page: str, config: CrawlConfig) -> list[Location]:
    """Haupteinstiegspunkt: erkennt automatisch, ob eine Domain oder eine direkte Seite übergeben wurde."""
    parsed = urlparse(base_url_or_page if "://" in base_url_or_page else f"https://{base_url_or_page}")
    if parsed.path and parsed.path not in ("", "/"):
        # direkte URL einer Kontakt-/Standortseite: nur diese Seite abrufen, kein Crawl nötig
        with httpx.Client(
            headers={"User-Agent": config.user_agent},
            timeout=config.request_timeout_seconds,
            follow_redirects=True,
        ) as client:
            resp = client.get(base_url_or_page if "://" in base_url_or_page else f"https://{base_url_or_page}")
            resp.raise_for_status()
            return dedupe_locations(extract_locations_from_html(resp.text, str(resp.url)))
    crawler = WebsiteCrawler(base_url_or_page, config)
    return crawler.crawl()
