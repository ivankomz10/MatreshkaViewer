"""The scene as geometry, drawn with the camera from the file.

The real thing rather than a flattened picture of it: one pass over a million
triangles with a depth buffer and multisampling. It costs more than reading a
table and gives back the three things flattening cannot -- any window size,
real edges, and mip levels on the video.

The camera is the one in the blend, used as authored. Its matrix is inverted
for the view; its lens and sensor give the projection; and the frame keeps the
shape the file is set up for rather than stretching to the window, so what is
on screen is what that camera sees.

Only the screens are shaded with any care. Everything else is matte grey and
black in the file and is here to show what hides what, so it gets a plain
two-sided light and nothing more.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import wgpu

SAMPLES = 4          # multisampling; the lamella slats are all thin edges

# The top screen is in the file twice, as two pieces of geometry showing the
# same video. `Screen_Top` is the honeycomb as modelled and stands still;
# `screen` is the same 1500 cells rigged to the motors, and is drawn in its
# place the moment a kinetic JSON is loaded. Which of the two is on is the
# window's business; what matters here is that only one of them ever is.
#
# Six vertices to a cell, kept together, so a vertex knows which cell it is in
# from its own index and nothing has to be baked beside the geometry to say so.
KINETIC_SCREEN = "screen"
DEFAULT_TOP = "Screen_Top"
CELL_VERTICES = 6
CELLS_ON_KINETIC = 1500

SHADER = """
struct Frame {
    view_projection: mat4x4<f32>,
    // x: 0 black behind the video, 1 calibration; y: video opacity;
    // z: 1 to read the colour as premultiplied rather than straight;
    // w: 1 to flood every screen with white, which is how the brightness
    //    match below measures what each of them covers
    backing: vec4<f32>,
    // xyz direction towards the light; w: 1 to drop the far side of the
    // top screen, so its own back does not show through its front
    light: vec4<f32>,
};

struct Piece {
    // rgb: flat colour; w: 1 when this is a screen
    colour: vec4<f32>,
    // x: which screen (0..2); y: 1 when this piece's cells move;
    // z: 1 when it is the top screen, whose far side can be dropped -- which
    //    is both of its geometries, standing still or moving alike
    which: vec4<f32>,
};

@group(0) @binding(0) var<uniform> frame: Frame;
// One transform per cell of the kinetic screen. A cell is six vertices kept
// together in the buffer, so which one a vertex belongs to is its own index
// divided by six -- nothing has to be baked beside the geometry to say so.
@group(0) @binding(1) var<storage, read> cells: array<mat4x4<f32>>;
@group(1) @binding(0) var<uniform> piece: Piece;

struct VOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) normal: vec3<f32>,
    @location(1) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) index: u32,
           @location(0) point: vec3<f32>,
           @location(1) normal: vec3<f32>,
           @location(2) uv: vec2<f32>) -> VOut {
    var here = point;
    var facing = normal;
    if (piece.which.y > 0.5) {
        let moved = cells[index / 6u];
        here = (moved * vec4<f32>(point, 1.0)).xyz;
        facing = (moved * vec4<f32>(normal, 0.0)).xyz;
    }
    var out: VOut;
    out.pos = frame.view_projection * vec4<f32>(here, 1.0);
    out.normal = facing;
    out.uv = uv;
    return out;
}

@group(2) @binding(0) var video_0: texture_2d<f32>;
@group(2) @binding(1) var alpha_0: texture_2d<f32>;
@group(2) @binding(2) var calib_0: texture_2d<f32>;
@group(2) @binding(3) var video_1: texture_2d<f32>;
@group(2) @binding(4) var alpha_1: texture_2d<f32>;
@group(2) @binding(5) var calib_1: texture_2d<f32>;
@group(2) @binding(6) var video_2: texture_2d<f32>;
@group(2) @binding(7) var alpha_2: texture_2d<f32>;
@group(2) @binding(8) var calib_2: texture_2d<f32>;
@group(2) @binding(9) var screen_sampler: sampler;
@group(2) @binding(11) var frame_colour: texture_2d<f32>;
@group(2) @binding(12) var frame_alpha: texture_2d<f32>;
// [0..2] one per screen -- x: 1 when the video is YCoCg, y: where the alpha is
// (-1 nothing loaded, 0 none, 1 its own plane, 2 the colour's fourth channel),
// zw: uv scale.
// [3] and [4] describe the frame laid over one of them; see `frame_over`.
// [5..7] one per screen: rgb is what its emission is multiplied by, which is
// how two screens of different build are made to read at the same brightness.
@group(2) @binding(10) var<uniform> screens: array<vec4<f32>, 8>;

fn from_ycocg(raw: vec4<f32>) -> vec3<f32> {
    let shifted = raw + vec4<f32>(-0.50196078431373, -0.50196078431373, 0.0, 0.0);
    let scale = (shifted.z * (255.0 / 8.0)) + 1.0;
    let co = shifted.x / scale;
    let cg = shifted.y / scale;
    let y = shifted.w;
    return vec3<f32>(y + co - cg, y + cg, y - co - cg);
}


// -- the frame laid over one screen -----------------------------------------
//
// A separate picture or movie composited on top of whatever that screen is
// showing, with its own alpha. Only one screen wears it, named by `place.z`;
// `place.z` below zero means there is none loaded.
//
//   about = screens[3]  x: 1 when YCoCg, y: where the alpha is, zw: uv scale
//   place = screens[4]  xy: how much of the screen the frame covers,
//                       z: which screen it is on, or -1,
//                       w: what its own light is multiplied by
//
// Fitted, `place.xy` is under one and the frame sits centred with nothing
// either side of it; stretched, both are one and it covers the screen.
fn frame_over(under: vec3<f32>, uv: vec2<f32>, premultiplied: f32) -> vec3<f32> {
    let about = screens[3];
    let place = screens[4];

    // Where this point of the screen falls inside the frame's own picture.
    let inner = (uv - (vec2<f32>(1.0, 1.0) - place.xy) * 0.5) / place.xy;
    let inside = all(inner >= vec2<f32>(0.0, 0.0)) && all(inner <= vec2<f32>(1.0, 1.0));
    // Sampled whether or not it is wanted, and thrown away after: a texture
    // may only be read where every pixel of the group agrees to read it, and
    // `inside` is a per-pixel answer.
    let scaled = clamp(inner, vec2<f32>(0.0, 0.0), vec2<f32>(1.0, 1.0)) * about.zw;

    let raw = textureSample(frame_colour, screen_sampler, scaled);
    let carried = raw.a;
    var colour = raw.rgb;
    if (about.x > 0.0) {
        colour = from_ycocg(raw);
    }
    var a = 1.0;
    if (about.y > 1.5) {
        a = carried;
    } else if (about.y > 0.5) {
        a = textureSample(frame_alpha, screen_sampler, scaled).r;
    }
    if (!inside) {
        a = 0.0;
    }

    // Read the same way the screens are, or the frame would answer a
    // different question from everything under it.
    var on = colour * a;
    if (premultiplied > 0.0) {
        on = colour;
    }
    // Turned up or down on its own: the frame is a separate thing laid over
    // the screen, and how bright it should be is a separate question.
    return under * (1.0 - a) + on * place.w;
}


// Where the alpha is, and whether there is anything here at all:
//   -1  nothing loaded on this screen -- only the backing shows
//    0  opaque
//    1  a plane of its own
//    2  the colour's fourth channel
// The fourth answer is the one that was missing: without it an empty
// screen was described as an opaque video, and the blank black texture
// standing in for it covered the calibration the moment anything else
// was loaded.
fn screen_colour(which: i32, baked_uv: vec2<f32>) -> vec3<f32> {
    // Flat white, ungained: this is the measurement, not a picture. What it
    // leaves on screen is exactly the area the screen covers, which is the
    // one thing the match needs to know.
    if (frame.backing.w > 0.5) {
        return vec3<f32>(1.0, 1.0, 1.0);
    }
    // Blender counts v from the bottom, a texture from the top.
    let uv = vec2<f32>(baked_uv.x, 1.0 - baked_uv.y);
    var raw: vec4<f32>;
    var alpha_raw: vec4<f32>;
    var calib: vec4<f32>;
    var about: vec4<f32>;

    if (which == 0) {
        about = screens[0];
        raw = textureSample(video_0, screen_sampler, uv * about.zw);
        alpha_raw = textureSample(alpha_0, screen_sampler, uv * about.zw);
        calib = textureSample(calib_0, screen_sampler, uv);
    } else if (which == 1) {
        about = screens[1];
        raw = textureSample(video_1, screen_sampler, uv * about.zw);
        alpha_raw = textureSample(alpha_1, screen_sampler, uv * about.zw);
        calib = textureSample(calib_1, screen_sampler, uv);
    } else {
        about = screens[2];
        raw = textureSample(video_2, screen_sampler, uv * about.zw);
        alpha_raw = textureSample(alpha_2, screen_sampler, uv * about.zw);
        calib = textureSample(calib_2, screen_sampler, uv);
    }

    // Read before the conversion below eats the fourth channel.
    var carried = raw.a;
    var video = raw.rgb;
    if (about.x > 0.0) {
        video = from_ycocg(raw);
    }
    // Where the alpha is: nothing, a plane of its own, or the colour's own
    // fourth channel. Three answers, not two -- Hap Q Alpha carries it beside
    // the colour, an ordinary RGBA picture carries it inside, and Hap Q on its
    // own puts luma in that channel and would be read as nonsense.
    var opacity = frame.backing.y;
    if (about.y < -0.5) {
        opacity = 0.0;
    } else if (about.y > 1.5) {
        opacity = opacity * carried;
    } else if (about.y > 0.5) {
        opacity = opacity * alpha_raw.r;
    }
    var behind = vec3<f32>(0.0, 0.0, 0.0);
    if (frame.backing.x > 0.0) {
        behind = calib.rgb;
    }
    // Straight alpha multiplies the colour by it, so whatever was left in the
    // picture under a transparent alpha is quietly multiplied away and the
    // screen looks clean whether or not it is. Premultiplied puts the colour
    // on whole and that rubbish shows, which is the only way to see it.
    var over = video * opacity;
    if (frame.backing.z > 0.0) {
        over = video * frame.backing.y;
    }
    if (about.y < -0.5) {
        over = vec3<f32>(0.0, 0.0, 0.0);
    }
    var shown = behind * (1.0 - opacity) + over;
    if (screens[4].z > -0.5 && i32(screens[4].z) == which) {
        shown = frame_over(shown, uv, frame.backing.z);
    }
    // Last, and to everything the screen emits -- content, backing and frame
    // alike. A screen is a lamp, and this is how brightly it is turned up.
    return shown * screens[5 + which].rgb;
}

@fragment
fn fs_main(in: VOut, @builtin(front_facing) front: bool) -> @location(0) vec4<f32> {
    if (piece.which.z > 0.5 && frame.light.w > 0.5 && !front) {
        discard;
    }
    if (piece.colour.w > 0.5) {
        // A screen shows what it is given, unlit: it is a lamp, not a surface.
        return vec4<f32>(screen_colour(i32(piece.which.x), in.uv), 1.0);
    }
    // Everything else only has to read as a shape. Lit from above and filled
    // from below so nothing goes to pure black and hides what it occludes.
    let n = normalize(in.normal);
    let facing = clamp(dot(n, normalize(frame.light.xyz)), -1.0, 1.0);
    let shade = 0.35 + 0.65 * (facing * 0.5 + 0.5);
    return vec4<f32>(piece.colour.rgb * shade, 1.0);
}
"""


def mend_seam(points, normals, uv, triangles):
    """Keep a face that straddles the u=0/1 seam from racing round the picture.

    On the cylindrical screens the back of the ring closes with faces whose
    corners carry u near 1 on one side and u near 0 on the other. Nothing
    wraps the texture here -- the sampler is clamp-to-edge -- so between those
    corners u is walked the long way, 0.99 down to 0.0, and the whole width of
    the video is crushed into that sliver. That is the band of noise seen at
    the seam of the top and bottom screens; the lamellas, which do not close,
    never show it.

    The cure is to send the low corner to the far end instead: u just past 1,
    a short step from the 0.99 beside it, so the face shows the edge of the
    picture rather than all of it.

    The honeycomb -- still (`Screen_Top`) or moving (`screen`) -- is kept as
    separate six-vertex cells, and a seam cell's vertices are shared with
    nothing outside it, so it is mended in place, a whole cell at a time: a
    cell that straddles the seam has corners at both ends of u, and lifting
    only some of them would leave the crush between those and the rest. That
    also leaves the vertex count and order untouched, which the moving screen
    needs: it finds a cell from `vertex_index / 6`. The bottom screen is a
    welded strip whose seam vertices are shared with their neighbours, so there
    the corner is split off into a copy that carries the raised u and only the
    seam faces point at it.
    """
    u = uv[:, 0]
    span = u[triangles].max(axis=1) - u[triangles].min(axis=1)
    seam = np.where(span > 0.5)[0]
    if len(seam) == 0:
        return points, normals, uv, triangles

    uv = uv.copy()
    grouped = all(len({int(v) // CELL_VERTICES for v in tri}) == 1
                  for tri in triangles)
    if grouped:
        # A cell is six consecutive vertices. Only the handful sitting on the
        # seam span more than half of u; in each of those, the corners near 0
        # belong just past 1, beside the ones near 1 already there.
        cells = len(uv) // CELL_VERTICES
        blocks = uv[:cells * CELL_VERTICES].reshape(cells, CELL_VERTICES, 2)
        us = blocks[..., 0]
        straddles = (us.max(axis=1) - us.min(axis=1)) > 0.5
        us[straddles[:, None] & (us < 0.5)] += 1.0
        return points, normals, uv, triangles

    points, normals = points.copy(), normals.copy()
    triangles = triangles.copy()
    extra_points, extra_normals, extra_uv = [], [], []
    raised: dict[int, int] = {}

    def past_the_end(vertex: int) -> int:
        if vertex not in raised:
            raised[vertex] = len(points) + len(extra_points)
            extra_points.append(points[vertex])
            extra_normals.append(normals[vertex])
            extra_uv.append([uv[vertex, 0] + 1.0, uv[vertex, 1]])
        return raised[vertex]

    for i in seam:
        high = uv[triangles[i], 0].max()
        for corner in range(3):
            vertex = int(triangles[i, corner])
            if uv[vertex, 0] < high - 0.5:
                triangles[i, corner] = past_the_end(vertex)

    if extra_points:
        points = np.vstack([points, np.array(extra_points, points.dtype)])
        normals = np.vstack([normals, np.array(extra_normals, normals.dtype)])
        uv = np.vstack([uv, np.array(extra_uv, uv.dtype)])
    return points, normals, uv, triangles


def look_through(matrix: np.ndarray) -> np.ndarray:
    """The view matrix of a Blender camera: its own transform, undone.

    A Blender camera looks along its local -Z with +Y up, which is the same
    convention the projection below expects, so nothing has to be flipped.
    """
    return np.linalg.inv(matrix.astype(np.float64))


def field_of_view(lens: float, sensor: tuple[float, float], fit: str,
                  frame: tuple[int, int]) -> tuple[float, float]:
    """The camera's angles, with the sensor fitted the way Blender fits it."""
    width, height = frame
    aspect = width / height
    sensor_width, sensor_height = sensor

    if fit == "VERTICAL":
        fov_y = 2.0 * math.atan(0.5 * sensor_height / lens)
        return 2.0 * math.atan(math.tan(fov_y / 2.0) * aspect), fov_y
    if fit == "HORIZONTAL":
        fov_x = 2.0 * math.atan(0.5 * sensor_width / lens)
        return fov_x, 2.0 * math.atan(math.tan(fov_x / 2.0) / aspect)
    # AUTO: the sensor width is given to whichever side of the frame is
    # longer, and the other follows from the aspect.
    if width >= height:
        fov_x = 2.0 * math.atan(0.5 * sensor_width / lens)
        return fov_x, 2.0 * math.atan(math.tan(fov_x / 2.0) / aspect)
    fov_y = 2.0 * math.atan(0.5 * sensor_width / lens)
    return 2.0 * math.atan(math.tan(fov_y / 2.0) * aspect), fov_y


def frustum(fov_x: float, fov_y: float, near: float, far: float,
            centre=(0.0, 0.0), zoom: float = 1.0) -> np.ndarray:
    """A projection from two angles, optionally windowed.

    `centre` and `zoom` cut a window out of what the camera sees without
    moving it: the frustum becomes off-centre instead. That is the difference
    between cropping a photograph and walking closer -- the second changes the
    perspective, and here the perspective is the thing being judged.

    Depth from zero to one, as wgpu wants.
    """
    half_x = near * math.tan(fov_x / 2.0)
    half_y = near * math.tan(fov_y / 2.0)
    left = half_x * (centre[0] - zoom)
    right = half_x * (centre[0] + zoom)
    bottom = half_y * (centre[1] - zoom)
    top = half_y * (centre[1] + zoom)
    return np.array([
        [2 * near / (right - left), 0, (right + left) / (right - left), 0],
        [0, 2 * near / (top - bottom), (top + bottom) / (top - bottom), 0],
        [0, 0, far / (near - far), far * near / (near - far)],
        [0, 0, -1, 0],
    ], dtype=np.float64)


def projection(lens: float, sensor: tuple[float, float], fit: str,
               frame: tuple[int, int], near: float, far: float) -> np.ndarray:
    """The camera's projection, with the sensor fitted the way Blender fits it."""
    width, height = frame
    aspect = width / height
    fov_x, fov_y = field_of_view(lens, sensor, fit, frame)
    return frustum(fov_x, fov_y, near, far)


class Orbit:
    """A camera that goes round the building instead of standing where the
    file put it.

    For looking at the thing rather than judging content on it: no crop, no
    frame to keep, the whole canvas and whatever angle answers the question.
    Everything else about the picture is unchanged -- the same screens, the
    same brightness, the same motors -- so what is being inspected is the same
    thing that was being watched.

    Kept in the file camera's own convention, looking down its local -Z with
    +Y up, so the projection below and the shader never learn which of the two
    cameras is driving.
    """

    UP = np.array([0.0, 0.0, 1.0])
    STEEPEST = math.radians(89.0)     # straight down puts `right` undefined

    def __init__(self, centre, eye, fov_y: float, span: float) -> None:
        """Looking at `centre` from where `eye` stands.

        Placed from the file's own camera rather than at some default angle,
        so switching into this mode keeps the view somebody already had and
        only lets go of the crop.
        """
        centre = np.asarray(centre, dtype=np.float64)
        offset = np.asarray(eye, dtype=np.float64) - centre
        self.centre = centre.copy()
        self.distance = float(np.linalg.norm(offset)) or span or 1.0
        self.yaw = math.atan2(offset[1], offset[0])
        self.pitch = math.atan2(offset[2], float(np.hypot(offset[0], offset[1])))
        self.fov_y = float(fov_y)
        self.aspect = 1.0

        # Room to go right round it and well away from it. Taken from the size
        # of the thing rather than fixed, because a near plane that suits a
        # twenty metre building would slice a model of a room.
        self.near = max(0.02, span / 2000.0)
        self.far = span * 20.0
        self.closest = span / 200.0
        self.furthest = span * 12.0
        self._home = (self.centre.copy(), self.distance, self.yaw, self.pitch)

    def reset(self) -> None:
        centre, self.distance, self.yaw, self.pitch = self._home
        self.centre = centre.copy()

    def turn(self, across: float, down: float) -> None:
        """Swing round and over, in radians."""
        self.yaw -= across
        self.pitch = max(-self.STEEPEST, min(self.STEEPEST, self.pitch + down))

    def dolly(self, factor: float) -> None:
        self.distance = min(self.furthest,
                            max(self.closest, self.distance * factor))

    def pan(self, across: float, down: float) -> None:
        """Slide what is being looked at, in fractions of the picture.

        In fractions rather than in metres so that dragging holds on to the
        thing under the pointer at any distance -- close up the same drag
        moves centimetres, far off it moves the whole building.
        """
        right, up, _ = self.axes()
        tall = 2.0 * self.distance * math.tan(self.fov_y / 2.0)
        self.centre -= right * (across * tall * self.aspect) + up * (down * tall)

    def eye(self) -> np.ndarray:
        flat = math.cos(self.pitch)
        return self.centre + self.distance * np.array(
            [flat * math.cos(self.yaw), flat * math.sin(self.yaw),
             math.sin(self.pitch)])

    def axes(self):
        """Right, up and forward, as the camera holds them."""
        forward = self.centre - self.eye()
        forward = forward / max(np.linalg.norm(forward), 1e-9)
        right = np.cross(forward, self.UP)
        length = float(np.linalg.norm(right))
        right = (right / length if length > 1e-6
                 else np.array([1.0, 0.0, 0.0]))
        return right, np.cross(right, forward), forward

    def view(self) -> np.ndarray:
        right, up, forward = self.axes()
        world = np.eye(4, dtype=np.float64)
        world[:3, 0], world[:3, 1], world[:3, 2] = right, up, -forward
        world[:3, 3] = self.eye()
        return np.linalg.inv(world)

    def projection(self) -> np.ndarray:
        fov_x = 2.0 * math.atan(math.tan(self.fov_y / 2.0) * self.aspect)
        return frustum(fov_x, self.fov_y, self.near, self.far)

    def describe(self) -> str:
        return (f"{self.distance:.1f} m out, "
                f"{math.degrees(self.yaw) % 360:.0f} deg round, "
                f"{math.degrees(self.pitch):+.0f} deg up")


class Piece:
    """One object: its geometry on the card and what it is made of."""

    def __init__(self, device, name: str, points, normals, triangles,
                 uv, colour, screen_index: int, kinetic: bool = False,
                 hollow: bool = False) -> None:
        self.name = name
        self.kinetic = kinetic
        # Open on both sides, so its own back shows through its front unless
        # something drops it. True of the top screen in either of its
        # geometries: it is a ring of separated cells whether it is moving or
        # standing at rest, and the switch has to reach both.
        self.hollow = hollow
        self.count = len(triangles) * 3
        self.screen_index = screen_index
        self.is_screen = screen_index >= 0

        if uv is None:
            uv = np.zeros((len(points), 2), dtype=np.float32)
        vertices = np.hstack([points, normals, uv]).astype(np.float32)

        self.vertices = device.create_buffer_with_data(
            data=np.ascontiguousarray(vertices),
            usage=wgpu.BufferUsage.VERTEX)
        self.indices = device.create_buffer_with_data(
            data=np.ascontiguousarray(triangles.astype(np.uint32)),
            usage=wgpu.BufferUsage.INDEX)

        about = np.zeros((2, 4), dtype=np.float32)
        about[0, :3] = colour
        about[0, 3] = 1.0 if self.is_screen else 0.0
        about[1, 0] = max(0, screen_index)
        about[1, 1] = 1.0 if kinetic else 0.0
        about[1, 2] = 1.0 if hollow else 0.0
        self.settings = device.create_buffer_with_data(
            data=about, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)


class Scene:
    """The whole scene, loaded once."""

    def __init__(self, device, folder: Path) -> None:
        folder = Path(folder)
        data = np.load(folder / "scene_mesh.npz", allow_pickle=True)
        self.raw = data
        self.device = device
        self.names = [str(n) for n in data["order"]]
        self.kinds = [str(k) for k in data["kinds"]]
        # Which video each object shows. Not the same list as the objects
        # themselves: the top screen is two pieces of geometry sharing one
        # video, and everything downstream -- the rows, the sliders, the
        # brightness match -- counts videos, of which there are three.
        if "feeds" in data:
            self.feeds = [str(f) for f in data["feeds"]]
        else:
            self.feeds = [n if k == "screen" else ""
                          for n, k in zip(self.names, self.kinds)]
        self.screens = list(dict.fromkeys(f for f in self.feeds if f))
        self.camera = str(data["camera"])
        self.frame = tuple(int(v) for v in data["frame"])
        self.lens = float(data["lens"])
        self.sensor = tuple(float(v) for v in data["sensor"])
        self.fit = str(data["sensor_fit"])
        near, far = (float(v) for v in data["clip"])
        self.near, self.far = max(near, 0.01), far

        self.cropped = None
        self.centre = [0.0, 0.0]
        self.zoom = 1.0
        # How much wider and taller than the frame the picture is drawn. One
        # and one is the frame alone, which is what is written out; the
        # preview opens this up to the shape of the window so that the scene
        # carries on past the frame instead of the frame sitting in black.
        self.spill = (1.0, 1.0)
        self.view = look_through(np.array(data["camera_matrix"]))
        self.projection = projection(self.lens, self.sensor, self.fit,
                                     self.frame, self.near, self.far)

        # How each screen unrolls: arc in metres, height in metres, the
        # azimuth at u=0 and how far it sweeps. Used by the flat layout to put
        # the strips side by side at one scale and lined up with each other.
        self.unrolled = {}
        if "unrolled" in data:
            for name, row in zip(data["unrolled_order"], data["unrolled"]):
                self.unrolled[str(name)] = tuple(float(v) for v in row)

        colours = np.array(data["colours"], dtype=np.float32)
        self.pieces = []
        low = np.full(3, np.inf)
        high = np.full(3, -np.inf)
        for index, name in enumerate(self.names):
            feed = self.feeds[index]
            screen = self.screens.index(feed) if feed else -1
            points = data[f"{name}__points"]
            normals = data[f"{name}__normals"]
            triangles = data[f"{name}__triangles"]
            uv = data.get(f"{name}__uv") if screen >= 0 else None
            if uv is not None:
                # Straighten the seam faces before the geometry goes to the
                # card, so the back of the ring does not crush the whole video
                # into a strip. Copies out of the read-only archive first.
                points, normals, uv, triangles = mend_seam(
                    np.asarray(points), np.asarray(normals),
                    np.asarray(uv), np.asarray(triangles))
            low = np.minimum(low, points.min(axis=0))
            high = np.maximum(high, points.max(axis=0))
            self.pieces.append(Piece(
                device, name, points, normals, triangles, uv,
                colours[index], screen, name == KINETIC_SCREEN,
                feed == DEFAULT_TOP))

        # How much room the whole thing takes up, which is what a free camera
        # needs to know to be placed anywhere sensible at all.
        self.bounds = (low, high)
        self.free = None             # an Orbit while inspecting, else nothing
        self.triangles = sum(p.count // 3 for p in self.pieces)

    def fly(self, on: bool) -> None:
        """Off the camera in the file and out into the room, or back onto it.

        The camera the file carries is not thrown away and not moved: this is
        a second one, and switching back leaves the first exactly where the
        crop and the zoom had it.
        """
        if not on:
            self.free = None
            return
        if self.free is not None:
            return
        low, high = self.bounds
        span = float(np.linalg.norm(high - low)) or 1.0
        _, fov_y = field_of_view(self.lens, self.sensor, self.fit, self.frame)
        # Where the file's own camera stands: its view matrix, undone.
        eye = np.linalg.inv(self.view)[:3, 3]
        self.free = Orbit((low + high) / 2.0, eye, fov_y, span)

    def look_at_window(self, centre=None, zoom: float = None) -> None:
        """Move or resize the window cut out of the camera's frame."""
        if centre is not None:
            self.centre = [float(centre[0]), float(centre[1])]
        if zoom is not None:
            self.zoom = float(min(1.0, max(0.02, zoom)))
        # Never past the edge of what the camera sees: this is a crop, and a
        # crop that wanders outside its picture is showing nothing.
        room = 1.0 - self.zoom
        self.centre[0] = min(room, max(-room, self.centre[0]))
        self.centre[1] = min(room, max(-room, self.centre[1]))
        self._rebuild()

    def _rebuild(self) -> None:
        fov_x, fov_y = field_of_view(self.lens, self.sensor, self.fit, self.frame)
        if self.cropped is not None:
            width, height = self.cropped
            fov_x = 2.0 * math.atan(math.tan(fov_y / 2.0) * (width / height))
        # Opened out to the window, with the window's own offset divided back
        # down by the same amount. That second half is what keeps the framed
        # rectangle where it was: the offset is measured in half-frustums, so
        # widening the frustum without it would drag the frame sideways.
        across, down = self.spill
        fov_x = 2.0 * math.atan(math.tan(fov_x / 2.0) * across)
        fov_y = 2.0 * math.atan(math.tan(fov_y / 2.0) * down)
        self.projection = frustum(
            fov_x, fov_y, self.near, self.far,
            (self.centre[0] / across, self.centre[1] / down), self.zoom)

    def crop_to(self, width: int, height: int) -> None:
        """Frame a centred window of that shape, without moving the camera.

        The vertical angle is kept and the horizontal narrowed to suit, so the
        whole height the camera sees is still there and only the empty sides
        are given up. Done by narrowing the frustum rather than by cutting
        pixels afterwards: cutting a 4096 square down to 1080 wide would throw
        away most of the resolution exactly where the screens need it.
        """
        self.cropped = (width, height)
        self._rebuild()

    def show_around(self, across: float, down: float) -> bool:
        """Draw this much more than the frame. True when that is a change.

        Answered rather than done quietly, so a caller on the drawing path
        can leave the card alone on the frames where nothing moved -- which
        is all of them but a resize.
        """
        wanted = (max(1.0, float(across)), max(1.0, float(down)))
        if wanted == self.spill:
            return False
        self.spill = wanted
        self._rebuild()
        return True

    def uncrop(self) -> None:
        """Back to the whole frame the file is set up for."""
        self.cropped = None
        self._rebuild()

    def view_projection(self) -> np.ndarray:
        if self.free is not None:
            return (self.free.projection() @ self.free.view()).astype(np.float32)
        return (self.projection @ self.view).astype(np.float32)

    def points_of(self, name: str) -> np.ndarray:
        """One object's vertices as they were baked, in world metres."""
        for piece in self.pieces:
            if piece.name == name:
                return self.raw[f"{name}__points"]
        raise KeyError(name)

    def describe(self) -> str:
        return (f"{len(self.pieces)} objects, {self.triangles:,} triangles, "
                f"camera {self.camera} at {self.lens:.1f} mm, "
                f"frame {self.frame[0]}x{self.frame[1]}")
