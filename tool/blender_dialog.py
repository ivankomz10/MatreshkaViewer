"""Asking what goes to Blender, and making it without holding the window.

The window offers a clip's frames; this asks for the rest -- where the .blend
goes, which Blender, and, if the models were rendered elsewhere, that render
-- and then writes the cache and runs Blender in a thread of its own (see
blender_export).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

import blender_export as bx
from lang import tr


class BlenderDialog(QDialog):
    """The clip's frames and the things only a person can say."""

    def __init__(self, parent, request: bx.Request, blender: str, frames_note: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Top в Blender"))
        self.setObjectName("qa_blender_dialog")
        whole = QVBoxLayout(self)
        intro = QLabel(tr("Сцена Blender на эти кадры шоу, чтобы вписать 3D-модели в объём "
                          "кинетики. «Top 3D»: соты на моторах сеткой, камера зрителя — сюда "
                          "ставятся модели и рендерятся. «Top flat»: тот же рендер, "
                          "разложенный по сотам, как они стоят в каждом кадре, — кадры "
                          "2560×1150 ставятся на дорожку Top с того же кадра."))
        intro.setWordWrap(True)
        whole.addWidget(intro)
        grid = QGridLayout()
        whole.addLayout(grid)

        grid.addWidget(QLabel(tr("Кадры шоу")), 0, 0)
        span = QWidget()
        line = QHBoxLayout(span)
        line.setContentsMargins(0, 0, 0, 0)
        self.first = QSpinBox()
        self.first.setObjectName("qa_blender_first")
        self.first.setRange(0, 10 ** 7)
        self.first.setValue(request.first)
        self.length = QSpinBox()
        self.length.setObjectName("qa_blender_length")
        self.length.setRange(1, 10 ** 6)
        self.length.setValue(request.length)
        line.addWidget(QLabel(tr("с")))
        line.addWidget(self.first)
        line.addWidget(QLabel(tr("кадров")))
        line.addWidget(self.length)
        line.addWidget(QLabel(frames_note))
        line.addStretch(1)
        grid.addWidget(span, 0, 1, 1, 2)

        grid.addWidget(QLabel(tr("Рендер с камеры")), 1, 0)
        self.source = QLineEdit(request.source)
        self.source.setObjectName("qa_blender_source")
        self.source.setPlaceholderText(tr("пусто — рендер сцены «Top 3D» этого файла"))
        self.source.setToolTip(tr("Только если модели уже отрендерены в другом месте с камеры "
                                  "зрителя 9:16: секвенция, видео или картинка"))
        grid.addWidget(self.source, 1, 1)
        pick = QPushButton(tr("Выбрать…"))
        pick.clicked.connect(self._pick_source)
        grid.addWidget(pick, 1, 2)

        grid.addWidget(QLabel(tr("Файл .blend")), 2, 0)
        self.target = QLineEdit(request.target)
        self.target.setObjectName("qa_blender_target")
        grid.addWidget(self.target, 2, 1)
        where = QPushButton(tr("Куда…"))
        where.clicked.connect(self._pick_target)
        grid.addWidget(where, 2, 2)

        grid.addWidget(QLabel(tr("Blender")), 3, 0)
        self.blender = QLineEdit(blender)
        self.blender.setObjectName("qa_blender_exe")
        self.blender.setPlaceholderText(tr("blender.exe не найден"))
        grid.addWidget(self.blender, 3, 1)
        exe = QPushButton(tr("Выбрать…"))
        exe.clicked.connect(self._pick_blender)
        grid.addWidget(exe, 3, 2)

        buttons = QDialogButtonBox()
        go = buttons.addButton(tr("Собрать сцену"), QDialogButtonBox.ButtonRole.AcceptRole)
        go.setObjectName("qa_blender_go")
        buttons.addButton(tr("Отмена"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        whole.addWidget(buttons)
        self.name = request.name
        self.offset = request.source_offset
        self.resize(640, self.sizeHint().height())

    def _pick_source(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, tr("Рендер с камеры зрителя"), str(Path(self.source.text()).parent) if self.source.text() else "",
            tr("Картинки и видео (*.png *.jpg *.jpeg *.exr *.tif *.tiff *.mov *.mp4 *.avi *.mkv);;Все файлы (*)"))
        if chosen:
            self.source.setText(chosen)

    def _pick_target(self) -> None:
        chosen, _ = QFileDialog.getSaveFileName(self, tr("Файл Blender"), self.target.text(),
                                                tr("Blender (*.blend)"))
        if chosen:
            self.target.setText(chosen)

    def _pick_blender(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, tr("blender.exe"), self.blender.text(),
                                                tr("Blender (blender.exe);;Все файлы (*)"))
        if chosen:
            self.blender.setText(chosen)

    def request(self) -> bx.Request:
        return bx.Request(target=self.target.text().strip(), first=self.first.value(),
                          length=self.length.value(), source=self.source.text().strip(),
                          source_offset=self.offset, name=self.name)


class BlenderJob(QThread):
    """The cache written and Blender run, away from the window."""

    progress = Signal(int, int)
    done = Signal(object)          # what was made
    failed = Signal(str)

    def __init__(self, request, mesh, motors_at, blender, parent=None) -> None:
        super().__init__(parent)
        self.args = (request, mesh, motors_at, blender)

    def run(self) -> None:  # noqa: D102 -- QThread entry point
        request, mesh, motors_at, blender = self.args
        try:
            made = bx.export(request, mesh, motors_at, blender,
                             progress=lambda done, total: self.progress.emit(done, total))
        except Exception as error:  # noqa: BLE001 -- said in the window
            self.failed.emit(str(error))
            return
        self.done.emit(made)
