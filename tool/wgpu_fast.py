"""wgpu's C interface prepared ahead of time, as a game prepares its shaders.

wgpu-py describes wgpu-native to cffi by its C header and lets cffi read it
at run time. Reading it is not the slow part; every struct the program first
asks for is: cffi parses its name with pycparser against the whole header,
again for each new one -- 76 of them before the first frame, 3.1 of the 4.5
seconds the window took to build (measured 2026-10-15).

cffi can do that work once, ahead: an "out-of-line ABI" module carries the
parsed header as a table that its C core reads at once. `generate` writes that
module (wgpu_ffi_built.py, beside this file) from the header of the wgpu that
is installed; the build makes it, and a run from source makes it the first
time it is missing or out of date. `install` puts it under wgpu before wgpu
loads, so wgpu never knows: its `ffi` is this one, with nothing to parse.

A header that has changed since the module was made -- a new wgpu -- is seen
by its hash, and then wgpu reads the header as it always did.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

NAME = "wgpu_ffi_built"
HERE = Path(__file__).resolve().parent


def _header() -> Path | None:
    spec = importlib.util.find_spec("wgpu")
    if spec is None or not spec.submodule_search_locations:
        return None
    found = Path(list(spec.submodule_search_locations)[0]) / "resources" / "combined_header.h"
    return found if found.is_file() else None


def _stamp(header: Path) -> str:
    return hashlib.sha1(header.read_bytes()).hexdigest()[:16]


def generate(folder: Path = HERE) -> Path:
    """Write the prepared interface for the installed wgpu into `folder`."""
    from cffi import FFI
    header = _header()
    if header is None:
        raise RuntimeError("wgpu's header is not where wgpu keeps it")
    builder = FFI()
    builder.cdef(header.read_text(encoding="utf-8"))
    builder.set_source(NAME, None)
    target = folder / f"{NAME}.py"
    builder.emit_python_code(str(target))
    with open(target, "a", encoding="utf-8") as out:
        out.write(f"\n# The header this was made from, so a new wgpu is noticed.\n"
                  f"STAMP = {_stamp(header)!r}\n")
    return target


class _Prepared:
    """The prepared ffi, standing in for the FFI() wgpu makes: its cdef and
    set_source have been done already."""

    def __init__(self, ffi) -> None:
        self.__dict__["_ffi"] = ffi

    def cdef(self, *args, **kwargs) -> None:
        pass

    def set_source(self, *args, **kwargs) -> None:
        pass

    def __getattr__(self, name):
        return getattr(self._ffi, name)


def install() -> str:
    """Before wgpu is imported: hand it the prepared interface.

    Says what it did: "prepared", "made" (and prepared), "stale" or "late"
    (wgpu reads its header itself)."""
    if "wgpu.backends.wgpu_native._ffi" in sys.modules:
        return "late"
    header = _header()
    if header is None:
        return "stale"
    stamp = _stamp(header)
    said = "prepared"
    try:
        built = importlib.import_module(NAME)
    except ImportError:
        built = None
    if built is None or getattr(built, "STAMP", None) != stamp:
        if getattr(sys, "frozen", False):
            return "stale"
        try:
            generate()
        except Exception:  # noqa: BLE001 -- wgpu then does it the slow way
            return "stale"
        sys.modules.pop(NAME, None)
        importlib.invalidate_caches()
        built = importlib.import_module(NAME)
        said = "made"
    import cffi
    real = cffi.FFI

    def first(*args, **kwargs):
        # The one FFI() wgpu makes; after it, cffi is as it was.
        cffi.FFI = real
        return _Prepared(built.ffi)

    cffi.FFI = first
    return said
