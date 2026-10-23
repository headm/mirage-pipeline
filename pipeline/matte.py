"""Person matte with Robust Video Matting (open-source ONNX model, run on CPU).

Writes a grayscale video, white where the person is, which Tesseract uses as a luma
track matte to cut the avatar out of its background.

    python -m pipeline.matte raw.mp4 matte.mp4
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort

from .config import ROOT

MODEL = Path(os.environ.get("RVM_MODEL", ROOT / "tools" / "rvm" / "rvm_mobilenetv3_fp32.onnx"))
DOWNSAMPLE = 0.4  # RVM's suggested range for ~720p portrait footage


def probe(video: Path) -> tuple[int, int, str]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate", "-of", "json", str(video)],
                         capture_output=True, text=True, check=True)
    s = json.loads(out.stdout)["streams"][0]
    return s["width"], s["height"], s["r_frame_rate"]


def make_matte(video: Path, out: Path) -> None:
    w, h, fps = probe(video)
    session = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    rec = [np.zeros((1, 1, 1, 1), np.float32)] * 4
    ratio = np.array([DOWNSAMPLE], np.float32)

    reader = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(video), "-f", "rawvideo",
                               "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    writer = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
                               "-s", f"{w}x{h}", "-r", fps, "-i", "-", "-c:v", "libx264", "-crf", "12",
                               "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    frames, started = 0, time.time()
    frame_bytes = w * h * 3
    while chunk := reader.stdout.read(frame_bytes):
        if len(chunk) < frame_bytes:
            break
        src = np.frombuffer(chunk, np.uint8).reshape(h, w, 3).transpose(2, 0, 1)[None].astype(np.float32) / 255
        _, pha, *rec = session.run(None, {"src": src, "r1i": rec[0], "r2i": rec[1], "r3i": rec[2],
                                         "r4i": rec[3], "downsample_ratio": ratio})
        writer.stdin.write((pha[0, 0] * 255).clip(0, 255).astype(np.uint8).tobytes())
        frames += 1
    writer.stdin.close()
    if writer.wait() != 0 or reader.wait() != 0:
        raise RuntimeError("ffmpeg failed while writing the matte")
    print(f"{out}: {frames} frames in {time.time() - started:.0f}s")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    make_matte(Path(sys.argv[1]), Path(sys.argv[2]))
