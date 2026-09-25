"""Reports storage: Postgres in production, in-memory for tests and the no-DB dev mode."""
from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from app.guardrails.input_guard import hamming

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
ROW_STATUS = {"awaiting_review": "на_проверке", "approved": "утверждено", "edited": "исправлено"}


def normalise_phone(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    if len(d) == 11 and d[0] == "8":
        d = "7" + d[1:]
    if len(d) == 10:
        d = "7" + d
    return d


class Repo(Protocol):
    def upsert_report(self, rec: dict) -> None: ...
    def get_report(self, report_id: str) -> dict | None: ...
    def list_reports(self, *, store_code: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]: ...
    def find_duplicates(self, phash: str, *, store_code: str, hours: int = 24, max_distance: int = 6,
                        exclude: str | None = None) -> list[str]: ...
    def rows_for_export(self) -> list[dict]: ...
    def mark_synced(self, ids: list[int]) -> None: ...
    def stores_for_route(self, route_code: str | None) -> list[dict]: ...
    def agent_by_phone(self, phone: str) -> dict | None: ...
    def agent_by_tg(self, tg_id: int) -> dict | None: ...
    def bind_agent_tg(self, agent_id: str, tg_id: int) -> None: ...


def _rows_from_rec(rec: dict) -> list[dict]:
    rep = (rec.get("body") or {}).get("report") or {}
    status = ROW_STATUS.get(rec["status"])
    if status is None:
        return []
    return [{
        "report_id": rec["report_id"], "route_code": rec.get("route_code", ""), "store_code": rec.get("store_code", ""),
        "store_name": rec.get("store_name", ""), "product_name": r["brand"], "product_subtype": r.get("subtype"),
        "package_format": r.get("package_format"), "shelf_index": r["shelf_index"], "position": r.get("position"),
        "front_facing_count": r["front_facing_count"], "needs_review": bool(r.get("needs_review")), "status": status,
    } for r in rep.get("rows", [])]


class MemoryRepo:
    def __init__(self):
        self._lock = threading.Lock()
        self.reports: dict[str, dict] = {}
        self.rows: list[dict] = []
        self.stores: dict[str, dict] = {}
        self.agents: dict[str, dict] = {}
        self._next = 1

    def upsert_report(self, rec):
        with self._lock:
            now = datetime.now(UTC).isoformat(timespec="seconds")
            old = self.reports.get(rec["report_id"], {})
            self.reports[rec["report_id"]] = {**old, **rec, "created_at": old.get("created_at", now), "updated_at": now}
            self.rows = [r for r in self.rows if r["report_id"] != rec["report_id"]]
            for r in _rows_from_rec(self.reports[rec["report_id"]]):
                self.rows.append({**r, "id": self._next, "report_date": now, "synced": False})
                self._next += 1

    def get_report(self, report_id):
        return self.reports.get(report_id)

    def list_reports(self, *, store_code=None, status=None, limit=50):
        out = [r for r in self.reports.values() if (not store_code or r.get("store_code") == store_code)
               and (not status or r.get("status") == status)]
        return sorted(out, key=lambda r: r["created_at"], reverse=True)[:limit]

    def find_duplicates(self, phash, *, store_code, hours=24, max_distance=6, exclude=None):
        since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        return [r["report_id"] for r in self.reports.values() if r["report_id"] != exclude and r.get("photo_phash")
                and r.get("store_code") == store_code and r["created_at"] >= since and hamming(phash, r["photo_phash"]) <= max_distance]

    def rows_for_export(self):
        return [r for r in self.rows if not r["synced"] and r["status"] != "на_проверке"]

    def mark_synced(self, ids):
        for r in self.rows:
            if r["id"] in ids:
                r["synced"] = True

    def stores_for_route(self, route_code):
        return [s for s in self.stores.values() if not route_code or s.get("route_code") == route_code]

    def agent_by_phone(self, phone):
        p = normalise_phone(phone)
        return next((a for a in self.agents.values() if a.get("phone") == p), None)

    def agent_by_tg(self, tg_id):
        return next((a for a in self.agents.values() if a.get("telegram_user_id") == tg_id), None)

    def bind_agent_tg(self, agent_id, tg_id):
        if agent_id in self.agents:
            self.agents[agent_id]["telegram_user_id"] = tg_id

    def seed(self, stores: list[dict], agents: list[dict]):
        for s in stores:
            self.stores[s["store_code"]] = s
        for a in agents:
            self.agents[a["agent_id"]] = {**a, "phone": normalise_phone(a.get("phone", ""))}


REPORT_COLS = ["report_id", "status", "store_code", "store_name", "route_code", "agent_id", "source", "photo_path",
               "photo_sha256", "photo_phash", "prompt_version", "verify_prompt_version", "config_id", "models",
               "total_units", "unknown_units", "needs_review_units", "overall_confidence", "low_confidence", "cost_usd",
               "latency_s", "reject_reason", "flags", "review", "body"]
JSON_COLS = {"flags", "review", "body"}


class PgRepo:
    def __init__(self, dsn: str):
        from psycopg_pool import ConnectionPool

        self.pool = ConnectionPool(dsn, min_size=1, max_size=5, kwargs={"autocommit": True}, open=True)
        with self.pool.connection() as c:
            c.execute(SCHEMA)

    def _dict(self, cur, row):
        return {d.name: v for d, v in zip(cur.description, row, strict=True)} if row else None

    def upsert_report(self, rec):
        vals = [json.dumps(rec.get(k), ensure_ascii=False, default=str) if k in JSON_COLS else rec.get(k) for k in REPORT_COLS]
        sets = ", ".join(f"{k}=EXCLUDED.{k}" for k in REPORT_COLS[1:])
        with self.pool.connection() as c, c.transaction():
            c.execute(f"INSERT INTO reports ({', '.join(REPORT_COLS)}) VALUES ({', '.join(['%s'] * len(REPORT_COLS))}) "
                      f"ON CONFLICT (report_id) DO UPDATE SET {sets}, updated_at=now()", vals)
            full = self.get_report(rec["report_id"], conn=c)
            c.execute("DELETE FROM report_rows WHERE report_id=%s", (rec["report_id"],))
            for r in _rows_from_rec(full):
                c.execute("""INSERT INTO report_rows (report_id, route_code, store_code, store_name, product_name, product_subtype,
                             package_format, shelf_index, position, front_facing_count, needs_review, status)
                             VALUES (%(report_id)s, %(route_code)s, %(store_code)s, %(store_name)s, %(product_name)s,
                             %(product_subtype)s, %(package_format)s, %(shelf_index)s, %(position)s, %(front_facing_count)s,
                             %(needs_review)s, %(status)s)""", r)

    def get_report(self, report_id, conn=None):
        def q(c):
            cur = c.execute("SELECT * FROM reports WHERE report_id=%s", (report_id,))
            d = self._dict(cur, cur.fetchone())
            if d:
                d["created_at"] = d["created_at"].isoformat()
                d["updated_at"] = d["updated_at"].isoformat()
                d["cost_usd"] = float(d["cost_usd"]) if d["cost_usd"] is not None else None
            return d
        if conn is not None:
            return q(conn)
        with self.pool.connection() as c:
            return q(c)

    def list_reports(self, *, store_code=None, status=None, limit=50):
        where, args = [], []
        if store_code:
            where.append("store_code=%s")
            args.append(store_code)
        if status:
            where.append("status=%s")
            args.append(status)
        sql = ("SELECT report_id FROM reports " + ("WHERE " + " AND ".join(where) if where else "")
               + " ORDER BY created_at DESC LIMIT %s")
        with self.pool.connection() as c:
            ids = [r[0] for r in c.execute(sql, [*args, limit]).fetchall()]
        return [self.get_report(i) for i in ids]

    def find_duplicates(self, phash, *, store_code, hours=24, max_distance=6, exclude=None):
        with self.pool.connection() as c:
            rows = c.execute("SELECT report_id, photo_phash FROM reports WHERE store_code=%s AND photo_phash IS NOT NULL "
                             "AND created_at > now() - make_interval(hours => %s) AND report_id <> %s",
                             (store_code, hours, exclude or "")).fetchall()
        return [rid for rid, ph in rows if hamming(phash, ph) <= max_distance]

    def rows_for_export(self):
        with self.pool.connection() as c:
            cur = c.execute("SELECT * FROM report_rows WHERE NOT synced AND status <> 'на_проверке' ORDER BY id")
            return [self._dict(cur, r) for r in cur.fetchall()]

    def mark_synced(self, ids):
        with self.pool.connection() as c:
            c.execute("UPDATE report_rows SET synced=true WHERE id = ANY(%s)", (ids,))

    def stores_for_route(self, route_code):
        with self.pool.connection() as c:
            cur = c.execute("SELECT * FROM stores" + (" WHERE route_code=%s" if route_code else "") + " ORDER BY store_name",
                            (route_code,) if route_code else ())
            return [self._dict(cur, r) for r in cur.fetchall()]

    def agent_by_phone(self, phone):
        with self.pool.connection() as c:
            cur = c.execute("SELECT * FROM agents WHERE phone=%s", (normalise_phone(phone),))
            return self._dict(cur, cur.fetchone())

    def agent_by_tg(self, tg_id):
        with self.pool.connection() as c:
            cur = c.execute("SELECT * FROM agents WHERE telegram_user_id=%s", (tg_id,))
            return self._dict(cur, cur.fetchone())

    def bind_agent_tg(self, agent_id, tg_id):
        with self.pool.connection() as c:
            c.execute("UPDATE agents SET telegram_user_id=%s WHERE agent_id=%s", (tg_id, agent_id))

    def seed(self, stores: list[dict], agents: list[dict]):
        with self.pool.connection() as c:
            for s in stores:
                c.execute("INSERT INTO stores (store_code, store_name, address, route_code) VALUES (%s,%s,%s,%s) "
                          "ON CONFLICT (store_code) DO NOTHING", (s["store_code"], s["store_name"], s.get("address", ""), s.get("route_code", "")))
            for a in agents:
                c.execute("INSERT INTO agents (agent_id, name, phone, route_code, role) VALUES (%s,%s,%s,%s,%s) "
                          "ON CONFLICT (agent_id) DO NOTHING",
                          (a["agent_id"], a.get("name", ""), normalise_phone(a.get("phone", "")), a.get("route_code", ""), a.get("role", "agent")))
