# Food Tracker Connector

A public connector backend for Meta Muse: a personal food-and-drink inventory
exposed as MCP tools over streamable HTTP. Any Muse user can point their agent
at it; submitted to Meta's connector directory it becomes one-tap installable.

**What it does**

- Tracks items across fridge, freezer, cupboard, and drinks, with quantities,
  expiry dates, and low-stock thresholds
- Bulk-adds from receipts or order confirmations (duplicates merge by quantity)
- Flags what's expiring soon and what's running low
- Suggests recipes from a 60-recipe database, ranked by ingredients on hand,
  and can push missing ingredients to the shopping list
- Keeps a shopping list; marking something bought moves it into inventory

Photo analysis happens in the agent: the user shows Muse a fridge photo, Muse
reads it and calls `add_item` / `bulk_add_items` with structured data. No
vision code needed server-side.

## Quickstart (local)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# issue an API key for a user (keys are the auth; keep them secret)
.venv/bin/python -m src.server create-key --name "zac"
# -> prints: user_id + api_key

# run
.venv/bin/python -m uvicorn src.server:app --host 0.0.0.0 --port 8000
```

- MCP endpoint: `POST/GET http://localhost:8000/mcp`
- Health: `GET http://localhost:8000/health`
- Landing page + self-serve signup: `GET http://localhost:8000/`
- Privacy policy: `GET http://localhost:8000/privacy` - Terms: `GET http://localhost:8000/terms`
- Auth: `Authorization: Bearer <api_key>` on `/mcp`, `/api/rotate-key`, `/api/account` (401 otherwise)
- Public, rate-limited API:
  - `POST /api/signup` -> `{user_id, api_key}` (key shown once; 10/hour per IP)
  - `POST /api/rotate-key` (Bearer) -> revokes the presented key, issues a new one
  - `DELETE /api/account` (Bearer) -> deletes the user and all their data
- Data: SQLite at `./food_tracker.db` (override with `FOOD_TRACKER_DB`)
- Config env vars: `PUBLIC_ORIGIN` (canonical https URL shown on the landing
  page), `SUPPORT_EMAIL` (shown on landing/privacy/terms pages)

## Connect it to Muse today (no directory listing needed)

Muse supports custom connectors to any hosted MCP server. Once this is
deployed at a public URL, say to Muse:

> Build a custom integration to my Food Tracker MCP server at
> https://your-host/mcp. It is a remote MCP server over streamable HTTP.
> Authenticate with `Authorization: Bearer <your-api-key>`. Connect to it,
> test every tool end to end, and save the integration as a reusable skill.

Muse will write the client, verify all 15 tools, and remember it.

## Deploy

The repo ships a `Dockerfile` plus configs for common hosts. SQLite lives on a
persistent volume (`/data`) so inventory survives restarts.

**Fly.io**

```bash
fly launch        # accepts fly.toml
fly volumes create food_tracker_data --size 1
fly deploy
```

**Render**: new Web Service -> point at this repo (uses `render.yaml`).

**Railway**: new project from repo; Railway auto-detects the Dockerfile. Add a
volume mounted at `/data`.

After deploy, issue keys with `create-key` (run it via the host's console or
against the same database file) and hand each user their key.

## Tools (15)

Inventory: `add_item`, `bulk_add_items`, `list_inventory`, `update_item`,
`remove_item`, `get_expiring_soon`, `get_low_stock`

Recipes: `suggest_recipes`, `get_recipe_details`,
`add_missing_ingredients_to_shopping`

Shopping: `add_shopping_item`, `list_shopping`, `toggle_shopping_item`,
`remove_shopping_item`, `mark_shopping_item_bought`

## Security notes

- API keys are stored as SHA-256 hashes; plaintext is shown once at creation.
- Every user is isolated by user id; tools can only touch the caller's rows.
- Rate limiting per IP: 10 signups/hour, 60 authed API calls/min, 600 MCP calls/min.
- Input validation: locations whitelisted, quantities non-negative, text
  fields length-capped, expiry dates format-checked.
- Users can rotate their key (`POST /api/rotate-key`) and delete their account
  and all data (`DELETE /api/account`) at any time.
- The server never sees anything but the Bearer key and the tool payloads.
- For a production directory listing, per-user OAuth (instead of API keys) is
  the expected upgrade; see SUBMISSION.md.

## Tests

```bash
.venv/bin/python test_e2e.py   # spins up a client against localhost:8000
```

Covers all 15 tools, duplicate merging, auth rejection (401s), recipe ranking,
and the shopping-to-inventory flow.
