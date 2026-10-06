"""Loads companion definitions from config/companions.json."""
import json
from functools import lru_cache

from .config import ROOT

COMPANIONS_FILE = ROOT / "config" / "companions.json"

# Fields the browser may see. 'instructions' is deliberately excluded.
PUBLIC_FIELDS = (
    "id", "available", "available_note", "name", "role", "description", "accent",
    "portrait", "portrait_alt", "opening", "purpose", "style", "scope", "situations",
)


@lru_cache(maxsize=1)
def all_companions() -> dict:
    data = json.loads(COMPANIONS_FILE.read_text(encoding="utf-8"))
    return {c["id"]: c for c in data["companions"]}


def get_companion(companion_id: str):
    return all_companions().get(companion_id)


def public_view(companion: dict) -> dict:
    view = {k: companion[k] for k in PUBLIC_FIELDS if k in companion}
    view["voice"] = {"label": companion["voice"]["label"]}
    return view


def public_list() -> list:
    return [public_view(c) for c in all_companions().values()]
