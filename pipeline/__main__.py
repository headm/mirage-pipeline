"""Command line: python -m pipeline <command>

    init            create the cloud folder layout and a starter topics.csv
    status          show topics left, videos in progress, and what is queued, ready and posted
    plan            list videos to work on (unfinished first, then a new topic if the queue is short)
    produce <id>    run the production steps for one video; script.json must be written first
    deliver         move the oldest queued video into ready/ (skipping expired topics)

A scheduled run is: plan -> write script.json for each video that needs one -> produce each -> deliver.
"""
import json
import sys
from datetime import date

from . import config, topics
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
    print(f"topics left:  {sum(1 for r in rows if not r.get('used_on'))}")
    print(f"in progress:  {len(in_progress)} {in_progress}")
    print(f"queued:       {len(queued)} (target {cfg.queue_target})")
    print(f"ready:        {len(ready)} {ready}")
    print(f"posted:       {len(posted)}")


def plan(store: Store, cfg: config.Config) -> None:
    ids = unfinished(store)
    if len(store.list_dirs("queue")) + len(ids) < cfg.queue_target:
        today = date.today()
        topic = topics.take_next(store, cfg.work_dir, today)
        if topic:
            video_id = f"{today.isoformat()}-{topic['id']}"
            v = VideoFolder(store, cfg.work_dir, video_id)
            (v.local / "topic.json").write_text(json.dumps(topic, indent=2))
            v.save("topic.json")
            ids.append(video_id)
        else:
            print("WARNING: no unused topics left in topics.csv", file=sys.stderr)

    todo = []
    for video_id in ids:
        v = VideoFolder(store, cfg.work_dir, video_id)
        todo.append({"id": video_id, "needs_script": not v.done("script.json"),
                     "script_path": str(v.local / "script.json"),
                     "topic": json.loads(v.path("topic.json").read_text())})
    print(json.dumps(todo, indent=2))


def produce(store: Store, cfg: config.Config, video_id: str) -> None:
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
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
