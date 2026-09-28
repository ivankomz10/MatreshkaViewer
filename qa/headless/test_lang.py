"""The window's words in English, read off the source.

Every word the window shows goes through tr() and has its English, with
the same numbered pieces: a string added without either fails here rather
than turning up in Russian in the middle of an English window. The windows
themselves, in English and switched, are in test_zz_language_window.py.
"""
from __future__ import annotations

import ast
import re
import string

from conftest import TOOL

MODULES = ("main.py", "timeline.py", "show.py", "kinetic.py", "sound.py",
           "depends.py", "scene3d.py")
# Said once, at import, and put through tr() where they are shown.
CONSTANTS = {"MODE_LABEL", "LAYER_LABEL", "CALLED", "SAID", "TRANSPORT",
             "WRITE_SIZE_HINT", "FLAT_SCALES", "KEYS", "EDIT_KEYS",
             "VIEW_KEYS", "MEDIA", "CUE", "ADVICE"}
# Words that are data, not the window's: keys the settings and the code are
# written in, and what each language is called in itself.
DATA = {"PREVIEW", "WAS_CALLED", "OLD_WORDS", "LANGUAGE_NAMES"}
CYR = re.compile("[А-Яа-яЁё]")


def _parents(tree):
    up = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            up[child] = node
    return up


def _scan():
    """(said through tr, constants, Russian left bare) across the modules."""
    through, constants, bare = {}, {}, []
    for name in MODULES:
        source = (TOOL / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        up = _parents(tree)
        docs = {node.body[0].value for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
                and node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "tr" and node.args
                    and isinstance(node.args[0], ast.Constant)):
                through[node.args[0].value] = f"{name}:{node.lineno}"
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and CYR.search(node.value)) or node in docs:
                continue
            # Where it stands: in tr(), in the log, in a constant, or bare.
            here, owner = node, None
            while here in up:
                here = up[here]
                if isinstance(here, ast.Call):
                    func = here.func
                    if isinstance(func, ast.Name) and func.id == "tr":
                        owner = "tr"
                        break
                    if (isinstance(func, ast.Attribute) and func.attr == "write"
                            and isinstance(func.value, ast.Name)
                            and func.value.id == "logfile"):
                        owner = "log"
                        break
                if isinstance(here, (ast.Assign, ast.AnnAssign)):
                    targets = (here.targets if isinstance(here, ast.Assign)
                               else [here.target])
                    named = {t.id for t in targets if isinstance(t, ast.Name)}
                    if named & CONSTANTS:
                        owner = "constant"
                        constants[node.value] = f"{name}:{node.lineno}"
                        break
                    if named & DATA:
                        owner = "data"
                        break
            if owner is None:
                bare.append(f"{name}:{node.lineno} {node.value[:60]!r}")
    return through, constants, bare


def _fields(text: str) -> list:
    return sorted((name, spec) for _, name, spec, _ in
                  string.Formatter().parse(text) if name is not None)


def test_no_word_of_the_window_goes_round_tr():
    _, _, bare = _scan()
    assert not bare, "Russian not put through tr():\n" + "\n".join(bare)


def test_every_word_has_its_english_with_the_same_pieces():
    from lang_en import EN
    through, constants, _ = _scan()
    wanted = {**through, **constants}
    missing = [f"{where} {text[:70]!r}" for text, where in wanted.items()
               if text not in EN]
    assert not missing, "no English for:\n" + "\n".join(missing)
    differ = [text[:70] for text in wanted
              if text in EN and _fields(text) != _fields(EN[text])]
    assert not differ, "the pieces do not match:\n" + "\n".join(differ)
    left = [text[:70] for text in EN if text not in wanted]
    assert not left, "English for nothing the window says:\n" + "\n".join(left)
    assert not [text for text in EN.values() if CYR.search(text)], \
        "Russian inside the English"


def test_tr_says_it_in_the_language_chosen():
    import lang
    try:
        assert lang.tr("кадр {0} из {1}", 3, 10) == "кадр 3 из 10"
        lang.set_language("en")
        assert lang.tr("кадр {0} из {1}", 3, 10) == "frame 3 of 10"
        assert lang.tr("нет такой строки") == "нет такой строки"
        assert lang.set_language("de") == "en", "an unknown language took"
        assert {"Чистка", "Clean"} <= lang.either("Clean")
        assert {"Чистка", "Clean"} <= lang.either("Чистка")
    finally:
        lang.set_language("ru")
