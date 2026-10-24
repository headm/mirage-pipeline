"""The cloud folder (Dropbox or Google Drive), reached through rclone.

Layout under the remote root:
    topics.csv          topic list you edit
    videos/<id>/        one folder per video; each step writes its own file here
    ready/<id>/         every finished video: video.mp4, cover.png, caption.txt
"""
import json
import subprocess
from pathlib import Path

FOLDERS = ("videos", "ready")


class Store:
    def __init__(self, remote: str):
        self.remote = remote

    def _path(self, rel: str) -> str:
        return f"{self.remote}/{rel}".rstrip("/")

    def _rclone(self, *args: str) -> str:
        out = subprocess.run(["rclone", *args], capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError(f"rclone {' '.join(args)} failed: {out.stderr.strip()}")
        return out.stdout

    def list_files(self, rel: str) -> list[str]:
        try:
            entries = json.loads(self._rclone("lsjson", "--files-only", self._path(rel)))
        except RuntimeError as e:
            if "directory not found" in str(e):
                return []
            raise
        return sorted(e["Name"] for e in entries)

    def list_dirs(self, rel: str) -> list[str]:
        try:
            entries = json.loads(self._rclone("lsjson", "--dirs-only", self._path(rel)))
        except RuntimeError as e:
            if "directory not found" in str(e):
                return []
            raise
        return sorted(e["Name"] for e in entries)

    def exists(self, rel: str) -> bool:
        parent, _, name = rel.rpartition("/")
        return name in self.list_files(parent)

    def download(self, rel: str, local: Path) -> Path:
        local.parent.mkdir(parents=True, exist_ok=True)
        self._rclone("copyto", self._path(rel), str(local))
        return local

    def upload(self, local: Path, rel: str) -> None:
        self._rclone("copyto", str(local), self._path(rel))

    def download_dir(self, rel: str, local: Path) -> None:
        """Copy a cloud folder to a local one, skipping files that are already up to date."""
        local.mkdir(parents=True, exist_ok=True)
        self._rclone("copy", self._path(rel), str(local))

    def copy_dir(self, src_rel: str, dst_rel: str) -> None:
        self._rclone("copy", self._path(src_rel), self._path(dst_rel))

    def move_dir(self, src_rel: str, dst_rel: str) -> None:
        self._rclone("move", self._path(src_rel), self._path(dst_rel), "--delete-empty-src-dirs")
        # Some backends leave the emptied source folder behind; others already removed it.
        try:
            self._rclone("rmdirs", self._path(src_rel))
        except RuntimeError as e:
            if "directory not found" not in str(e) and "no such file" not in str(e):
                raise

    def delete_file(self, rel: str) -> None:
        self._rclone("deletefile", self._path(rel))

    def purge(self, rel: str) -> None:
        self._rclone("purge", self._path(rel))

    def mkdir(self, rel: str) -> None:
        self._rclone("mkdir", self._path(rel))
