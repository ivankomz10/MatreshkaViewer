"""Fetching ffmpeg: where the trusted roots come from, and the way round.

On a mac the Download button did nothing but say
CERTIFICATE_VERIFY_FAILED -- unable to get local issuer certificate. A frozen
build carries its own Python, whose OpenSSL looks for a CA file where the
machine that built it kept one; a mac without Homebrew has nothing there and
so has nothing to verify against.

Nothing here downloads anything. What is checked is that the build has a
bundle of roots to point at, and that a certificate failure -- and only a
certificate failure -- falls back to curl, which trusts what the machine
trusts.
"""
from __future__ import annotations

import ssl
import urllib.error
from pathlib import Path

import depends
import pytest


def test_the_build_carries_a_file_of_trusted_roots():
    where = depends.certificates()
    assert where is not None, (
        "no certifi in this build: a frozen mac has nothing to verify a "
        "download against")
    assert Path(where).exists(), where
    assert Path(where).stat().st_size > 100_000, "that bundle looks too small"


def test_a_certificate_failure_is_told_apart_from_a_dead_network():
    cert = ssl.SSLCertVerificationError("unable to get local issuer certificate")
    assert depends._is_certificate_trouble(cert)
    assert depends._is_certificate_trouble(urllib.error.URLError(cert))
    assert not depends._is_certificate_trouble(
        urllib.error.URLError(OSError("no route to host")))
    assert not depends._is_certificate_trouble(RuntimeError("cancelled"))


def test_a_certificate_failure_falls_back_to_curl(tmp_path, monkeypatch):
    tried = []

    def no_roots(url, target, on_progress, should_stop):
        tried.append("python")
        raise urllib.error.URLError(
            ssl.SSLCertVerificationError("unable to get local issuer certificate"))

    def by_curl(url, target, on_progress, should_stop):
        tried.append("curl")
        Path(target).write_bytes(b"PK\x03\x04 and the rest")

    monkeypatch.setattr(depends, "_fetch_with_python", no_roots)
    monkeypatch.setattr(depends, "_fetch_with_curl", by_curl)
    target = tmp_path / "ffmpeg.zip"
    depends.fetch_archive("https://example.invalid/ffmpeg.zip", target)
    assert tried == ["python", "curl"]
    assert target.exists(), "the fallback wrote nothing"


def test_anything_else_is_raised_rather_than_worked_around(tmp_path, monkeypatch):
    """A refused connection is not a certificate; curl would fail the same way."""
    def no_network(url, target, on_progress, should_stop):
        Path(target).write_bytes(b"half a file")
        raise urllib.error.URLError(OSError("no route to host"))

    def must_not_run(*_):
        raise AssertionError("curl was tried for something that is not a cert")

    monkeypatch.setattr(depends, "_fetch_with_python", no_network)
    monkeypatch.setattr(depends, "_fetch_with_curl", must_not_run)
    target = tmp_path / "ffmpeg.zip"
    with pytest.raises(urllib.error.URLError):
        depends.fetch_archive("https://example.invalid/ffmpeg.zip", target)
    assert not target.exists(), "a half-written archive was left behind"


def test_curl_is_asked_for_the_right_thing(monkeypatch, tmp_path):
    """The command, not the download: where it writes and that it follows on."""
    seen = {}

    class Ran:
        returncode = 0

        def __init__(self, argv, **rest):
            seen["argv"] = argv
            Path(argv[argv.index("-o") + 1]).write_bytes(b"PK\x03\x04")

        def poll(self):
            return 0

    monkeypatch.setattr(depends.subprocess, "Popen", Ran)
    monkeypatch.setattr(depends.shutil, "which", lambda name: "/usr/bin/curl")
    target = tmp_path / "ffmpeg.zip"
    depends._fetch_with_curl("https://example.invalid/x.zip", target, None, None)
    argv = seen["argv"]
    assert argv[0] == "/usr/bin/curl"
    assert "-fL" in argv, "curl must follow redirects; the mac archive is one"
    assert argv[argv.index("-o") + 1] == str(target)
    assert argv[-1] == "https://example.invalid/x.zip"


def test_without_curl_it_says_what_to_do_instead(monkeypatch, tmp_path):
    monkeypatch.setattr(depends.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError) as gone:
        depends._fetch_with_curl("https://example.invalid/x.zip",
                                 tmp_path / "x.zip", None, None)
    assert "PATH" in str(gone.value), str(gone.value)
