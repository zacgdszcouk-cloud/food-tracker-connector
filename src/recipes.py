"""Recipe matching: rank recipes by how many ingredients the user already has."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import db

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "recipes.json"

_recipes: list[dict] | None = None


def _load() -> list[dict]:
    global _recipes
    if _recipes is None:
        _recipes = json.loads(DATA_PATH.read_text())
    return _recipes


def _normalize(name: str) -> set[str]:
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    tokens = set()
    for tok in name.split():
        tok = tok.strip()
        if not tok or len(tok) < 3:
            continue
        # crude singularization
        if tok.endswith("ies"):
            tok = tok[:-3] + "y"
        elif tok.endswith("es") and len(tok) > 4:
            tok = tok[:-2]
        elif tok.endswith("s") and len(tok) > 3:
            tok = tok[:-1]
        tokens.add(tok)
    return tokens


def _have(ingredient: str, inventory_tokens: list[set[str]]) -> bool:
    ing = _normalize(ingredient)
    if not ing:
        return False
    for inv in inventory_tokens:
        if not inv:
            continue
        # match if every significant token of the ingredient appears in the item,
        # or vice versa (handles "cheddar cheese" vs "cheese")
        if ing <= inv or inv <= ing or ing & inv:
            # require at least one strong overlap; single-token overlap counts
            # only if the shared token is reasonably specific (len > 4)
            shared = ing & inv
            if ing <= inv or inv <= ing:
                return True
            if any(len(t) > 4 for t in shared):
                return True
    return False


def suggest(user_id: int, max_missing: int = 2, limit: int = 5) -> list[dict]:
    items = db.list_items(user_id)
    inventory_tokens = [_normalize(i["name"]) for i in items]
    scored = []
    for r in _load():
        ingredients = r["ingredients"]
        missing = [ing["name"] for ing in ingredients
                   if not _have(ing["name"], inventory_tokens)]
        if len(missing) <= max_missing:
            scored.append({
                "id": r["id"],
                "name": r["name"],
                "minutes": r["minutes"],
                "tags": r["tags"],
                "matched": len(ingredients) - len(missing),
                "total_ingredients": len(ingredients),
                "missing": missing,
            })
    scored.sort(key=lambda s: (len(s["missing"]), -s["matched"]))
    return scored[:limit]


def details(recipe_id: str) -> dict | None:
    for r in _load():
        if r["id"] == recipe_id:
            return r
    return None
