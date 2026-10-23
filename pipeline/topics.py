"""topics.csv in the cloud folder: pick the next unused topic and mark it used."""
import csv
import io
from datetime import date
from pathlib import Path

from .store import Store

FIELDS = ["id", "topic", "notes", "kind", "expires_on", "used_on"]


def load(store: Store, work_dir: Path) -> list[dict]:
    local = store.download("topics.csv", work_dir / "topics.csv")
    return list(csv.DictReader(io.StringIO(local.read_text())))


def save(store: Store, work_dir: Path, rows: list[dict]) -> None:
    local = work_dir / "topics.csv"
    with local.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    store.upload(local, "topics.csv")


def is_expired(row: dict, today: date) -> bool:
    expires = (row.get("expires_on") or "").strip()
    return bool(expires) and date.fromisoformat(expires) < today


def take_next(store: Store, work_dir: Path, today: date) -> dict | None:
    """Return the first unused, unexpired topic and mark it used today."""
    rows = load(store, work_dir)
    for row in rows:
        if not (row.get("used_on") or "").strip() and not is_expired(row, today):
            row["used_on"] = today.isoformat()
            save(store, work_dir, rows)
            return row
    return None
