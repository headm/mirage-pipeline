#!/usr/bin/env bash
# Prepare a fresh Claude Code cloud session (Linux x86_64) to run the pipeline.
# Downloads are pinned and checksum-verified. Writes tools/env.sh; `source tools/env.sh` after.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
mkdir -p tools

TSRCT_VERSION=0.4.0
TSRCT_SHA256=1281d1b7003ec632f8ed3054ee8db8501dcc66d4d650a2b47ba2d2f9da817e53
RCLONE_VERSION=v1.75.2
RVM_SHA256=88d4531297118f595bf2fd60f6f566aec2e559393802d1f436c380f0cbbd2828

as_root() { if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi; }

# ffmpeg (matte and frame checks) and a software Vulkan driver (Tesseract renders with wgpu).
if ! command -v ffmpeg >/dev/null || ! ls /usr/share/vulkan/icd.d/lvp_icd* >/dev/null 2>&1 || ! python3 -c "import venv, ensurepip" 2>/dev/null; then
  as_root apt-get update -qq
  as_root apt-get install -y -qq ffmpeg unzip libvulkan1 mesa-vulkan-drivers python3-venv >/dev/null
fi

if ! command -v rclone >/dev/null; then
  curl -fsSL "https://downloads.rclone.org/${RCLONE_VERSION}/rclone-${RCLONE_VERSION}-linux-amd64.zip" -o /tmp/rclone.zip
  unzip -q -o /tmp/rclone.zip -d /tmp/rclone
  mkdir -p "$HOME/.local/bin"
  install -m 755 "/tmp/rclone/rclone-${RCLONE_VERSION}-linux-amd64/rclone" "$HOME/.local/bin/rclone"
fi

TSRCT_DIR="tools/tesseract-${TSRCT_VERSION}"
if [ ! -x "$TSRCT_DIR/tesseract-${TSRCT_VERSION}-linux-x86_64/bin/tsrct" ]; then
  zip="/tmp/tesseract-${TSRCT_VERSION}-linux-x86_64.zip"
  curl -fsSL "https://github.com/mirage-hq/Tesseract/releases/download/v${TSRCT_VERSION}/tesseract-${TSRCT_VERSION}-linux-x86_64.zip" -o "$zip"
  echo "${TSRCT_SHA256}  $zip" | sha256sum -c -
  mkdir -p "$TSRCT_DIR"
  unzip -q -o "$zip" -d "$TSRCT_DIR"
fi
TSRCT="$ROOT/$TSRCT_DIR/tesseract-${TSRCT_VERSION}-linux-x86_64/bin/tsrct"

RVM="tools/rvm/rvm_mobilenetv3_fp32.onnx"
if [ ! -f "$RVM" ]; then
  mkdir -p tools/rvm
  curl -fsSL "https://github.com/PeterL1n/RobustVideoMatting/releases/download/v1.0.0/rvm_mobilenetv3_fp32.onnx" -o "$RVM"
  echo "${RVM_SHA256}  $RVM" | sha256sum -c -
fi

# Own Python environment: the image ships a broken system Pillow that pip would otherwise reuse.
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt

cat > tools/env.sh <<EOF
export PATH="$ROOT/.venv/bin:\$HOME/.local/bin:\$PATH"
export TSRCT="$TSRCT"
export RVM_MODEL="$ROOT/$RVM"
export FONT="$ROOT/brand/font.ttf"
export TSRCT_FFMPEG="$(command -v ffmpeg)"
EOF
# shellcheck disable=SC1091
source tools/env.sh

missing=()
for v in ELEVENLABS_API_KEY ELEVENLABS_VOICE_ID MIRAGE_API_KEY PIPELINE_REMOTE \
         RCLONE_CONFIG_GDRIVE_TYPE RCLONE_CONFIG_GDRIVE_CLIENT_ID RCLONE_CONFIG_GDRIVE_CLIENT_SECRET \
         RCLONE_CONFIG_GDRIVE_TOKEN; do
  [ -n "${!v:-}" ] || missing+=("$v")
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "Missing environment variables: ${missing[*]}" >&2
  exit 1
fi

"$TSRCT" --version
rclone lsd "${PIPELINE_REMOTE%%:*}:" >/dev/null
python3 -m pipeline fetch-assets
echo "cloud setup complete"
