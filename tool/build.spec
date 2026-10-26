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
# What Blender runs to build the top screen's scene: a script for Blender's own
# Python, not the viewer's, so it goes as a file beside the modules
# (blender_export looks for it beside itself).
datas += [(os.path.join(TOOL, "blender_top.py"), ".")]

# And the button icons, which are Houdini's -- see the note in that folder.
icons = os.path.join(TOOL, "icons")
datas += [(os.path.join(icons, name), "icons")
          for name in sorted(os.listdir(icons))
          if name.endswith(".png")]

# The design's faces, IBM Plex, when they have been put in tool/fonts. Without
# them the window is set in Segoe UI and Cascadia Mono, and nothing breaks.
fonts = os.path.join(TOOL, "fonts")
if os.path.isdir(fonts):
    datas += [(os.path.join(fonts, name), "fonts")
              for name in sorted(os.listdir(fonts))
              if name.lower().endswith((".ttf", ".otf"))
              or name.lower().startswith(("ofl", "license"))]

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

# The remap page: its lookup tables, its icons and the layout map, under
# remap/ in the bundle, where remap/constants.py and remap/icons.py look.
remap = os.path.join(TOOL, "remap")
datas += [(os.path.join(remap, "tables", name), os.path.join("remap", "tables"))
          for name in sorted(os.listdir(os.path.join(remap, "tables")))
          if name.endswith(".npz")]
datas += [(os.path.join(remap, "icons", name), os.path.join("remap", "icons"))
          for name in sorted(os.listdir(os.path.join(remap, "icons")))
          if name.endswith(".png")]
datas += [(os.path.join(remap, "Check.png"), "remap")]

# wgpu's C interface, prepared now rather than parsed on every start (see
# wgpu_fast.py): made from the header of the wgpu this build packs.
sys.path.insert(0, TOOL)
import wgpu_fast  # noqa: E402
print(f"build.spec: prepared wgpu interface {wgpu_fast.generate()}")

a = Analysis(
    [os.path.join(TOOL, "main.py")],
    pathex=[TOOL],
    binaries=[],
    datas=datas,
    hiddenimports=["rendercanvas.pyside6", "remap.page", "kinedit", "wgpu_ffi_built"],
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

# The splash comes from the bootloader itself, so it is up before Python is
# running; once Python starts, every line written to the log is also written
# across it, and it closes when the window appears. Windows and Linux only --
# PyInstaller has no splash for macOS, and the mac build starts at once.
splash = None if MAC else Splash(
    os.path.join(TOOL, "splash.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(30, 152),
    text_size=9,
    text_color="#b0b0b0",
    text_default="loading...",
    minify_script=True,
    always_on_top=False,
)

# A folder on both systems now, and on Windows one file all the same.
#
# A one-file build unpacks its whole archive into a temporary folder on
# *every* launch -- two seconds before Python is even running. So on Windows
# the program is built as a folder, and that folder is packed onto the end of
# a small door, launcher.py, which is the MatreshkaViewer.exe handed over: the
# first start lays the folder out in bin/<build> beside it, every start after
# runs it from there at once, and an update writes only the files that
# changed (see launcher.py and binpack.py). On macOS a .app is a folder
# already.
exe = EXE(
    pyz,
    *([] if MAC else [splash]),
    a.scripts,
    [],
    exclude_binaries=True,
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

NATIVE_KINETIC = None
if not MAC:
    import re as _re
    import shutil as _shutil
    from pathlib import Path as _Path

    folder_name = "MatreshkaViewer_bin"
    COLLECT(exe, splash.binaries, a.binaries, a.datas, strip=False, upx=False,
            name=folder_name)

    # The door: a few megabytes of Python with the same picture, which shows
    # how far the laying out has gone.
    gate = Analysis(
        [os.path.join(TOOL, "launcher.py")],
        pathex=[TOOL],
        binaries=[],
        datas=[],
        hiddenimports=[],
        excludes=["numpy", "PySide6", "wgpu", "rendercanvas", "tkinter",
                  "unittest", "pydoc", "email", "http", "xml"],
        noarchive=False,
    )
    gate_splash = Splash(
        os.path.join(TOOL, "splash.png"),
        binaries=gate.binaries,
        datas=gate.datas,
        text_pos=(30, 152),
        text_size=9,
        text_color="#b0b0b0",
        text_default="Matreshka Viewer",
        minify_script=True,
        always_on_top=False,
    )
    EXE(
        PYZ(gate.pure),
        gate_splash,
        gate_splash.binaries,
        gate.scripts,
        gate.binaries,
        gate.datas,
        [],
        # Its own name while it is built -- the program inside is
        # MatreshkaViewer too, and the two would share the work files --
        # and the program's once it is packed.
        name="MatreshkaViewer_door",
        debug=False,
        strip=False,
        upx=False,
        console=False,
    )
    version = _re.search(r'^APP_VERSION = "([^"]+)"',
                         open(os.path.join(TOOL, "main.py"), encoding="utf-8").read(),
                         _re.M).group(1)
    sys.path.insert(0, TOOL)
    import binpack
    door = _Path(DISTPATH) / "MatreshkaViewer_door.exe"
    final = _Path(DISTPATH) / "MatreshkaViewer.exe"
    # The door in C when there is a compiler (door.c): it starts in
    # milliseconds, where the Python one spends most of a second unpacking its
    # own Python on every start. The Python one then only installs, from
    # inside it. Without a compiler the Python door is the door.
    native = _Path(TOOL) / "build" / "door_native.exe"
    kinetic_native = _Path(TOOL) / "build" / "door_kinetic.exe"
    source = _Path(TOOL) / "door.c"
    if binpack.compile_door(source, native) and \
            binpack.compile_door(source, kinetic_native, kinetic=True):
        packed = binpack.pack_native(native, door, _Path(DISTPATH) / folder_name,
                                     version, final)
        door.unlink()
        NATIVE_KINETIC = kinetic_native      # put in place once its own is built
        print("build.spec: the doors are native (door.c)")
    else:
        packed = binpack.pack(door, _Path(DISTPATH) / folder_name, version)
        os.replace(door, final)
        print("build.spec: no C compiler; the Python door it is")
    _shutil.rmtree(_Path(DISTPATH) / folder_name, ignore_errors=True)
    print(f"build.spec: packed build {packed['id']}, {len(packed['files'])} files")

# The kinetic editor's own name on Windows: MatreshkaKinetic.exe, a few
# megabytes that start MatreshkaViewer.exe --kinetic beside it (see
# kin_launcher.py). The editor itself is inside the viewer's executable, so it
# is not a second hundred megabytes of the same Qt and the same building. On
# macOS the editor is started the same way, from the viewer's bundle, with
# --kinetic.
if not MAC:
    door = Analysis(
        [os.path.join(TOOL, "kin_launcher.py")],
        pathex=[TOOL],
        binaries=[],
        datas=[],
        hiddenimports=[],
        excludes=["numpy", "PySide6", "wgpu", "rendercanvas", "tkinter",
                  "unittest", "pydoc", "email", "http", "xml"],
        noarchive=False,
    )
    EXE(
        PYZ(door.pure),
        door.scripts,
        door.binaries,
        door.datas,
        [],
        name="MatreshkaKinetic",
        debug=False,
        strip=False,
        upx=False,
        console=False,
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
            "CFBundleShortVersionString": "0.4",
            "CFBundleVersion": "0.4",
            "LSMinimumSystemVersion": "11.0",
            # Otherwise the window is drawn at half resolution and upscaled,
            # which on a preview tool is the one thing that must not happen.
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )

# The kinetic editor's door in C, when it was built, in place of the Python
# one just made: the same job, in milliseconds.
if NATIVE_KINETIC is not None:
    os.replace(NATIVE_KINETIC, os.path.join(DISTPATH, "MatreshkaKinetic.exe"))
