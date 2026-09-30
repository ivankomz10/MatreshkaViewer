"""The video as the cells show it, one colour a cell: for the strip.

The 3D view draws the video onto the cells in its shader, and the picture
never comes back to the CPU. The strip wants the same thing fifteen hundred
times over, flat -- so this reads it on the GPU instead: a compute pass that
samples the frame at every cell's own place in it (a few taps across the
cell, averaged, so a fine picture does not alias into noise), in the same
three ways the screens read their alpha and with the same YCoCg for Hap Q,
and hands back a small buffer.

Where a cell is in the picture is read off the geometry once: the middle of
its corners' UVs, taken the short way round where a cell straddles the seam.
"""
from __future__ import annotations

import math

import numpy as np
import wgpu

SHADER = """
struct About {
    // x: 1 when YCoCg; y: where the alpha is (0 none, 1 own plane, 2 fourth
    // channel); zw: uv scale -- what the screens' own `screens[i]` says
    look: vec4<f32>,
};

@group(0) @binding(0) var colour_tex: texture_2d<f32>;
@group(0) @binding(1) var alpha_tex: texture_2d<f32>;
@group(0) @binding(2) var tap: sampler;
@group(0) @binding(3) var<storage, read> places: array<vec4<f32>>;
@group(0) @binding(4) var<storage, read_write> got: array<vec4<f32>>;
@group(0) @binding(5) var<uniform> about: About;

fn from_ycocg(raw: vec4<f32>) -> vec3<f32> {
    let shifted = raw + vec4<f32>(-0.50196078431373, -0.50196078431373, 0.0, 0.0);
    let scale = (shifted.z * (255.0 / 8.0)) + 1.0;
    let co = shifted.x / scale;
    let cg = shifted.y / scale;
    let y = shifted.w;
    return vec3<f32>(y + co - cg, y + cg, y - co - cg);
}

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) id: vec3<u32>) {
    let i = id.x;
    if (i >= arrayLength(&places)) {
        return;
    }
    let place = places[i];
    var sum = vec3<f32>(0.0, 0.0, 0.0);
    for (var a = -1; a <= 1; a = a + 1) {
        for (var b = -1; b <= 1; b = b + 1) {
            let uv = (place.xy + vec2<f32>(f32(a), f32(b)) * place.zw) * about.look.zw;
            let raw = textureSampleLevel(colour_tex, tap, uv, 0.0);
            var colour = raw.rgb;
            if (about.look.x > 0.5) {
                colour = from_ycocg(raw);
            }
            var alpha = 1.0;
            if (about.look.y > 1.5) {
                alpha = raw.a;
            } else if (about.look.y > 0.5) {
                alpha = textureSampleLevel(alpha_tex, tap, uv, 0.0).r;
            }
            sum = sum + colour * alpha;
        }
    }
    got[i] = vec4<f32>(clamp(sum / 9.0, vec3<f32>(0.0), vec3<f32>(1.0)), 1.0);
}
"""


def cell_places(uv: np.ndarray, cell: np.ndarray, count: int) -> np.ndarray:
    """Every cell's middle in the picture and how far a tap reaches from it,
    (count, 4): u, v in texture terms (v from the top), and a third of the
    cell's half size each way."""
    uv = np.asarray(uv, np.float64).reshape(-1, 2)
    cell = np.asarray(cell, np.int64).reshape(-1)
    out = np.zeros((count, 4), np.float32)
    order = np.argsort(cell, kind="stable")
    starts = np.searchsorted(cell[order], np.arange(count + 1))
    for which in range(count):
        mine = uv[order[starts[which]:starts[which + 1]]]
        if not len(mine):
            continue
        u = mine[:, 0].copy()
        if u.max() - u.min() > 0.5:          # across the seam: the short way
            u[u < 0.5] += 1.0
        v = mine[:, 1]
        out[which] = ((u.mean() % 1.0), 1.0 - v.mean(),
                      (u.max() - u.min()) / 6.0, (v.max() - v.min()) / 6.0)
    return out


class CellSampler:
    """One colour a cell off a video's textures, on the GPU."""

    def __init__(self, device, places: np.ndarray) -> None:
        self.device = device
        self.count = len(places)
        module = device.create_shader_module(code=SHADER)
        self.pipeline = device.create_compute_pipeline(
            layout="auto", compute={"module": module, "entry_point": "main"})
        self.places = device.create_buffer_with_data(
            data=np.ascontiguousarray(places, np.float32),
            usage=wgpu.BufferUsage.STORAGE)
        size = self.count * 16
        self.got = device.create_buffer(
            size=size, usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC)
        self.readback = device.create_buffer(
            size=size, usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ)
        self.about = device.create_buffer(
            size=16, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        self.tap = device.create_sampler(mag_filter="linear", min_filter="linear",
                                         address_mode_u="clamp-to-edge",
                                         address_mode_v="clamp-to-edge")
        self._group = None
        self._bound = None

    def read(self, colour, alpha, ycocg: bool, alpha_from: int,
             uv_scale=(1.0, 1.0)) -> np.ndarray:
        """(count, 3) colours 0..1 of the picture in these textures now."""
        if self._bound != (id(colour), id(alpha)):
            self._group = self.device.create_bind_group(
                layout=self.pipeline.get_bind_group_layout(0),
                entries=[
                    {"binding": 0, "resource": colour.create_view()},
                    {"binding": 1, "resource": alpha.create_view()},
                    {"binding": 2, "resource": self.tap},
                    {"binding": 3, "resource": {"buffer": self.places, "offset": 0,
                                                "size": self.places.size}},
                    {"binding": 4, "resource": {"buffer": self.got, "offset": 0,
                                                "size": self.got.size}},
                    {"binding": 5, "resource": {"buffer": self.about, "offset": 0,
                                                "size": 16}},
                ])
            self._bound = (id(colour), id(alpha))
        look = np.array([1.0 if ycocg else 0.0, float(alpha_from),
                         uv_scale[0], uv_scale[1]], np.float32)
        self.device.queue.write_buffer(self.about, 0, look.tobytes())
        encoder = self.device.create_command_encoder()
        work = encoder.begin_compute_pass()
        work.set_pipeline(self.pipeline)
        work.set_bind_group(0, self._group)
        work.dispatch_workgroups(-(-self.count // 64))
        work.end()
        encoder.copy_buffer_to_buffer(self.got, 0, self.readback, 0, self.got.size)
        self.device.queue.submit([encoder.finish()])
        self.readback.map_sync("read")
        try:
            raw = np.frombuffer(bytes(self.readback.read_mapped()), np.float32)
        finally:
            self.readback.unmap()
        return raw.reshape(self.count, 4)[:, :3].copy()


# -- the strip itself, the picture on each cell -----------------------------------------

STRIP_SHADER = """
struct View {
    centre: vec2<f32>,     // the strip's point in the middle of the widget, cells
    middle: vec2<f32>,     // where that is drawn, pixels
    size: f32,             // pixels a cell
    period: f32,           // cells round
    wide: f32,
    tall: f32,
};

struct About {
    look: vec4<f32>,       // x: YCoCg; y: where the alpha is; zw: uv scale
    has: vec4<f32>,        // x: 1 with a video; y: 1 with the calibration behind
};

@group(0) @binding(0) var<uniform> view: View;
@group(0) @binding(1) var<uniform> about: About;
@group(0) @binding(2) var colour_tex: texture_2d<f32>;
@group(0) @binding(3) var alpha_tex: texture_2d<f32>;
@group(0) @binding(4) var calib_tex: texture_2d<f32>;
@group(0) @binding(5) var tap: sampler;

struct VOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@location(0) centre: vec2<f32>, @location(1) offset: vec2<f32>,
           @location(2) uv: vec2<f32>) -> VOut {
    // Round the strip the way it wraps: each cell at its copy nearest the view.
    let half = view.period * 0.5;
    let raw = centre.x - view.centre.x + half;
    let gap = raw - view.period * floor(raw / view.period) - half;
    let x = view.middle.x + (gap + offset.x) * view.size;
    let y = view.middle.y - (centre.y - view.centre.y + offset.y) * view.size;
    var out: VOut;
    out.pos = vec4<f32>(x / view.wide * 2.0 - 1.0, 1.0 - y / view.tall * 2.0, 0.0, 1.0);
    out.uv = uv;
    return out;
}

fn from_ycocg(raw: vec4<f32>) -> vec3<f32> {
    let shifted = raw + vec4<f32>(-0.50196078431373, -0.50196078431373, 0.0, 0.0);
    let scale = (shifted.z * (255.0 / 8.0)) + 1.0;
    let co = shifted.x / scale;
    let cg = shifted.y / scale;
    let y = shifted.w;
    return vec3<f32>(y + co - cg, y + cg, y - co - cg);
}

@fragment
fn fs_main(in: VOut) -> @location(0) vec4<f32> {
    let uv = vec2<f32>(fract(in.uv.x), clamp(in.uv.y, 0.0, 1.0));
    let raw = textureSample(colour_tex, tap, uv * about.look.zw);
    let alpha_raw = textureSample(alpha_tex, tap, uv * about.look.zw);
    let calib = textureSample(calib_tex, tap, uv);
    var video = raw.rgb;
    if (about.look.x > 0.5) {
        video = from_ycocg(raw);
    }
    var opacity = 1.0;
    if (about.look.y > 1.5) {
        opacity = raw.a;
    } else if (about.look.y > 0.5) {
        opacity = alpha_raw.r;
    }
    if (about.has.x < 0.5) {
        opacity = 0.0;
    }
    var behind = vec3<f32>(0.0, 0.0, 0.0);
    if (about.has.y > 0.5) {
        behind = calib.rgb;
    }
    return vec4<f32>(behind * (1.0 - opacity) + video * opacity, 1.0);
}
"""

HEX_RADIUS = 0.577 * 0.94          # as the strip draws a cell, in cells
PITCH_M = 0.278                    # a ring, metres, at rest


def strip_geometry(points, uv, cell, middles, address, places, ring_pitch) -> np.ndarray:
    """Six triangles a cell, as the strip draws it, with the picture's UV at
    each corner -- the cell's own patch of the picture: each corner of the
    drawn hexagon where the building's own cell has that point of the
    picture, by a fit of its corners' UVs to where they stand on the strip.
    (n, 6) rows: the cell's middle on the strip, the corner's offset from
    it, the UV in texture terms (v from the top)."""
    points = np.asarray(points, np.float64)
    uv = np.asarray(uv, np.float64)
    cell = np.asarray(cell, np.int64).reshape(-1)
    count = len(middles)
    corners = [(HEX_RADIUS * math.cos(math.radians(90 + 60 * k)),
                -HEX_RADIUS * math.sin(math.radians(90 + 60 * k))) for k in range(6)]
    rows = []
    order = np.argsort(cell, kind="stable")
    starts = np.searchsorted(cell[order], np.arange(count + 1))
    period = places.shape[1]
    for which in range(count):
        mine = order[starts[which]:starts[which + 1]]
        if len(mine) < 3:
            continue
        row, slot = address[which]
        across, up = places[row, slot]
        spot = points[mine]
        middle = middles[which]
        azimuth = np.degrees(np.arctan2(spot[:, 1], spot[:, 0]))
        centre_az = math.degrees(math.atan2(middle[1], middle[0]))
        dx = ((azimuth - centre_az + 180.0) % 360.0 - 180.0) / 360.0 * period
        dy = (spot[:, 2] - middle[2]) / PITCH_M * ring_pitch
        u = uv[mine, 0].copy()
        if u.max() - u.min() > 0.5:          # across the picture's seam
            u[u < 0.5] += 1.0
        fit, *_ = np.linalg.lstsq(np.stack([dx, dy, np.ones_like(dx)], axis=1),
                                  np.stack([u, uv[mine, 1]], axis=1), rcond=None)

        def at(ox, oy):
            got = np.array([ox, oy, 1.0]) @ fit
            return float(got[0]), 1.0 - float(got[1])

        middle_uv = at(0.0, 0.0)
        for k in range(6):
            a, b = corners[k], corners[(k + 1) % 6]
            rows.append((across, up, 0.0, 0.0) + middle_uv)
            rows.append((across, up) + a + at(*a))
            rows.append((across, up) + b + at(*b))
    return np.array(rows, np.float32)


class StripPicture:
    """The strip as it looks in Video: each cell showing its own patch of
    the picture, rendered on the GPU into an image the strip lays under its
    outlines."""

    FORMAT = "rgba8unorm"

    def __init__(self, device, geometry: np.ndarray) -> None:
        self.device = device
        module = device.create_shader_module(code=STRIP_SHADER)
        self.pipeline = device.create_render_pipeline(
            layout="auto",
            vertex={"module": module, "entry_point": "vs_main",
                    "buffers": [{"array_stride": 24, "step_mode": "vertex",
                                 "attributes": [
                                     {"format": "float32x2", "offset": 0, "shader_location": 0},
                                     {"format": "float32x2", "offset": 8, "shader_location": 1},
                                     {"format": "float32x2", "offset": 16,
                                      "shader_location": 2}]}]},
            fragment={"module": module, "entry_point": "fs_main",
                      "targets": [{"format": self.FORMAT}]},
            primitive={"topology": "triangle-list", "cull_mode": "none"},
        )
        self.vertices = device.create_buffer_with_data(
            data=np.ascontiguousarray(geometry, np.float32), usage=wgpu.BufferUsage.VERTEX)
        self.count = len(geometry)
        self.view = device.create_buffer(
            size=32, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        self.about = device.create_buffer(
            size=32, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        self.tap = device.create_sampler(mag_filter="linear", min_filter="linear",
                                         address_mode_u="clamp-to-edge",
                                         address_mode_v="clamp-to-edge")
        self._size = None
        self._group = None
        self._bound = None

    def _targets(self, width: int, height: int) -> None:
        if self._size == (width, height):
            return
        self._target = self.device.create_texture(
            size=(width, height, 1), format=self.FORMAT,
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)
        self._stride = -(-width * 4 // 256) * 256
        self._readback = self.device.create_buffer(
            size=self._stride * height,
            usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ)
        self._size = (width, height)

    def render(self, width: int, height: int, centre, middle, size: float, period: int,
               colour, alpha, calibration, ycocg: bool, alpha_from: int,
               uv_scale=(1.0, 1.0), has_video: bool = True):
        """(bytes, bytes a row) of an RGBA picture `width` x `height` pixels."""
        width, height = max(1, int(width)), max(1, int(height))
        self._targets(width, height)
        if self._bound != (id(colour), id(alpha), id(calibration)):
            self._group = self.device.create_bind_group(
                layout=self.pipeline.get_bind_group_layout(0),
                entries=[
                    {"binding": 0, "resource": {"buffer": self.view, "offset": 0, "size": 32}},
                    {"binding": 1, "resource": {"buffer": self.about, "offset": 0, "size": 32}},
                    {"binding": 2, "resource": colour.create_view()},
                    {"binding": 3, "resource": alpha.create_view()},
                    {"binding": 4, "resource": calibration.create_view()},
                    {"binding": 5, "resource": self.tap},
                ])
            self._bound = (id(colour), id(alpha), id(calibration))
        view = np.array([centre[0], centre[1], middle[0], middle[1], size, period,
                         width, height], np.float32)
        about = np.array([1.0 if ycocg else 0.0, float(alpha_from), uv_scale[0], uv_scale[1],
                          1.0 if has_video else 0.0, 1.0, 0.0, 0.0], np.float32)
        queue = self.device.queue
        queue.write_buffer(self.view, 0, view.tobytes())
        queue.write_buffer(self.about, 0, about.tobytes())
        encoder = self.device.create_command_encoder()
        drawing = encoder.begin_render_pass(color_attachments=[{
            "view": self._target.create_view(), "load_op": "clear", "store_op": "store",
            "clear_value": (0.0, 0.0, 0.0, 0.0)}])
        drawing.set_pipeline(self.pipeline)
        drawing.set_bind_group(0, self._group)
        drawing.set_vertex_buffer(0, self.vertices)
        drawing.draw(self.count)
        drawing.end()
        encoder.copy_texture_to_buffer(
            {"texture": self._target},
            {"buffer": self._readback, "bytes_per_row": self._stride, "rows_per_image": height},
            (width, height, 1))
        queue.submit([encoder.finish()])
        self._readback.map_sync("read")
        try:
            raw = bytes(self._readback.read_mapped())
        finally:
            self._readback.unmap()
        return raw, self._stride
