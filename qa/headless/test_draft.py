"""A show being edited, without a window: as data, its history, its draft.

The editor's undo is snapshots of the show as data, and its working file is
the same data on disk. So what has to hold is that a show survives the trip
to data and back whole -- every clip, every field -- and that the history
and the draft do what they say.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import draft as drafts
import show as showfile

RUSDAY = Path(r"D:\Content\_SHOW"
              r"\2026-Daily-RusDay-Matreshka_Day-MuzeyTransporta-v001.trix")


def small_show(clips) -> "showfile.Show":
    show = showfile.chained({"Top": [(str(clips["top"]), 2)],
                             "Bottom": [(str(clips["bottom"]), 1)]})
    show.name = "проба"
    show.loops[:] = [(10, 20)]
    return show


@pytest.mark.skipif(not RUSDAY.exists(), reason="the RusDay show is not here")
def test_a_real_show_goes_to_data_and_back_whole():
    show = showfile.read(RUSDAY)
    back = drafts.show_from_dict(json.loads(json.dumps(drafts.show_to_dict(show))))
    assert drafts.show_to_dict(back) == drafts.show_to_dict(show)
    assert [clip.tail for clip in back.clips] == [clip.tail for clip in show.clips]


def test_back_and_forward(clips):
    show = small_show(clips)
    history = drafts.History()
    first = show.on("Top")[0]
    moved = first.ident

    def tx_of():
        return next(one.tx for one in show.clips if one.ident == moved)

    history.before(show, "перенос")
    first.tx = 500
    history.before(show, "удалить")
    show.clips.remove(show.on("Bottom")[0])
    assert history.undo(show) == "удалить"
    assert len(show.on("Bottom")) == 1, "the deleted clip did not come back"
    assert history.undo(show) == "перенос"
    assert tx_of() == 0
    assert history.undo(show) is None
    assert history.redo(show) == "перенос"
    assert tx_of() == 500
    # A new change forgets what could have been redone.
    history.before(show, "имя")
    show.name = "другое"
    assert history.redo(show) is None


def test_typing_into_one_field_is_one_step(clips):
    show = small_show(clips)
    history = drafts.History()
    clip = show.on("Top")[0]
    for value in (-1, -12, -120):
        history.before(show, "поле fade_end", key=(clip.ident, "fade_end"))
        clip.fade_end = value
    assert len(history.back) == 1
    history.before(show, "поле crop_end", key=(clip.ident, "crop_end"))
    assert len(history.back) == 2, "another field was folded into the first"
    history.forget_last()
    history.undo(show)
    assert show.on("Top")[0].fade_end == 0


def test_the_draft_is_written_whole_and_read_back(tmp_path, clips):
    show = small_show(clips)
    source = tmp_path / "Show-v001.trix"
    source.write_text("{}", encoding="utf-8")
    where = drafts.path_for(tmp_path, str(source))
    one = drafts.Draft(where, str(source), drafts.stamp(str(source)))
    one.file_loops = [(800, 1099)]
    one.changes = 3
    one.save(show)
    assert where.exists() and not where.with_suffix(".writing").exists()
    again, read = drafts.Draft.load(where)
    assert drafts.show_to_dict(read) == drafts.show_to_dict(show)
    assert again.changes == 3 and again.file_loops == [(800, 1099)]
    assert not again.source_changed()
    time.sleep(0.02)
    source.write_text('{"changed": 1}', encoding="utf-8")
    assert again.source_changed(), "the show file changed and nobody noticed"


def test_a_file_that_is_gone_is_missing_when_the_draft_opens(tmp_path, clips):
    show = small_show(clips)
    show.clips.append(showfile.Clip(kind="video", row="Top", level=1,
                                    path=str(tmp_path / "gone.mov"), tx=5,
                                    frames=10, ident=99))
    where = drafts.path_for(tmp_path, "")
    drafts.Draft(where).save(show)
    _, read = drafts.Draft.load(where)
    assert [clip.missing for clip in read.clips if clip.ident == 99] == [True]


def test_a_draft_put_aside_is_kept(tmp_path, clips):
    where = drafts.path_for(tmp_path, "")
    one = drafts.Draft(where)
    one.save(small_show(clips))
    aside = one.put_aside()
    assert not where.exists() and aside.exists()
    assert aside.parent.name == "old"


def test_two_shows_of_one_name_are_two_drafts(tmp_path):
    one = drafts.path_for(tmp_path, r"D:\A\Show-v001.trix")
    other = drafts.path_for(tmp_path, r"D:\B\Show-v001.trix")
    assert one != other and one.name.startswith("Show-v001-")
    assert drafts.path_for(tmp_path, r"d:\a\show-v001.trix") == one


def test_a_still_stands_until_the_next_clip_and_the_show_grows(clips, tmp_path):
    from PySide6.QtGui import QImage
    picture = tmp_path / "still.png"
    QImage(8, 8, QImage.Format.Format_RGBA8888).save(str(picture))
    show = showfile.Show(length=1000)
    show.clips = [
        showfile.Clip(kind="video", row="Top", level=0, path=str(picture),
                      tx=100, frames=0, ident=1),
        showfile.Clip(kind="video", row="Top", level=0, path=str(clips["top"]),
                      tx=400, frames=60, ident=2),
        showfile.Clip(kind="video", row="Bottom", level=0,
                      path=str(clips["bottom"]), tx=990, frames=60, ident=3)]
    drafts.settle(show)
    assert show.clips[0].last == 400, "the still ran past the next clip"
    assert show.length == 1050, "a clip past the end did not take the end along"
