"""What the application needs from the machine, and how to get it.

Carried over from the renderer next door. Only ffmpeg is fetched, and only
because writing the preview out needs it -- watching one does not, so a
machine that never exports never has to have it.

Everything Python is inside the executable. The one thing that is not is
ffmpeg: it is the render pipeline's decoder and encoder, it is large, and its
licence makes shipping a build inside someone else's binary a question better
left alone. So it is looked for, and offered.

A downloaded copy lands in a folder beside the application rather than anywhere
system-wide -- nothing is installed, nothing is put on PATH, and deleting the
folder undoes it completely.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import logfile

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

TOOLS_DIR = "ffmpeg"                     # beside the application
BINARY = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"

# Direct archives, one per platform. Both are the builds their communities
# point at; both are plain zips holding the binary and nothing to install.
DOWNLOADS = {
    "win32": (
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
        "ffmpeg-master-latest-win64-gpl.zip",
        163,
    ),
    "darwin": ("https://evermeet.cx/ffmpeg/getrelease/zip", 30),
}

# Where there is no single archive worth hard-coding, say so instead.
ADVICE = {
    "linux": "install ffmpeg with the package manager, e.g. apt install ffmpeg",
}


# Where a package manager leaves it when PATH does not say so. An application
# started from Finder inherits none of the shell's PATH -- it gets
# /usr/bin:/bin:/usr/sbin:/sbin and nothing more -- so a Homebrew ffmpeg sits
# on the disk and `which` cannot see it. These are the places worth a look:
# Homebrew on Apple silicon, Homebrew on Intel, MacPorts.
ELSEWHERE = {
    "darwin": ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"),
    "linux": ("/usr/local/bin", "/snap/bin"),
}


@dataclass
class Requirement:
    """One thing that was looked for."""

    name: str
    ok: bool
    detail: str
    required: bool = True
    fixable: bool = False
    detail_ok: str = ""
    # What is lost without it, for the sentence at the foot of the checks.
    when_absent: str = ""


def tools_dir() -> Path:
    return logfile.app_dir() / TOOLS_DIR


def ffmpeg_candidates() -> list[str]:
    """Every ffmpeg this machine offers, in the order they are preferred.

    The downloaded one beside the application first, then whatever PATH says,
    then the handful of places a package manager would have put it. The last
    of those is for the Mac, where PATH inside the application is not the PATH
    in the terminal that installed it.
    """
    found = []
    local = tools_dir() / BINARY
    if local.is_file():
        found.append(str(local))
    on_path = shutil.which("ffmpeg")
    if on_path:
        found.append(on_path)
    for folder in ELSEWHERE.get(sys.platform, ()):
        candidate = Path(folder) / BINARY
        if candidate.is_file() and os.access(candidate, os.X_OK):
            found.append(str(candidate))
    return list(dict.fromkeys(found))          # order kept, repeats dropped


def ffmpeg_command() -> str:
    """The ffmpeg to use when it does not matter which."""
    candidates = ffmpeg_candidates()
    return candidates[0] if candidates else "ffmpeg"


_BUILT_WITH: dict[str, set[str]] = {}


def encoders_of(command: str) -> set[str]:
    """Which video encoders that particular ffmpeg was built with."""
    if command not in _BUILT_WITH:
        try:
            listing = subprocess.run(
                [command, "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=20,
                creationflags=NO_WINDOW).stdout
            _BUILT_WITH[command] = {line.split()[1]
                                    for line in listing.splitlines()
                                    if line.startswith(" V")
                                    and len(line.split()) > 1}
        except Exception:  # noqa: BLE001 -- absence is the answer
            _BUILT_WITH[command] = set()
    return _BUILT_WITH[command]


def forget_ffmpeg() -> None:
    """Ask everything again -- a copy may have arrived since."""
    _BUILT_WITH.clear()


def ffmpeg_for(encoder: str) -> str:
    """The ffmpeg to use for one particular encoder.

    Not every build has every one, and the difference is not cosmetic: hap
    needs snappy, the usual Homebrew build is made without it, and the copy
    this application downloads has it. Picking by what a build can actually
    do, rather than by which was found first, is the difference between a
    re-bake that works and one that stops on the first frame saying "Broken
    pipe" while a perfectly good ffmpeg sits in the next folder.
    """
    if not encoder:
        return ffmpeg_command()
    for candidate in ffmpeg_candidates():
        if encoder in encoders_of(candidate):
            return candidate
    return ffmpeg_command()


def can_encode(encoder: str) -> bool:
    """Whether anything on this machine can encode that."""
    return any(encoder in encoders_of(one) for one in ffmpeg_candidates())


def ffmpeg_version(command: str | None = None) -> str:
    """The first line of `ffmpeg -version`, or an empty string if it will not run."""
    try:
        first = subprocess.run(
            [command or ffmpeg_command(), "-hide_banner", "-version"],
            capture_output=True, text=True, timeout=20,
            creationflags=NO_WINDOW).stdout.splitlines()
        return first[0].strip() if first else ""
    except Exception:  # noqa: BLE001 -- absence is the answer
        return ""


def gpu() -> tuple[str, bool, str]:
    """The adapter, whether it can read compressed textures, and why not.

    Both answers come from one look at the adapter because asking twice can
    give two different ones: on a laptop with two GPUs the second request may
    land on the other card.
    """
    try:
        import wgpu

        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        if adapter is None:
            return "", False, "no GPU adapter at all"
        info = adapter.info
        name = f"{info.get('device', 'unknown')} "                f"({info.get('backend_type', '')})".strip()
        if "texture-compression-bc" not in [str(f) for f in adapter.features]:
            return name, False, "cannot read compressed textures"
        if os.environ.get("MATRESHKA_NO_BC"):
            # The same override the device honours. Reported here too, or the
            # log contradicts itself in exactly the situation someone set it
            # to investigate.
            return name, False, "MATRESHKA_NO_BC is set"
        return name, True, ""
    except Exception as error:  # noqa: BLE001 -- any failure is a refusal
        return "", False, str(error)



def can_download() -> bool:
    return sys.platform in DOWNLOADS


def download_size_mb() -> int:
    return DOWNLOADS.get(sys.platform, ("", 0))[1]


def check() -> list[Requirement]:
    """Look for everything, in the order it matters."""
    found = []

    # First, because a machine with no GPU at all has nothing for this
    # application to do.
    name, blocks, why = gpu()
    found.append(Requirement("GPU", bool(name), name or why))
    # Not a requirement any more, only a difference in how the frames get
    # there: a card without it has its blocks unpacked by a compute pass at
    # about half a millisecond a frame. Apple silicon is the case in practice.
    found.append(Requirement(
        "Compressed textures", True,
        "texture-compression-bc -- blocks go straight to the sampler" if blocks
        else f"not on this GPU ({why or 'no such feature'}), so the blocks are "
             f"unpacked by a compute pass instead -- under a millisecond a frame",
        required=False))

    command = ffmpeg_command()
    version = ffmpeg_version(command)
    if version:
        where = "beside the application" if command != "ffmpeg" \
            and str(tools_dir()) in command else command
        found.append(Requirement("ffmpeg", True, f"{version[:70]}   [{where}]",
                                 when_absent="nothing can be written out"))
        # Whether it can write Hap is a second question, and the answer is no
        # more than half the time: hap needs snappy, and the usual Homebrew
        # build is made without it. Its own line, because "ffmpeg is here" and
        # "the re-bake can run" stopped being the same sentence.
        if not can_encode("hap"):
            found.append(Requirement(
                "ffmpeg with hap", False,
                "this one has no hap encoder -- it wants a build made with "
                "snappy. Watching and rendering are unaffected; re-baking to "
                "Hap Q Alpha needs one. Download fetches a build that has it.",
                required=False, fixable=can_download(),
                when_absent="ReBake can only write ProRes"))
    else:
        found.append(Requirement(
            "ffmpeg", False,
            ADVICE.get(sys.platform, "only RENDER and Snap to video need it; "
                                     "watching does not"),
            required=False, fixable=can_download()))

    return found


AGENT = "MatreshkaRemapRenderer"


def certificates() -> str | None:
    """The file of trusted roots to check the download's certificate against.

    A frozen build carries its own Python, and that Python's OpenSSL looks for
    a CA file where the machine that built it kept one. On a mac built with
    Homebrew that is a path inside Homebrew, and a mac without Homebrew has
    nothing there: the download then fails with CERTIFICATE_VERIFY_FAILED
    having never had anything to verify against. certifi's bundle travels
    inside the build, so there is always something.

    None means "use whatever this machine has", which is right when running
    from source and on Windows, where the store is the system's own.
    """
    try:
        import certifi
    except Exception:                   # noqa: BLE001 -- not in this build
        return None
    where = certifi.where()
    return where if os.path.exists(where) else None


def _fetch_with_python(url: str, target: Path, on_progress, should_stop) -> None:
    """The download as Python does it, checked against the roots above."""
    import ssl
    import urllib.request

    context = ssl.create_default_context(cafile=certificates())
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=60, context=context) as answer:
        total = int(answer.headers.get("Content-Length") or 0)
        done = 0
        with open(target, "wb") as writing:
            while True:
                if should_stop is not None and should_stop():
                    raise RuntimeError("cancelled")
                block = answer.read(1 << 20)
                if not block:
                    break
                writing.write(block)
                done += len(block)
                if on_progress is not None:
                    on_progress(done, total)


def _is_certificate_trouble(error: Exception) -> bool:
    """Whether what went wrong was the certificate rather than the network."""
    import ssl
    if isinstance(error, ssl.SSLError):
        return True
    reason = getattr(error, "reason", None)
    return isinstance(reason, ssl.SSLError)


def _fetch_with_curl(url: str, target: Path, on_progress, should_stop) -> None:
    """The same download through curl, which has the machine's own roots.

    For the case above where the build's own store is no use: macOS has always
    had curl, it trusts what the machine trusts, and this asks nothing of
    whoever is using the application.
    """
    curl = shutil.which("curl")
    if curl is None:
        raise RuntimeError("no certificates this build can verify against, "
                           "and no curl to fall back on -- install ffmpeg "
                           "yourself and put it on PATH")
    running = subprocess.Popen(
        [curl, "-fL", "--silent", "--show-error", "-A", AGENT,
         "-o", str(target), url],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=NO_WINDOW)
    import time
    while running.poll() is None:
        if should_stop is not None and should_stop():
            running.kill()
            raise RuntimeError("cancelled")
        if on_progress is not None:
            # No length to count against -- curl knows it and is not saying,
            # so the bar is told how much has landed and nothing about the end.
            on_progress(target.stat().st_size if target.exists() else 0, 0)
        time.sleep(0.2)
    if running.returncode:
        said = (running.stderr.read() or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"curl could not fetch it: {said[:120]}")


def fetch_archive(url: str, target: Path, on_progress=None,
                  should_stop=None) -> None:
    """The archive on disk, by whichever way this machine can reach it."""
    try:
        _fetch_with_python(url, target, on_progress, should_stop)
    except Exception as trouble:        # noqa: BLE001 -- sorted out here
        if not _is_certificate_trouble(trouble):
            target.unlink(missing_ok=True)
            raise
        # Nothing to verify against, or nothing that knows this certificate.
        # curl trusts what the machine trusts; on the mac where this turned up
        # that is the difference between a download and a dead button.
        logfile.write(f"ffmpeg download: {trouble}; trying curl instead")
        _fetch_with_curl(url, target, on_progress, should_stop)


def install_ffmpeg(on_progress=None, should_stop=None) -> Path:
    """Fetch the archive for this platform and keep only the binary.

    Returns the path it was written to. Everything happens under a temporary
    name and is moved into place at the end, so an interrupted download cannot
    leave something half-written that looks usable.
    """
    import tempfile

    if not can_download():
        raise RuntimeError(f"no download for {sys.platform}")
    try:
        import urllib.request
        import ssl  # noqa: F401 -- present or not, that is the question
    except ImportError as error:
        raise RuntimeError(
            f"this build cannot reach the network ({error}); "
            f"install ffmpeg yourself and put it on PATH") from error

    url, _ = DOWNLOADS[sys.platform]
    folder = tools_dir()
    folder.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False,
                                     dir=str(folder)) as archive:
        temporary = Path(archive.name)
    fetch_archive(url, temporary, on_progress, should_stop)

    try:
        with zipfile.ZipFile(temporary) as bundle:
            wanted = next(
                (item for item in bundle.namelist()
                 if Path(item).name.lower() == BINARY.lower()), None)
            if wanted is None:
                raise RuntimeError(f"{BINARY} is not in the archive")
            with bundle.open(wanted) as source:
                landing = folder / (BINARY + ".part")
                landing.write_bytes(source.read())
    finally:
        temporary.unlink(missing_ok=True)

    target = folder / BINARY
    target.unlink(missing_ok=True)
    landing.rename(target)
    if sys.platform != "win32":
        target.chmod(target.stat().st_mode | 0o755)

    if not ffmpeg_version(str(target)):
        target.unlink(missing_ok=True)
        raise RuntimeError("the downloaded ffmpeg would not run")
    return target


def summary() -> str:
    """One line for the log."""
    parts = []
    for item in check():
        parts.append(f"{item.name}: {'ok' if item.ok else 'MISSING'}")
    return f"{platform.system()} {platform.release()}   " + "   ".join(parts)
