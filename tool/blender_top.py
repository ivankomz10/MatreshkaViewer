"""Runs inside Blender: builds the top screen's scene from what the viewer wrote.

    blender -b --factory-startup -P blender_top.py -- <stem>_top.json

Beside the JSON: the cells' vertices for every frame (`.pc2`), the geometry at
rest with its UVs and the rest of the building (`.npz`). See blender_export.py
for why; this is the how. Works in Blender 4.2 and later -- the projection
needs the matrix sockets of the geometry nodes, which came in 4.2.

Two scenes. "Top 3D" is for looking: the cells on their cache, the building,
the viewer's camera as the scene camera at 2160 x 3840, the camera the viewer
was looking through, an empty for the decal. "Top развертка" is for
rendering: the same cells, the same projection, unrolled to the screen's own
frame and filmed from above at 2560 x 1150 -- every frame of it is the frame
the top screen plays.

The projection is one geometry-nodes group on both, its Mode a number on the
modifier: 0 from the viewer's camera, 1 decal, 2 from the camera of the view.
It writes two attributes the material reads: `proj`, where in the picture a
point is, and `seen`, whether it faces that way at all.
"""
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix

ASK = Path(sys.argv[sys.argv.index("--") + 1])
D = json.loads(ASK.read_text(encoding="utf-8"))
HERE = ASK.parent
R = D["request"]
N = int(R["length"])
W, H = D["frame"]
MOVIES = {".mov", ".mp4", ".avi", ".mkv", ".webm", ".m4v", ".mxf"}

bpy.ops.wm.read_factory_settings(use_empty=True)
geo = np.load(HERE / D["geometry"])


# -- small helpers ------------------------------------------------------------------

def mesh_object(name, points, triangles, uv=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata(points.astype(np.float64).tolist(), [], triangles.astype(np.int64).tolist())
    if uv is not None:
        layer = me.uv_layers.new(name="uv")
        layer.data.foreach_set("uv", uv[triangles.ravel()].astype(np.float32).ravel())
    me.update()
    return bpy.data.objects.new(name, me)


def first_of(owner, prop, wanted):
    items = [one.identifier for one in owner.bl_rna.properties[prop].enum_items]
    for one in wanted:
        if one in items:
            return one
    return None


def put(owner, prop, wanted):
    """The first of `wanted` the property takes. The colour names come from
    the colour configuration in use, so they are asked by trying."""
    for one in wanted:
        try:
            setattr(owner, prop, one)
            return one
        except (TypeError, ValueError):
            continue
    return None


def node(tree, kind, at=(0, 0), **settings):
    made = tree.nodes.new(kind)
    made.location = at
    for key, value in settings.items():
        setattr(made, key, value)
    return made


def link(tree, a, b):
    tree.links.new(a, b)


def math_node(tree, op, a, b=None, at=(0, 0)):
    made = node(tree, "ShaderNodeMath", at, operation=op)
    for slot, value in ((0, a), (1, b)):
        if value is None:
            continue
        if isinstance(value, (int, float)):
            made.inputs[slot].default_value = value
        else:
            link(tree, value, made.inputs[slot])
    return made.outputs[0]


def socket(group, name, kind, io="INPUT", default=None, low=None, high=None):
    made = group.interface.new_socket(name=name, in_out=io, socket_type=kind)
    if default is not None:
        made.default_value = default
    if low is not None:
        made.min_value = low
    if high is not None:
        made.max_value = high
    return made


def group_frame(name):
    g = bpy.data.node_groups.new(name, "GeometryNodeTree")
    if hasattr(g, "is_modifier"):
        g.is_modifier = True
    gi = node(g, "NodeGroupInput", (-1400, 0))
    go = node(g, "NodeGroupOutput", (1400, 0))
    return g, gi, go


# -- the projection ------------------------------------------------------------------

def camera_projection(g, gi, cam, tan, aspect, y):
    """Where a point lands in a picture projected from a camera, and whether it
    faces the camera: the same sum as blender_export.project."""
    pos = node(g, "GeometryNodeInputPosition", (-1200, y)).outputs[0]
    info = node(g, "GeometryNodeObjectInfo", (-1200, y - 150), transform_space="ORIGINAL")
    link(g, gi.outputs[cam], info.inputs["Object"])
    inv = node(g, "FunctionNodeInvertMatrix", (-1000, y - 150))
    link(g, info.outputs["Transform"], inv.inputs[0])
    local = node(g, "FunctionNodeTransformPoint", (-800, y))
    link(g, pos, local.inputs[0])
    link(g, inv.outputs[0], local.inputs[1])
    xyz = node(g, "ShaderNodeSeparateXYZ", (-600, y))
    link(g, local.outputs[0], xyz.inputs[0])
    depth = math_node(g, "MULTIPLY", xyz.outputs[2], -1.0, (-400, y - 100))
    span = math_node(g, "MULTIPLY", gi.outputs[tan], 2.0, (-400, y - 250))
    v = math_node(g, "ADD", math_node(g, "DIVIDE", math_node(g, "DIVIDE", xyz.outputs[1], depth, (-200, y)), span, (0, y)), 0.5, (200, y))
    u = math_node(g, "ADD", math_node(g, "DIVIDE", math_node(g, "DIVIDE", math_node(g, "DIVIDE", xyz.outputs[0], depth, (-200, y + 150)), span, (0, y + 150)), gi.outputs[aspect], (100, y + 150)), 0.5, (200, y + 150))
    uv = node(g, "ShaderNodeCombineXYZ", (400, y))
    link(g, u, uv.inputs[0])
    link(g, v, uv.inputs[1])
    normal = node(g, "GeometryNodeInputNormal", (-800, y - 300)).outputs[0]
    toward = node(g, "ShaderNodeVectorMath", (-600, y - 300), operation="SUBTRACT")
    link(g, info.outputs["Location"], toward.inputs[0])
    link(g, pos, toward.inputs[1])
    dot = node(g, "ShaderNodeVectorMath", (-400, y - 300), operation="DOT_PRODUCT")
    link(g, normal, dot.inputs[0])
    link(g, toward.outputs[0], dot.inputs[1])
    facing = math_node(g, "GREATER_THAN", dot.outputs["Value"], 0.0, (-200, y - 300))
    ahead = math_node(g, "GREATER_THAN", depth, 0.0, (-200, y - 400))
    return uv.outputs[0], math_node(g, "MULTIPLY", facing, ahead, (0, y - 350))


def decal_projection(g, gi, aspect, y):
    """Laid round the building in metres of the surface, centred on the empty."""
    pos = node(g, "GeometryNodeInputPosition", (-1200, y)).outputs[0]
    p = node(g, "ShaderNodeSeparateXYZ", (-1000, y))
    link(g, pos, p.inputs[0])
    info = node(g, "GeometryNodeObjectInfo", (-1200, y - 200), transform_space="ORIGINAL")
    link(g, gi.outputs["Декаль"], info.inputs["Object"])
    e = node(g, "ShaderNodeSeparateXYZ", (-1000, y - 200))
    link(g, info.outputs["Location"], e.inputs[0])
    s = node(g, "ShaderNodeSeparateXYZ", (-1000, y - 350))
    link(g, info.outputs["Scale"], s.inputs[0])
    # How far round from the decal, taken at the middle of each triangle and
    # only then out to its corners: a cell standing on the far side, across
    # the line where the angle jumps from +180 to -180, would otherwise have
    # its corners a whole turn apart and smear the picture across itself.
    middle = node(g, "GeometryNodeFieldOnDomain", (-1000, y + 500), domain="FACE", data_type="FLOAT_VECTOR")
    link(g, pos, middle.inputs[0])
    m = node(g, "ShaderNodeSeparateXYZ", (-800, y + 500))
    link(g, middle.outputs[0], m.inputs[0])
    at_middle = math_node(g, "ARCTAN2", m.outputs[1], m.outputs[0], (-600, y + 500))

    def wrap(value, at):
        made = node(g, "ShaderNodeMath", at, operation="WRAP")
        link(g, value, made.inputs[0])
        made.inputs[1].default_value = math.pi
        made.inputs[2].default_value = -math.pi
        return made.outputs[0]

    to_middle = wrap(math_node(g, "SUBTRACT", at_middle, math_node(g, "ARCTAN2", e.outputs[1], e.outputs[0], (-800, y - 200)), (-500, y + 400)), (-400, y + 400))
    beside = wrap(math_node(g, "SUBTRACT", math_node(g, "ARCTAN2", p.outputs[1], p.outputs[0], (-800, y)), at_middle, (-500, y)), (-400, y - 50))
    turn_total = math_node(g, "ADD", to_middle, beside, (-300, y))
    flat = node(g, "ShaderNodeCombineXYZ", (-800, y + 200))
    link(g, p.outputs[0], flat.inputs[0])
    link(g, p.outputs[1], flat.inputs[1])
    reach = node(g, "ShaderNodeVectorMath", (-600, y + 200), operation="LENGTH")
    link(g, flat.outputs[0], reach.inputs[0])
    arc = math_node(g, "MULTIPLY", turn_total, reach.outputs["Value"], (-200, y))
    tall = math_node(g, "MULTIPLY", gi.outputs["Высота декали"], s.outputs[0], (-600, y - 350))
    wide = math_node(g, "MULTIPLY", tall, gi.outputs[aspect], (-400, y - 350))
    u = math_node(g, "ADD", math_node(g, "DIVIDE", arc, wide, (0, y)), 0.5, (200, y))
    v = math_node(g, "ADD", math_node(g, "DIVIDE", math_node(g, "SUBTRACT", p.outputs[2], e.outputs[2], (-200, y - 150)), tall, (0, y - 150)), 0.5, (200, y - 150))
    uv = node(g, "ShaderNodeCombineXYZ", (400, y))
    link(g, u, uv.inputs[0])
    link(g, v, uv.inputs[1])
    out = node(g, "ShaderNodeVectorMath", (-600, y + 350), operation="NORMALIZE")
    link(g, flat.outputs[0], out.inputs[0])
    dot = node(g, "ShaderNodeVectorMath", (-400, y + 350), operation="DOT_PRODUCT")
    link(g, node(g, "GeometryNodeInputNormal", (-600, y + 500)).outputs[0], dot.inputs[0])
    link(g, out.outputs[0], dot.inputs[1])
    return uv.outputs[0], math_node(g, "GREATER_THAN", dot.outputs["Value"], 0.0, (-200, y + 350))


def projection_group():
    g, gi, go = group_frame("Matreshka · проекция")
    socket(g, "Geometry", "NodeSocketGeometry")
    socket(g, "Geometry", "NodeSocketGeometry", "OUTPUT")
    socket(g, "Режим", "NodeSocketInt", default=0, low=0, high=2).description = \
        "0 по зрителю (камера файла), 1 декаль на сотах, 2 с камеры вида"
    socket(g, "Камера зрителя", "NodeSocketObject")
    socket(g, "Тангенс зрителя", "NodeSocketFloat", default=0.38)
    socket(g, "Камера вида", "NodeSocketObject")
    socket(g, "Тангенс вида", "NodeSocketFloat", default=0.38)
    socket(g, "Декаль", "NodeSocketObject")
    socket(g, "Высота декали", "NodeSocketFloat", default=800.0)
    socket(g, "Пропорции картинки", "NodeSocketFloat", default=0.5625)
    viewer_uv, viewer_seen = camera_projection(g, gi, "Камера зрителя", "Тангенс зрителя", "Пропорции картинки", 1200)
    decal_uv, decal_seen = decal_projection(g, gi, "Пропорции картинки", 0)
    view_uv, view_seen = camera_projection(g, gi, "Камера вида", "Тангенс вида", "Пропорции картинки", -1200)
    pick_uv = node(g, "GeometryNodeIndexSwitch", (700, 200), data_type="VECTOR")
    pick_seen = node(g, "GeometryNodeIndexSwitch", (700, -200), data_type="FLOAT")
    for one in (pick_uv, pick_seen):
        while len(one.index_switch_items) < 3:
            one.index_switch_items.new()
        link(g, gi.outputs["Режим"], one.inputs[0])
    for slot, (uv, seen) in enumerate(((viewer_uv, viewer_seen), (decal_uv, decal_seen), (view_uv, view_seen))):
        link(g, uv, pick_uv.inputs[slot + 1])
        link(g, seen, pick_seen.inputs[slot + 1])
    keep_uv = node(g, "GeometryNodeStoreNamedAttribute", (950, 100), data_type="FLOAT2", domain="CORNER")
    keep_uv.inputs["Name"].default_value = "proj"
    link(g, gi.outputs["Geometry"], keep_uv.inputs["Geometry"])
    link(g, pick_uv.outputs[0], keep_uv.inputs["Value"])
    keep_seen = node(g, "GeometryNodeStoreNamedAttribute", (1150, 100), data_type="FLOAT", domain="POINT")
    keep_seen.inputs["Name"].default_value = "seen"
    link(g, keep_uv.outputs["Geometry"], keep_seen.inputs["Geometry"])
    link(g, pick_seen.outputs[0], keep_seen.inputs["Value"])
    link(g, keep_seen.outputs["Geometry"], go.inputs[0])
    return g


def flat_group():
    g, gi, go = group_frame("Matreshka · развертка")
    socket(g, "Geometry", "NodeSocketGeometry")
    socket(g, "Geometry", "NodeSocketGeometry", "OUTPUT")
    socket(g, "Ширина", "NodeSocketFloat", default=float(W))
    socket(g, "Высота", "NodeSocketFloat", default=float(H))
    uv = node(g, "GeometryNodeInputNamedAttribute", (-1000, 0), data_type="FLOAT_VECTOR")
    uv.inputs["Name"].default_value = "uv"
    xyz = node(g, "ShaderNodeSeparateXYZ", (-800, 0))
    link(g, uv.outputs["Attribute"], xyz.inputs[0])
    at = node(g, "ShaderNodeCombineXYZ", (-400, 0))
    link(g, math_node(g, "MULTIPLY", xyz.outputs[0], gi.outputs["Ширина"], (-600, 100)), at.inputs[0])
    link(g, math_node(g, "MULTIPLY", xyz.outputs[1], gi.outputs["Высота"], (-600, -100)), at.inputs[1])
    put = node(g, "GeometryNodeSetPosition", (0, 0))
    link(g, gi.outputs["Geometry"], put.inputs["Geometry"])
    link(g, at.outputs[0], put.inputs["Position"])
    link(g, put.outputs["Geometry"], go.inputs[0])
    return g


# -- the picture -----------------------------------------------------------------------

def picture():
    source = R.get("source") or ""
    if not source:
        image = bpy.data.images.new("Проверка 9x16", 1080, 1920)
        image.generated_type = "COLOR_GRID"
        return image, 1080 / 1920
    path = Path(source)
    image = bpy.data.images.load(str(path), check_existing=True)
    image.name = path.name
    offset = int(R.get("source_offset") or 0)
    if path.suffix.lower() in MOVIES:
        image.source = "MOVIE"
    else:
        tail = len(path.stem) - len(path.stem.rstrip("0123456789"))
        if tail and len(list(path.parent.glob(path.stem[:-tail] + "?" * tail + path.suffix))) > 1:
            image.source = "SEQUENCE"
            offset += int(path.stem[-tail:]) - 1
    image["matreshka_offset"] = offset
    wide, tall = image.size[:]
    aspect = float(D.get("aspect") or (wide / tall if wide and tall else 0.5625))
    return image, aspect


def passthrough(image, scene):
    """The picture's own numbers out, untouched: read raw, shown raw. Where the
    colour configuration has no raw view, read as sRGB and shown as sRGB,
    which comes back to the same numbers."""
    if put(scene.view_settings, "view_transform", ["Raw"]):
        put(image.colorspace_settings, "name", ["Non-Color", "Raw", "Utility - Raw"])
    else:
        put(scene.view_settings, "view_transform", ["Standard", "Un-tone-mapped"])
        put(image.colorspace_settings, "name", ["sRGB", "sRGB Encoded Rec.709 (sRGB)", "sRGB - Texture"])
    put(scene.view_settings, "look", ["None"])
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0


def screen_material(image):
    mat = bpy.data.materials.new("Top · проекция")
    mat.use_nodes = True
    t = mat.node_tree
    t.nodes.clear()
    where = node(t, "ShaderNodeAttribute", (-900, 0), attribute_type="GEOMETRY", attribute_name="proj")
    seen = node(t, "ShaderNodeAttribute", (-900, -250), attribute_type="GEOMETRY", attribute_name="seen")
    tex = node(t, "ShaderNodeTexImage", (-600, 0), image=image, extension="CLIP", interpolation="Linear")
    tex.image_user.frame_start = 1
    tex.image_user.frame_offset = int(image.get("matreshka_offset", 0))
    tex.image_user.frame_duration = N
    tex.image_user.use_auto_refresh = True
    link(t, where.outputs["Vector"], tex.inputs["Vector"])
    much = math_node(t, "MULTIPLY", tex.outputs["Alpha"], seen.outputs["Fac"], (-300, -200))
    lit = node(t, "ShaderNodeVectorMath", (-100, 0), operation="SCALE")
    link(t, tex.outputs["Color"], lit.inputs[0])
    link(t, much, lit.inputs["Scale"])
    glow = node(t, "ShaderNodeEmission", (150, 0))
    glow.inputs["Strength"].default_value = 1.0
    link(t, lit.outputs[0], glow.inputs["Color"])
    out = node(t, "ShaderNodeOutputMaterial", (400, 0))
    link(t, glow.outputs[0], out.inputs["Surface"])
    return mat


def camera_object(name, c):
    data = bpy.data.cameras.new(name)
    data.lens = c["lens"]
    data.sensor_fit = "VERTICAL"
    data.sensor_height = c["sensor"]
    data.sensor_width = c["sensor"]
    data.clip_start, data.clip_end = 10.0, 100000.0
    ob = bpy.data.objects.new(name, data)
    right, up, back = c["axes"]
    loc = c["location"]
    ob.matrix_world = Matrix(((right[0], up[0], back[0], loc[0]), (right[1], up[1], back[1], loc[1]),
                              (right[2], up[2], back[2], loc[2]), (0, 0, 0, 1)))
    return ob


def drive_tan(ob, mod, ident, cam):
    """The projection's angle follows the camera's lens, so a lens changed in
    Blender stays right. A simple expression: no scripts need trusting."""
    curve = ob.driver_add(input_path(mod, ident))
    drv = curve.driver
    drv.type = "SCRIPTED"
    for name, path in (("sh", "sensor_height"), ("lens", "lens")):
        var = drv.variables.new()
        var.name = name
        var.type = "SINGLE_PROP"
        var.targets[0].id_type = "CAMERA"
        var.targets[0].id = cam.data
        var.targets[0].data_path = path
    drv.expression = "sh / (2 * lens)"


def ident_of(group, name):
    return next(one.identifier for one in group.interface.items_tree
                if getattr(one, "in_out", "") == "INPUT" and one.name == name)


# Where a geometry-nodes modifier keeps the values of its inputs moved in 5.0:
# from ID properties on the modifier to `properties.inputs.<socket>.value`.
NEW_INPUTS = bpy.app.version >= (5, 0, 0)


def set_input(mod, ident, value):
    if NEW_INPUTS:
        getattr(mod.properties.inputs, ident).value = value
    else:
        mod[ident] = value


def input_path(mod, ident):
    if NEW_INPUTS:
        return f'modifiers["{mod.name}"].properties.inputs.{ident}.value'
    return f'modifiers["{mod.name}"]["{ident}"]'


# -- the scenes ---------------------------------------------------------------------------

def setup_scene(scene, size):
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.01
    scene.unit_settings.length_unit = "CENTIMETERS"
    scene.render.fps = D["fps"]
    scene.render.fps_base = 1.0
    scene.frame_start, scene.frame_end = 1, N
    scene.render.resolution_x, scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    engine = first_of(scene.render, "engine", ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"])
    if engine:
        scene.render.engine = engine
    world = bpy.data.worlds.new(f"{scene.name} · фон")
    world.use_nodes = False
    world.color = (0, 0, 0)
    scene.world = world


def cells_object(name, image_mat, proj, viewer_cam, view_cam, decal, aspect, flat=None):
    ob = mesh_object(name, geo["points"], geo["triangles"], geo["uv"])
    cells = ob.data.attributes.new("cell", "INT", "POINT")
    cells.data.foreach_set("value", geo["cell"].astype(np.int32))
    cache = ob.modifiers.new("Кинетика", "MESH_CACHE")
    cache.cache_format = "PC2"
    cache.filepath = "//" + D["cache"]
    cache.time_mode = "FRAME"
    cache.play_mode = "SCENE"
    # Frame 1 of the scene is the first frame in the cache.
    cache.frame_start = 1.0
    mod = ob.modifiers.new("Проекция", "NODES")
    mod.node_group = proj
    set_input(mod, ident_of(proj, "Режим"), int(D["mode"]))
    set_input(mod, ident_of(proj, "Камера зрителя"), viewer_cam)
    set_input(mod, ident_of(proj, "Камера вида"), view_cam)
    set_input(mod, ident_of(proj, "Декаль"), decal)
    set_input(mod, ident_of(proj, "Высота декали"), float(D["decal"]["height"]))
    set_input(mod, ident_of(proj, "Пропорции картинки"), float(aspect))
    set_input(mod, ident_of(proj, "Тангенс зрителя"), float(D["cameras"]["viewer"]["tan_half"]))
    set_input(mod, ident_of(proj, "Тангенс вида"), float(D["cameras"]["view"]["tan_half"]))
    drive_tan(ob, mod, ident_of(proj, "Тангенс зрителя"), viewer_cam)
    drive_tan(ob, mod, ident_of(proj, "Тангенс вида"), view_cam)
    if flat is not None:
        unroll = ob.modifiers.new("Развертка", "NODES")
        unroll.node_group = flat
    ob.data.materials.append(image_mat)
    return ob


def main():
    image, aspect = picture()
    look = bpy.context.scene
    look.name = "Top 3D"
    setup_scene(look, D["cameras"]["viewer"]["resolution"])
    out = bpy.data.scenes.new("Top развертка")
    setup_scene(out, (W, H))
    for scene in (look, out):
        passthrough(image, scene)
    out.render.image_settings.file_format = "PNG"
    out.render.image_settings.color_mode = "RGB"
    out.render.image_settings.color_depth = "8"
    out.render.filepath = D["render"]
    out.render.film_transparent = False
    if hasattr(out, "eevee") and hasattr(out.eevee, "taa_render_samples"):
        out.eevee.taa_render_samples = 16
    out.render.filter_size = 1.0

    rigs = bpy.data.collections.new("Камеры и декаль")
    look.collection.children.link(rigs)
    out.collection.children.link(rigs)        # so the unrolled screen sees them move
    viewer_cam = camera_object(D["cameras"]["viewer"]["name"], D["cameras"]["viewer"])
    view_cam = camera_object(D["cameras"]["view"]["name"], D["cameras"]["view"])
    decal = bpy.data.objects.new("Декаль", None)
    decal.empty_display_type = "PLAIN_AXES"
    decal.empty_display_size = 100.0
    decal.location = D["decal"]["location"]
    for one in (viewer_cam, view_cam, decal):
        rigs.objects.link(one)
    look.camera = viewer_cam

    proj, flat = projection_group(), flat_group()
    mat = screen_material(image)
    kinetic = bpy.data.collections.new("Top кинетика")
    look.collection.children.link(kinetic)
    kinetic.objects.link(cells_object("Top_kinetic", mat, proj, viewer_cam, view_cam, decal, aspect))

    building = bpy.data.collections.new("Здание")
    look.collection.children.link(building)
    grey = bpy.data.materials.new("Здание · серый")
    grey.diffuse_color = (0.2, 0.2, 0.2, 1)
    for name in [str(one) for one in geo["names"]]:
        piece = mesh_object(name, geo[f"{name}__points"], geo[f"{name}__triangles"])
        piece.data.materials.append(grey)
        piece.hide_render = True
        building.objects.link(piece)

    unrolled = bpy.data.collections.new("Развертка")
    out.collection.children.link(unrolled)
    unrolled.objects.link(cells_object("Top_flat", mat, proj, viewer_cam, view_cam, decal, aspect, flat))
    above = bpy.data.cameras.new("Камера развертки")
    above.type = "ORTHO"
    above.ortho_scale = float(W)
    above.clip_start, above.clip_end = 1.0, 5000.0
    above_ob = bpy.data.objects.new("Камера развертки", above)
    above_ob.location = (W / 2.0, H / 2.0, 1000.0)
    unrolled.objects.link(above_ob)
    out.camera = above_ob

    look["matreshka_export"] = json.dumps({k: R[k] for k in ("first", "length", "mode", "source")}, ensure_ascii=False)
    out["matreshka_export"] = look["matreshka_export"]

    # Did the cache take? The first frame's vertices against the rest pose is
    # not the question -- the motors may be at rest -- but there must be as
    # many of them as the cache says, or Blender quietly shows the rest pose.
    look.frame_set(1)
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = bpy.data.objects["Top_kinetic"].evaluated_get(deps).to_mesh()
    print(f"matreshka: {len(evaluated.vertices)} vertices, {N} frames, mode {D['mode']}, "
          f"engine {out.render.engine}, view {out.view_settings.view_transform}, image {image.name}")
    bpy.data.objects["Top_kinetic"].evaluated_get(deps).to_mesh_clear()

    bpy.ops.wm.save_as_mainfile(filepath=str(HERE / D["target"]), relative_remap=True)
    print("matreshka: saved", HERE / D["target"])


main()
