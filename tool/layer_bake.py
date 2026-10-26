"""Show clips with layers, baked into files of their own for a .trix.

The show editor on site knows nothing of layers: what it plays is files. So a
clip with layers goes out as a new movie -- its source with its layers laid on
it, frame for frame, the way the viewer shows it -- and the exported show has
that file where the clip's source was. Nothing else of the clip changes: the
whole of its file is baked, not only the part on show, so its place, its
crops, its fades and a loop's range (a share of the file's length) mean what
they meant. A still is baked to a still, its layers as they are where the
clip comes on: a video layer on a still does not play in the .trix.

The files go in a folder beside the new .trix, `<its name>_layers`, named
after the source and the clip: `<source>_L<ident>.mov`, Hap Q Alpha -- the
alpha written the way the window reads the tracks' (premultiplied or
straight), so the baked clip plays as the clip with its layers did.

Baked on a thread of its own, with the window not drawing: the device is the
job's for as long as it runs, as for a render.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread, Signal

import layer_gpu
import layer_video
import layers
import player
import rebake
import screen_gpu
import show as showfile


def to_bake(show) -> list:
    """The clips of a show that have layers on show."""
    return [clip for clip in show.clips
            if clip.kind == "video" and not clip.missing and clip.path
            and clip.layers and layers.Stacks.of_clip(clip).shown(clip.row)]


def folder_for(target: Path) -> Path:
    target = Path(target)
    return target.parent / f"{target.stem}_layers"


def file_for(target: Path, clip) -> Path:
    return folder_for(target) / f"{Path(clip.path).stem}_L{clip.ident}{'.png' if clip.still else '.mov'}"


def baked_show(show, files: dict):
    """A copy of `show` with each baked clip's source the file it was baked
    into (`files`, by ident) and its layers left behind."""
    out = copy.copy(show)
    out.clips = []
    for clip in show.clips:
        clip = copy.copy(clip)
        if clip.ident in files:
            clip.path = str(files[clip.ident])
            clip.layers = []
        out.clips.append(clip)
    out.loops = list(show.loops)
    return out


def light_to_pixels(light: np.ndarray, premultiplied: bool) -> np.ndarray:
    """A composed picture (light and cover, half floats) as RGBA bytes, the
    alpha read back the way it was read in."""
    light = np.nan_to_num(np.asarray(light, np.float32))
    cover = np.clip(light[..., 3:4], 0.0, 1.0)
    colour = light[..., :3] if premultiplied else np.where(
        cover > 1e-6, light[..., :3] / np.maximum(cover, 1e-6), 0.0)
    out = np.concatenate([np.clip(colour, 0.0, 1.0), cover], -1)
    return np.round(out * 255.0).astype(np.uint8)


class Baker:
    """One clip baked, frame by frame, on whichever thread holds the device."""

    def __init__(self, device, clip, name: str, frame: tuple, rasters,
                 premultiplied: bool, remap_for, ffmpeg: str | None = None) -> None:
        self.device = device
        self.clip = clip
        self.name = name                    # the baked screen
        self.width, self.height = int(frame[0]), int(frame[1])
        self.premultiplied = premultiplied
        self.remap_for = remap_for          # seconds of the show -> the remap pass's, or None
        self.ffmpeg = ffmpeg
        self.pictures = layer_gpu.Pictures(device)
        self.pictures.movies = layer_video.Movies(device)
        self.pictures.rasters = rasters
        self.pictures.premultiplied = premultiplied
        self.blender = layer_gpu.LayerBlender(device, self.width, self.height)
        self.composer = screen_gpu.Compositor(device, self.width, self.height)
        self.shown = layers.Stacks.of_clip(clip).shown(clip.row)

    @property
    def count(self) -> int:
        """How many frames: the whole of its file, or one for a still."""
        return 1 if self.clip.still else max(1, int(self.clip.frames))

    def frame(self, screen, index: int) -> np.ndarray:
        """Frame `index` of the file, its layers on it, as RGBA bytes."""
        show_frame = self.clip.tx + index
        local = (show_frame - self.clip.first) / showfile.FPS
        timed = [(one, local) for one in layers.playing_of(self.shown)]
        self.pictures.movies.exact(timed)
        self.composer.compose([(screen, 1.0)], premultiplied=self.premultiplied)
        remap = self.remap_for(show_frame / showfile.FPS) if self.remap_for else None
        self.blender.apply(None, self.composer.texture, self.shown, self.pictures, remap)
        return light_to_pixels(self.composer.to_array(), self.premultiplied)

    def run(self, target: Path, should_stop=lambda: False, progress=lambda done: None) -> bool:
        """Baked into `target`. False when stopped."""
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        source = player.open_source(self.clip.path)
        source.start()
        held = None
        writer = None
        try:
            screen = screen_gpu.Screen(self.device, source.movie)
            if target.suffix.lower() == ".png":
                frame = source.exact(0, None)
                if frame is not None:
                    screen.upload([memoryview(b) for b in frame.buffers])
                from PIL import Image
                Image.fromarray(self.frame(screen, 0)).save(target)
                progress(1)
                return True
            writer = rebake.writer_for(rebake.HAPM, target, self.width, self.height,
                                       showfile.FPS, self.ffmpeg)
            source.seek(0)
            for index in range(self.count):
                if should_stop():
                    writer.cancel()
                    writer = None
                    return False
                frame = source.exact(min(index, max(0, source.movie.frames - 1)), held,
                                     should_stop=should_stop)
                if frame is not None and frame is not held:
                    if held is not None:
                        source.give_back(held)
                    held = frame
                    screen.upload([memoryview(b) for b in frame.buffers])
                writer.write(self.frame(screen, index))
                progress(index + 1)
            writer.finish()
            writer = None
            return True
        finally:
            if writer is not None:
                writer.cancel()
            if held is not None:
                source.give_back(held)
            player.let_go([source])
            self.pictures.movies.close()


class LayerBakeJob(QThread):
    """Every clip to bake, one after the other: the files by ident at the end."""

    progress = Signal(int, int, float, float)   # done, total, fps, eta
    failed = Signal(str)
    # The files by the clips' idents. As an object: a dict through Qt comes
    # out with its keys made strings, and no ident would be found.
    finished_ok = Signal(object)

    def __init__(self, bakers, targets, parent=None) -> None:
        super().__init__(parent)
        self.bakers = list(bakers)
        self.targets = list(targets)
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def run(self) -> None:  # noqa: D102 -- QThread entry point
        started = time.perf_counter()
        total = sum(one.count for one in self.bakers)
        done = [0]
        files = {}
        try:
            for baker, target in zip(self.bakers, self.targets):
                before = done[0]

                def said(count, before=before):
                    done[0] = before + count
                    ran = max(1e-6, time.perf_counter() - started)
                    self.progress.emit(done[0], total, done[0] / ran,
                                       (total - done[0]) * ran / max(1, done[0]))
                if not baker.run(target, lambda: self._stop, said):
                    self.failed.emit("cancelled")
                    return
                files[baker.clip.ident] = target
            self.finished_ok.emit(files)
        except Exception as error:  # noqa: BLE001 -- surfaced in the window
            self.failed.emit(str(error))
