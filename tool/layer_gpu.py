"""The layers laid over a composed screen, on the graphics card.

A screen's compositor (screen_gpu.Compositor) has made the screen out of its
own video. This lays the screen's stack over that, a layer at a time: a pass
over the whole frame reads what is there so far and the layer, and writes the
two blended into the other of two textures -- the blend modes other than
plain addition need what is under them, which one pass of hardware blending
cannot give. The last is copied back into the compositor's texture, which is
what the building, Flat and the render read.

A folder's layers are laid first on a clear pair of their own, and the
result then lies on its parent as one layer, by the folder's opacity and mode.

The sums are `layers.blend`, on premultiplied colour; a picture from disk is
straight and is premultiplied here. Where a picture lands is an affine map
from the frame's pixels to the picture's 0..1, two rows of three numbers --
for now the picture fitted whole and centred; the transform of the next step
fills the same six numbers.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import wgpu

import layers as stacks

FORMAT = "rgba16float"

SHADER_HEAD = """
struct VOut {
    @builtin(position) pos: vec4<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) index: u32) -> VOut {
    var corners = array<vec2<f32>, 3>(
        vec2<f32>(-1.0, -1.0), vec2<f32>(3.0, -1.0), vec2<f32>(-1.0, 3.0));
    var out: VOut;
    out.pos = vec4<f32>(corners[index], 0.0, 1.0);
    return out;
}

struct Blend {
    // x: the mode (layers.BLENDS order), y: opacity, z: 1 when the layer's
    // colour is premultiplied already (a folder), 0 when straight (a picture)
    info: vec4<f32>,
    // frame pixel -> the layer's 0..1: u = dot(row0.xyz, (x, y, 1)), v the same
    row0: vec4<f32>,
    row1: vec4<f32>,
};

@group(0) @binding(0) var under: texture_2d<f32>;
@group(0) @binding(1) var picture: texture_2d<f32>;
@group(0) @binding(2) var picture_sampler: sampler;
@group(0) @binding(3) var<uniform> how: Blend;
"""

SUMS = """
fn mixed(cb: vec3<f32>, cs: vec3<f32>, mode: i32) -> vec3<f32> {
    if (mode == 1) { return cb * cs; }
    if (mode == 2) { return cb + cs - cb * cs; }
    if (mode == 3) {
        return select(1.0 - 2.0 * (1.0 - cb) * (1.0 - cs), 2.0 * cb * cs, cb <= vec3<f32>(0.5));
    }
    if (mode == 5) { return abs(cb - cs); }
    if (mode == 6) {
        let d = select(sqrt(max(cb, vec3<f32>(0.0))), ((16.0 * cb - 12.0) * cb + 4.0) * cb,
                       cb <= vec3<f32>(0.25));
        return select(cb + (2.0 * cs - 1.0) * (d - cb), cb - (1.0 - 2.0 * cs) * cb * (1.0 - cb),
                      cs <= vec3<f32>(0.5));
    }
    return cs;
}

// One layer over what is under it, both premultiplied: layers.blend.
fn laid(base: vec4<f32>, top: vec4<f32>, mode: i32) -> vec4<f32> {
    let a_s = top.a;
    let a_b = base.a;
    if (mode == 4) {
        return vec4<f32>(top.rgb + base.rgb, min(a_s + a_b, 1.0));
    }
    var rgb = top.rgb + base.rgb * (1.0 - a_s);
    if (mode != 0) {
        let s = select(vec3<f32>(0.0), top.rgb / a_s, a_s > 0.0);
        let b = select(vec3<f32>(0.0), base.rgb / a_b, a_b > 0.0);
        rgb = top.rgb * (1.0 - a_b) + base.rgb * (1.0 - a_s) + a_s * a_b * mixed(b, s, mode);
    }
    return vec4<f32>(rgb, a_s + a_b * (1.0 - a_s));
}
"""

SHADER = SHADER_HEAD + SUMS + """
@fragment
fn fs_main(in: VOut) -> @location(0) vec4<f32> {
    let base = textureLoad(under, vec2<i32>(in.pos.xy), 0);
    let at = vec3<f32>(in.pos.xy, 1.0);
    let uv = vec2<f32>(dot(how.row0.xyz, at), dot(how.row1.xyz, at));
    var top = vec4<f32>(0.0);
    if (all(uv >= vec2<f32>(0.0)) && all(uv <= vec2<f32>(1.0))) {
        top = textureSampleLevel(picture, picture_sampler, uv, 0.0);
        if (how.info.z < 0.5) {
            top = vec4<f32>(top.rgb * top.a, top.a);
        }
    }
    return laid(base, top * how.info.y, i32(how.info.x + 0.5));
}
"""


REMAP_SHADER = """
// A picture laid on the building as the file's camera sees it. The screen's
// own mesh is drawn in its own UV -- every triangle onto the part of the
// frame it shows -- and each fragment knows where on the building it is, the
// top screen's cells posed as they stand; that point seen through the camera
// is where in the picture it takes its colour from.
struct Remap {
    view_projection: mat4x4<f32>,
    eye: vec4<f32>,
    // x mode, y opacity, z 1 when the cells move (cells[] applies), w unused
    info: vec4<f32>,
    // the camera's picture in pixels, y down -> the layer's 0..1
    row0: vec4<f32>,
    row1: vec4<f32>,
    // xy the camera's picture in pixels
    camera: vec4<f32>,
};

@group(0) @binding(0) var under: texture_2d<f32>;
@group(0) @binding(1) var picture: texture_2d<f32>;
@group(0) @binding(2) var picture_sampler: sampler;
@group(0) @binding(3) var<uniform> how: Remap;
@group(0) @binding(4) var<storage, read> cells: array<mat4x4<f32>>;

struct VOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) world: vec3<f32>,
    @location(1) normal: vec3<f32>,
};

@vertex
fn vs_main(@location(0) point: vec3<f32>, @location(1) normal: vec3<f32>,
           @location(2) uv: vec2<f32>, @location(3) cell: f32) -> VOut {
    var placed = mat4x4<f32>(vec4<f32>(1.0, 0.0, 0.0, 0.0), vec4<f32>(0.0, 1.0, 0.0, 0.0),
                             vec4<f32>(0.0, 0.0, 1.0, 0.0), vec4<f32>(0.0, 0.0, 0.0, 1.0));
    if (how.info.z > 0.5) {
        placed = cells[u32(cell)];
    }
    var out: VOut;
    out.world = (placed * vec4<f32>(point, 1.0)).xyz;
    out.normal = (placed * vec4<f32>(normal, 0.0)).xyz;
    // The frame's top row is v = 1: the scene reads the video at (u, 1 - v).
    out.pos = vec4<f32>(uv.x * 2.0 - 1.0, uv.y * 2.0 - 1.0, 0.5, 1.0);
    return out;
}
""" + SUMS + """
@fragment
fn fs_main(in: VOut) -> @location(0) vec4<f32> {
    let base = textureLoad(under, vec2<i32>(in.pos.xy), 0);
    let clip = how.view_projection * vec4<f32>(in.world, 1.0);
    var top = vec4<f32>(0.0);
    let facing = dot(in.normal, how.eye.xyz - in.world) > 0.0;
    if (clip.w > 0.0 && facing) {
        let ndc = clip.xy / clip.w;
        let at = vec3<f32>((ndc.x + 1.0) * 0.5 * how.camera.x, (1.0 - ndc.y) * 0.5 * how.camera.y, 1.0);
        let uv = vec2<f32>(dot(how.row0.xyz, at), dot(how.row1.xyz, at));
        if (all(uv >= vec2<f32>(0.0)) && all(uv <= vec2<f32>(1.0))) {
            top = textureSampleLevel(picture, picture_sampler, uv, 0.0);
            top = vec4<f32>(top.rgb * top.a, top.a);
        }
    }
    return laid(base, top * how.info.y, i32(how.info.x + 0.5));
}
"""

CAMERA_PICTURE = (2160, 3840)      # the file camera's 9:16 picture, in pixels


class Surface:
    """A screen's mesh on the card, for the remap pass: its points, normals
    and UVs at rest, and which cell each vertex is in."""

    def __init__(self, device, raw, name: str, kinetic: bool = False) -> None:
        points = np.asarray(raw[f"{name}__points"], np.float32)
        normals = np.asarray(raw[f"{name}__normals"], np.float32)
        uv = np.asarray(raw[f"{name}__uv"], np.float32)
        cell = (np.asarray(raw[f"{name}__cell"], np.float32) if f"{name}__cell" in raw.files
                else np.zeros(len(points), np.float32))
        vertices = np.hstack([points, normals, uv, cell[:, None]]).astype(np.float32)
        self.vertices = device.create_buffer_with_data(data=vertices.tobytes(),
                                                       usage=wgpu.BufferUsage.VERTEX)
        triangles = np.asarray(raw[f"{name}__triangles"], np.uint32)
        self.indices = device.create_buffer_with_data(data=triangles.tobytes(),
                                                      usage=wgpu.BufferUsage.INDEX)
        self.count = int(triangles.size)
        self.kinetic = kinetic
        cells = max(1, int(cell.max()) + 1 if len(cell) else 1)
        self.cells = device.create_buffer(size=cells * 64,
                                          usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST)
        rest = np.tile(np.eye(4, dtype=np.float32), (cells, 1, 1))
        device.queue.write_buffer(self.cells, 0, rest.tobytes())
        self.device = device
        self.moving = False

    def pose(self, matrices) -> None:
        """The cells as they stand, or None for rest."""
        self.moving = matrices is not None and self.kinetic
        if self.moving:
            m = np.ascontiguousarray(np.asarray(matrices, np.float32).transpose(0, 2, 1))
            self.device.queue.write_buffer(self.cells, 0, m.tobytes())


def camera_rows(picture: tuple, layer) -> tuple:
    """`placed` in the camera's picture, its y counted upwards as a person
    reads it: up is plus."""
    import copy
    upright = copy.copy(layer)
    upright.y = -layer.y
    return placed(CAMERA_PICTURE, picture, upright)


def fitted(frame: tuple, picture: tuple) -> tuple:
    """The two rows mapping the frame's pixels to a picture fitted whole and
    centred, its shape kept."""
    width, height = frame
    wide, tall = picture
    scale = min(width / wide, height / tall)
    left = (width - wide * scale) / 2.0
    top = (height - tall * scale) / 2.0
    across = 1.0 / (scale * wide)
    down = 1.0 / (scale * tall)
    return (across, 0.0, -left * across), (0.0, down, -top * down)


def placed(frame: tuple, picture: tuple, layer) -> tuple:
    """The two rows for a picture where its layer puts it: fitted whole and
    centred, then scaled about its middle, turned clockwise, mirrored, moved.

    A pixel f of the frame is p = (w, h) / 2 + k * M * R(-angle) * (f - c) of
    the picture, k the picture's pixels to a frame pixel, M the mirror, c the
    picture's middle on the frame; divided by (w, h) it is 0..1."""
    import math
    width, height = frame
    wide, tall = picture
    k = 1.0 / (min(width / wide, height / tall) * max(layer.scale, 1e-6))
    angle = math.radians(layer.rotation)
    c, s = math.cos(angle), math.sin(angle)
    mirror = -1.0 if layer.flip else 1.0
    cx, cy = width / 2.0 + layer.x, height / 2.0 + layer.y
    # q = k * (c*dx + s*dy, -s*dx + c*dy), mirrored across; u = q.x / w + 1/2
    a0, b0 = mirror * k * c / wide, mirror * k * s / wide
    a1, b1 = -k * s / tall, k * c / tall
    return ((a0, b0, 0.5 - a0 * cx - b0 * cy), (a1, b1, 0.5 - a1 * cx - b1 * cy))


def whole(frame: tuple) -> tuple:
    """The rows of a layer as large as the frame itself: a folder's result."""
    width, height = frame
    return (1.0 / width, 0.0, 0.0), (0.0, 1.0 / height, 0.0)


class Pictures:
    """Pictures from disk as textures, read once while their file stands."""

    def __init__(self, device) -> None:
        self.device = device
        self._held: dict = {}

    def get(self, path: str):
        """(texture, (width, height)) of a picture, or None if it will not open."""
        where = Path(path)
        try:
            facts = where.stat()
        except OSError:
            return None
        key = (str(where), facts.st_size, facts.st_mtime_ns)
        if key not in self._held:
            self._held[key] = self._load(where)
        return self._held[key]

    def _load(self, where: Path):
        from PIL import Image
        try:
            with Image.open(where) as opened:
                pixels = np.asarray(opened.convert("RGBA"), dtype=np.uint8)
        except Exception:  # noqa: BLE001 -- a layer that will not open shows nothing
            return None
        tall, wide = pixels.shape[:2]
        texture = self.device.create_texture(
            size=(wide, tall, 1), format="rgba8unorm",
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        self.device.queue.write_texture(
            {"texture": texture}, np.ascontiguousarray(pixels),
            {"bytes_per_row": wide * 4, "rows_per_image": tall}, (wide, tall, 1))
        return texture, (wide, tall)

    def thumbnail(self, path: str, side: int = 34):
        """A small RGBA array of a picture, for the stack's rows."""
        from PIL import Image
        try:
            with Image.open(path) as opened:
                small = opened.convert("RGBA")
                small.thumbnail((side, side))
                return np.asarray(small, dtype=np.uint8)
        except Exception:  # noqa: BLE001
            return None


class LayerBlender:
    """Lays a screen's stack over its composed picture, in place."""

    def __init__(self, device, width: int, height: int) -> None:
        self.device = device
        self.width, self.height = int(width), int(height)
        shader = device.create_shader_module(code=SHADER)
        self.layout = device.create_bind_group_layout(entries=[
            {"binding": 0, "visibility": wgpu.ShaderStage.FRAGMENT,
             "texture": {"sample_type": wgpu.TextureSampleType.unfilterable_float}},
            {"binding": 1, "visibility": wgpu.ShaderStage.FRAGMENT,
             "texture": {"sample_type": wgpu.TextureSampleType.float}},
            {"binding": 2, "visibility": wgpu.ShaderStage.FRAGMENT,
             "sampler": {"type": wgpu.SamplerBindingType.filtering}},
            {"binding": 3, "visibility": wgpu.ShaderStage.FRAGMENT,
             "buffer": {"type": wgpu.BufferBindingType.uniform}},
        ])
        self.pipeline = device.create_render_pipeline(
            layout=device.create_pipeline_layout(bind_group_layouts=[self.layout]),
            vertex={"module": shader, "entry_point": "vs_main"},
            fragment={"module": shader, "entry_point": "fs_main",
                      "targets": [{"format": FORMAT}]},
            primitive={"topology": "triangle-list"})
        self.sampler = device.create_sampler(
            mag_filter="linear", min_filter="linear",
            address_mode_u="clamp-to-edge", address_mode_v="clamp-to-edge")
        remap = device.create_shader_module(code=REMAP_SHADER)
        self.remap_layout = device.create_bind_group_layout(entries=[
            {"binding": 0, "visibility": wgpu.ShaderStage.FRAGMENT,
             "texture": {"sample_type": wgpu.TextureSampleType.unfilterable_float}},
            {"binding": 1, "visibility": wgpu.ShaderStage.FRAGMENT,
             "texture": {"sample_type": wgpu.TextureSampleType.float}},
            {"binding": 2, "visibility": wgpu.ShaderStage.FRAGMENT,
             "sampler": {"type": wgpu.SamplerBindingType.filtering}},
            {"binding": 3, "visibility": wgpu.ShaderStage.VERTEX | wgpu.ShaderStage.FRAGMENT,
             "buffer": {"type": wgpu.BufferBindingType.uniform}},
            {"binding": 4, "visibility": wgpu.ShaderStage.VERTEX,
             "buffer": {"type": wgpu.BufferBindingType.read_only_storage}},
        ])
        self.remap_pipeline = device.create_render_pipeline(
            layout=device.create_pipeline_layout(bind_group_layouts=[self.remap_layout]),
            vertex={"module": remap, "entry_point": "vs_main", "buffers": [{
                "array_stride": 9 * 4, "step_mode": "vertex",
                "attributes": [
                    {"format": "float32x3", "offset": 0, "shader_location": 0},
                    {"format": "float32x3", "offset": 12, "shader_location": 1},
                    {"format": "float32x2", "offset": 24, "shader_location": 2},
                    {"format": "float32", "offset": 32, "shader_location": 3}]}]},
            fragment={"module": remap, "entry_point": "fs_main",
                      "targets": [{"format": FORMAT}]},
            primitive={"topology": "triangle-list", "cull_mode": "none"})
        self._remap_uniforms: list = []
        self._pairs: list = []        # work textures, a pair a depth of folder
        self._uniforms: list = []
        self._groups: dict = {}
        self._pass = 0

    def _texture(self):
        return self.device.create_texture(
            size=(self.width, self.height, 1), format=FORMAT,
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.TEXTURE_BINDING
            | wgpu.TextureUsage.COPY_SRC | wgpu.TextureUsage.COPY_DST)

    def _pair(self, depth: int):
        while len(self._pairs) <= depth:
            self._pairs.append([self._texture(), self._texture()])
        return self._pairs[depth]

    def _uniform(self, index: int):
        # One a pass: every pass of the frame is recorded before any runs,
        # and a buffer written twice would be read by both as its last value.
        while len(self._uniforms) <= index:
            self._uniforms.append(self.device.create_buffer(
                size=48, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST))
        return self._uniforms[index]

    def _lay(self, encoder, under, layer_texture, rows, mode: int, opacity: float,
             premultiplied: bool, into) -> None:
        index = self._pass
        self._pass += 1
        values = np.array([mode, opacity, 1.0 if premultiplied else 0.0, 0.0,
                           *rows[0], 0.0, *rows[1], 0.0], dtype=np.float32)
        buffer = self._uniform(index)
        self.device.queue.write_buffer(buffer, 0, values.tobytes())
        key = (id(under), id(layer_texture), index)
        group = self._groups.get(key)
        if group is None:
            group = self.device.create_bind_group(layout=self.layout, entries=[
                {"binding": 0, "resource": under.create_view()},
                {"binding": 1, "resource": layer_texture.create_view()},
                {"binding": 2, "resource": self.sampler},
                {"binding": 3, "resource": {"buffer": buffer, "offset": 0, "size": 48}},
            ])
            self._groups[key] = group
        pass_ = encoder.begin_render_pass(color_attachments=[{
            "view": into.create_view(), "load_op": "clear", "store_op": "store",
            "clear_value": (0.0, 0.0, 0.0, 0.0)}])
        pass_.set_pipeline(self.pipeline)
        pass_.set_bind_group(0, group)
        pass_.draw(3)
        pass_.end()

    def _remap_uniform(self, index: int):
        while len(self._remap_uniforms) <= index:
            self._remap_uniforms.append(self.device.create_buffer(
                size=160, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST))
        return self._remap_uniforms[index]

    def _lay_remapped(self, encoder, under, layer_texture, size, layer, mode: int, into,
                      surface, camera) -> None:
        """A picture as the camera sees it on the building: what is under
        copied across first, then the screen's mesh drawn over it in its UV."""
        index = self._pass
        self._pass += 1
        rows = camera_rows(size, layer)
        view_projection, eye = camera
        values = np.concatenate([
            np.asarray(view_projection, np.float32).T.reshape(-1),
            [eye[0], eye[1], eye[2], 1.0],
            [mode, layer.opacity, 1.0 if surface.moving else 0.0, 0.0],
            [*rows[0], 0.0], [*rows[1], 0.0],
            [CAMERA_PICTURE[0], CAMERA_PICTURE[1], 0.0, 0.0]]).astype(np.float32)
        buffer = self._remap_uniform(index)
        self.device.queue.write_buffer(buffer, 0, values.tobytes())
        encoder.copy_texture_to_texture({"texture": under}, {"texture": into},
                                        (self.width, self.height, 1))
        key = ("remap", id(under), id(layer_texture), id(surface), index)
        group = self._groups.get(key)
        if group is None:
            group = self.device.create_bind_group(layout=self.remap_layout, entries=[
                {"binding": 0, "resource": under.create_view()},
                {"binding": 1, "resource": layer_texture.create_view()},
                {"binding": 2, "resource": self.sampler},
                {"binding": 3, "resource": {"buffer": buffer, "offset": 0, "size": 160}},
                {"binding": 4, "resource": {"buffer": surface.cells, "offset": 0,
                                            "size": surface.cells.size}},
            ])
            self._groups[key] = group
        pass_ = encoder.begin_render_pass(color_attachments=[{
            "view": into.create_view(), "load_op": "load", "store_op": "store"}])
        pass_.set_pipeline(self.remap_pipeline)
        pass_.set_bind_group(0, group)
        pass_.set_vertex_buffer(0, surface.vertices)
        pass_.set_index_buffer(surface.indices, wgpu.IndexFormat.uint32)
        pass_.draw_indexed(surface.count)
        pass_.end()

    def _clear(self, encoder, texture) -> None:
        pass_ = encoder.begin_render_pass(color_attachments=[{
            "view": texture.create_view(), "load_op": "clear", "store_op": "store",
            "clear_value": (0.0, 0.0, 0.0, 0.0)}])
        pass_.end()

    def _stack(self, encoder, shown, start, depth: int, pictures, remap=None):
        """Lay `shown` over the texture `start`; the texture the result is in.
        `remap` is (Surface, (view_projection, eye)) for the layers laid as
        the camera sees them, or None where there is no camera to see by."""
        pair = self._pair(depth)
        now = start
        for layer, inner in shown:
            mode = stacks.BLENDS.index(layer.blend)
            if inner is not None:
                below = self._pair(depth + 1)[0]
                self._clear(encoder, below)
                made = self._stack(encoder, inner, below, depth + 1, pictures, remap)
                target = pair[0] if now is not pair[0] else pair[1]
                self._lay(encoder, now, made, whole((self.width, self.height)), mode,
                          layer.opacity, True, target)
                now = target
                continue
            got = pictures.get(layer.path)
            if got is None:
                continue
            texture, size = got
            target = pair[0] if now is not pair[0] else pair[1]
            if layer.remap:
                if remap is None:
                    continue
                self._lay_remapped(encoder, now, texture, size, layer, mode, target, *remap)
            else:
                self._lay(encoder, now, texture, placed((self.width, self.height), size, layer),
                          mode, layer.opacity, False, target)
            now = target
        return now

    def apply(self, encoder, composed_texture, shown, pictures, remap=None) -> bool:
        """Lay `shown` (layers.Stacks.shown) over `composed_texture`, which
        must allow being copied into. False, and nothing done, when there is
        nothing to lay."""
        if not shown:
            return False
        own = encoder is None
        if own:
            encoder = self.device.create_command_encoder()
        self._pass = 0
        first = self._pair(0)[1]
        encoder.copy_texture_to_texture({"texture": composed_texture}, {"texture": first},
                                        (self.width, self.height, 1))
        result = self._stack(encoder, shown, first, 0, pictures, remap)
        encoder.copy_texture_to_texture({"texture": result}, {"texture": composed_texture},
                                        (self.width, self.height, 1))
        if own:
            self.device.queue.submit([encoder.finish()])
        return True
