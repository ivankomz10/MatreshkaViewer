#!/usr/bin/env bash
# Build the viewer on macOS or Linux and put it NEXT TO this folder, one up.
#
# The baked scene travels inside the binary; ffmpeg does not and is found or
# fetched at run time. The spec does the building: --exclude-module only
# reaches Python modules, and most of the weight is Qt that PySide6 ships
# whether or not anything imports it.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

# Made here rather than demanded of whoever runs this. A venv is part of the
# build, not a thing to be arranged beforehand, and the two ways it goes wrong
# -- never made, or left pointing at a Python that has since moved -- look the
# same from outside and are fixed the same way.
if [ ! -x ".venv/bin/python" ]; then
    # This script sits next to build.bat and shares its folder. A Windows venv
    # keeps its interpreter in Scripts, not bin, so without this the test above
    # would call a perfectly good one broken and delete it.
    if [ -e ".venv/Scripts/python.exe" ]; then
        echo "That .venv was made on Windows. Use build.bat there; this script"
        echo "is for macOS and Linux, and the two cannot share one venv."
        exit 1
    fi
    if [ -d ".venv" ]; then
        echo "The .venv here is broken -- most likely it points at a Python"
        echo "that has been upgraded or removed. Making it again."
        rm -rf .venv
    else
        echo "No .venv here yet. Making one."
    fi
    if ! command -v "$PYTHON" >/dev/null 2>&1; then
        echo "$PYTHON is not on PATH. Install Python 3, or point this at one:"
        echo "    PYTHON=/opt/homebrew/bin/python3.12 bash build.sh"
        exit 1
    fi
    "$PYTHON" -m venv .venv
    echo "Installing what it needs. This fetches about 200 MB the first time."
    .venv/bin/python -m pip install --quiet --upgrade pip
    .venv/bin/pip install -r requirements.txt
    echo
else
    # An existing .venv is not assumed to hold everything the list asks for.
    # It cost a mac its Download button once: the build carried no bundle of
    # trusted roots because certifi had been added to the list after that
    # .venv was made. Satisfied already, this is a second and says nothing.
    .venv/bin/pip install --quiet -r requirements.txt
fi

if [ ! -f "baked/scene_mesh.npz" ]; then
    echo "No baked scene. Run this first:"
    echo "    blender -b ../Prepare.blend --factory-startup -P bake_mesh.py -- baked"
    exit 1
fi

# Not fatal: the upgrade is a nicety, and it is the step most likely to fail on
# a machine where something was once run under sudo and part of the venv now
# belongs to root. PyInstaller already being there is enough to build.
if ! .venv/bin/python -m pip install --quiet --upgrade pyinstaller 2>/dev/null; then
    echo "could not upgrade pyinstaller; using the one that is installed"
fi

if [ ! -x ".venv/bin/pyinstaller" ]; then
    echo "PyInstaller is missing and could not be installed. The usual cause is"
    echo "a virtual environment that belongs to root after a sudo pip. Either:"
    echo '    sudo chown -R "$(whoami)" .venv ~/Library/Caches/pip'
    echo "or throw it away and make it again, without sudo:"
    echo "    rm -rf .venv"
    echo "    python3 -m venv .venv"
    echo "    .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# On macOS, carry a hap-capable ffmpeg inside the .app so a re-bake to Hap Q
# Alpha works out of the box instead of waiting on the first-run Download
# button. The evermeet build is the one depends.py would have downloaded and it
# has the snappy that hap needs. This is deliberately mac-only: the Windows
# BtbN build already has hap and Linux installs it from the package manager, so
# the spec bundles nothing there.
#
# Note the tradeoff the rest of the code was written to avoid: ffmpeg is GPL,
# and shipping it inside a redistributed binary carries the GPL's obligations.
# Done here because the user asked for a self-contained mac build.
#
# Best-effort and idempotent: an already-vendored copy is reused, an explicit
# MATRESHKA_FFMPEG is honoured, and a failed fetch only warns -- the build then
# carries no ffmpeg and the app falls back to finding or downloading one.
if [ "$(uname)" = "Darwin" ] && [ -z "${MATRESHKA_FFMPEG:-}" ]; then
    vendored="vendor/ffmpeg"
    if [ ! -x "$vendored" ]; then
        echo "Fetching a hap-capable ffmpeg to bundle (evermeet)..."
        ffmpeg_url="https://evermeet.cx/ffmpeg/getrelease/zip"
        work="$(mktemp -d)"
        if curl -fL --silent --show-error -A MatreshkaViewer \
                -o "$work/ffmpeg.zip" "$ffmpeg_url" \
           && unzip -o -q "$work/ffmpeg.zip" -d "$work"; then
            found="$(find "$work" -maxdepth 2 -name ffmpeg -type f | head -n 1)"
            if [ -n "$found" ]; then
                mkdir -p vendor
                mv "$found" "$vendored"
                chmod +x "$vendored"
                echo "Vendored ffmpeg at tool/$vendored"
            else
                echo "warning: no ffmpeg in the archive; building without a bundle"
            fi
        else
            echo "warning: could not fetch ffmpeg; building without a bundle"
        fi
        rm -rf "$work"
    fi
    if [ -x "$vendored" ]; then
        export MATRESHKA_FFMPEG="$(cd "$(dirname "$vendored")" && pwd)/ffmpeg"
    fi
fi

# CODESIGN_IDENTITY is read by the spec. Without it the build is unsigned,
# which is fine for carrying between machines by hand -- the first run needs
# right-click > Open, or:  xattr -dr com.apple.quarantine MatreshkaViewer.app
.venv/bin/pyinstaller \
    --noconfirm \
    --distpath ".." \
    --workpath "build" \
    build.spec

echo
if [ -d "../MatreshkaViewer.app" ]; then
    echo "Built: $(cd .. && pwd)/MatreshkaViewer.app"
else
    echo "Built: $(cd .. && pwd)/MatreshkaViewer"
fi
