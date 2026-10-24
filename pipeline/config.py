"""Settings from environment variables (a local .env, or secrets in the cloud agent's environment)."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Read KEY=value lines into os.environ without overriding variables already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Config:
    remote: str           # rclone remote root, e.g. "gdrive:mirage-pipeline" or a local path for testing
    work_dir: Path        # local scratch space for the current run
    tsrct: str            # Tesseract CLI binary
    font: Path            # TTF embedded in every edit


def load() -> Config:
    load_dotenv()
    return Config(
        remote=os.environ["PIPELINE_REMOTE"].rstrip("/"),
        work_dir=Path(os.environ.get("PIPELINE_WORK_DIR", ROOT / "work")),
        tsrct=os.environ.get("TSRCT", "tsrct"),
        font=Path(os.environ.get("FONT", ROOT / "brand" / "font.ttf")),
    )
