Building the viewer on macOS
============================

Nothing here has been run on a Mac. It is a scaffold: the parts known to differ
are handled, and the parts that cannot be checked from Windows are listed at
the end as exactly that.


Apple silicon: handled
----------------------
HAP frames are DXT blocks handed to the GPU without being decoded. Metal reads
those on Mac family GPUs -- the Intel and AMD chips in Intel Macs -- and not on
Apple family, which is every M-series machine. Apple exposes the difference as
`MTLDevice.supportsBCTextureCompression`; wgpu turns it into the
`texture-compression-bc` feature being offered or not.

Where it is not offered, `blockdecode.py` unpacks the blocks in a compute pass
and hands on an ordinary texture. The processor still decodes nothing, and
nothing above the plane knows which of the two paths it is on -- in particular
the YCoCg transform stays in the drawing shaders, so both paths run the same
colour code.

Measured on this machine, on the real Character City files:

  the pass itself            0.41 ms for 4608x1584, under 1 ms for all six
                             planes of the three screens
  against the hardware       colour max 3 of 255, alpha bit for bit
  against ffmpeg's decoder   max 3 of 255, the same band the hardware lands in
  playing three 60 fps HAPs  58.1 frames a second, against 58.9 in hardware

Formats: DXT1, DXT5 and RGTC1 are decoded, which covers everything Hap and Hap
Q Alpha produce. BC7 is refused in words rather than implemented on
speculation -- no content here uses it, and it is a table-driven decoder
several hundred lines long.

To walk this path on a machine that does not need it, which is how all of the
above was measured:

    MATRESHKA_NO_BC=1 ./MatreshkaViewer

The log says which path it took on every run.

So the expectation is that M-series works. It has not been seen working, and
that is a different sentence.


Building
--------
    cd tool
    bash build.sh

That is the whole of it. The script makes its own virtual environment and
installs what it needs the first time, which fetches about 200 MB; after that
it goes straight to the build. To use a particular interpreter:

    PYTHON=/opt/homebrew/bin/python3.12 bash build.sh

`bash build.sh` rather than `./build.sh` because it does not care whether the
executable bit survived unpacking. If it did, both work.

Do not run any of that under sudo. pip inside a venv needs no privileges, and
a `sudo pip` leaves ~/Library/Caches/pip owned by root, after which every later
pip prints a warning and runs with its cache disabled. If that has already
happened:

    sudo chown -R "$(whoami)" ~/Library/Caches/pip

`build.sh` mirrors `build.bat`. It checks for the venv and the baked scene,
then runs `build.spec`, which knows about macOS:

  * the machine's own architecture, which is what you want on the machine you
    are testing on. A universal binary needs a universal Python *and* universal
    wheels for every compiled dependency; a Homebrew Python is arm64 alone, and
    PyInstaller stops with "is not a fat binary". If the whole toolchain really
    is universal, ask for it:

        MATRESHKA_ARCH=universal2 ./build.sh

  * a `BUNDLE` step, so the result is `MatreshkaViewer.app` rather than a bare
    binary -- otherwise there is no Dock icon and no name in the menu bar.
  * Qt exclusions matched on the whole path, because on macOS those libraries
    are frameworks rather than loose files.

  * a folder rather than one file. A one-file build is a stub that unpacks the
    whole archive into a temporary folder on *every* launch and then starts a
    second process to run it -- which is why such a build takes seconds to
    appear and shows two processes. On Windows one file is worth that, because
    a single .exe is the thing you hand somebody. Inside a .app it buys
    nothing: the bundle is already a folder. Built this way it starts at once,
    shows one process, and is the layout codesigning and notarisation expect.

The baked scene travels inside the bundle. ffmpeg does not.


Signing and quarantine
----------------------
Unsigned unless `CODESIGN_IDENTITY` is set:

    CODESIGN_IDENTITY="Developer ID Application: ..." ./build.sh

Unsigned is fine for carrying a build between machines by hand, but the first
run needs right-click > Open, or the quarantine flag removed:

    xattr -dr com.apple.quarantine MatreshkaViewer.app


ffmpeg
------
Only RENDER and the video snapshot need it; watching does not. Looked for in
this order: an `ffmpeg` folder beside the .app, then PATH, then the Download
button in the first-run check, which fetches a build from evermeet.cx into that
folder. Nothing is installed and nothing goes on PATH.

"Beside the .app" means beside the bundle, not inside it -- `logfile.app_dir()`
walks out of `Contents/MacOS` on purpose, and Logs, OUT and settings.json land
there too. That keeps a bundle you can delete without leaving anything behind.


Already handled, and why
------------------------
Learned the hard way on the renderer next door; listed so nobody spends the
afternoon again.

  * **`-vsync` is gone in ffmpeg 8.** This project never used it. Frames go in
    as rawvideo on stdin with `-framerate`, and nothing needs a sync mode.
  * **VideoToolbox H.264 stops at 4096 across.** So does NVENC. Rather than
    tabulating limits the encoder is asked: it is run at the real size and
    dropped for the software one if it refuses.
  * **ProRes has hardware too.** Apple's chips from the M1 Pro up carry an
    engine for it, and `prores_videotoolbox` is tried before `prores_ks`, which
    is one of the slowest things ffmpeg does. Same probe, same fallback.
  * **`-allow_sw` is a trap.** VideoToolbox's software fallback is slower than
    libx264, so a refusal that can be seen beats a render nobody can wait out.
    It is deliberately not passed.
  * **`subprocess.CREATE_NO_WINDOW` does not exist off Windows.** Fetched with
    `getattr(..., 0)` everywhere it is used.
  * **A frozen app inside a bundle.** `logfile.app_dir()` walks up past the
    `.app` so the folders it makes land beside it.


Not checked from here
---------------------
  * whether Metal offers `rgba8unorm` as a storage texture format. It is core
    WebGPU, so it should, but the compute path needs it and has only been run
    on Vulkan.
  * how long the first launch takes -- onefile unpacks itself to a temporary
    folder every run, and it is about 95 MB
  * whether Metal reports the canvas format as `bgra8unorm`. If the screens
    come out with red and blue swapped, that is where to look: the snapshot
    path already handles it, the canvas takes what it is given.
