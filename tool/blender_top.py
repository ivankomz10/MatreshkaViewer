"""Runs inside Blender: builds the top screen's scene from what the viewer wrote.

    blender -b --factory-startup -P blender_top.py -- <stem>_top.json

Beside the JSON: the cells' vertices for every frame (`.pc2`), the geometry at
rest with its UVs and the rest of the building (`.npz`). See blender_export.py
for why; this is the how. Works in Blender 4.2 and later -- the projection
needs the matrix sockets of the geometry nodes, which came in 4.2.

Two scenes, rendered one after the other. "Top 3D" is where the models go:
the cells on their cache as a wire cage, so the volume they sweep is in view
and out of the render, the building likewise, and the viewer's camera, which
renders the models at 2160 x 3840 on a clear ground. "Top flat" is the
same cells unrolled to the screen's own frame and filmed from above at
2560 x 1150; each cell takes its piece of that frame's Top 3D render from
where the cell stands that frame -- every frame of it is the frame the top
screen plays.

The projection is a geometry-nodes group on the unrolled cells. It writes two
attributes the material reads: `proj`, where in the camera's picture a point
is, and `seen`, whether it faces the camera at all.
"""
import json
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


def projection_group():
    g, gi, go = group_frame("Matreshka · projection")
    socket(g, "Geometry", "NodeSocketGeometry")
    socket(g, "Geometry", "NodeSocketGeometry", "OUTPUT")
    socket(g, "Camera", "NodeSocketObject")
    socket(g, "Tan half", "NodeSocketFloat", default=0.38)
    socket(g, "Aspect", "NodeSocketFloat", default=0.5625)
    uv, seen = camera_projection(g, gi, "Camera", "Tan half", "Aspect", 0)
    keep_uv = node(g, "GeometryNodeStoreNamedAttribute", (950, 100), data_type="FLOAT2", domain="CORNER")
    keep_uv.inputs["Name"].default_value = "proj"
    link(g, gi.outputs["Geometry"], keep_uv.inputs["Geometry"])
    link(g, uv, keep_uv.inputs["Value"])
    keep_seen = node(g, "GeometryNodeStoreNamedAttribute", (1150, 100), data_type="FLOAT", domain="POINT")
    keep_seen.inputs["Name"].default_value = "seen"
    link(g, keep_uv.outputs["Geometry"], keep_seen.inputs["Geometry"])
    link(g, seen, keep_seen.inputs["Value"])
    link(g, keep_seen.outputs["Geometry"], go.inputs[0])
    return g


def flat_group():
    g, gi, go = group_frame("Matreshka · flat")
    socket(g, "Geometry", "NodeSocketGeometry")
    socket(g, "Geometry", "NodeSocketGeometry", "OUTPUT")
    socket(g, "Width", "NodeSocketFloat", default=float(W))
    socket(g, "Height", "NodeSocketFloat", default=float(H))
    uv = node(g, "GeometryNodeInputNamedAttribute", (-1000, 0), data_type="FLOAT_VECTOR")
    uv.inputs["Name"].default_value = "uv"
    xyz = node(g, "ShaderNodeSeparateXYZ", (-800, 0))
    link(g, uv.outputs["Attribute"], xyz.inputs[0])
    at = node(g, "ShaderNodeCombineXYZ", (-400, 0))
    link(g, math_node(g, "MULTIPLY", xyz.outputs[0], gi.outputs["Width"], (-600, 100)), at.inputs[0])
    link(g, math_node(g, "MULTIPLY", xyz.outputs[1], gi.outputs["Height"], (-600, -100)), at.inputs[1])
    put = node(g, "GeometryNodeSetPosition", (0, 0))
    link(g, gi.outputs["Geometry"], put.inputs["Geometry"])
    link(g, at.outputs[0], put.inputs["Position"])
    link(g, put.outputs["Geometry"], go.inputs[0])
    return g


# -- the picture -----------------------------------------------------------------------

def picture():
    """What the unrolled screen reads: Top 3D's own render, frame by frame,
    unless a picture rendered elsewhere from the same camera was given."""
    source = R.get("source") or ""
    if not source:
        wide, tall = D["camera"]["resolution"]
        image = bpy.data.images.new("Top 3D render", wide, tall, alpha=True)
        image.source = "SEQUENCE"
        image.filepath = D["content"] + "0001.png"
        image["matreshka_offset"] = 0
        return image, wide / tall
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
    mat = bpy.data.materials.new("Top · projection")
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
    world = bpy.data.worlds.new(f"{scene.name} · world")
    world.use_nodes = False
    world.color = (0, 0, 0)
    scene.world = world


def cells_object(name):
    """The cells, on the cache of their motion."""
    ob = mesh_object(name, geo["points"], geo["triangles"], geo["uv"])
    cells = ob.data.attributes.new("cell", "INT", "POINT")
    cells.data.foreach_set("value", geo["cell"].astype(np.int32))
    cache = ob.modifiers.new("Kinetic", "MESH_CACHE")
    cache.cache_format = "PC2"
    cache.filepath = "//" + D["cache"]
    cache.time_mode = "FRAME"
    cache.play_mode = "SCENE"
    # Frame 1 of the scene is the first frame in the cache.
    cache.frame_start = 1.0
    return ob


def unrolled_cells(mat, proj, flat, camera, aspect):
    """The cells, projected on from the camera, then laid out flat."""
    ob = cells_object("Top_flat")
    mod = ob.modifiers.new("Projection", "NODES")
    mod.node_group = proj
    set_input(mod, ident_of(proj, "Camera"), camera)
    set_input(mod, ident_of(proj, "Aspect"), float(aspect))
    set_input(mod, ident_of(proj, "Tan half"), float(D["camera"]["tan_half"]))
    drive_tan(ob, mod, ident_of(proj, "Tan half"), camera)
    unroll = ob.modifiers.new("Flat", "NODES")
    unroll.node_group = flat
    ob.data.materials.append(mat)
    return ob


def main():
    image, aspect = picture()
    look = bpy.context.scene
    look.name = "Top 3D"
    setup_scene(look, D["camera"]["resolution"])
    out = bpy.data.scenes.new("Top flat")
    setup_scene(out, (W, H))

    # Top 3D renders the models as they look: lit, on a clear ground, through
    # the ordinary view of the colour configuration; Cycles, as the test scene.
    put(look.render, "engine", ["CYCLES"])
    if hasattr(look, "cycles"):
        look.cycles.samples = 128
        look.cycles.use_denoising = True
    put(look.view_settings, "view_transform", ["Standard", "Un-tone-mapped"])
    put(look.view_settings, "look", ["None"])
    look.render.film_transparent = True
    look.render.image_settings.file_format = "PNG"
    look.render.image_settings.color_mode = "RGBA"
    look.render.image_settings.color_depth = "8"
    look.render.filepath = D["content"]
    look.world.color = (0.05, 0.05, 0.05)

    # The unrolled screen passes the render's numbers through untouched.
    passthrough(image, out)
    out.render.image_settings.file_format = "PNG"
    out.render.image_settings.color_mode = "RGB"
    out.render.image_settings.color_depth = "8"
    out.render.filepath = D["render"]
    out.render.film_transparent = False
    if hasattr(out, "eevee") and hasattr(out.eevee, "taa_render_samples"):
        out.eevee.taa_render_samples = 16
    out.render.filter_size = 1.0

    rigs = bpy.data.collections.new("Viewer camera")
    look.collection.children.link(rigs)
    out.collection.children.link(rigs)        # so the unrolled screen projects from it
    camera = camera_object(D["camera"]["name"], D["camera"])
    rigs.objects.link(camera)
    look.camera = camera

    models = bpy.data.collections.new("Models")
    look.collection.children.link(models)

    cage = bpy.data.collections.new("Top kinetic")
    look.collection.children.link(cage)
    cells = cells_object("Top_kinetic")
    cells.display_type = "WIRE"
    cells.hide_render = True
    cage.objects.link(cells)

    building = bpy.data.collections.new("Building")
    look.collection.children.link(building)
    grey = bpy.data.materials.new("Building · grey")
    grey.diffuse_color = (0.2, 0.2, 0.2, 1)
    for name in [str(one) for one in geo["names"]]:
        piece = mesh_object(name, geo[f"{name}__points"], geo[f"{name}__triangles"])
        piece.data.materials.append(grey)
        piece.hide_render = True
        building.objects.link(piece)

    unrolled = bpy.data.collections.new("Flat")
    out.collection.children.link(unrolled)
    unrolled.objects.link(unrolled_cells(screen_material(image), projection_group(), flat_group(), camera, aspect))
    above = bpy.data.cameras.new("Flat camera")
    above.type = "ORTHO"
    above.ortho_scale = float(W)
    above.clip_start, above.clip_end = 1.0, 5000.0
    above_ob = bpy.data.objects.new("Flat camera", above)
    above_ob.location = (W / 2.0, H / 2.0, 1000.0)
    unrolled.objects.link(above_ob)
    out.camera = above_ob

    look["matreshka_export"] = json.dumps({k: R[k] for k in ("first", "length", "source")}, ensure_ascii=False)
    out["matreshka_export"] = look["matreshka_export"]

    # Did the cache take? There must be as many vertices as the cache says,
    # or Blender quietly shows the rest pose.
    look.frame_set(1)
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = bpy.data.objects["Top_kinetic"].evaluated_get(deps).to_mesh()
    print(f"matreshka: {len(evaluated.vertices)} vertices, {N} frames, "
          f"engines {look.render.engine}/{out.render.engine}, view {out.view_settings.view_transform}, "
          f"image {image.name}")
    bpy.data.objects["Top_kinetic"].evaluated_get(deps).to_mesh_clear()

    bpy.ops.wm.save_as_mainfile(filepath=str(HERE / D["target"]), relative_remap=True)
    print("matreshka: saved", HERE / D["target"])


main()
