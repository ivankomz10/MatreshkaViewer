# PyInstaller spec for the Matreshka Viewer.
#
#   pyinstaller --noconfirm --distpath ".." --workpath "build" build.spec
#
# A spec rather than a command line because --exclude-module only reaches
# Python modules, and most of the weight here is Qt DLLs that PySide6 ships
# whether or not anything imports them.

import os
import sys

MAC = sys.platform == "darwin"

HERE = os.path.abspath(os.path.dirname(SPECPATH))
TOOL = HERE if os.path.exists(os.path.join(HERE, "main.py")) else SPECPATH

# Qt libraries nothing in this application touches. The window is plain
# widgets, and every pixel of the picture goes through wgpu's own Vulkan or
# Metal backend, so Qt's QML stack and its software OpenGL fallback are dead
# weight -- about 20 MB of it.
#
# Matched as a substring of the whole path, not as a file name: on Windows
# these are loose DLLs, on macOS they are frameworks with the library buried
# inside a Versions/A folder and no suffix at all.
# Network is NOT in here, however unused it looks: Qt6Multimedia.dll imports
# it, and without it the sound module will not load at all. Checked by reading
# the import table rather than by reasoning about what a thing ought to need.
UNWANTED = (
    "Quick", "QuickControls2", "QuickTemplates2", "QuickWidgets",
    "Qml", "QmlModels", "QmlWorkerScript",
    "Pdf", "PdfWidgets",
    "Sql", "Test", "Designer",
)
UNWANTED_EXACT = ("opengl32sw.dll", "d3dcompiler_47.dll")


def keep(item):
    name = os.path.basename(item[0])
    if name in UNWANTED_EXACT:
        return False
    for part in UNWANTED:
        if f"Qt6{part}." in item[0] or f"Qt{part}.framework" in item[0]:
            return False
    return True


# The baked scene travels inside the executable: it is what makes the viewer a
# viewer rather than three rectangles, and a copy that can be left behind is a
# copy that will be.
baked = os.path.join(TOOL, "baked")
datas = [(os.path.join(baked, name), "baked")
         for name in sorted(os.listdir(baked))
         if name.endswith((".npz", ".png"))]

# The loading picture travels too: the bootloader's own splash is Windows and
# Linux only, and on a mac the application puts the same picture up itself.
datas += [(os.path.join(TOOL, "splash.png"), ".")]

# And the button icons, which are Houdini's -- see the note in that folder.
icons = os.path.join(TOOL, "icons")
datas += [(os.path.join(icons, name), "icons")
          for name in sorted(os.listdir(icons))
          if name.endswith(".png")]

# An ffmpeg carried inside the build, when one is provided. depends.py normally
# finds ffmpeg on the machine or offers to download it; the note at the top of
# that module explains why shipping one is usually left alone -- it is large and
# a GPL build inside a redistributed binary carries the GPL's obligations with
# it. The mac build carries one on purpose (see build.sh): the evermeet build
# has the snappy that hap needs, so a re-bake to Hap Q Alpha works out of the
# box rather than waiting on the first-run Download button.
#
# It is optional and additive: with no source, the build is exactly as before
# and the application falls back to finding or downloading ffmpeg. The source is
# an ffmpeg binary named by MATRESHKA_FFMPEG, or a vendored tool/vendor/ffmpeg.
# It travels as data, landing at _MEIPASS/ffmpeg/<binary> to match
# depends.bundled_ffmpeg(); data drops the exec bit, so depends.py chmods it at
# run time for unsigned builds.
FFMPEG_BINARY = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
ffmpeg_source = os.environ.get("MATRESHKA_FFMPEG") \
    or os.path.join(TOOL, "vendor", FFMPEG_BINARY)
if os.path.isfile(ffmpeg_source):
    # depends.bundled_ffmpeg() looks for exactly _MEIPASS/ffmpeg/<binary>, so
    # the name has to be that whatever the source was called. A datas entry
    # keeps the source's own name, so a differently named source is copied to
    # the wanted name beside the workpath first.
    if os.path.basename(ffmpeg_source) != FFMPEG_BINARY:
        import shutil as _shutil
        staged_dir = os.path.join(TOOL, "build", "ffmpeg")
        os.makedirs(staged_dir, exist_ok=True)
        staged = os.path.join(staged_dir, FFMPEG_BINARY)
        _shutil.copy2(ffmpeg_source, staged)
        ffmpeg_source = staged
    datas += [(ffmpeg_source, "ffmpeg")]
    print(f"build.spec: bundling ffmpeg from {ffmpeg_source}")
else:
    print("build.spec: no ffmpeg to bundle; the app will find or download one")

a = Analysis(
    [os.path.join(TOOL, "main.py")],
    pathex=[TOOL],
    binaries=[],
    datas=datas,
    hiddenimports=["rendercanvas.pyside6"],
    excludes=[
        "cv2", "tkinter", "matplotlib", "scipy", "PIL", "pandas",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        # QtMultimedia stays: the sound row plays a WAV through QAudioSink.
        "PySide6.QtQuick", "PySide6.QtQml",
        "PySide6.QtCharts", "PySide6.QtPdf",
        "PySide6.QtOpenGL", "PySide6.Qt3DCore", "PySide6.QtSql",
    ],
    noarchive=False,
)

a.binaries = [item for item in a.binaries if keep(item)]
a.datas = [item for item in a.datas if keep(item)]

pyz = PYZ(a.pure)

# A one-file build spends its first seconds unpacking, before Python is even
# running, and nothing on screen says so. The splash comes from the bootloader
# itself, so it is up in that gap; once Python starts, every line written to
# the log is also written across it, and it closes when the window appears.
# Windows and Linux only -- PyInstaller has no splash for macOS, and the mac
# build is a folder that starts at once anyway.
splash = None if MAC else Splash(
    os.path.join(TOOL, "splash.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(30, 152),
    text_size=9,
    text_color="#b0b0b0",
    text_default="unpacking...",
    minify_script=True,
    always_on_top=False,
)

# One file on Windows, a folder on macOS, and the difference matters.
#
# A one-file build is a stub that unpacks the whole archive into a temporary
# folder on *every* launch and then starts a second process to run it. That is
# why it takes seconds to appear and why two processes show up: the parent is
# the unpacker, the child is the application.
#
# On Windows one file is worth that, because a single .exe is the thing you
# hand to somebody. On macOS it buys nothing: a .app is already a folder, so
# packing a folder into one file inside it only adds the unpacking. Built as a
# folder it starts at once, shows one process, and is the layout codesigning
# and notarisation expect.
exe = EXE(
    pyz,
    a.scripts,
    *([] if MAC else [splash, splash.binaries]),
    [] if MAC else a.binaries,
    [] if MAC else a.datas,
    [],
    exclude_binaries=MAC,
    name="MatreshkaViewer",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    # The machine's own architecture, which is what you want on the machine you
    # are testing on. A universal binary needs a universal Python and universal
    # wheels for every compiled dependency; a Homebrew Python is arm64 alone,
    # and PyInstaller stops with "is not a fat binary". Ask for it explicitly
    # if the whole toolchain is universal:
    #
    #     MATRESHKA_ARCH=universal2 ./build.sh
    target_arch=(os.environ.get("MATRESHKA_ARCH") or None) if MAC else None,
    codesign_identity=os.environ.get("CODESIGN_IDENTITY") or None,
    entitlements_file=None,
)

if MAC:
    collected = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="MatreshkaViewer",
    )
    # And the bundle around it: without one there is no Dock icon, no name in
    # the menu bar, and Gatekeeper has nothing to attach a quarantine decision
    # to.
    app = BUNDLE(
        collected,
        name="MatreshkaViewer.app",
        icon=None,
        bundle_identifier="ru.zaryadye.matreshkaviewer",
        info_plist={
            "CFBundleName": "Matreshka Viewer",
            "CFBundleDisplayName": "Matreshka Viewer",
            "CFBundleShortVersionString": "0.3",
            "CFBundleVersion": "0.3",
            "LSMinimumSystemVersion": "11.0",
            # Otherwise the window is drawn at half resolution and upscaled,
            # which on a preview tool is the one thing that must not happen.
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
