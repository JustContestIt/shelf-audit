"""Retention: photos of reports older than N days are deleted (customer data minimisation).
Reports, rows and boxes stay; the photo path is kept so the UI shows «фото удалено».

    python -m app.jobs.cleanup --days 30
"""
from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

from app.config import get_settings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    root = Path(get_settings().photos_dir)
    cutoff = time.time() - a.days * 86400
    removed = 0
    for d in root.glob("R_*"):
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    print(f"removed photo folders: {removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
