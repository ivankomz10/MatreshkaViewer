"""Run inside Blender by test_blender_export: opens a made .blend and writes out
what Blender evaluates on the frames asked -- the cells' vertices in Top 3D,
and on the unrolled cells of Top flat their `proj` and their vertices.

    blender -b made.blend --factory-startup -P blender_probe.py -- out.npz 1,6,12
"""
import sys
from pathlib import Path

import bpy
import numpy as np

out = Path(sys.argv[sys.argv.index("--") + 1])
frames = [int(f) for f in sys.argv[sys.argv.index("--") + 2].split(",")]
got = {}
look = bpy.data.scenes["Top 3D"]
flat_scene = bpy.data.scenes["Top flat"]


def vertices(me):
    co = np.zeros(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


for f in frames:
    look.frame_set(f)
    deps = look.view_layers[0].depsgraph
    deps.update()
    ob = bpy.data.objects["Top_kinetic"].evaluated_get(deps)
    got[f"co_{f}"] = vertices(ob.to_mesh())
    ob.to_mesh_clear()
    flat_scene.frame_set(f)
    deps = flat_scene.view_layers[0].depsgraph
    deps.update()
    flat = bpy.data.objects["Top_flat"].evaluated_get(deps)
    me = flat.to_mesh()
    pv = np.zeros(len(me.loops) * 2, np.float32)
    me.attributes["proj"].data.foreach_get("vector", pv)
    got[f"proj_{f}"] = pv.reshape(-1, 2)
    loops = np.zeros(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", loops)
    got["loop_vertex"] = loops
    got["flat"] = vertices(me)
    flat.to_mesh_clear()
got["render_size"] = np.array([flat_scene.render.resolution_x, flat_scene.render.resolution_y])
got["frames"] = np.array([look.frame_start, look.frame_end])
got["look_size"] = np.array([look.render.resolution_x, look.render.resolution_y])
got["look_hidden"] = np.array([bpy.data.objects["Top_kinetic"].hide_render])
np.savez(out, **got)
