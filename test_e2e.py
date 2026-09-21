"""End-to-end test of the Food Tracker MCP server over streamable HTTP."""
import asyncio
import json
import os
import sys

# test talks to localhost directly; ignore any ambient proxy config
for _v in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
           "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_v, None)

sys.path.insert(0, "/home/hatch/workspace/food-tracker-connector")

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

import httpx


def _client_factory(headers=None, timeout=30, auth=None):
    return httpx.AsyncClient(
        headers=headers, timeout=timeout, auth=auth, trust_env=False
    )

from src import db

URL = "http://127.0.0.1:8000/mcp"


def call_text(result):
    assert result.content, "empty tool result"
    return result.content[0].text


async def _mcp_checks():
    _, key = db.create_user("e2e-test")
    headers = {"Authorization": f"Bearer {key}"}

    async with streamablehttp_client(URL, headers=headers,
                                       httpx_client_factory=_client_factory) as (read, write, _sid):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print("tools:", len(names))
            expected = {"add_item", "bulk_add_items", "list_inventory", "update_item",
                        "remove_item", "get_expiring_soon", "get_low_stock",
                        "suggest_recipes", "get_recipe_details",
                        "add_missing_ingredients_to_shopping", "add_shopping_item",
                        "list_shopping", "toggle_shopping_item", "remove_shopping_item",
                        "mark_shopping_item_bought"}
            assert expected <= set(names), f"missing: {expected - set(names)}"

            # 1. add items
            for args in [
                {"name": "whole milk", "quantity": 1, "unit": "litre", "location": "fridge",
                 "expiry_date": "2026-09-28", "low_stock_threshold": 0.5},
                {"name": "eggs", "quantity": 12, "unit": "pc", "location": "fridge",
                 "low_stock_threshold": 4},
                {"name": "chicken breast", "quantity": 2, "unit": "pc", "location": "fridge",
                 "expiry_date": "2026-09-23"},
                {"name": "rice", "quantity": 1, "unit": "kg", "location": "cupboard"},
                {"name": "soy sauce", "quantity": 1, "unit": "bottle", "location": "cupboard"},
                {"name": "bread", "quantity": 1, "unit": "loaf", "location": "cupboard",
                 "expiry_date": "2026-09-22"},
            ]:
                r = await session.call_tool("add_item", args)
                item = json.loads(call_text(r))
                assert item["name"] == args["name"], item
            print("add_item: OK (6 items)")

            # 2. bulk add with a duplicate (should merge milk)
            r = await session.call_tool("bulk_add_items", {"items": [
                {"name": "whole milk", "quantity": 1, "unit": "litre", "location": "fridge"},
                {"name": "cheddar cheese", "quantity": 200, "unit": "g", "location": "fridge"},
                {"name": "cola", "quantity": 6, "unit": "cans", "location": "drinks"},
            ]})
            res = json.loads(call_text(r))
            assert len(res["added"]) == 2, res
            assert len(res["merged"]) == 1 and res["merged"][0]["quantity"] == 2, res
            print("bulk_add_items: OK (2 added, 1 merged)")

            # 3. list + expiring + low stock
            r = await session.call_tool("list_inventory", {})
            items = json.loads(call_text(r))
            assert len(items) == 8, f"expected 8 items, got {len(items)}"
            r = await session.call_tool("get_expiring_soon", {"days": 7})
            exp = json.loads(call_text(r))
            assert any(i["name"] == "chicken breast" for i in exp), exp
            print(f"list_inventory: OK ({len(items)} items), expiring_soon: OK ({len(exp)} items)")

            # 4. recipes from inventory (have eggs, rice, soy sauce -> fried rice family)
            r = await session.call_tool("suggest_recipes", {"max_missing": 2, "limit": 5})
            recs = json.loads(call_text(r))
            assert recs, "no recipes suggested"
            print("suggest_recipes: OK ->", [x["name"] for x in recs])
            rid = recs[0]["id"]
            r = await session.call_tool("get_recipe_details", {"recipe_id": rid})
            det = json.loads(call_text(r))
            assert det["steps"], det
            print(f"get_recipe_details: OK ({det['name']}, {len(det['steps'])} steps)")

            # 5. missing ingredients -> shopping
            r = await session.call_tool("add_missing_ingredients_to_shopping", {"recipe_id": rid})
            res = json.loads(call_text(r))
            print(f"add_missing_ingredients_to_shopping: OK ({len(res['added_to_shopping'])} added)")

            # 6. shopping list ops
            r = await session.call_tool("add_shopping_item", {"name": "coffee", "quantity": 1, "unit": "bag"})
            shop_item = json.loads(call_text(r))
            r = await session.call_tool("list_shopping", {})
            shop = json.loads(call_text(r))
            assert len(shop) >= 1
            r = await session.call_tool("mark_shopping_item_bought",
                                        {"item_id": shop_item["id"], "location": "cupboard"})
            moved = json.loads(call_text(r))
            assert moved["name"] == "coffee" and moved["location"] == "cupboard", moved
            print("shopping list: OK (add/list/buy-move)")

            # 7. update + remove
            first_id = items[0]["id"]
            r = await session.call_tool("update_item", {"item_id": first_id, "quantity": 99})
            assert json.loads(call_text(r))["quantity"] == 99
            r = await session.call_tool("remove_item", {"item_id": first_id})
            assert json.loads(call_text(r))["removed"] is True
            print("update/remove: OK")

    print("\nALL E2E CHECKS PASSED")


BASE = "http://127.0.0.1:8000"


async def test_http_api():
    """Public pages, signup, key rotation, account deletion, auth, rate limits."""
    async with _client_factory() as c:
        # public pages
        r = await c.get(BASE + "/")
        assert r.status_code == 200 and "Food Tracker" in r.text, r.status_code
        r = await c.get(BASE + "/health")
        assert r.json()["status"] == "ok", r.text
        r = await c.get(BASE + "/privacy")
        assert r.status_code == 200 and "Privacy Policy" in r.text
        r = await c.get(BASE + "/terms")
        assert r.status_code == 200 and "Terms of Service" in r.text
        print("public pages (/, /health, /privacy, /terms): OK")

        # signup issues a working key
        r = await c.post(BASE + "/api/signup", json={"name": "http-test"})
        assert r.status_code == 200, r.text
        key = r.json()["api_key"]
        assert key.startswith("ft_")
        print("POST /api/signup: OK")

        # unauthenticated /mcp -> 401
        r = await c.post(BASE + "/mcp", json={})
        assert r.status_code == 401, r.status_code
        # bad key -> 401
        r = await c.post(BASE + "/mcp", json={}, headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401
        print("auth rejection on /mcp: OK")

        h = {"Authorization": f"Bearer {key}"}
        # authed account endpoints need the key
        r = await c.post(BASE + "/api/rotate-key")
        assert r.status_code == 401
        r = await c.post(BASE + "/api/rotate-key", headers=h)
        assert r.status_code == 200, r.text
        new_key = r.json()["api_key"]
        assert new_key != key
        # old key is dead
        r = await c.post(BASE + "/mcp", json={}, headers=h)
        assert r.status_code == 401, "old key should be revoked"
        h2 = {"Authorization": f"Bearer {new_key}"}
        print("POST /api/rotate-key: OK (old key revoked)")

        # delete account wipes the user
        r = await c.request("DELETE", BASE + "/api/account", headers=h2)
        assert r.status_code == 200 and r.json()["deleted"] is True
        r = await c.post(BASE + "/mcp", json={}, headers=h2)
        assert r.status_code == 401, "deleted user's key should stop working"
        print("DELETE /api/account: OK")

    print("\nALL HTTP API CHECKS PASSED")


async def main():
    await _mcp_checks()
    await test_http_api()


asyncio.run(main())
