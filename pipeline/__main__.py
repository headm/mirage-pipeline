"""Command line: python -m pipeline <command>

    init            create the cloud folder layout and a starter topics.csv
    status          show topics left, videos in progress, and what is in ready/
    plan            list videos to work on: unfinished ones first, then one new topic
    produce <id>    run the production steps for one video; finished videos land in ready/
    fetch-assets    download the Paper II image library from the cloud folder into brand/paper2/
    review <id>     automatic checks of a finished edit, plus a contact sheet of frames to look at
    reedit <id>     after changing script.json: check it and clear the edit so produce redoes it (free)

A scheduled run is: plan -> write script.json -> produce -> review (and fix).
What happens to a video after it lands in ready/ is up to you.
"""
import json
import sys
from datetime import date

from . import config, paper2, topics
from .config import ROOT
from . import review as reviewer
from .steps import check_script, production_steps
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
    ready = store.list_dirs("ready")
    in_progress = unfinished(store)
    print(f"topics:       {len(rows)} ({sum(1 for r in rows if topics.times_used(r) == 0)} never used)")
    print(f"in progress:  {len(in_progress)} {in_progress}")
    print(f"ready:        {len(ready)} {ready}")


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
    today = date.today()
    ids = unfinished(store)
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
    print(f"[{video_id}] finished, in ready/")


EDIT_OUTPUTS = ("final.mp4", "cover.png", "edit.tsrct", "layout.json", "caption.txt", "review.png")


def review(store: Store, cfg: config.Config, video_id: str) -> None:
    v = VideoFolder(store, cfg.work_dir, video_id)
    if not (v.done("final.mp4") and v.done("layout.json")):
        sys.exit(f"{video_id} has no finished edit to review; run produce first")
    layout = json.loads(v.path("layout.json").read_text())
    problems = reviewer.layout_checks(layout) + reviewer.media_checks(v.path("final.mp4"), layout)
    sheet = v.local / "review.png"
    frames = reviewer.contact_sheet(v.path("final.mp4"), layout, sheet)
    v.save("review.png")
    print(json.dumps({"video": video_id, "problems": problems, "contact_sheet": str(sheet),
                      "frames_on_sheet": frames, "moments_placed": layout["placed"],
                      "script_path": str(v.local / "script.json")}, indent=2))


def reedit(store: Store, cfg: config.Config, video_id: str) -> None:
    """Check the changed script.json, then clear the edit so the next produce rebuilds it.
    Voice, avatar and matte are kept, so this never pays for a render again."""
    v = VideoFolder(store, cfg.work_dir, video_id)
    v.path("script.json")
    check_script(v)
    v.save("script.json")
    for name in EDIT_OUTPUTS:
        if v.done(name):
            store.delete_file(f"{v.rel}/{name}")
        (v.local / name).unlink(missing_ok=True)
    print(f"[{video_id}] edit cleared; run produce again")


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
    elif command == "fetch-assets":
        fetch_assets(store)
    elif command == "review" and len(args) == 2:
        review(store, cfg, args[1])
    elif command == "reedit" and len(args) == 2:
        reedit(store, cfg, args[1])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
