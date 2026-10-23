"""Command line: python -m pipeline <command>

    init     create the cloud folder layout and a starter topics.csv
    status   show topics left, videos in progress, and what is queued, ready and posted
"""
import csv
import io
import sys

from . import config
from .config import ROOT
from .store import FOLDERS, Store


def init(store: Store) -> None:
    for folder in FOLDERS:
        store.mkdir(folder)
    if store.exists("topics.csv"):
        print("topics.csv already exists, left as is")
    else:
        store.upload(ROOT / "templates" / "topics.csv", "topics.csv")
        print("created topics.csv from the template")
    print(f"layout ready at {store.remote}")


def status(store: Store, cfg: config.Config) -> None:
    topics_left = 0
    if store.exists("topics.csv"):
        local = store.download("topics.csv", cfg.work_dir / "topics.csv")
        rows = csv.DictReader(io.StringIO(local.read_text()))
        topics_left = sum(1 for r in rows if not r.get("used_on"))

    queued, ready, posted = (store.list_dirs(f) for f in ("queue", "ready", "posted"))
    finished = set(queued) | set(ready) | set(posted)
    in_progress = [v for v in store.list_dirs("videos") if v not in finished]

    print(f"topics left:  {topics_left}")
    print(f"in progress:  {len(in_progress)} {in_progress}")
    print(f"queued:       {len(queued)} (target {cfg.queue_target})")
    print(f"ready:        {len(ready)} {ready}")
    print(f"posted:       {len(posted)}")


def main() -> None:
    cfg = config.load()
    store = Store(cfg.remote)
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "init":
        init(store)
    elif command == "status":
        status(store, cfg)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
