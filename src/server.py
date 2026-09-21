"""Food Tracker MCP server (streamable HTTP).

Exposes a personal food-and-drink inventory as MCP tools so any MCP-capable
agent (including Meta Muse via a custom connector) can:

- track items across fridge / freezer / cupboard / drinks, with expiry dates
- flag expiring and low-stock items
- suggest recipes from what the user already has
- keep a shopping list

Auth: callers pass a per-user API key as `Authorization: Bearer <key>`.
Get a key at POST /api/signup (public, rate-limited) or issue one with:
  python server.py create-key --name "someone"
Rotate a key at POST /api/rotate-key, delete everything at DELETE /api/account.

Run:  uvicorn server:app --host 0.0.0.0 --port 8000
The MCP endpoint is POST/GET http://host:8000/mcp
Landing page at http://host:8000/ ; privacy at /privacy ; terms at /terms.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Annotated

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from . import db
from . import recipes as recipe_engine
from . import web

mcp = FastMCP("Food Tracker")


# ---------- helpers ----------

def _user_id(ctx: Context) -> int:
    req = ctx.request_context.request
    uid = getattr(req.state, "user_id", None)
    if uid is None:
        raise RuntimeError("Missing authenticated user (no Bearer API key).")
    return uid


def _ok(data) -> str:
    import json
    return json.dumps(data, default=str)


# ---------- inventory tools ----------

@mcp.tool()
async def add_item(
    ctx: Context,
    name: Annotated[str, Field(description="Item name, e.g. 'whole milk'")],
    quantity: Annotated[float, Field(description="Amount", ge=0)] = 1,
    unit: Annotated[str, Field(description="Unit, e.g. pc, ml, g, cans, loaves")] = "pc",
    location: Annotated[str, Field(description="One of: fridge, freezer, cupboard, drinks")] = "fridge",
    expiry_date: Annotated[str | None, Field(description="Expiry as YYYY-MM-DD, if known")] = None,
    low_stock_threshold: Annotated[float | None, Field(description="Warn when quantity falls to this or below")] = None,
    notes: Annotated[str, Field(description="Optional notes")] = "",
) -> str:
    """Add one food or drink item to the user's inventory."""
    try:
        item = db.add_item(_user_id(ctx), name, quantity, unit, location,
                           expiry_date, low_stock_threshold, notes)
    except ValueError as e:
        return f"Error: {e}"
    return _ok(item)


@mcp.tool()
async def bulk_add_items(
    ctx: Context,
    items: Annotated[list[dict], Field(description=(
        "List of {name, quantity?, unit?, location?, expiry_date?, notes?}. "
        "Use for receipts or order confirmations. Duplicates merge by quantity."
    ))],
) -> str:
    """Add many items at once, e.g. parsed from a grocery receipt or order.
    Items with the same name and location merge instead of duplicating."""
    try:
        result = db.bulk_add_items(_user_id(ctx), items)
    except ValueError as e:
        return f"Error: {e}"
    return _ok(result)


@mcp.tool()
async def list_inventory(
    ctx: Context,
    location: Annotated[str | None, Field(description="Filter: fridge, freezer, cupboard, drinks")] = None,
    search: Annotated[str | None, Field(description="Filter by name substring")] = None,
) -> str:
    """List inventory items, with days-until-expiry and low-stock flags."""
    try:
        items = db.list_items(_user_id(ctx), location, search)
    except ValueError as e:
        return f"Error: {e}"
    return _ok(items)


@mcp.tool()
async def update_item(
    ctx: Context,
    item_id: Annotated[int, Field(description="Inventory item id")],
    name: Annotated[str | None, Field(description="New name")] = None,
    quantity: Annotated[float | None, Field(description="New quantity")] = None,
    unit: Annotated[str | None, Field(description="New unit")] = None,
    location: Annotated[str | None, Field(description="fridge, freezer, cupboard, drinks")] = None,
    expiry_date: Annotated[str | None, Field(description="New expiry YYYY-MM-DD")] = None,
    low_stock_threshold: Annotated[float | None, Field(description="New threshold")] = None,
    notes: Annotated[str | None, Field(description="New notes")] = None,
) -> str:
    """Update an inventory item. Only the fields you pass are changed."""
    try:
        item = db.update_item(_user_id(ctx), item_id, name=name, quantity=quantity,
                              unit=unit, location=location, expiry_date=expiry_date,
                              low_stock_threshold=low_stock_threshold, notes=notes)
    except ValueError as e:
        return f"Error: {e}"
    if item is None:
        return "Error: item not found."
    return _ok(item)


@mcp.tool()
async def remove_item(
    ctx: Context,
    item_id: Annotated[int, Field(description="Inventory item id")],
) -> str:
    """Remove an item from inventory (used up, thrown away)."""
    ok = db.remove_item(_user_id(ctx), item_id)
    return _ok({"removed": ok})


@mcp.tool()
async def get_expiring_soon(
    ctx: Context,
    days: Annotated[int, Field(description="Lookahead window in days", ge=1)] = 7,
) -> str:
    """Items expiring within the next N days, soonest first."""
    items = [i for i in db.list_items(_user_id(ctx))
             if i["days_until_expiry"] is not None and 0 <= i["days_until_expiry"] <= days]
    items.sort(key=lambda i: i["days_until_expiry"])
    return _ok(items)


@mcp.tool()
async def get_low_stock(ctx: Context) -> str:
    """Items at or below their low-stock threshold."""
    items = [i for i in db.list_items(_user_id(ctx)) if i["is_low_stock"]]
    return _ok(items)


# ---------- recipes ----------

@mcp.tool()
async def suggest_recipes(
    ctx: Context,
    max_missing: Annotated[int, Field(description="Max ingredients the user may lack", ge=0)] = 2,
    limit: Annotated[int, Field(description="Max recipes to return", ge=1, le=20)] = 5,
) -> str:
    """Suggest recipes ranked by how many ingredients the user already has.
    Each suggestion lists which ingredients are missing."""
    return _ok(recipe_engine.suggest(_user_id(ctx), max_missing, limit))


@mcp.tool()
async def get_recipe_details(
    ctx: Context,
    recipe_id: Annotated[str, Field(description="Recipe id from suggest_recipes")],
) -> str:
    """Full ingredients, quantities and steps for one recipe."""
    r = recipe_engine.details(recipe_id)
    if r is None:
        return "Error: recipe not found."
    return _ok(r)


@mcp.tool()
async def add_missing_ingredients_to_shopping(
    ctx: Context,
    recipe_id: Annotated[str, Field(description="Recipe id from suggest_recipes")],
) -> str:
    """Add a recipe's missing ingredients to the shopping list. Skips any the
    user already has in inventory."""
    r = recipe_engine.details(recipe_id)
    if r is None:
        return "Error: recipe not found."
    uid = _user_id(ctx)
    inv_names = {i["name"].lower() for i in db.list_items(uid)}
    added = []
    for ing in r["ingredients"]:
        if ing["name"].lower() not in inv_names:
            added.append(db.add_shopping_item(uid, ing["name"], 1, "pc"))
    return _ok({"recipe": r["name"], "added_to_shopping": added})


# ---------- shopping list ----------

@mcp.tool()
async def add_shopping_item(
    ctx: Context,
    name: Annotated[str, Field(description="Item name")],
    quantity: Annotated[float, Field(description="Amount", ge=0)] = 1,
    unit: Annotated[str, Field(description="Unit")] = "pc",
) -> str:
    """Add an item to the shopping list."""
    try:
        return _ok(db.add_shopping_item(_user_id(ctx), name, quantity, unit))
    except ValueError as e:
        return f"Error: {e}"


@mcp.tool()
async def list_shopping(
    ctx: Context,
    include_checked: Annotated[bool, Field(description="Include checked-off items")] = True,
) -> str:
    """Show the shopping list."""
    return _ok(db.list_shopping(_user_id(ctx), include_checked))


@mcp.tool()
async def toggle_shopping_item(
    ctx: Context,
    item_id: Annotated[int, Field(description="Shopping item id")],
    checked: Annotated[bool | None, Field(description="Set checked state; omit to flip")] = None,
) -> str:
    """Check or uncheck a shopping list item."""
    item = db.toggle_shopping_item(_user_id(ctx), item_id, checked)
    if item is None:
        return "Error: item not found."
    return _ok(item)


@mcp.tool()
async def remove_shopping_item(
    ctx: Context,
    item_id: Annotated[int, Field(description="Shopping item id")],
) -> str:
    """Remove an item from the shopping list."""
    ok = db.remove_shopping_item(_user_id(ctx), item_id)
    return _ok({"removed": ok})


@mcp.tool()
async def mark_shopping_item_bought(
    ctx: Context,
    item_id: Annotated[int, Field(description="Shopping item id")],
    location: Annotated[str, Field(description="Where to store it: fridge, freezer, cupboard, drinks")] = "fridge",
    expiry_date: Annotated[str | None, Field(description="Expiry as YYYY-MM-DD, if known")] = None,
) -> str:
    """Mark a shopping item as bought: moves it into inventory."""
    try:
        item = db.move_shopping_to_inventory(_user_id(ctx), item_id, location, expiry_date)
    except ValueError as e:
        return f"Error: {e}"
    if item is None:
        return "Error: item not found."
    return _ok(item)


# ---------- HTTP app: rate limiting, auth, public API ----------

# (path prefix, max requests, window seconds)
RATE_LIMITS = [
    ("/api/signup", 10, 3600),   # 10 signups/hour per IP
    ("/api/", 60, 60),           # 60 authed API calls/min per IP
    ("/mcp", 600, 60),           # 600 MCP calls/min per IP
]

_rate_buckets: dict[tuple[str, str], tuple[float, int]] = {}
_rate_lock = threading.Lock()


def _client_ip(request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(request):
    path = request.url.path
    rule = next((r for r in RATE_LIMITS if path.startswith(r[0])), None)
    if rule is None:
        return None
    prefix, limit, window = rule
    key = (prefix, _client_ip(request))
    now = time.monotonic()
    with _rate_lock:
        start, count = _rate_buckets.get(key, (now, 0))
        if now - start >= window:
            start, count = now, 0
        count += 1
        _rate_buckets[key] = (start, count)
        if count > limit:
            return JSONResponse(
                {"error": "Rate limit exceeded. Please slow down and try again."},
                status_code=429,
            )
    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        limited = _rate_limited(request)
        if limited is not None:
            return limited
        return await call_next(request)


# Paths that need a Bearer API key. Everything else public.
AUTH_REQUIRED = ("/mcp", "/api/rotate-key", "/api/account")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith(AUTH_REQUIRED):
            auth = request.headers.get("authorization", "")
            parts = auth.split()
            if len(parts) != 2 or parts[0].lower() != "bearer":
                return JSONResponse(
                    {"error": "Provide your Food Tracker API key as 'Authorization: Bearer <key>'."},
                    status_code=401,
                )
            user_id = db.get_user_for_key(parts[1])
            if user_id is None:
                return JSONResponse({"error": "Invalid API key."}, status_code=401)
            request.state.user_id = user_id
        return await call_next(request)


async def _health(request):
    return JSONResponse({"status": "ok", "service": "food-tracker", "mcp_endpoint": "/mcp"})


async def _landing(request):
    origin = os.environ.get("PUBLIC_ORIGIN", str(request.base_url)).rstrip("/")
    return HTMLResponse(web.landing_page(origin))


async def _privacy(request):
    return HTMLResponse(web.privacy_page())


async def _terms(request):
    return HTMLResponse(web.terms_page())


async def _signup(request):
    """Public self-serve signup: create a user and issue an API key (shown once)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    name = str((body or {}).get("name", ""))[:80]
    user_id, key = db.create_user(name)
    return JSONResponse({
        "user_id": user_id,
        "api_key": key,
        "mcp_endpoint": "/mcp",
        "warning": "This key is shown once. Save it now; anyone with it can read and change your inventory.",
    })


async def _rotate_key(request):
    """Revoke the presented key and issue a fresh one for the same user."""
    parts = request.headers.get("authorization", "").split()
    presented = parts[1] if len(parts) == 2 else ""
    try:
        new_key = db.rotate_key(request.state.user_id, presented)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({
        "api_key": new_key,
        "warning": "Your old key is revoked. Save the new key now.",
    })


async def _delete_account(request):
    """Delete the user and all of their data permanently."""
    db.delete_user(request.state.user_id)
    return JSONResponse({"deleted": True})


# The streamable_http_app() already exposes the MCP endpoint at /mcp, so we
# add middleware and extra routes to it directly instead of re-mounting.
app = mcp.streamable_http_app()
app.add_middleware(RateLimitMiddleware)
app.add_middleware(BearerAuthMiddleware)
app.routes.append(Route("/health", _health))
app.routes.append(Route("/", _landing))
app.routes.append(Route("/privacy", _privacy))
app.routes.append(Route("/terms", _terms))
app.routes.append(Route("/api/signup", _signup, methods=["POST"]))
app.routes.append(Route("/api/rotate-key", _rotate_key, methods=["POST"]))
app.routes.append(Route("/api/account", _delete_account, methods=["DELETE"]))


def _cli_create_key(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--name", default="", help="Label for the key, e.g. a username")
    args = p.parse_args(argv)
    user_id, key = db.create_user(args.name)
    print(f"user_id: {user_id}")
    print(f"api_key: {key}")
    print("Keep this key secret. Pass it as:  Authorization: Bearer <key>")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "create-key":
        sys.exit(_cli_create_key(sys.argv[2:]))
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(__import__("os").environ.get("PORT", "8000")))
