#!/usr/bin/env bash
# Cloud Agent install for Matreshka Viewer.
#
# Two jobs: put the system pieces the viewer needs on the machine, and build
# the Python virtual environment the tool and its tests run from. Written to be
# run again without harm -- apt only fetches what is missing, and the venv is
# left alone once it is good.
#
# The viewer draws through wgpu/Vulkan and shows a real Qt window, so the
# machine needs a Vulkan driver and Qt's runtime libraries. There is no GPU
# here, so Mesa's software rasteriser (lavapipe) stands in; the Vulkan loader
# finds it on its own once mesa-vulkan-drivers is installed. ffmpeg is only
# used to write and probe video, but the render tests need it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

export DEBIAN_FRONTEND=noninteractive

APT_PACKAGES=(
    # Software Vulkan (lavapipe) plus the loader, so wgpu has an adapter with
    # no GPU present. vulkan-tools gives vulkaninfo for checking it by hand.
    mesa-vulkan-drivers
    vulkan-tools
    libvulkan1
    # Writes and probes video for the render tests and the RENDER button.
    ffmpeg
    # Building and running the venv.
    python3.12-venv
    python3-pip
    # Qt's runtime libraries. PySide6's wheels carry Qt itself but link these
    # from the system; without libEGL the import fails outright.
    libegl1
    libgl1
    libglib2.0-0
    libdbus-1-3
    libfontconfig1
    libxrender1
    libxi6
    libxkbcommon0
    libxkbcommon-x11-0
    libxcb-cursor0
    libxcb-icccm4
    libxcb-image0
    libxcb-keysyms1
    libxcb-randr0
    libxcb-render-util0
    libxcb-shape0
    libxcb-xinerama0
    libxcb-util1
    # A headless X server, so the tests have a display to open their window on
    # even when the desktop one is not up: run them under `xvfb-run`.
    xvfb
)

echo "==> Installing system packages"
$SUDO apt-get update -qq
$SUDO apt-get install -y --no-install-recommends "${APT_PACKAGES[@]}"

echo "==> Building the Python virtual environment (tool/.venv)"
VENV="tool/.venv"
if [ ! -x "$VENV/bin/python" ]; then
    rm -rf "$VENV"
    python3 -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --quiet --upgrade pip
# The viewer's own dependencies, pinned in the repo.
"$VENV/bin/pip" install --quiet -r tool/requirements.txt
# The headless test suite reaches for these two on top of the tool's own set:
# Pillow to compare a snapshot against a rendered frame, pytest to run it.
"$VENV/bin/pip" install --quiet pillow pytest

echo "==> Checking wgpu can reach a Vulkan adapter"
"$VENV/bin/python" - <<'PY'
import wgpu
adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
print("wgpu adapter:", adapter.info.get("device"), "via", adapter.info.get("backend_type"))
PY

echo "==> Install complete"
