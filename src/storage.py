"""Mandantenverwaltung: Verzeichnisstruktur, Config-Merge, Persistenz von
Standorten und Rohdaten unter clients/<kunde>/.
"""
from __future__ import annotations

import copy
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

import yaml

from src.models import Location

REPO_ROOT = Path(__file__).resolve().parent.parent
GLOBAL_CONFIG_PATH = REPO_ROOT / "config.yaml"


def clients_dir() -> Path:
    override = os.environ.get("GBP_AUDIT_CLIENTS_DIR")
    return Path(override) if override else REPO_ROOT / "clients"


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^www\.", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def load_global_config() -> dict[str, Any]:
    with open(GLOBAL_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class ClientDirs:
    def __init__(self, slug: str):
        self.slug = slug
        self.root = clients_dir() / slug
        self.config_path = self.root / "config.yaml"
        self.locations_path = self.root / "locations.yaml"
        self.token_path = self.root / "token.json"
        self.runs_dir = self.root / "runs"
        self.output_dir = self.root / "output"

    def exists(self) -> bool:
        return self.root.exists()

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_date: Optional[str] = None) -> Path:
        run_date = run_date or date.today().isoformat()
        d = self.runs_dir / run_date
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list_runs(self) -> list[str]:
        if not self.runs_dir.exists():
            return []
        return sorted(p.name for p in self.runs_dir.iterdir() if p.is_dir())

    def load_config(self) -> dict[str, Any]:
        global_cfg = load_global_config()
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                client_cfg = yaml.safe_load(f) or {}
            return _deep_merge(global_cfg, client_cfg)
        return global_cfg

    def save_client_config(self, client_cfg: dict[str, Any]) -> None:
        self.ensure()
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(client_cfg, f, allow_unicode=True, sort_keys=False)

    def load_locations(self) -> list[Location]:
        if not self.locations_path.exists():
            return []
        with open(self.locations_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
        return [Location.from_dict(item) for item in data]

    def save_locations(self, locations: list[Location]) -> None:
        self.ensure()
        data = [loc.to_dict() for loc in locations]
        with open(self.locations_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    def save_run_json(self, run_date: str, filename: str, data: Any) -> Path:
        path = self.run_dir(run_date) / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        return path

    def load_run_json(self, run_date: str, filename: str) -> Any:
        path = self.runs_dir / run_date / filename
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)


def list_clients() -> list[str]:
    base = clients_dir()
    if not base.exists():
        return []
    return sorted(
        p.name
        for p in base.iterdir()
        if p.is_dir() and ((p / "locations.yaml").exists() or (p / "config.yaml").exists())
    )


def get_client(slug_or_url: str) -> ClientDirs:
    slug = slugify(slug_or_url)
    return ClientDirs(slug)
