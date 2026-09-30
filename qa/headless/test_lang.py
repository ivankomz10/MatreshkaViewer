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
           "depends.py", "scene3d.py",
           # The kinetic editor.
           "kinedit.py", "kin_model.py", "kin_tools.py", "kin_timeline.py",
           "kin_unwrap.py", "kin_sim.py", "kin_gizmo.py", "kin_overlay.py")
# Said once, at import, and put through tr() where they are shown.
CONSTANTS = {"MODE_LABEL", "LAYER_LABEL", "CALLED", "SAID", "TRANSPORT",
             "WRITE_SIZE_HINT", "FLAT_SCALES", "KEYS", "EDIT_KEYS",
             "VIEW_KEYS", "MEDIA", "CUE", "ADVICE",
             "LAYER_NAMES", "TOOL_NAMES", "FAMILIES", "MODES", "GRAINS",
             "FAMILY_NAME", "GHOSTS", "VIEW_NAMES", "TIMELINE_NAMES",
             "GRAIN_NAMES"}
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


def test_each_english_string_answers_for_one_russian():
    """Switching in place looks the English up to find the Russian: two
    Russian strings with one English would come back as the wrong one."""
    from collections import defaultdict
    from lang_en import EN
    back = defaultdict(list)
    for russian, english in EN.items():
        back[english].append(russian)
    shared = {english: many for english, many in back.items() if len(many) > 1}
    assert not shared, f"one English for several: {shared}"


# -- switching where the window stands ----------------------------------------

VOLATILE = {"qa_status_pace", "qa_eta", "qa_time_label", "qa_frame_label",
            "qa_full_time", "qa_stats", "qa_status", "qa_status_files",
            "qa_show_note"}


def _words(window) -> list:
    """Every piece of text on the window, in order: (where, what)."""
    from PySide6.QtWidgets import (QAbstractButton, QComboBox, QLabel,
                                   QLineEdit, QWidget)
    import main
    found = []
    widgets = [window] + window.findChildren(QWidget)
    for number, widget in enumerate(widgets):
        name = widget.objectName() or f"{type(widget).__name__}#{number}"
        if name in VOLATILE or widget.property("fixed_words"):
            continue
        if isinstance(widget, (QAbstractButton, QLabel)) and widget.text():
            found.append((name + ".text", widget.text()))
        if isinstance(widget, QLineEdit) and widget.placeholderText():
            found.append((name + ".placeholder", widget.placeholderText()))
        if isinstance(widget, QComboBox):
            for index in range(widget.count()):
                found.append((f"{name}[{index}]", widget.itemText(index)))
        if widget.toolTip():
            found.append((name + ".tip", widget.toolTip()))
        if widget in main.HINTS:
            says, story = main.HINTS[widget]
            found.append((name + ".says", says))
            found.append((name + ".story", story))
    return found


def test_switching_turns_every_word_where_it_stands(window, clips, tick):
    """No window built again, nothing opened again: the words turn in place,
    all of them, and come back exactly as they were."""
    import lang
    from test_quiet import put_back
    put_back(window, clips, tick)
    streams = list(window.streams)
    canvas = window.canvas
    # From words worked out once already: the show's clock in the pane that
    # is not on show, Undo saying there is nothing to undo -- the switch works
    # them out again, and a window that never had them would differ by them.
    window._retell()
    tick(0.2)
    before = _words(window)
    try:
        window._choose_language("en")
        tick(0.4)
        assert lang.language() == "en"
        english = _words(window)
        russian_left = [(where, what[:60]) for where, what in english
                        if CYR.search(what)]
        assert not russian_left, "still in Russian:\n" + "\n".join(
            f"{where}: {what}" for where, what in russian_left)
        assert window.level_buttons["view"].text() == "Quick look"
        assert window.sources_count.text() == "3 of 6 loaded"
        assert window.row_for("Top").note.text().count(" fps ") == 1
        assert window.row_for("Frame").label.text() == "Frame", \
            "a card's title was taken for words"
        assert window.streams == streams and window.canvas is canvas, \
            "the window opened its files again"
    finally:
        window._choose_language("ru")
        tick(0.4)
    assert lang.language() == "ru"
    after = _words(window)
    changed = [(where, was, now) for (where, was), (_, now)
               in zip(before, after) if was != now]
    assert len(after) == len(before) and not changed, (
        "not as they were:\n" + "\n".join(
            f"{where}: {was[:40]!r} -> {now[:40]!r}"
            for where, was, now in changed[:20]))
