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
