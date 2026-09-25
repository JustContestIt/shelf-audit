"""Scheduled export of approved report rows to the customer's Google Sheet (was «Sheets Sync» in n8n).

Only rows with a final status (утверждено / исправлено) are exported, once (report_rows.synced).
Google Sheets is optional: without credentials the rows go to data/exports/report_rows_<date>.csv —
the hot path never depends on Google API (lesson of 24.08: 300–800 ms per Sheets call).

    python -m app.jobs.sheets_export            # once
    python -m app.jobs.sheets_export --daily 21:00   # loop, Asia/Almaty (UTC+5)
Env: DATABASE_URL, SHEETS_SPREADSHEET_ID, GOOGLE_APPLICATION_CREDENTIALS (service account json).
"""
from __future__ import annotations

import argparse
import csv
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import get_settings
from app.storage.repo import PgRepo

ALMATY = timezone(timedelta(hours=5))
COLS = ["report_id", "report_date", "route_code", "store_code", "store_name", "product_name", "product_subtype",
        "package_format", "shelf_index", "position", "front_facing_count", "status"]


def export_once() -> int:
    s = get_settings()
    if not s.database_url:
        print("DATABASE_URL is not set — nothing to export")
        return 0
    repo = PgRepo(s.database_url)
    rows = repo.rows_for_export()
    if not rows:
        print("no new approved rows")
        return 0
    values = [[str(r.get(c) if r.get(c) is not None else "") for c in COLS] for r in rows]
    sheet_id, creds = os.environ.get("SHEETS_SPREADSHEET_ID"), os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if sheet_id and creds:
        import gspread  # optional dependency: pip install gspread

        ws = gspread.service_account(filename=creds).open_by_key(sheet_id).sheet1
        ws.append_rows(values, value_input_option="USER_ENTERED")
        where = f"Google Sheet {sheet_id}"
    else:
        out = Path(s.data_dir) / "exports" / f"report_rows_{datetime.now(ALMATY):%Y-%m-%d_%H%M}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(COLS)
            w.writerows(values)
        where = str(out)
    repo.mark_synced([r["id"] for r in rows])
    print(f"exported {len(rows)} rows -> {where}")
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", help="HH:MM Asia/Almaty; run forever, once a day")
    a = ap.parse_args()
    if not a.daily:
        export_once()
        return 0
    hh, mm = map(int, a.daily.split(":"))
    while True:
        now = datetime.now(ALMATY)
        nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        time.sleep((nxt - now).total_seconds())
        try:
            export_once()
        except Exception as e:  # noqa: BLE001 — a failed export must not kill the scheduler
            print(f"export failed: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
