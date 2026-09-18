"""Headless Blender: mount the VPK via SourceIO's ContentManager, import the model,
export GLB + an NPR material descriptor JSON (textures, channels, tint/outline params).

Usage:
  blender.exe --background --python tools/blender_export_glb.py -- <vpk_path> <inner_vmdl_path> <out_dir>
"""
import json
import os
import sys
from pathlib import Path

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
vpk_path, vmdl_path, out_dir = Path(argv[0]), argv[1], argv[2]
os.makedirs(out_dir, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="SourceIO")

from SourceIO.library.shared.content_manager import ContentManager
from SourceIO.library.shared.content_manager.providers.vpk_provider import VPKContentProvider
from SourceIO.library.source2 import CompiledModelResource
from SourceIO.library.utils import FileBuffer
from SourceIO.library.utils.tiny_path import TinyPath
from SourceIO.blender_bindings.source2.vmdl_loader import load_model, ImportContext

cm = ContentManager()
vpk_provider = VPKContentProvider(TinyPath(str(vpk_path)))
cm.add_child(vpk_provider)

inner = TinyPath(vmdl_path)
file_buffer = vpk_provider.find_file(inner)
if file_buffer is None:
    raise RuntimeError(f"{vmdl_path} not found in {vpk_path.name}")
model_resource = CompiledModelResource.from_buffer(file_buffer, inner)

import_context = ImportContext(scale=0.01905, lod_mask=0xFFFF,
                               import_physics=False, import_attachments=False,
                               import_materials=True)
container = load_model(cm, model_resource, import_context)
print("MODEL loaded:", model_resource.name)

npr_materials = {}
mesh_count = 0
for obj in bpy.data.objects:
    if obj.type != "MESH":
        continue
    mesh_count += 1
    for slot in obj.material_slots:
        mat = slot.material
        if not mat or mat.name in npr_materials:
            continue
        info = {"name": mat.name, "textures": {}}
        if mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image:
                    img = node.image
                    p = ""
                    try:
                        p = bpy.path.abspath(img.filepath).replace("\\", "/")
                    except Exception:
                        pass
                    info["textures"][node.name] = p
        for key in mat.keys():
            if key.startswith(("g_", "F_")):
                v = mat[key]
                info[key] = v if isinstance(v, (int, float, str)) else str(v)
        npr_materials[mat.name] = info

print(f"IMPORTED meshes={mesh_count} materials={len(npr_materials)}")

bpy.ops.object.select_all(action="SELECT")
glb_path = os.path.join(out_dir, os.path.basename(vmdl_path).replace(".vmdl_c", ".glb"))
bpy.ops.export_scene.gltf(filepath=glb_path, use_selection=True, export_format="GLB")
print("GLB ->", glb_path)

json.dump(npr_materials, open(os.path.join(out_dir, "materials.json"), "w"), indent=1)
print("MATS ->", os.path.join(out_dir, "materials.json"))
