"""Drawing the scene: the pipeline, the depth buffer and the multisampling.

Kept apart from `scene3d` because the geometry and the camera are the part
worth reading; this is the plumbing that puts them on screen.
"""
from __future__ import annotations

import numpy as np
import wgpu

import scene3d
from scene3d import SAMPLES, SHADER, Scene


class Renderer3D:
    """One pass over the scene, with what is switched on."""

    def __init__(self, scene: Scene, target_format: str = "rgba8unorm") -> None:
        self.scene = scene
        device = self.device = scene.device
        self.format = target_format
        shader = device.create_shader_module(code=SHADER)

        self.pipeline = device.create_render_pipeline(
            layout="auto",
            vertex={
                "module": shader, "entry_point": "vs_main",
                "buffers": [{
                    "array_stride": 8 * 4,
                    "step_mode": "vertex",
                    "attributes": [
                        {"format": "float32x3", "offset": 0, "shader_location": 0},
                        {"format": "float32x3", "offset": 12, "shader_location": 1},
                        {"format": "float32x2", "offset": 24, "shader_location": 2},
                    ],
                }],
            },
            fragment={"module": shader, "entry_point": "fs_main",
                      "targets": [{"format": target_format}]},
            primitive={"topology": "triangle-list", "cull_mode": "none"},
            depth_stencil={
                "format": "depth32float",
                "depth_write_enabled": True,
                "depth_compare": "less",
            },
            multisample={"count": SAMPLES},
        )

        self.frame_uniform = device.create_buffer(
            size=16 * 4 + 16 + 16,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        self.screen_settings = device.create_buffer(
            size=128, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        self.sampler = device.create_sampler(
            mag_filter="linear", min_filter="linear", mipmap_filter="linear",
            address_mode_u="clamp-to-edge", address_mode_v="clamp-to-edge")

        # One 4x4 per cell of the kinetic screen, rewritten whenever the
        # motors move. Still, it is 1500 identities and costs nothing.
        self.cell_count = scene3d.CELLS_ON_KINETIC
        blank = np.tile(np.eye(4, dtype=np.float32), (self.cell_count, 1, 1))
        self.cell_buffer = device.create_buffer_with_data(
            data=np.ascontiguousarray(blank),
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST)

        self.frame_group = device.create_bind_group(
            layout=self.pipeline.get_bind_group_layout(0),
            entries=[{"binding": 0, "resource": {
                "buffer": self.frame_uniform, "offset": 0,
                "size": self.frame_uniform.size}},
                     {"binding": 1, "resource": {
                "buffer": self.cell_buffer, "offset": 0,
                "size": self.cell_buffer.size}}])
        self.piece_groups = [
            device.create_bind_group(
                layout=self.pipeline.get_bind_group_layout(1),
                entries=[{"binding": 0, "resource": {
                    "buffer": piece.settings, "offset": 0, "size": 32}}])
            for piece in scene.pieces]

        self.on = {piece.name: True for piece in scene.pieces}
        self.backing = 1.0
        self.video_opacity = 0.0
        self.premultiplied = 1.0
        self.flood = 0.0             # white everywhere, for the measurement
        self.cull_far_side = 0.0     # drop the back of the top screen
        self.frame = None            # the picture laid over one screen
        self.gain = {name: (1.0, 1.0, 1.0) for name in scene.screens}
        self.frame_gain = 1.0
        self.light = np.array([-0.3, -0.5, 0.8], dtype=np.float32)

        self.blank = self._flat(0)
        # -1 in the second slot: nothing is loaded on any of them yet, which
        # is not the same as a video that happens to be opaque.
        self.videos = {name: (self.blank, self._flat(255), (0.0, -1.0, 1.0, 1.0))
                       for name in scene.screens}
        self.calibration = {name: self.blank for name in scene.screens}
        self._rebuild_screens()
        self._write_frame()

        self._sized = None
        self._colour = None
        self._depth = None

    # -- textures --------------------------------------------------------------

    def _flat(self, value: int):
        texture = self.device.create_texture(
            size=(1, 1, 1), format="rgba8unorm",
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        self.device.queue.write_texture(
            {"texture": texture}, bytes([value] * 4),
            {"bytes_per_row": 4, "rows_per_image": 1}, (1, 1, 1))
        return texture

    def load_calibration(self, name: str, rgba) -> None:
        height, width = rgba.shape[:2]
        texture = self.device.create_texture(
            size=(width, height, 1), format="rgba8unorm",
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        self.device.queue.write_texture(
            {"texture": texture}, np.ascontiguousarray(rgba),
            {"bytes_per_row": width * 4, "rows_per_image": height},
            (width, height, 1))
        self.calibration[name] = texture
        self._rebuild_screens()

    def set_video(self, name: str, colour, alpha, ycocg: bool, alpha_from: int,
                  uv_scale=(1.0, 1.0)) -> None:
        """`alpha_from`: 0 none, 1 a plane of its own, 2 inside the colour."""
        self.videos[name] = (colour, alpha,
                             (1.0 if ycocg else 0.0, float(alpha_from),
                              uv_scale[0], uv_scale[1]))
        self._rebuild_screens()

    def set_frame(self, name: str | None, colour=None, alpha=None,
                  ycocg: bool = False, alpha_from: int = 0,
                  uv_scale=(1.0, 1.0), covers=(1.0, 1.0)) -> None:
        """The picture laid over one screen, or `name` None to take it off.

        `covers` is how much of the screen it takes up: (1, 1) stretched to
        the corners, less than that fitted and centred.
        """
        if name is None:
            self.frame = None
        else:
            self.frame = (name, colour, alpha,
                          (1.0 if ycocg else 0.0, float(alpha_from),
                           uv_scale[0], uv_scale[1]),
                          (covers[0], covers[1]))
        self._rebuild_screens()

    def clear_video(self, name: str) -> None:
        """Take the video off a screen, leaving it showing its backing.

        Needed as its own call: dropping the Screen on the other side is not
        enough, because what the card is bound to is held here, and an
        unbound screen went on showing its last frame.
        """
        if name in self.videos:
            self.videos[name] = (self.blank, self._flat(255),
                                 (0.0, -1.0, 1.0, 1.0))
            self._rebuild_screens()

    def clear_all_videos(self) -> None:
        for name in self.videos:
            self.videos[name] = (self.blank, self._flat(255),
                                 (0.0, -1.0, 1.0, 1.0))
        self._rebuild_screens()

    def _rebuild_screens(self) -> None:
        entries = []
        settings = np.zeros((8, 4), dtype=np.float32)
        settings[:, 2:] = 1.0
        for index in range(3):
            if index < len(self.scene.screens):
                name = self.scene.screens[index]
                colour, alpha, values = self.videos[name]
                calibration = self.calibration[name]
                settings[index] = values
            else:
                colour = alpha = calibration = self.blank
            for offset, texture in enumerate((colour, alpha, calibration)):
                entries.append({"binding": index * 3 + offset,
                                "resource": texture.create_view()})
        # [3] what the frame is, [4] where it sits and which screen wears it.
        # -1 for the screen when there is no frame: an index nothing matches.
        settings[4, 2] = -1.0
        frame_colour = frame_alpha = self.blank
        if self.frame is not None:
            name, frame_colour, frame_alpha, values, covers = self.frame
            if name in self.scene.screens:
                settings[3] = values
                settings[4, 0], settings[4, 1] = covers
                settings[4, 2] = float(self.scene.screens.index(name))
        settings[4, 3] = self.frame_gain
        entries.append({"binding": 11, "resource": frame_colour.create_view()})
        entries.append({"binding": 12, "resource": frame_alpha.create_view()})

        for index in range(3):
            name = (self.scene.screens[index]
                    if index < len(self.scene.screens) else None)
            settings[5 + index, :3] = self.gain.get(name, (1.0, 1.0, 1.0))

        entries.append({"binding": 9, "resource": self.sampler})
        entries.append({"binding": 10, "resource": {
            "buffer": self.screen_settings, "offset": 0, "size": 128}})
        self.device.queue.write_buffer(self.screen_settings, 0, settings.tobytes())
        self.screen_group = self.device.create_bind_group(
            layout=self.pipeline.get_bind_group_layout(2), entries=entries)

    def _write_frame(self) -> None:
        values = np.zeros(16 + 4 + 4, dtype=np.float32)
        # Column-major, which is how WGSL reads a mat4x4.
        values[:16] = self.scene.view_projection().T.reshape(-1)
        values[16] = self.backing
        values[17] = self.video_opacity
        values[18] = self.premultiplied
        values[19] = self.flood
        values[20:23] = self.light
        values[23] = self.cull_far_side
        self.device.queue.write_buffer(self.frame_uniform, 0, values.tobytes())

    # -- what the window changes -----------------------------------------------

    def show(self, name: str, on: bool) -> None:
        self.on[name] = on

    def frame_as(self, width: int, height: int, crop: bool) -> None:
        """Narrow the camera to a centred window of that shape, or restore it."""
        if crop:
            self.scene.crop_to(width, height)
        else:
            self.scene.uncrop()
        self._write_frame()

    def show_around(self, across: float, down: float) -> None:
        """How much past the frame the preview reaches. One and one is the
        frame alone, which is what a render writes."""
        if self.scene.show_around(across, down):
            self._write_frame()

    def look_at_window(self, centre=None, zoom: float = None) -> None:
        self.scene.look_at_window(centre, zoom)
        self._write_frame()

    def fly(self, on: bool) -> None:
        """Let the camera off the one in the file, or put it back."""
        self.scene.fly(on)
        self._write_frame()

    def refresh(self) -> None:
        """The camera has moved; hand the card where it is now."""
        self._write_frame()

    @property
    def free(self):
        """The free camera while there is one, for whoever is steering it."""
        return self.scene.free

    def set_backing(self, calibration: bool) -> None:
        self.backing = 1.0 if calibration else 0.0
        self._write_frame()

    def set_alpha_mode(self, premultiplied: bool) -> None:
        """How the video's colour is read against its own alpha.

        Straight is what the content is supposed to be and what the wall will
        show. Premultiplied is the inspection: it puts the colour on whole, so
        anything sitting in the picture under a transparent alpha appears
        instead of being multiplied away, and a semi-transparent pixel whose
        colour is brighter than its alpha blows out instead of looking normal.
        """
        self.premultiplied = 1.0 if premultiplied else 0.0
        self._write_frame()

    def cull(self, on: bool) -> None:
        """Whether the far side of the top screen shows through.

        Both of its geometries answer to this, the one that moves and the one
        that stands at rest: the honeycomb is a ring of separated cells either
        way, and a switch that only reached the moving one did nothing at all
        until a motor file was loaded.

        Done in the fragment shader rather than by the rasteriser: a cull mode
        belongs to a pipeline in wgpu, and a second pipeline built with an
        automatic layout gets bind group layouts of its own that the first
        one's groups are refused by.
        """
        self.cull_far_side = 1.0 if on else 0.0
        self._write_frame()

    def set_cells(self, matrices) -> None:
        """Where every cell of the moving screen is, this instant.

        Column major on the way over, because that is how WGSL reads a matrix
        and transposing 1500 of them here is cheaper than being wrong.
        """
        data = np.ascontiguousarray(
            np.asarray(matrices, dtype=np.float32).transpose(0, 2, 1))
        self.device.queue.write_buffer(self.cell_buffer, 0, data)

    def rest_cells(self) -> None:
        """Put every cell back where it was modelled."""
        self.set_cells(np.tile(np.eye(4, dtype=np.float32), (self.cell_count, 1, 1)))

    def set_gain(self, gains: dict, frame: float | None = None) -> None:
        """How brightly each screen is turned up, as rgb multipliers."""
        for name, value in gains.items():
            if name in self.gain:
                self.gain[name] = tuple(float(v) for v in value)
        if frame is not None:
            self.frame_gain = float(frame)
        self._rebuild_screens()

    def measure_cover(self, width: int = 1080, height: int = 1920) -> dict:
        """What fraction of its own patch of the picture each screen lights.

        Every screen is flooded with white and drawn on its own, and what
        comes back is averaged over the rectangle it occupies. A screen built
        of separated cells -- the top one is hexagons, the lamellas are slats
        -- leaves part of that rectangle dark however bright its pixels are,
        and reads dimmer for it. This is that fraction, measured rather than
        guessed, so it stays true when the scene is baked again.

        Done at the size that gets written. The answer barely moves with
        resolution -- 0.752 at 1080x1920, twice that and four times it -- but
        measuring where the check is made costs one pass at startup and takes
        the last half a percent out of it.
        """
        was_on, was_backing = dict(self.on), self.backing
        # The flood returns before the gain is applied, so what is measured is
        # the geometry alone and a slider cannot chase its own tail.
        self.flood, self.backing = 1.0, 0.0
        self._write_frame()
        covered = {}
        try:
            for name in self.scene.screens:
                for other in self.on:
                    self.on[other] = (other == name)
                picture = self.to_array(width, height)[..., :3].astype(np.float64)
                lit = picture.max(axis=2) > 8
                if not lit.any():
                    covered[name] = 0.0
                    continue
                rows, columns = np.where(lit)
                patch = picture[rows.min():rows.max() + 1,
                                columns.min():columns.max() + 1]
                covered[name] = float(patch.mean() / 255.0)
        finally:
            self.on.update(was_on)
            self.flood, self.backing = 0.0, was_backing
            self._write_frame()
        return covered

    def set_video_opacity(self, opacity: float) -> None:
        self.video_opacity = float(max(0.0, min(1.0, opacity)))
        self._write_frame()

    # -- drawing ----------------------------------------------------------------

    def _surfaces(self, width: int, height: int):
        """The multisampled colour and depth to draw into, made once per size."""
        if self._sized != (width, height):
            self._colour = self.device.create_texture(
                size=(width, height, 1), format=self.format,
                sample_count=SAMPLES,
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT)
            self._depth = self.device.create_texture(
                size=(width, height, 1), format="depth32float",
                sample_count=SAMPLES,
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT)
            self._sized = (width, height)
        return self._colour.create_view(), self._depth.create_view()

    def draw(self, encoder, view, width: int, height: int, viewport=None) -> None:
        # A free camera has no frame of its own to keep, so it takes the shape
        # of whatever it is being drawn into -- the window one moment, a
        # snapshot at some other size the next. Settled here, where the size is
        # actually known, rather than left for the caller to remember.
        if self.scene.free is not None:
            self.scene.free.aspect = max(width, 1) / max(height, 1)
            self._write_frame()
        colour, depth = self._surfaces(width, height)
        pass_ = encoder.begin_render_pass(
            color_attachments=[{
                "view": colour,
                "resolve_target": view,
                "load_op": "clear", "store_op": "store",
                "clear_value": (0, 0, 0, 1),
            }],
            depth_stencil_attachment={
                "view": depth,
                "depth_load_op": "clear", "depth_store_op": "store",
                "depth_clear_value": 1.0,
            })
        if viewport is not None:
            x, y, wide, tall = viewport
            pass_.set_viewport(x, y, max(1.0, wide), max(1.0, tall), 0.0, 1.0)
        pass_.set_pipeline(self.pipeline)
        pass_.set_bind_group(0, self.frame_group)
        pass_.set_bind_group(2, self.screen_group)
        for piece, group in zip(self.scene.pieces, self.piece_groups):
            if not self.on[piece.name]:
                continue
            pass_.set_bind_group(1, group)
            pass_.set_vertex_buffer(0, piece.vertices)
            pass_.set_index_buffer(piece.indices, "uint32")
            pass_.draw_indexed(piece.count)
        pass_.end()

    def to_array(self, width: int, height: int):
        """One frame into an array, for looking at and for writing out.

        The target and the buffer are kept between calls: a render is thousands
        of frames of the same size, and at four thousand square each of these
        is sixty-seven megabytes to allocate and throw away.
        """
        if getattr(self, "_capture", None) != (width, height):
            row = width * 4
            stride = -(-row // 256) * 256
            self._target = self.device.create_texture(
                size=(width, height, 1), format=self.format,
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT
                      | wgpu.TextureUsage.COPY_SRC)
            self._readback = self.device.create_buffer(
                size=stride * height,
                usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ)
            self._capture = (width, height)
        target, readback = self._target, self._readback
        row = width * 4
        stride = -(-row // 256) * 256

        encoder = self.device.create_command_encoder()
        self.draw(encoder, target.create_view(), width, height)
        encoder.copy_texture_to_buffer(
            {"texture": target},
            {"buffer": readback, "bytes_per_row": stride, "rows_per_image": height},
            (width, height, 1))
        self.device.queue.submit([encoder.finish()])

        readback.map_sync("read")
        try:
            raw = np.frombuffer(bytes(readback.read_mapped()), dtype=np.uint8)
        finally:
            readback.unmap()
        return raw[:stride * height].reshape(height, stride)[:, :row] \
                                    .reshape(height, width, 4)
