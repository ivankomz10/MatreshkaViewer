"""Unpacking DXT blocks on cards that will not do it themselves.

HAP frames are BC blocks, handed to the card exactly as they came out of the
file. Every desktop GPU reads them -- except Apple's own. Metal supports the BC
formats on Mac family GPUs, the Intel and AMD chips in Intel Macs, and not on
Apple family, which is every M-series machine; Apple exposes the difference as
`MTLDevice.supportsBCTextureCompression` and wgpu turns it into the
`texture-compression-bc` feature being offered or not.

So where the sampler will not unpack a block, a compute pass does, and hands on
an ordinary texture. The processor still decodes nothing. Measured on one real
4608x1584 plane the pass costs 0.41 ms, and it agrees with ffmpeg's own decoder
to three parts in 255 -- the same tolerance the hardware path lands in.

What comes out is what the sampler would have produced and nothing more: the
YCoCg transform stays where it was, in the drawing shaders. A block decoder
that also did colour would be two things wearing one name, and the fallback
would quietly disagree with the fast path.
"""
from __future__ import annotations

import numpy as np
import wgpu

# Everything decodes to this. r8unorm would do for the one-channel planes and
# would halve their memory, but it is not a storage format every backend has to
# offer, and this is the path for machines already short of capabilities.
TARGET = "rgba8unorm"

PRELUDE = """
@group(0) @binding(0) var<storage, read> blocks: array<u32>;
@group(0) @binding(1) var out_image: texture_storage_2d<rgba8unorm, write>;
@group(0) @binding(2) var<uniform> shape: vec4<u32>;    // blocks across, down

fn from565(v: u32) -> vec3<f32> {
    let r = (v >> 11u) & 31u;
    let g = (v >> 5u) & 63u;
    let b = v & 31u;
    // Repeated high bits, not a bare shift: 31 must come out 255, not 248.
    return vec3<f32>(f32((r << 3u) | (r >> 2u)),
                     f32((g << 2u) | (g >> 4u)),
                     f32((b << 3u) | (b >> 2u))) / 255.0;
}

// One texel's three-bit index out of the forty-eight that follow the two
// endpoints: the first five sit in the top half of the first word, the sixth
// straddles the pair, the rest are in the second.
fn ramp_index(w0: u32, w1: u32, n: u32) -> u32 {
    if (n < 5u) { return (w0 >> (16u + n * 3u)) & 7u; }
    if (n == 5u) { return ((w0 >> 31u) & 1u) | ((w1 & 3u) << 1u); }
    return (w1 >> (n * 3u - 16u)) & 7u;
}

// The eight- or six-step ramp between two ends, as BC4 and the alpha half of
// BC3 both define it. Which of the two applies depends on the order of the
// ends, which is how the format spends its one spare bit of meaning.
fn ramp_value(e0: f32, e1: f32, k: u32) -> f32 {
    if (k == 0u) { return e0; }
    if (k == 1u) { return e1; }
    if (e0 > e1) {
        return (f32(8u - k) * e0 + f32(k - 1u) * e1) / 7.0;
    }
    if (k == 6u) { return 0.0; }
    if (k == 7u) { return 1.0; }
    return (f32(6u - k) * e0 + f32(k - 1u) * e1) / 5.0;
}

fn place(id: vec3<u32>, n: u32) -> vec2<i32> {
    return vec2<i32>(i32(id.x * 4u + n % 4u), i32(id.y * 4u + n / 4u));
}
"""

# -- BC1: eight bytes, colour only -------------------------------------------
BC1 = PRELUDE + """
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) id: vec3<u32>) {
    if (id.x >= shape.x || id.y >= shape.y) { return; }
    let base = (id.y * shape.x + id.x) * 2u;
    let ends = blocks[base];
    let bits = blocks[base + 1u];

    let e0 = ends & 0xFFFFu;
    let e1 = (ends >> 16u) & 0xFFFFu;
    let c0 = from565(e0);
    let c1 = from565(e1);

    for (var n = 0u; n < 16u; n = n + 1u) {
        let k = (bits >> (n * 2u)) & 3u;
        var rgb = c0;
        var a = 1.0;
        if (e0 > e1) {
            if (k == 1u) { rgb = c1; }
            else if (k == 2u) { rgb = (c0 * 2.0 + c1) / 3.0; }
            else if (k == 3u) { rgb = (c0 + c1 * 2.0) / 3.0; }
        } else {
            // The punchthrough half of BC1: three colours and a hole. Hap
            // calls this texture RGB, but the hardware applies the rule, so
            // this has to as well or the two paths part company.
            if (k == 1u) { rgb = c1; }
            else if (k == 2u) { rgb = (c0 + c1) * 0.5; }
            else if (k == 3u) { rgb = vec3<f32>(0.0, 0.0, 0.0); a = 0.0; }
        }
        textureStore(out_image, place(id, n), vec4<f32>(rgb, a));
    }
}
"""

# -- BC3: sixteen bytes, an alpha ramp then a colour block -------------------
BC3 = PRELUDE + """
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) id: vec3<u32>) {
    if (id.x >= shape.x || id.y >= shape.y) { return; }
    let base = (id.y * shape.x + id.x) * 4u;
    let w0 = blocks[base];          // both alpha ends, then index bits 0..15
    let w1 = blocks[base + 1u];     // alpha index bits 16..47
    let ends = blocks[base + 2u];
    let bits = blocks[base + 3u];

    let a0 = f32(w0 & 255u) / 255.0;
    let a1 = f32((w0 >> 8u) & 255u) / 255.0;
    let c0 = from565(ends & 0xFFFFu);
    let c1 = from565((ends >> 16u) & 0xFFFFu);

    for (var n = 0u; n < 16u; n = n + 1u) {
        // Always four colours here: BC3 carries its own alpha, so the colour
        // half has no punchthrough case whatever the order of the ends.
        let k = (bits >> (n * 2u)) & 3u;
        var rgb = c0;
        if (k == 1u) { rgb = c1; }
        else if (k == 2u) { rgb = (c0 * 2.0 + c1) / 3.0; }
        else if (k == 3u) { rgb = (c0 + c1 * 2.0) / 3.0; }

        let a = ramp_value(a0, a1, ramp_index(w0, w1, n));
        textureStore(out_image, place(id, n), vec4<f32>(rgb, a));
    }
}
"""

# -- BC4: eight bytes, one channel -------------------------------------------
BC4 = PRELUDE + """
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) id: vec3<u32>) {
    if (id.x >= shape.x || id.y >= shape.y) { return; }
    let base = (id.y * shape.x + id.x) * 2u;
    let w0 = blocks[base];
    let w1 = blocks[base + 1u];

    let e0 = f32(w0 & 255u) / 255.0;
    let e1 = f32((w0 >> 8u) & 255u) / 255.0;

    for (var n = 0u; n < 16u; n = n + 1u) {
        let v = ramp_value(e0, e1, ramp_index(w0, w1, n));
        // Into red, where the sampler would have put it. The rest is filled
        // rather than left, so nothing downstream reads whatever the texture
        // happened to hold.
        textureStore(out_image, place(id, n), vec4<f32>(v, 0.0, 0.0, 1.0));
    }
}
"""

SHADERS = {
    "bc1-rgba-unorm": BC1,
    "bc3-rgba-unorm": BC3,
    "bc4-r-unorm": BC4,
}

# BC7 is a table-driven decoder several hundred lines long: partitions, two
# index sets, per-subset endpoint modes. None of the Hap files this is for use
# it, so it is refused in words rather than implemented on speculation.
CANNOT = {"bc7-rgba-unorm"}


class Unsupported(Exception):
    """A block format this cannot unpack, on a card that will not either."""


class Decoder:
    """The compute pipelines, made once and shared by every plane."""

    def __init__(self, device) -> None:
        self.device = device
        self._pipelines: dict[str, object] = {}

    def can_do(self, gpu_format: str) -> bool:
        return gpu_format in SHADERS

    def pipeline(self, gpu_format: str):
        if gpu_format not in SHADERS:
            why = ("no software decoder for it is written" if gpu_format in CANNOT
                   else "it is not a block format this knows")
            raise Unsupported(
                f"this GPU cannot read {gpu_format} and {why}")
        made = self._pipelines.get(gpu_format)
        if made is None:
            module = self.device.create_shader_module(code=SHADERS[gpu_format])
            made = self.device.create_compute_pipeline(
                layout="auto", compute={"module": module, "entry_point": "main"})
            self._pipelines[gpu_format] = made
        return made


class Softened:
    """One plane's blocks, and the plain texture they are unpacked into.

    Wears the same face as the hardware `Plane` next door -- `texture`, `view`,
    `padded`, `upload` -- so nothing above has to know which of the two it is
    holding.
    """

    def __init__(self, decoder: Decoder, width: int, height: int,
                 gpu_format: str) -> None:
        self.device = decoder.device
        self.width, self.height = width, height
        self.compressed = True              # on the way in, at least
        self.across = (width + 3) // 4
        self.down = (height + 3) // 4
        self.padded = (self.across * 4, self.down * 4)
        block_bytes = 8 if gpu_format.startswith(("bc1", "bc4")) else 16
        self.bytes_per_row = self.across * block_bytes

        self.pipeline = decoder.pipeline(gpu_format)
        self.blocks = self.device.create_buffer(
            size=self.across * self.down * block_bytes,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST)
        self.texture = self.device.create_texture(
            size=(self.padded[0], self.padded[1], 1), format=TARGET,
            usage=wgpu.TextureUsage.STORAGE_BINDING
            | wgpu.TextureUsage.TEXTURE_BINDING
            | wgpu.TextureUsage.COPY_SRC)
        self.view = self.texture.create_view()

        self._shape = self.device.create_buffer_with_data(
            data=np.array([self.across, self.down, 0, 0],
                          dtype=np.uint32).tobytes(),
            usage=wgpu.BufferUsage.UNIFORM)
        self.group = self.device.create_bind_group(
            layout=self.pipeline.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": self.blocks, "offset": 0,
                                            "size": self.blocks.size}},
                {"binding": 1, "resource": self.view},
                {"binding": 2, "resource": {"buffer": self._shape, "offset": 0,
                                            "size": 16}},
            ])

    def upload(self, blocks, encoder=None) -> None:
        """Take a frame's blocks and unpack them into the texture.

        The dispatch goes into the caller's encoder when there is one, so a
        screen's planes cost one submission between them rather than one each.
        """
        self.device.queue.write_buffer(self.blocks, 0, blocks)

        own = encoder is None
        if own:
            encoder = self.device.create_command_encoder()
        pass_ = encoder.begin_compute_pass()
        pass_.set_pipeline(self.pipeline)
        pass_.set_bind_group(0, self.group)
        pass_.dispatch_workgroups(-(-self.across // 8), -(-self.down // 8), 1)
        pass_.end()
        if own:
            self.device.queue.submit([encoder.finish()])
