"""Flat shapes drawn over the 3D picture: the handles of what is chosen.

A pass of its own after the scene, into the same picture, with nothing but
coloured triangles in the canvas's own pixels -- no depth, no textures, no
bind groups, so it shares nothing with the scene's pipeline and cannot upset
it. The caller hands over triangles already worked out on the CPU (a few
hundred at most) each frame they change.
"""
from __future__ import annotations

import numpy as np
import wgpu

SHADER = """
struct VOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) colour: vec4<f32>,
};

@vertex
fn vs_main(@location(0) at: vec2<f32>, @location(1) colour: vec4<f32>) -> VOut {
    var out: VOut;
    out.pos = vec4<f32>(at, 0.0, 1.0);
    out.colour = colour;
    return out;
}

@fragment
fn fs_main(in: VOut) -> @location(0) vec4<f32> {
    return in.colour;
}
"""

STRIDE = 6 * 4          # x, y, r, g, b, a


class Overlay:
    def __init__(self, device, target_format: str) -> None:
        self.device = device
        shader = device.create_shader_module(code=SHADER)
        layout = device.create_pipeline_layout(bind_group_layouts=[])
        self.pipeline = device.create_render_pipeline(
            layout=layout,
            vertex={"module": shader, "entry_point": "vs_main",
                    "buffers": [{"array_stride": STRIDE, "step_mode": "vertex",
                                 "attributes": [
                                     {"format": "float32x2", "offset": 0,
                                      "shader_location": 0},
                                     {"format": "float32x4", "offset": 8,
                                      "shader_location": 1}]}]},
            fragment={"module": shader, "entry_point": "fs_main",
                      "targets": [{"format": target_format, "blend": {
                          "color": {"src_factor": "src-alpha",
                                    "dst_factor": "one-minus-src-alpha",
                                    "operation": "add"},
                          "alpha": {"src_factor": "one",
                                    "dst_factor": "one-minus-src-alpha",
                                    "operation": "add"}}}]},
            primitive={"topology": "triangle-list", "cull_mode": "none"},
        )
        self.buffer = None
        self.count = 0

    def set_triangles(self, vertices: np.ndarray) -> None:
        """(n, 6) rows of x, y in NDC and r, g, b, a -- three rows a triangle."""
        vertices = np.ascontiguousarray(np.asarray(vertices, np.float32).reshape(-1, 6))
        self.count = len(vertices)
        if not self.count:
            return
        size = vertices.nbytes
        if self.buffer is None or self.buffer.size < size:
            self.buffer = self.device.create_buffer(
                size=max(size, 4096),
                usage=wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST)
        self.device.queue.write_buffer(self.buffer, 0, vertices.tobytes())

    def draw(self, encoder, view) -> None:
        if not self.count:
            return
        pass_ = encoder.begin_render_pass(color_attachments=[{
            "view": view, "load_op": "load", "store_op": "store"}])
        pass_.set_pipeline(self.pipeline)
        pass_.set_vertex_buffer(0, self.buffer)
        pass_.draw(self.count)
        pass_.end()


class Shapes:
    """Triangles for the overlay, built in the canvas's logical pixels."""

    def __init__(self, width: float, height: float) -> None:
        self.width, self.height = max(1.0, width), max(1.0, height)
        self.rows: list = []

    def _ndc(self, x: float, y: float):
        return 2.0 * x / self.width - 1.0, 1.0 - 2.0 * y / self.height

    def triangle(self, a, b, c, colour) -> None:
        for point in (a, b, c):
            self.rows.append((*self._ndc(*point), *colour))

    def line(self, a, b, width: float, colour) -> None:
        a, b = np.asarray(a, float), np.asarray(b, float)
        along = b - a
        length = float(np.hypot(*along))
        if length < 1e-6:
            return
        side = np.array([-along[1], along[0]]) / length * (width / 2.0)
        self.triangle(a + side, b + side, b - side, colour)
        self.triangle(a + side, b - side, a - side, colour)

    def arrow(self, a, b, width: float, colour, head: float = 9.0) -> None:
        a, b = np.asarray(a, float), np.asarray(b, float)
        along = b - a
        length = float(np.hypot(*along))
        if length < 1e-6:
            return
        unit = along / length
        side = np.array([-unit[1], unit[0]])
        neck = b - unit * head
        self.line(a, neck, width, colour)
        self.triangle(b, neck + side * head * 0.55, neck - side * head * 0.55, colour)

    def arc(self, centre, radius: float, start: float, sweep: float, width: float,
            colour, pieces: int = 24) -> None:
        centre = np.asarray(centre, float)
        angles = np.linspace(start, start + sweep, pieces + 1)
        points = [centre + radius * np.array([np.cos(t), -np.sin(t)]) for t in angles]
        for a, b in zip(points[:-1], points[1:]):
            self.line(a, b, width, colour)

    def disc(self, centre, radius: float, colour, pieces: int = 16) -> None:
        centre = np.asarray(centre, float)
        angles = np.linspace(0, 2 * np.pi, pieces + 1)
        for a, b in zip(angles[:-1], angles[1:]):
            self.triangle(centre, centre + radius * np.array([np.cos(a), np.sin(a)]),
                          centre + radius * np.array([np.cos(b), np.sin(b)]), colour)

    def array(self) -> np.ndarray:
        return np.array(self.rows, np.float32).reshape(-1, 6)
