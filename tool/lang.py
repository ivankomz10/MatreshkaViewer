"""The window's language: Russian, which it is written in, or English.

Every word the window shows goes through `tr`. The Russian is the source --
it is what the code says -- and English is looked up from it in lang_en.py,
so a string with no English yet stays Russian rather than going blank. A
string with something put into it is a template, with the pieces numbered
in the order the code hands them over:

    tr("кадр {0} из {1}", at, last)

The log stays English whichever is chosen: it is for working out what went
wrong, and it is read by the people who read the code.

Switching is done where the window stands (see `Viewer._retranslate`):
every word on it is looked up in the other language and put back in its
place, and what the window works out as it goes -- the status line, what a
card says of its file -- is worked out again. For that each English string
answers for exactly one Russian one; the tests hold the dictionary to it.
"""
from __future__ import annotations

from lang_en import EN

LANGUAGES = ("ru", "en")
_current = "ru"
_back = {english: russian for russian, english in EN.items()}


def set_language(code: str) -> str:
    """Make `code` the language, if it is one; say which it is now."""
    global _current
    code = str(code or "").lower()
    if code in LANGUAGES:
        _current = code
    return _current


def language() -> str:
    return _current


def tr(text: str, *pieces) -> str:
    """The words in the window's language, with the pieces put in."""
    if _current == "en":
        text = EN.get(text, text)
    return text.format(*pieces) if pieces else text


def other(text: str, to: str):
    """`text` in language `to`, when it is words the window says in the other
    one; None when it is not -- a name, a number, a path, a sentence with
    something put into it."""
    if to == "en":
        return EN.get(text)
    return _back.get(text)


def either(text: str) -> set:
    """The same words in both languages: for a settings file written in the
    other one, whose lists said their lines in it."""
    text = str(text)
    return {text, EN.get(text, text), _back.get(text, text)}
