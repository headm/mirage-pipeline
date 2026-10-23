"""Command line: python -m pipeline <command>

    init            create the cloud folder layout and a starter topics.csv
    status          show topics left, videos in progress, and what is queued, ready and posted
    plan            list videos to work on (unfinished first, then a new topic if the queue is short)
    produce <id>    run the production steps for one video; script.json must be written first
    deliver         move the oldest queued video into ready/ (skipping expired topics)
    fetch-assets    download the Paper II image library from the cloud folder into brand/paper2/

A scheduled run is: plan -> write script.json for each video that needs one -> produce each -> deliver.
"""
import json
import sys
from datetime import date

from . import config, paper2, topics
from .config import ROOT
from .steps import production_steps
from .store import FOLDERS, Store
from .video import VideoFolder


def init(store: Store) -> None:
    for folder in FOLDERS:
        store.mkdir(folder)
    if store.exists("topics.csv"):
        print("topics.csv already exists, left as is")
    else:
        store.upload(ROOT / "templates" / "topics.csv", "topics.csv")
        print("created topics.csv from the template")
    print(f"layout ready at {store.remote}")


def unfinished(store: Store) -> list[str]:
    return [v for v in store.list_dirs("videos") if "caption.txt" not in store.list_files(f"videos/{v}")]


def status(store: Store, cfg: config.Config) -> None:
    rows = topics.load(store, cfg.work_dir) if store.exists("topics.csv") else []
    queued, ready, posted = (store.list_dirs(f) for f in ("queue", "ready", "posted"))
    in_progress = unfinished(store)
    print(f"topics:       {len(rows)} ({sum(1 for r in rows if topics.times_used(r) == 0)} never used)")
    print(f"in progress:  {len(in_progress)} {in_progress}")
    print(f"queued:       {len(queued)} (target {cfg.queue_target})")
    print(f"ready:        {len(ready)} {ready}")
    print(f"posted:       {len(posted)}")


def previous_videos(store: Store, cfg: config.Config, topic_id: str, exclude: str) -> list[dict]:
    """What earlier videos on this topic already did, so a reuse can take a different angle."""
    out = []
    for vid in store.list_dirs("videos"):
        rest = vid[11:]  # ids are YYYY-MM-DD-<topic> or YYYY-MM-DD-<topic>-<n>
        same_topic = rest == topic_id or (rest.startswith(topic_id + "-") and rest[len(topic_id) + 1:].isdigit())
        if vid == exclude or not same_topic:
            continue
        v = VideoFolder(store, cfg.work_dir, vid)
        if not v.done("script.json"):
            continue
        s = json.loads(v.path("script.json").read_text())
        out.append({"id": vid, "hook": s.get("hook"),
                    "opening": " ".join(s.get("script", "").split()[:40]),
                    "on_screen": paper2.on_screen_text(s.get("moments", [])),
                    "assets": sorted({m.get(k) for m in s.get("moments", []) for k in ("sticker", "photo", "circle") if m.get(k)}
                                     | {x for m in s.get("moments", []) for x in m.get("stickers", [])})})
    return out


def new_video_id(store: Store, today: date, topic_id: str) -> str:
    base = f"{today.isoformat()}-{topic_id}"
    existing = set(store.list_dirs("videos"))
    n, video_id = 2, base
    while video_id in existing:
        video_id, n = f"{base}-{n}", n + 1
    return video_id


def plan(store: Store, cfg: config.Config) -> None:
    ids = unfinished(store)
    if len(store.list_dirs("queue")) + len(ids) < cfg.queue_target:
        today = date.today()
        topic = topics.take_next(store, cfg.work_dir, today)
        if topic:
            video_id = new_video_id(store, today, topic["id"])
            v = VideoFolder(store, cfg.work_dir, video_id)
            (v.local / "topic.json").write_text(json.dumps(topic, indent=2))
            v.save("topic.json")
            ids.append(video_id)
        else:
            print("WARNING: no usable topics in topics.csv (all expired?)", file=sys.stderr)

    todo = []
    for video_id in ids:
        v = VideoFolder(store, cfg.work_dir, video_id)
        topic = json.loads(v.path("topic.json").read_text())
        todo.append({"id": video_id, "needs_script": not v.done("script.json"),
                     "script_path": str(v.local / "script.json"), "topic": topic,
                     "previous_videos_on_this_topic": previous_videos(store, cfg, topic["id"], video_id)})
    print(json.dumps(todo, indent=2))


ASSET_FOLDERS = ("stickers", "photos", "circles", "paper")


def fetch_assets(store: Store) -> None:
    """The images are Pexels-derived, so they live in the private cloud folder, not the public repo."""
    for folder in ASSET_FOLDERS:
        store.download_dir(f"assets/paper2/{folder}", ROOT / "brand" / "paper2" / folder)
    print("assets ready in brand/paper2/")


def produce(store: Store, cfg: config.Config, video_id: str) -> None:
    if not all((ROOT / "brand" / "paper2" / f).is_dir() for f in ASSET_FOLDERS):
        fetch_assets(store)
    VideoFolder(store, cfg.work_dir, video_id).run(production_steps(cfg))
    print(f"[{video_id}] queued")


def deliver(store: Store, cfg: config.Config) -> None:
    today = date.today()
    for video_id in store.list_dirs("queue"):  # names start with the date, so oldest first
        topic = json.loads(VideoFolder(store, cfg.work_dir, video_id).path("topic.json").read_text())
        if topics.is_expired(topic, today):
            store.purge(f"queue/{video_id}")
            print(f"[{video_id}] expired, removed from queue")
            continue
        store.move_dir(f"queue/{video_id}", f"ready/{video_id}")
        print(f"[{video_id}] delivered to ready/")
        return
    print("nothing in the queue to deliver")


def main() -> None:
    cfg = config.load()
    store = Store(cfg.remote)
    args = sys.argv[1:]
    command = args[0] if args else ""
    if command == "init":
        init(store)
    elif command == "status":
        status(store, cfg)
    elif command == "plan":
        plan(store, cfg)
    elif command == "produce" and len(args) == 2:
        produce(store, cfg, args[1])
    elif command == "deliver":
        deliver(store, cfg)
    elif command == "fetch-assets":
        fetch_assets(store)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
