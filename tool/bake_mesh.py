"""Runs inside Blender, once: exports the scene as geometry the viewer draws.

    blender -b Prepare.blend --factory-startup -P bake_mesh.py -- <output_dir>

The scene is kept as geometry rather than flattened into layers of pixels: it
costs a little more to draw and gives back everything flattening took away --
any window size, real anti-aliasing, and mip levels on the video, which is the
whole point, because the screens are what this is for.

Nothing about how the scene is lit is exported. The surrounding objects are
here to show where the screens are and what hides what; they are matte grey and
black in the file, and a plain shading in the viewer says the same thing at no
cost. Anything spent on making them beautiful would be spent on the part
nobody is looking at.

Everything comes out in metres. The file is authored in centimetres so that it
lines up with the FBX from the rig, and `scale_length` is the number that says
so; the viewer works in metres throughout, because the motors are specified in
millimetres and something that had to remember which unit it was in would get
it wrong eventually.
"""
import os
import sys

import bpy
import numpy as np

# The surfaces that show video, and the UV layer each of them shows it on.
#
# Two of these are the same screen. `Screen_Top` is the honeycomb as modelled,
# standing still; `screen` is the same 1500 cells rigged to the motors, and is
# what moves when a kinetic JSON is loaded. They carry the same UV cell for
# cell, so the same content lands in the same place on either.
SCREENS = {
    "Screen_Bottom": "uv",
    "Screen_Top": "uv",
    "screen": "uv",
    "Lamel_screen": "uv",
}

# Which video a surface shows. Only three videos, whatever the geometry count.
FEEDS = {
    "Screen_Bottom": "Screen_Bottom",
    "Screen_Top": "Screen_Top",
    "screen": "Screen_Top",
    "Lamel_screen": "Lamel_screen",
}

# Everything else: there to show where the screens are and what hides what.
# A missing one is skipped rather than fatal -- the file is edited between
# bakes, and a prop that has gone away should not stop the whole export.
ELEMENTS = ["Body_hide", "Lamel_Body_hide", "Cylinder"]
DEFAULT_GREY = (0.35, 0.35, 0.36)


def say(tag, message=""):
    print(f">>>{tag} {message}".rstrip(), flush=True)


def fail(message):
    say("ERROR", message)
    sys.exit(2)


def base_colour(obj):
    """The flat colour of a surface, straight off its material."""
    for material in obj.data.materials:
        if material is None or not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.bl_idname == "ShaderNodeBsdfPrincipled":
                socket = node.inputs.get("Base Color")
                if socket is not None and not socket.is_linked:
                    return tuple(socket.default_value)[:3]
    return DEFAULT_GREY


def main():
    out_dir = os.path.abspath(sys.argv[sys.argv.index("--") + 1:][0])
    os.makedirs(out_dir, exist_ok=True)

    scene = bpy.context.scene
    camera = scene.camera
    if camera is None:
        fail("the scene has no camera")

    # Blender units to metres. The file is authored in centimetres to match
    # the FBX from the rig.
    scale = float(scene.unit_settings.scale_length) or 1.0

    # `screen` is deformed by the rig, so the frame it is read at becomes the
    # rest the viewer measures its own motion from. The first frame, which is
    # where the motors' own timeline starts.
    scene.frame_set(scene.frame_start)
    bpy.context.view_layer.update()

    missing = [n for n in ELEMENTS if bpy.data.objects.get(n) is None]
    for name in missing:
        say("INFO", f"{name} is not in this file; skipping it")
    order = [n for n in ELEMENTS if n not in missing] + list(SCREENS)
    for name in SCREENS:
        if bpy.data.objects.get(name) is None:
            fail(f"{name} is not in this file")

    depsgraph = bpy.context.evaluated_depsgraph_get()
    saved = {}
    colours = []
    total_v = total_t = 0

    for name in order:
        obj = bpy.data.objects[name]
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        is_screen = name in SCREENS

        count = len(mesh.vertices)
        points = np.empty(count * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", points)
        normals = np.empty(count * 3, dtype=np.float32)
        mesh.vertices.foreach_get("normal", normals)

        # Into world space here, and into metres, so the viewer never has to
        # know about object transforms or about what unit the file is in.
        matrix = np.array(obj.matrix_world, dtype=np.float32)
        rotation = matrix[:3, :3]
        world = (points.reshape(-1, 3) @ rotation.T + matrix[:3, 3]) * scale
        # Normals do not transform like positions; with no shear here the
        # rotation alone is right, and they are renormalised anyway.
        facing = normals.reshape(-1, 3) @ rotation.T
        lengths = np.linalg.norm(facing, axis=1, keepdims=True)
        facing = facing / np.maximum(lengths, 1e-9)

        mesh.calc_loop_triangles()
        loop_tris = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get("loops", loop_tris)
        loop_verts = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", loop_verts)
        faces = loop_verts[loop_tris.reshape(-1, 3)].astype(np.uint32)

        saved[f"{name}__points"] = world.astype(np.float32)
        saved[f"{name}__normals"] = facing.astype(np.float32)
        saved[f"{name}__triangles"] = faces

        if is_screen:
            layer = mesh.uv_layers.get(SCREENS[name]) or mesh.uv_layers.active
            if layer is None:
                fail(f"{name} has no UV layer {SCREENS[name]!r}")
            loop_uv = np.empty(len(mesh.loops) * 2, dtype=np.float32)
            layer.data.foreach_get("uv", loop_uv)
            per_vertex = np.zeros((count, 2), dtype=np.float32)
            per_vertex[loop_verts] = loop_uv.reshape(-1, 2)
            saved[f"{name}__uv"] = per_vertex
            colours.append((0.0, 0.0, 0.0))
        else:
            colours.append(base_colour(obj))

        say("INFO", f"{name:18s} {'screen' if is_screen else 'element':7s} "
                    f"{count:8,} verts  {len(faces):8,} tris")
        total_v += count
        total_t += len(faces)
        evaluated.to_mesh_clear()

    # How each screen sits around the structure, so a flat layout can put them
    # side by side truthfully: at one scale in metres, and lined up so that a
    # vertical line through the layout is one direction around the building.
    #
    # Only the three that carry a video of their own. The flat layout is about
    # the content, and the moving geometry shows the content of the still one
    # it stands in for.
    laid_out = list(dict.fromkeys(FEEDS[name] for name in SCREENS))
    unrolled = {}
    for name in laid_out:
        obj = bpy.data.objects[name]
        mesh = obj.evaluated_get(depsgraph).to_mesh()
        count = len(mesh.vertices)
        points = np.empty(count * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", points)
        matrix = np.array(obj.matrix_world, dtype=np.float32)
        world = (points.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]) * scale
        layer = mesh.uv_layers.get(SCREENS[name]) or mesh.uv_layers.active
        loop_uv = np.empty(len(mesh.loops) * 2, dtype=np.float32)
        layer.data.foreach_get("uv", loop_uv)
        loop_verts = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", loop_verts)
        uv = np.zeros((count, 2), dtype=np.float32)
        uv[loop_verts] = loop_uv.reshape(-1, 2)

        angle = np.arctan2(world[:, 1], world[:, 0])
        # Unwrapped along u, not around the circle: sorted the other way the
        # jump at the seam turns the fit into nonsense.
        along_u = np.argsort(uv[:, 0])
        straight = np.unwrap(angle[along_u])
        columns = np.vstack([uv[along_u, 0], np.ones(count)]).T
        slope, offset = np.linalg.lstsq(columns, straight, rcond=None)[0]
        radius = float(np.linalg.norm(world[:, :2], axis=1).mean())
        unrolled[name] = (radius * abs(float(slope)),          # arc, metres
                          float(world[:, 2].max() - world[:, 2].min()),
                          float(offset), float(slope),
                          float(world[:, 2].max()))
        obj.evaluated_get(depsgraph).to_mesh_clear()
        say("INFO", f"{name:18s} unrolled {unrolled[name][0]:6.2f} m around by "
                    f"{unrolled[name][1]:5.2f} m tall, u=0 at "
                    f"{np.degrees(offset):6.1f} deg")

    saved["unrolled"] = np.array([unrolled[n] for n in laid_out], dtype=np.float64)
    saved["unrolled_order"] = np.array(laid_out)

    lens = camera.data
    camera_matrix = np.array(camera.matrix_world, dtype=np.float32)
    camera_matrix[:3, 3] *= scale
    saved.update({
        "order": np.array(order),
        "kinds": np.array(["screen" if n in SCREENS else "element" for n in order]),
        # Which video each object shows, empty for the ones that show none.
        "feeds": np.array([FEEDS.get(n, "") for n in order]),
        "colours": np.array(colours, dtype=np.float32),
        "camera_matrix": camera_matrix,
        "lens": np.float32(lens.lens),
        "sensor": np.array([lens.sensor_width, lens.sensor_height], dtype=np.float32),
        "sensor_fit": np.array(lens.sensor_fit),
        "clip": np.array([lens.clip_start * scale, lens.clip_end * scale],
                         dtype=np.float32),
        "frame": np.array([scene.render.resolution_x, scene.render.resolution_y]),
        "camera": np.array(camera.name),
        "units": np.float32(scale),
    })

    path = os.path.join(out_dir, "scene_mesh.npz")
    np.savez_compressed(path, **saved)
    say("INFO", f"{total_v:,} verts and {total_t:,} triangles, "
                f"{os.path.getsize(path)/1e6:.1f} MB")
    say("INFO", f"baked at frame {scene.frame_start}, "
                f"{scale:g} metres to the unit")
    say("INFO", f"camera {camera.name}: lens {lens.lens:.2f} mm, sensor "
                f"{lens.sensor_width:.1f}x{lens.sensor_height:.1f} "
                f"({lens.sensor_fit}), frame {scene.render.resolution_x}x"
                f"{scene.render.resolution_y}")
    say("DONE", path)


if __name__ == "__main__":
    main()
