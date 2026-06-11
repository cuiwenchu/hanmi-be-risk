from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


def _default_root() -> Path:
    return Path(__file__).resolve().parent.parent


ROOT_DIR = Path(os.environ.get("PIPELINE58_HOME", "")).expanduser().resolve() if os.environ.get("PIPELINE58_HOME") else _default_root()
DATA_DIR = Path(os.environ.get("PIPELINE58_DATA_HOME", "")).expanduser().resolve() if os.environ.get("PIPELINE58_DATA_HOME") else (ROOT_DIR / "pipeline58_data")
LOG_DIR = Path(os.environ.get("PIPELINE58_LOG_HOME", "")).expanduser().resolve() if os.environ.get("PIPELINE58_LOG_HOME") else (DATA_DIR / "logs")
RUNS_DIR = DATA_DIR / "runs"
REPORTS_DIR = DATA_DIR / "reports"
AUTH_DIR = DATA_DIR / "auth"
TASKS_DIR = DATA_DIR / "tasks"
USERS_FILE = AUTH_DIR / "users.json"
SESSIONS_FILE = AUTH_DIR / "sessions.json"
AUTH_AUDIT_FILE = AUTH_DIR / "auth_audit.jsonl"
CONFIG_FILE = ROOT_DIR / "config" / "pipeline58_local.json"
PG_HOST = os.environ.get("PIPELINE58_PG_HOST", "").strip()
PG_PORT = int(os.environ.get("PIPELINE58_PG_PORT", "5432") or "5432")
PG_DB = os.environ.get("PIPELINE58_PG_DB", "").strip()
PG_USER = os.environ.get("PIPELINE58_PG_USER", "").strip()
PG_PASSWORD = os.environ.get("PIPELINE58_PG_PASSWORD", "")


@dataclass
class Pipeline58Settings:
    service_name: str
    service_version: str
    host: str
    port: int
    prefer_real_admet_model: bool
    prefer_real_pbpk_model: bool
    prefer_real_pkpd_model: bool
    rscript_bin: str
    default_species: str
    default_weight_kg: float
    default_micromolar_potency: float
    max_simulation_hours: int
    ddi_sources: Dict[str, str]


DEFAULT_SETTINGS: Dict[str, Any] = {
    "service_name": "hanmi-be-risk",
    "service_version": "2.0.0",
    "host": "0.0.0.0",
    "port": 8781,
    "prefer_real_admet_model": True,
    "prefer_real_pbpk_model": True,
    "prefer_real_pkpd_model": True,
    "rscript_bin": "Rscript",
    "default_species": "human",
    "default_weight_kg": 70.0,
    "default_micromolar_potency": 0.8,
    "max_simulation_hours": 72,
    "ddi_sources": {
        "drugbank": "https://go.drugbank.com",
        "stitch": "http://stitch.embl.de",
        "pubmed": "https://pubmed.ncbi.nlm.nih.gov",
    },
}


def ensure_data_dirs() -> None:
    for path in [DATA_DIR, LOG_DIR, RUNS_DIR, REPORTS_DIR, AUTH_DIR, TASKS_DIR, CONFIG_FILE.parent]:
        path.mkdir(parents=True, exist_ok=True)


def load_settings() -> Pipeline58Settings:
    ensure_data_dirs()
    payload = dict(DEFAULT_SETTINGS)
    if CONFIG_FILE.exists():
        try:
            payload.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig")))
        except Exception:
            pass
    else:
        CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return Pipeline58Settings(**payload)
