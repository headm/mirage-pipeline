"""One video's folder in the cloud, and the step runner that fills it.

There is no database: a step is done when its output files exist in videos/<id>/.
A rerun (for example the next day's scheduled run after a failure) skips finished
steps and picks up at the first missing file.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .store import Store


@dataclass(frozen=True)
class Step:
    name: str
    outputs: tuple[str, ...]
    run: Callable[["VideoFolder"], None]


class VideoFolder:
    def __init__(self, store: Store, work_dir: Path, video_id: str):
        self.store = store
        self.id = video_id
        self.rel = f"videos/{video_id}"
        self.local = work_dir / video_id
        self.local.mkdir(parents=True, exist_ok=True)
        self._remote = set(store.list_files(self.rel))

    def done(self, name: str) -> bool:
        return name in self._remote

    def path(self, name: str) -> Path:
        """Local path for a file, downloading it first if only the cloud copy exists."""
        local = self.local / name
        if not local.exists() and self.done(name):
            self.store.download(f"{self.rel}/{name}", local)
        return local

    def save(self, name: str) -> None:
        self.store.upload(self.local / name, f"{self.rel}/{name}")
        self._remote.add(name)

    def run(self, steps: list[Step]) -> None:
        for step in steps:
            if all(self.done(o) for o in step.outputs):
                print(f"[{self.id}] {step.name}: already done")
                continue
            print(f"[{self.id}] {step.name}: running")
            step.run(self)
            for output in step.outputs:
                if not (self.local / output).exists():
                    raise RuntimeError(f"step {step.name} did not write {output}")
                self.save(output)
