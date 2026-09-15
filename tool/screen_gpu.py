"""Putting HAP frames on the card, still compressed.

The blocks that come out of the file are uploaded exactly as they are, into a
BC texture, and unpacked by the sampler while it reads them. Nothing here ever
holds a frame as pixels: at 4608x1584 that would be 29 MB where the blocks are
11, and moving the difference sixty times a second for three screens is the
whole cost the format exists to avoid.

Two things the real files insisted on.

A compressed texture must be created on the block grid. Two of the three
screens are not multiples of four -- 1150 and 110 high -- and the card refuses
those sizes outright, so the texture covers 1152 and 112 and the shader is told
where the real edge is. Sampling without that would show the padding.

And Hap Q Alpha is two textures, not one: the colour as YCoCg DXT5, the alpha
as a separate one-channel plane. Luma lives in the colour texture's alpha
channel, where DXT5 keeps its extra precision, so the transparency cannot live
there too and needs a plane of its own.
"""
from __future__ import annotations

import os

import numpy as np
import wgpu

import blockdecode

SHADER = """
struct VOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) index: u32) -> VOut {
    // One oversized triangle: no vertex buffer, no index buffer, no seam.
    var corners = array<vec2<f32>, 3>(
        vec2<f32>(-1.0, -1.0), vec2<f32>(3.0, -1.0), vec2<f32>(-1.0, 3.0));
    let corner = corners[index];
    var out: VOut;
    out.pos = vec4<f32>(corner, 0.0, 1.0);
    out.uv = vec2<f32>((corner.x + 1.0) * 0.5, 1.0 - (corner.y + 1.0) * 0.5);
    return out;
}

@group(0) @binding(0) var colour_plane: texture_2d<f32>;
@group(0) @binding(1) var alpha_plane: texture_2d<f32>;
@group(0) @binding(2) var plane_sampler: sampler;
// [0] x: 1 when the colour is YCoCg, y: where the alpha is (0 none, 1 its own
//     plane, 2 the colour's fourth channel), zw: how much of the texture the
//     picture actually occupies.
// [1] rgb: what the colour is multiplied by on its way out.
// [2] the re-bake: x is 0 off, 1 dither, 2 clean; y the threshold as a
//     fraction; z what to do with the colour above the threshold -- 0 leave
//     it, 1 hold it down to the alpha, 2 multiply it by the alpha; w 1 to
//     ignore the gain, which is what writing a file does: a slider is how
//     somebody looks at a screen, not what the content is.
@group(0) @binding(3) var<uniform> about: array<vec4<f32>, 3>;
// One threshold per pixel of the picture, for the dither. Read rather than
// sampled: a threshold that had been averaged with its neighbours would not
// be a threshold any more.
@group(0) @binding(4) var noise_map: texture_2d<f32>;

@fragment
fn fs_main(in: VOut) -> @location(0) vec4<f32> {
    let settings = about[0];
    let uv = in.uv * settings.zw;
    var colour = textureSample(colour_plane, plane_sampler, uv);
    let carried = colour.a;              // before the conversion below eats it

    if (settings.x > 0.0) {
        // Hap Q: luma sits in alpha, chroma in red and green, and blue holds
        // the scale the two chroma channels were stretched by.
        let shifted = colour + vec4<f32>(-0.50196078431373, -0.50196078431373,
                                         0.0, 0.0);
        let scale = (shifted.z * (255.0 / 8.0)) + 1.0;
        let co = shifted.x / scale;
        let cg = shifted.y / scale;
        let y = shifted.w;
        colour = vec4<f32>(y + co - cg, y + cg, y - co - cg, 1.0);
    }

    // Where the alpha is: nothing, a plane of its own, or the colour's own
    // fourth channel. Three answers, not two -- Hap Q Alpha carries it beside
    // the colour, an ordinary RGBA picture carries it inside, and Hap Q on its
    // own puts luma in that channel and would be read as nonsense.
    if (settings.y > 1.5) {
        colour.a = carried;
    } else if (settings.y > 0.5) {
        colour.a = textureSample(alpha_plane, plane_sampler, uv).r;
    } else {
        colour.a = 1.0;
    }

    // -- the re-bake ---------------------------------------------------------
    //
    // Here rather than in a pass of its own, so that what the window shows and
    // what gets written are the same arithmetic. Off, this is one comparison
    // against zero and nothing else happens.
    let recipe = about[2];
    if (recipe.x > 1.5) {
        // Clean. The alpha is left exactly as it was; the colour goes where it
        // is too faint to be anything but the rubbish that shows up when the
        // file is read as premultiplied.
        if (colour.a < recipe.y) {
            colour = vec4<f32>(0.0, 0.0, 0.0, colour.a);
        } else if (recipe.z > 1.5) {
            // Multiplied. The colour is folded into its own alpha, which is
            // what premultiplied means, so the premultiplied reading becomes
            // the right one. It costs the other: read straight, the alpha is
            // applied a second time and the fade comes out darker by exactly
            // that factor. Softer than the clamp below -- a scale rather than
            // a ceiling, so nothing has a knee in it.
            colour = vec4<f32>(colour.rgb * colour.a, colour.a);
        } else if (recipe.z > 0.5) {
            colour = vec4<f32>(min(colour.rgb, vec3<f32>(colour.a)), colour.a);
        }
    } else if (recipe.x > 0.5) {
        // Dither. The alpha becomes one or the other against a fixed
        // threshold, so the two readings of the file agree by construction.
        //
        // The threshold is taken half a step in from the ends: a map running
        // 0 to 255 read as 0 to 1 would drop one pixel in 256 out of a fully
        // opaque area and light one in 256 of an empty one. Half a step in,
        // solid stays solid and clear stays clear, and everything between is
        // still unbiased.
        let size = vec2<f32>(textureDimensions(noise_map));
        let at = vec2<i32>(clamp(in.uv * size, vec2<f32>(0.0), size - 1.0));
        let level = (textureLoad(noise_map, at, 0).r * 255.0 + 0.5) / 256.0;
        if (colour.a > level) {
            colour.a = 1.0;
        } else {
            // The colour goes too. Left behind, a premultiplied read would lay
            // it on whole and the screen would come up all at once with no
            // fade at all -- which is the thing being cured.
            colour = vec4<f32>(0.0, 0.0, 0.0, 0.0);
        }
    }

    let paint = select(about[1].rgb, vec3<f32>(1.0, 1.0, 1.0), recipe.w > 0.5);
    return vec4<f32>(colour.rgb * paint, colour.a);
}
"""


def make_device(power: str = "high-performance"):
    """A device, and whether its sampler will unpack a block itself.

    Asked for rather than assumed: BC is an optional feature in WebGPU. Where
    it is there the blocks go straight to the sampler, which is the cheap path
    and the reason this application is built the way it is. Where it is not --
    Apple silicon, and only Apple silicon among the machines this will meet --
    a compute pass unpacks them instead, at about half a millisecond a frame.

    The device carries the answer on itself as `decodes_blocks`, so nothing has
    to ask the adapter a second time and get a different card.
    """
    adapter = wgpu.gpu.request_adapter_sync(power_preference=power)
    if adapter is None:
        raise RuntimeError("no GPU adapter at all")
    in_hardware = "texture-compression-bc" in [str(f) for f in adapter.features]
    if os.environ.get("MATRESHKA_NO_BC"):
        # The Apple silicon path, on a machine that does not need it. Kept in
        # because the alternative is that the fallback is only ever exercised
        # on the one machine nobody testing this owns.
        in_hardware = False
    device = adapter.request_device_sync(
        required_features=["texture-compression-bc"] if in_hardware else [])
    device.decodes_blocks = not in_hardware
    return adapter, device


def plane_for(device, width: int, height: int, texture_format: str):
    """A block texture the sampler reads, or one a compute pass fills in.

    One call rather than a check at every site: which of the two it is depends
    on the machine, and everything above only ever wants a thing with a view
    and an `upload`.
    """
    if getattr(device, "decodes_blocks", False) and texture_format.startswith("bc"):
        if not hasattr(device, "_block_decoder"):
            device._block_decoder = blockdecode.Decoder(device)
        return blockdecode.Softened(device._block_decoder, width, height,
                                    texture_format)
    return Plane(device, width, height, texture_format)


class Plane:
    """One compressed texture, sized to the block grid."""

    def __init__(self, device, width: int, height: int, texture_format: str) -> None:
        self.width, self.height = width, height
        self.compressed = texture_format.startswith("bc")
        if self.compressed:
            self.across = (width + 3) // 4
            self.down = (height + 3) // 4
            self.padded = (self.across * 4, self.down * 4)
            block_bytes = 8 if texture_format.startswith(("bc1", "bc4")) else 16
            self.bytes_per_row = self.across * block_bytes
        else:
            # A decoded frame is pixels, not blocks: nothing to round up to.
            self.across, self.down = width, height
            self.padded = (width, height)
            self.bytes_per_row = width * 4

        self.texture = device.create_texture(
            size=(self.padded[0], self.padded[1], 1), format=texture_format,
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        self.view = self.texture.create_view()
        self.device = device

    def upload(self, blocks, encoder=None) -> None:
        # `encoder` is what the softened plane beside this one needs; here
        # there is nothing to record, so it is accepted and ignored.
        self.device.queue.write_texture(
            {"texture": self.texture}, blocks,
            {"bytes_per_row": self.bytes_per_row, "rows_per_image": self.down},
            (self.padded[0], self.padded[1], 1))


class Screen:
    """One video surface: its planes, and what the shader must know about them."""

    def __init__(self, device, movie) -> None:
        self.device = device
        self.width, self.height = movie.width, movie.height
        self.planes = [plane_for(device, plane.width, plane.height,
                                 plane.gpu_format)
                       for plane in movie.planes]
        self.ycocg = movie.planes[0].is_ycocg
        self.has_alpha = len(self.planes) > 1
        # 0 none, 1 a plane of its own, 2 inside the colour. A movie that says
        # nothing is taken to be opaque, which is what a decoded one was.
        self.alpha_from = (1 if self.has_alpha
                           else 2 if getattr(movie, "alpha_in_colour", False)
                           else 0)

        # Where the picture stops inside a texture rounded up to whole blocks.
        padded = self.planes[0].padded
        self.uv_scale = (self.width / padded[0], self.height / padded[1])

        if not self.has_alpha:
            # The layout is fixed, so something has to sit at the alpha binding.
            self.planes.append(plane_for(device, 4, 4, "bc4-r-unorm"))
            self.planes[-1].upload(bytes(8))

        self.sampler = device.create_sampler(
            mag_filter="linear", min_filter="linear",
            address_mode_u="clamp-to-edge", address_mode_v="clamp-to-edge")
        self.gain = (1.0, 1.0, 1.0)
        # 0 off, 1 dither, 2 clean; the threshold as a fraction; whether to
        # clamp the colour to its alpha; whether to ignore the gain.
        self.rebake = (0.0, 0.0, 0.0, 0.0)
        # Two of them, holding the same screen with and without its re-bake.
        # Not one buffer written twice: both halves of the split preview are
        # recorded into one submission, and a uniform written between two
        # recorded draws is read by neither -- they would both see whatever
        # was written last.
        self.settings = device.create_buffer(
            size=48, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        self.rebake_settings = device.create_buffer(
            size=48, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        # Something has to sit at the noise binding whether or not anybody is
        # dithering: the layout is fixed and a hole in it is a refusal.
        self.noise = device.create_texture(
            size=(1, 1, 1), format="r8unorm",
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        device.queue.write_texture({"texture": self.noise}, bytes(1),
                                   {"bytes_per_row": 1, "rows_per_image": 1},
                                   (1, 1, 1))
        self._write_settings()

    def _write_settings(self) -> None:
        common = [1.0 if self.ycocg else 0.0, float(self.alpha_from),
                  self.uv_scale[0], self.uv_scale[1],
                  self.gain[0], self.gain[1], self.gain[2], 1.0]
        self.device.queue.write_buffer(self.settings, 0, np.array(
            common + [0.0, 0.0, 0.0, 0.0], dtype=np.float32).tobytes())
        self.device.queue.write_buffer(self.rebake_settings, 0, np.array(
            common + list(self.rebake), dtype=np.float32).tobytes())

    def set_gain(self, rgb) -> None:
        """What this screen's colour is multiplied by on its way to the target."""
        self.gain = tuple(float(v) for v in rgb)
        self._write_settings()

    def set_rebake(self, what: int = 0, threshold: float = 0.0,
                   colour: int = 0, own_colour: bool = False) -> None:
        """How this screen's alpha is to be remade, if at all.

        `colour` is what happens to the colour above the threshold: 0 leaves
        it, 1 holds it down to the alpha, 2 multiplies it by the alpha.

        `own_colour` turns the brightness slider off for the duration, which is
        what writing a file wants: the slider says how somebody is looking at
        the screen, not what the content is.
        """
        self.rebake = (float(what), float(threshold),
                       float(colour), 1.0 if own_colour else 0.0)
        self._write_settings()

    def load_noise(self, values) -> None:
        """The dither's threshold map, one byte a pixel of the picture."""
        values = np.ascontiguousarray(values, dtype=np.uint8)
        height, width = values.shape
        self.noise = self.device.create_texture(
            size=(width, height, 1), format="r8unorm",
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        self.device.queue.write_texture(
            {"texture": self.noise}, values,
            {"bytes_per_row": width, "rows_per_image": height},
            (width, height, 1))

    def upload(self, buffers) -> None:
        """Hand one frame to the card, exactly as it came out of the file.

        One encoder between all of a screen's planes: where they have to be
        unpacked by a compute pass, that is one submission a frame instead of
        one for the colour and another for the alpha.
        """
        encoder = (self.device.create_command_encoder()
                   if getattr(self.device, "decodes_blocks", False) else None)
        for plane, blocks in zip(self.planes, buffers):
            plane.upload(blocks, encoder)
        if encoder is not None:
            self.device.queue.submit([encoder.finish()])


FILL_SHADER = """
@vertex
fn vs_main(@builtin(vertex_index) index: u32) -> @builtin(position) vec4<f32> {
    var corners = array<vec2<f32>, 3>(
        vec2<f32>(-1.0, -1.0), vec2<f32>(3.0, -1.0), vec2<f32>(-1.0, 3.0));
    return vec4<f32>(corners[index], 0.0, 1.0);
}

@fragment
fn fs_main() -> @location(0) vec4<f32> {
    return vec4<f32>(0.0, 0.0, 0.0, 1.0);
}
"""


PICTURE_SHADER = """
struct VOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) index: u32) -> VOut {
    var corners = array<vec2<f32>, 3>(
        vec2<f32>(-1.0, -1.0), vec2<f32>(3.0, -1.0), vec2<f32>(-1.0, 3.0));
    let corner = corners[index];
    var out: VOut;
    out.pos = vec4<f32>(corner, 0.0, 1.0);
    out.uv = vec2<f32>((corner.x + 1.0) * 0.5, 1.0 - (corner.y + 1.0) * 0.5);
    return out;
}

@group(0) @binding(0) var picture: texture_2d<f32>;
@group(0) @binding(1) var picture_sampler: sampler;

@fragment
fn fs_main(in: VOut) -> @location(0) vec4<f32> {
    return vec4<f32>(textureSample(picture, picture_sampler, in.uv).rgb, 1.0);
}
"""


class Painter:
    """Draws a screen's texture into a target."""

    def __init__(self, device, target_format: str = "rgba8unorm") -> None:
        self.device = device
        self.target_format = target_format
        self._plain = None
        self._fill = None
        shader = device.create_shader_module(code=SHADER)
        # The shader hands out the colour and the alpha as they are; which of
        # the two readings applies is left to the blend, so the same shader and
        # the same bind groups serve both and nothing has to be re-bound to
        # change the mode.
        #
        #   premultiplied  rgb   + dst * (1 - a)
        #   straight       rgb*a + dst * (1 - a)
        #
        # Spelled out rather than "auto" because there are two pipelines and one
        # set of bind groups between them: an automatic layout belongs to the
        # pipeline that made it, and a group built against one is refused by
        # the other.
        self.group_layout = device.create_bind_group_layout(entries=[
            {"binding": 0, "visibility": wgpu.ShaderStage.FRAGMENT,
             "texture": {"sample_type": wgpu.TextureSampleType.float}},
            {"binding": 1, "visibility": wgpu.ShaderStage.FRAGMENT,
             "texture": {"sample_type": wgpu.TextureSampleType.float}},
            {"binding": 2, "visibility": wgpu.ShaderStage.FRAGMENT,
             "sampler": {"type": wgpu.SamplerBindingType.filtering}},
            {"binding": 3, "visibility": wgpu.ShaderStage.FRAGMENT,
             "buffer": {"type": wgpu.BufferBindingType.uniform}},
            {"binding": 4, "visibility": wgpu.ShaderStage.FRAGMENT,
             "texture": {"sample_type": wgpu.TextureSampleType.float}},
        ])
        pipeline_layout = device.create_pipeline_layout(
            bind_group_layouts=[self.group_layout])

        self.pipelines = {}
        for mode, factor in (("premultiplied", "one"), ("straight", "src-alpha")):
            self.pipelines[mode] = device.create_render_pipeline(
                layout=pipeline_layout,
                vertex={"module": shader, "entry_point": "vs_main"},
                fragment={"module": shader, "entry_point": "fs_main",
                          "targets": [{
                              "format": target_format,
                              "blend": {
                                  "color": {"src_factor": factor,
                                            "dst_factor": "one-minus-src-alpha",
                                            "operation": "add"},
                                  "alpha": {"src_factor": "one",
                                            "dst_factor": "one-minus-src-alpha",
                                            "operation": "add"}}}]},
                primitive={"topology": "triangle-list"},
            )
        self.pipeline = self.pipelines["premultiplied"]
        self._groups: dict[int, object] = {}
        self.sampler = device.create_sampler(
            mag_filter="linear", min_filter="linear",
            address_mode_u="clamp-to-edge", address_mode_v="clamp-to-edge")

    def _picture_pipeline(self):
        """A second, plainer pipeline: an ordinary texture straight to screen.

        The calibration pictures are not video and are not compressed, so they
        cannot go through the pipeline above, which is built to unpack blocks
        and undo YCoCg.
        """
        if getattr(self, "_plain", None) is None:
            shader = self.device.create_shader_module(code=PICTURE_SHADER)
            self._plain = self.device.create_render_pipeline(
                layout="auto",
                vertex={"module": shader, "entry_point": "vs_main"},
                fragment={"module": shader, "entry_point": "fs_main",
                          "targets": [{"format": self.target_format}]},
                primitive={"topology": "triangle-list"})
            self._plain_groups = {}
        return self._plain

    def fill(self, encoder, view, viewport=None) -> None:
        """Black over one rectangle of the target.

        Drawn rather than cleared: a pass clears the whole attachment whatever
        the viewport says, and what is wanted here is one strip of it.
        """
        if getattr(self, "_fill", None) is None:
            shader = self.device.create_shader_module(code=FILL_SHADER)
            self._fill = self.device.create_render_pipeline(
                layout=self.device.create_pipeline_layout(bind_group_layouts=[]),
                vertex={"module": shader, "entry_point": "vs_main"},
                fragment={"module": shader, "entry_point": "fs_main",
                          "targets": [{"format": self.target_format}]},
                primitive={"topology": "triangle-list"})

        pass_ = encoder.begin_render_pass(color_attachments=[{
            "view": view, "load_op": "load", "store_op": "store",
            "clear_value": (0, 0, 0, 1)}])
        if viewport is not None:
            x, y, wide, tall = viewport
            pass_.set_viewport(x, y, max(1.0, wide), max(1.0, tall), 0.0, 1.0)
        pass_.set_pipeline(self._fill)
        pass_.draw(3)
        pass_.end()

    def draw_picture(self, encoder, texture, view, viewport=None,
                     clear: bool = False) -> None:
        pipeline = self._picture_pipeline()
        key = id(texture)
        group = self._plain_groups.get(key)
        if group is None:
            group = self.device.create_bind_group(
                layout=pipeline.get_bind_group_layout(0),
                entries=[{"binding": 0, "resource": texture.create_view()},
                         {"binding": 1, "resource": self.sampler}])
            self._plain_groups[key] = group

        pass_ = encoder.begin_render_pass(color_attachments=[{
            "view": view,
            "load_op": "clear" if clear else "load",
            "store_op": "store",
            "clear_value": (0, 0, 0, 1)}])
        if viewport is not None:
            x, y, wide, tall = viewport
            pass_.set_viewport(x, y, max(1.0, wide), max(1.0, tall), 0.0, 1.0)
        pass_.set_pipeline(pipeline)
        pass_.set_bind_group(0, group)
        pass_.draw(3)
        pass_.end()

    def group_for(self, screen: Screen, rebaked: bool = False):
        # Keyed on the noise as well as the screen: loading a threshold map
        # makes a new texture, and a group cached against the old one would go
        # on dithering by a map nobody can see any more.
        key = (id(screen), id(screen.noise), rebaked)
        group = self._groups.get(key)
        if group is None:
            settings = screen.rebake_settings if rebaked else screen.settings
            group = self.device.create_bind_group(
                layout=self.group_layout,
                entries=[
                    {"binding": 0, "resource": screen.planes[0].view},
                    {"binding": 1, "resource": screen.planes[1].view},
                    {"binding": 2, "resource": screen.sampler},
                    {"binding": 3, "resource": {"buffer": settings,
                                                "offset": 0, "size": 48}},
                    {"binding": 4, "resource": screen.noise.create_view()},
                ])
            self._groups[key] = group
        return group

    def clear(self, encoder, view, opaque: bool = True) -> None:
        """Black, everywhere, before any screen is drawn.

        A pass of its own rather than a flag on the first screen, because the
        first screen is not always drawn: one that has run past its end goes
        dark, and the clearing must not go with it.

        `opaque` is what the window wants and what a file with an alpha does
        not: the blend adds the screen's own alpha to whatever is underneath,
        so starting from one leaves every pixel solid however transparent the
        content was.
        """
        pass_ = encoder.begin_render_pass(
            color_attachments=[{
                "view": view, "load_op": "clear", "store_op": "store",
                "clear_value": (0, 0, 0, 1 if opaque else 0),
            }])
        pass_.end()

    def draw(self, encoder, screen: Screen, view, viewport=None,
             clear: bool = False, alpha: str = "premultiplied",
             clip=None, rebaked: bool = False) -> None:
        """One screen into one rectangle of the target, over what is there.

        `clip` keeps only part of that rectangle, which is how the same strip
        is drawn twice -- once as it is and once re-baked -- into two halves of
        one place, without either half being squashed to fit.
        """
        pass_ = encoder.begin_render_pass(
            color_attachments=[{
                "view": view,
                "load_op": "clear" if clear else "load",
                "store_op": "store",
                "clear_value": (0, 0, 0, 1),
            }])
        if viewport is not None:
            x, y, width, height = viewport
            pass_.set_viewport(x, y, max(1.0, width), max(1.0, height), 0.0, 1.0)
        if clip is not None:
            left, top, wide, tall = (int(v) for v in clip)
            if wide <= 0 or tall <= 0:
                pass_.end()
                return
            pass_.set_scissor_rect(max(0, left), max(0, top), wide, tall)
        pass_.set_pipeline(self.pipelines[alpha])
        pass_.set_bind_group(0, self.group_for(screen, rebaked))
        pass_.draw(3)
        pass_.end()

    def _writing_pipeline(self):
        """The screen as it is, straight into a target: no blend, no backing.

        The compositing pipelines above answer "what does this look like on
        the wall". This one answers "what is in the file", which is what has to
        be handed to an encoder.
        """
        if getattr(self, "_write", None) is None:
            shader = self.device.create_shader_module(code=SHADER)
            self._write = self.device.create_render_pipeline(
                layout=self.device.create_pipeline_layout(
                    bind_group_layouts=[self.group_layout]),
                vertex={"module": shader, "entry_point": "vs_main"},
                fragment={"module": shader, "entry_point": "fs_main",
                          "targets": [{"format": "rgba8unorm"}]},
                primitive={"topology": "triangle-list"})
        return self._write

    def frame_of(self, screen: Screen):
        """One frame of a screen as straight RGBA at its own size.

        Whatever the screen's re-bake is set to is already in this: it happens
        in the same shader the window draws through, so a file written from
        here cannot disagree with the picture that was looked at.
        """
        width, height = screen.width, screen.height
        row, stride = width * 4, -(-(width * 4) // 256) * 256
        # Kept per shape rather than one at a time. A re-bake walks two screens
        # turn and turn about, and a single slot would throw the target and the
        # readback away and build them again on every frame -- 29 MB of buffer
        # a frame for the bottom screen, allocated to be used once.
        if not hasattr(self, "_writing"):
            self._writing: dict = {}
        if (width, height) not in self._writing:
            self._writing[(width, height)] = (
                self.device.create_texture(
                    size=(width, height, 1), format="rgba8unorm",
                    usage=wgpu.TextureUsage.RENDER_ATTACHMENT
                          | wgpu.TextureUsage.COPY_SRC),
                self.device.create_buffer(
                    size=stride * height,
                    usage=wgpu.BufferUsage.COPY_DST
                          | wgpu.BufferUsage.MAP_READ))
        self._writing_target, self._writing_back = self._writing[(width, height)]

        encoder = self.device.create_command_encoder()
        pass_ = encoder.begin_render_pass(color_attachments=[{
            "view": self._writing_target.create_view(),
            "load_op": "clear", "store_op": "store",
            "clear_value": (0, 0, 0, 0)}])
        pass_.set_pipeline(self._writing_pipeline())
        pass_.set_bind_group(0, self.group_for(screen, rebaked=True))
        pass_.draw(3)
        pass_.end()
        encoder.copy_texture_to_buffer(
            {"texture": self._writing_target},
            {"buffer": self._writing_back, "bytes_per_row": stride,
             "rows_per_image": height},
            (width, height, 1))
        self.device.queue.submit([encoder.finish()])

        # Copied once, straight out of the mapped rows into a picture of its
        # own. It used to go `bytes(read_mapped())` and then take the padding
        # off, which is two passes over the whole frame -- 29 MB twice for the
        # bottom screen, and that copying, not waiting for the card, was the
        # larger half of what a re-bake spent here.
        #
        # It has to be a copy: the rows only exist until the unmap below, and
        # where the stride happens to match the width -- the bottom screen is
        # 18432 bytes either way -- a view would be handed out instead.
        picture = np.empty((height, width, 4), np.uint8)
        self._writing_back.map_sync("read")
        try:
            rows = np.frombuffer(self._writing_back.read_mapped(), np.uint8)
            picture.reshape(height, row)[:] = (
                rows[:stride * height].reshape(height, stride)[:, :row])
        finally:
            self._writing_back.unmap()
        return picture

    def to_array(self, screen: Screen, width: int = 0, height: int = 0,
                 alpha: str = "premultiplied"):
        """Render one screen into an array, for looking at and for testing."""
        width = width or screen.width
        height = height or screen.height
        target = self.device.create_texture(
            size=(width, height, 1), format="rgba8unorm",
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)

        row = width * 4
        stride = -(-row // 256) * 256
        readback = self.device.create_buffer(
            size=stride * height,
            usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ)

        encoder = self.device.create_command_encoder()
        # Cleared, not loaded: the target is new here, and now that the draw
        # blends, what it blends onto has to be something.
        self.draw(encoder, screen, target.create_view(), clear=True, alpha=alpha)
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
