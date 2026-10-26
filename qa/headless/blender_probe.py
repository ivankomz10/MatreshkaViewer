"""Run inside Blender by test_blender_export: opens a made .blend and writes out
what Blender evaluates -- the cells' vertices, `proj` and `seen` on the frames
asked, and the unrolled screen's vertices on the last of them.

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
for f in frames:
    look.frame_set(f)
    deps = bpy.context.evaluated_depsgraph_get()
    ob = bpy.data.objects["Top_kinetic"].evaluated_get(deps)
    me = ob.to_mesh()
    co = np.zeros(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    got[f"co_{f}"] = co.reshape(-1, 3)
    pv = np.zeros(len(me.loops) * 2, np.float32)
    me.attributes["proj"].data.foreach_get("vector", pv)
    got[f"proj_{f}"] = pv.reshape(-1, 2)
    loops = np.zeros(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", loops)
    got["loop_vertex"] = loops
    ob.to_mesh_clear()
flat_scene = bpy.data.scenes["Top развертка"]
flat_scene.frame_set(frames[-1])
deps = flat_scene.view_layers[0].depsgraph
deps.update()
flat = bpy.data.objects["Top_flat"].evaluated_get(deps)
me = flat.to_mesh()
co = np.zeros(len(me.vertices) * 3, np.float32)
me.vertices.foreach_get("co", co)
got["flat"] = co.reshape(-1, 3)
flat.to_mesh_clear()
got["render_size"] = np.array([flat_scene.render.resolution_x, flat_scene.render.resolution_y])
got["frames"] = np.array([look.frame_start, look.frame_end])
np.savez(out, **got)
