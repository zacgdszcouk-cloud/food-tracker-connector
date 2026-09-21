"""SQLite storage layer for the Food Tracker connector.

One database holds every user, isolated by user id. API keys map to users;
keys are stored as SHA-256 hashes, never plaintext.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("FOOD_TRACKER_DB", Path(__file__).resolve().parent.parent / "food_tracker.db"))

VALID_LOCATIONS = ("fridge", "freezer", "cupboard", "drinks")

# Input size caps (defense against accidental or malicious oversized payloads)
MAX_NAME_LEN = 200
MAX_UNIT_LEN = 40
MAX_NOTES_LEN = 2000

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL;")
        _conn.execute("PRAGMA foreign_keys=ON;")
        _init_schema(_conn)
    return _conn


def _init_schema(c: sqlite3.Connection) -> None:
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS api_keys (
            key_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            quantity REAL NOT NULL DEFAULT 1,
            unit TEXT NOT NULL DEFAULT 'pc',
            location TEXT NOT NULL DEFAULT 'fridge',
            expiry_date TEXT,               -- YYYY-MM-DD or NULL
            low_stock_threshold REAL,      -- NULL means no threshold
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_items_user ON items(user_id);
        CREATE TABLE IF NOT EXISTS shopping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            quantity REAL NOT NULL DEFAULT 1,
            unit TEXT NOT NULL DEFAULT 'pc',
            checked INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_shopping_user ON shopping(user_id);
        """
    )
    c.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


# ---------- API keys ----------

def create_user(name: str = "") -> tuple[int, str]:
    """Create a user and issue them an API key. Returns (user_id, plaintext_key)."""
    key = "ft_" + secrets.token_urlsafe(32)
    with _lock:
        c = _connect()
        cur = c.execute("INSERT INTO users (created_at) VALUES (?)", (_now(),))
        user_id = cur.lastrowid
        c.execute(
            "INSERT INTO api_keys (key_hash, user_id, name, created_at) VALUES (?, ?, ?, ?)",
            (_hash_key(key), user_id, name, _now()),
        )
        c.commit()
    return user_id, key


def get_user_for_key(key: str) -> int | None:
    with _lock:
        c = _connect()
        row = c.execute(
            "SELECT user_id FROM api_keys WHERE key_hash = ?", (_hash_key(key),)
        ).fetchone()
    return row["user_id"] if row else None


def rotate_key(user_id: int, presented_key: str) -> str:
    """Revoke the presented key and issue a fresh one for the same user.

    Returns the new plaintext key. Raises ValueError if the presented key
    does not belong to the user."""
    with _lock:
        c = _connect()
        row = c.execute(
            "SELECT user_id FROM api_keys WHERE key_hash = ?",
            (_hash_key(presented_key),),
        ).fetchone()
        if not row or row["user_id"] != user_id:
            raise ValueError("key does not belong to this user")
        new_key = "ft_" + secrets.token_urlsafe(32)
        c.execute("DELETE FROM api_keys WHERE key_hash = ?", (_hash_key(presented_key),))
        c.execute(
            "INSERT INTO api_keys (key_hash, user_id, name, created_at) VALUES (?, ?, ?, ?)",
            (_hash_key(new_key), user_id, "rotated", _now()),
        )
        c.commit()
    return new_key


def delete_user(user_id: int) -> bool:
    """Delete a user and everything they own (keys, items, shopping lists).

    Returns True if a user was deleted."""
    with _lock:
        c = _connect()
        cur = c.execute("DELETE FROM users WHERE id = ?", (user_id,))
        c.commit()
    return cur.rowcount > 0


def _check_text(value: str, field: str, max_len: int) -> str:
    v = (value or "").strip()
    if len(v) > max_len:
        raise ValueError(f"{field} is too long (max {max_len} characters)")
    return v


# ---------- inventory ----------

def _row_to_item(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["days_until_expiry"] = None
    if d.get("expiry_date"):
        try:
            delta = date.fromisoformat(d["expiry_date"]) - date.today()
            d["days_until_expiry"] = delta.days
        except ValueError:
            pass
    if d.get("low_stock_threshold") is not None:
        d["is_low_stock"] = d["quantity"] <= d["low_stock_threshold"]
    else:
        d["is_low_stock"] = False
    return d


def add_item(user_id: int, name: str, quantity: float = 1, unit: str = "pc",
             location: str = "fridge", expiry_date: str | None = None,
             low_stock_threshold: float | None = None, notes: str = "") -> dict:
    name = _check_text(name, "name", MAX_NAME_LEN)
    if not name:
        raise ValueError("name is required")
    unit = _check_text(unit, "unit", MAX_UNIT_LEN) or "pc"
    notes = _check_text(notes, "notes", MAX_NOTES_LEN)
    if location not in VALID_LOCATIONS:
        raise ValueError(f"location must be one of {VALID_LOCATIONS}")
    if quantity < 0:
        raise ValueError("quantity cannot be negative")
    if low_stock_threshold is not None and low_stock_threshold < 0:
        raise ValueError("low_stock_threshold cannot be negative")
    if expiry_date:
        date.fromisoformat(expiry_date)  # validates YYYY-MM-DD
    with _lock:
        c = _connect()
        cur = c.execute(
            """INSERT INTO items
               (user_id, name, quantity, unit, location, expiry_date,
                low_stock_threshold, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, name, quantity, unit, location, expiry_date,
             low_stock_threshold, notes, _now(), _now()),
        )
        item_id = cur.lastrowid
        c.commit()
        row = c.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return _row_to_item(row)


def update_item(user_id: int, item_id: int, **fields) -> dict | None:
    allowed = {"name", "quantity", "unit", "location", "expiry_date",
               "low_stock_threshold", "notes"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "name" in updates:
        updates["name"] = _check_text(updates["name"], "name", MAX_NAME_LEN)
        if not updates["name"]:
            raise ValueError("name is required")
    if "unit" in updates:
        updates["unit"] = _check_text(updates["unit"], "unit", MAX_UNIT_LEN) or "pc"
    if "notes" in updates:
        updates["notes"] = _check_text(updates["notes"], "notes", MAX_NOTES_LEN)
    if "quantity" in updates and updates["quantity"] < 0:
        raise ValueError("quantity cannot be negative")
    if "low_stock_threshold" in updates and updates["low_stock_threshold"] is not None \
            and updates["low_stock_threshold"] < 0:
        raise ValueError("low_stock_threshold cannot be negative")
    if "location" in updates and updates["location"] not in VALID_LOCATIONS:
        raise ValueError(f"location must be one of {VALID_LOCATIONS}")
    if "expiry_date" in updates and updates["expiry_date"]:
        date.fromisoformat(updates["expiry_date"])
    if not updates:
        return get_item(user_id, item_id)
    sets = ", ".join(f"{k} = ?" for k in updates) + ", updated_at = ?"
    with _lock:
        c = _connect()
        cur = c.execute(
            f"UPDATE items SET {sets} WHERE id = ? AND user_id = ?",
            (*updates.values(), _now(), item_id, user_id),
        )
        c.commit()
        if cur.rowcount == 0:
            return None
        row = c.execute(
            "SELECT * FROM items WHERE id = ? AND user_id = ?", (item_id, user_id)
        ).fetchone()
    return _row_to_item(row) if row else None


def remove_item(user_id: int, item_id: int) -> bool:
    with _lock:
        c = _connect()
        cur = c.execute(
            "DELETE FROM items WHERE id = ? AND user_id = ?", (item_id, user_id)
        )
        c.commit()
    return cur.rowcount > 0


def get_item(user_id: int, item_id: int) -> dict | None:
    with _lock:
        c = _connect()
        row = c.execute(
            "SELECT * FROM items WHERE id = ? AND user_id = ?", (item_id, user_id)
        ).fetchone()
    return _row_to_item(row) if row else None


def list_items(user_id: int, location: str | None = None, search: str | None = None) -> list[dict]:
    q = "SELECT * FROM items WHERE user_id = ?"
    params: list = [user_id]
    if location:
        if location not in VALID_LOCATIONS:
            raise ValueError(f"location must be one of {VALID_LOCATIONS}")
        q += " AND location = ?"
        params.append(location)
    if search:
        q += " AND name LIKE ?"
        params.append(f"%{search}%")
    q += " ORDER BY location, name"
    with _lock:
        c = _connect()
        rows = c.execute(q, params).fetchall()
    return [_row_to_item(r) for r in rows]


def bulk_add_items(user_id: int, items: list[dict]) -> dict:
    """Add many items at once (e.g. from a receipt). Merges with an existing
    item of the same name + location by bumping its quantity instead of
    duplicating. Returns {added, merged}."""
    added, merged = [], []
    for it in items:
        name = str(it.get("name", "")).strip()
        if not name:
            continue
        location = it.get("location", "fridge")
        if location not in VALID_LOCATIONS:
            location = "fridge"
        try:
            qty = float(it.get("quantity", 1) or 1)
        except (TypeError, ValueError):
            raise ValueError(f"invalid quantity for item {name!r}")
        if qty < 0:
            raise ValueError(f"quantity cannot be negative for item {name!r}")
        expiry = it.get("expiry_date")
        if expiry:
            try:
                date.fromisoformat(str(expiry))
            except ValueError:
                raise ValueError(f"invalid expiry_date for item {name!r} (use YYYY-MM-DD)")
        with _lock:
            c = _connect()
            existing = c.execute(
                "SELECT * FROM items WHERE user_id = ? AND lower(name) = lower(?) AND location = ?",
                (user_id, name, location),
            ).fetchone()
            if existing:
                new_qty = existing["quantity"] + qty
                c.execute(
                    "UPDATE items SET quantity = ?, updated_at = ? WHERE id = ?",
                    (new_qty, _now(), existing["id"]),
                )
                c.commit()
                merged.append({"id": existing["id"], "name": existing["name"],
                               "quantity": new_qty, "unit": existing["unit"],
                               "location": location})
                existing = True
        if not existing:
            added.append(add_item(
                user_id, name=name, quantity=qty,
                unit=str(it.get("unit", "pc")), location=location,
                expiry_date=str(expiry) if expiry else None,
                notes=str(it.get("notes", "")),
            ))
    return {"added": added, "merged": merged}


# ---------- shopping list ----------

def _row_to_shopping(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["checked"] = bool(d["checked"])
    return d


def add_shopping_item(user_id: int, name: str, quantity: float = 1, unit: str = "pc") -> dict:
    name = _check_text(name, "name", MAX_NAME_LEN)
    if not name:
        raise ValueError("name is required")
    unit = _check_text(unit, "unit", MAX_UNIT_LEN) or "pc"
    if quantity < 0:
        raise ValueError("quantity cannot be negative")
    with _lock:
        c = _connect()
        cur = c.execute(
            "INSERT INTO shopping (user_id, name, quantity, unit, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, name.strip(), quantity, unit, _now()),
        )
        sid = cur.lastrowid
        c.commit()
        row = c.execute(
            "SELECT * FROM shopping WHERE id = ? AND user_id = ?", (sid, user_id)
        ).fetchone()
    return _row_to_shopping(row)


def list_shopping(user_id: int, include_checked: bool = True) -> list[dict]:
    q = "SELECT * FROM shopping WHERE user_id = ?"
    if not include_checked:
        q += " AND checked = 0"
    q += " ORDER BY checked, created_at"
    with _lock:
        c = _connect()
        rows = c.execute(q, (user_id,)).fetchall()
    return [_row_to_shopping(r) for r in rows]


def toggle_shopping_item(user_id: int, item_id: int, checked: bool | None = None) -> dict | None:
    with _lock:
        c = _connect()
        row = c.execute(
            "SELECT * FROM shopping WHERE id = ? AND user_id = ?", (item_id, user_id)
        ).fetchone()
        if not row:
            return None
        new_val = (not row["checked"]) if checked is None else bool(checked)
        c.execute("UPDATE shopping SET checked = ? WHERE id = ?", (int(new_val), item_id))
        c.commit()
        row = c.execute(
            "SELECT * FROM shopping WHERE id = ? AND user_id = ?", (item_id, user_id)
        ).fetchone()
    return _row_to_shopping(row)


def remove_shopping_item(user_id: int, item_id: int) -> bool:
    with _lock:
        c = _connect()
        cur = c.execute(
            "DELETE FROM shopping WHERE id = ? AND user_id = ?", (item_id, user_id)
        )
        c.commit()
    return cur.rowcount > 0


def move_shopping_to_inventory(user_id: int, item_id: int, location: str = "fridge",
                               expiry_date: str | None = None) -> dict | None:
    """Mark a shopping item as bought: move it into inventory."""
    with _lock:
        c = _connect()
        row = c.execute(
            "SELECT * FROM shopping WHERE id = ? AND user_id = ?", (item_id, user_id)
        ).fetchone()
        if not row:
            return None
        c.execute("DELETE FROM shopping WHERE id = ?", (item_id,))
        c.commit()
    item = add_item(user_id, name=row["name"], quantity=row["quantity"],
                    unit=row["unit"], location=location, expiry_date=expiry_date)
    return item
