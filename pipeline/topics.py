"""topics.csv in the cloud folder: pick the next topic and record its use.

Topics are reused. The next topic is the least-used one, oldest use first, skipping anything
used within COOLDOWN_DAYS (unless every topic is that recent). Each reuse gets a new script and
new graphics: plan() shows the agent what earlier videos on the topic already did.
"""
import csv
import io
from datetime import date, timedelta
from pathlib import Path

from .store import Store

FIELDS = ["id", "topic", "notes", "kind", "expires_on", "used_on", "times_used"]
COOLDOWN_DAYS = 14


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


def times_used(row: dict) -> int:
    value = (row.get("times_used") or "").strip()
    return int(value) if value else (1 if (row.get("used_on") or "").strip() else 0)


def take_next(store: Store, work_dir: Path, today: date) -> dict | None:
    """Pick the least-used topic (oldest use first) outside the cooldown, and record the use."""
    rows = load(store, work_dir)
    live = [r for r in rows if not is_expired(r, today)]
    if not live:
        return None
    cutoff = (today - timedelta(days=COOLDOWN_DAYS)).isoformat()
    rested = [r for r in live if (r.get("used_on") or "") < cutoff] or live
    row = min(rested, key=lambda r: (times_used(r), r.get("used_on") or ""))
    row["times_used"] = str(times_used(row) + 1)
    row["used_on"] = today.isoformat()
    save(store, work_dir, rows)
    return row
