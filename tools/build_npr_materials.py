"""Build nprMaterials descriptors for tools/model_preview_manifest.json.

Reads decompiled .vmat files under assets/previews/<mod>/ (VRF text output) and the
extracted texture PNGs, mapping Valve texture slots to viewer channels:
  TextureColor                -> albedo
  TextureNormalRoughness      -> normalRoughness
  TextureAmbientOcclusion     -> ambientOcclusion
  TextureTintMaskRimLightMask -> tintMaskRimLightMask (r=tint, g/b=rim)
  TextureTintMask             -> tintMask
  TextureNprOutlineMask       -> nprOutlineMask
  TextureNprTransmissiveColor -> nprTransmissiveColor
Also captures g_vColorTint / outline tint vectors and F_USE_NPR_LIGHTING.
"""
import json
import os
import re

MOD_DIRS = {
    "mayu": "assets/previews/mayu",
    "weiss": "assets/previews/weiss",
}

CHANNEL_MAP = {
    "TextureColor": "albedo",
    "TextureNormalRoughness": "normalRoughness",
    "TextureNormal": "normal",
    "TextureAmbientOcclusion": "ambientOcclusion",
    "TextureTintMaskRimLightMask": "tintMaskRimLightMask",
    "TextureTintMask": "tintMask",
    "TextureNprOutlineMask": "nprOutlineMask",
    "TextureNprTransmissiveColor": "nprTransmissiveColor",
    "TextureRimLightMask": "rimLightMask",
    "TextureRoughness": "roughness",
    "TextureMetalness": "metalness",
}

VEC_RE = re.compile(r"^\[([-\d. ]+)\]$")


def parse_vmat(path):
    props = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.match(r'\s*"([^"]+)"\s+"([^"]*)"', line)
            if m:
                props[m.group(1)] = m.group(2)
    return props


def vec4(s):
    m = VEC_RE.match(s or "")
    return [round(float(x), 4) for x in m.group(1).split()] if m else None


def find_png(basename, search_dirs):
    if not basename:
        return None
    stem = os.path.basename(basename)
    for d in search_dirs:
        p = os.path.join(d, stem)
        if os.path.exists(p):
            return p.replace("\\", "/").replace("assets/", "", 1)
    return None


def scan_vmat_dirs(preview_dir):
    out = []
    for dirpath, _, files in os.walk(preview_dir):
        if "glb" in os.path.basename(dirpath):
            continue
        for f in files:
            if f.endswith(".vmat"):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


manifest_path = "tools/model_preview_manifest.json"
mpm = json.load(open(manifest_path))

for mod in mpm["mods"]:
    mod_id = mod["id"]
    pd = MOD_DIRS.get(mod_id)
    if not pd or not os.path.isdir(pd):
        continue
    png_dirs = [pd, os.path.join(pd, "glb", "models")]  # glb textures land nearby
    # also walk deeper: VRF drops glb textures next to the glb output tree
    png_index = {}
    for dirpath, _, files in os.walk(pd):
        for f in files:
            if f.endswith(".png"):
                png_index.setdefault(f, os.path.join(dirpath, f).replace("\\", "/"))

    def png_url(basename):
        if not basename:
            return None
        p = png_index.get(os.path.basename(basename))
        return p.replace("assets/", "", 1) if p else None

    materials = []
    for vmat_path in scan_vmat_dirs(pd):
        props = parse_vmat(vmat_path)
        if not props:
            continue
        entry = {
            "name": os.path.basename(vmat_path).replace(".vmat", ""),
            "shader": props.get("shader", ""),
            "nprLighting": props.get("F_USE_NPR_LIGHTING") == "1",
            "channels": {},
            "params": {},
        }
        for slot, channel in CHANNEL_MAP.items():
            tex = props.get(slot, "")
            if tex and not tex.startswith("["):
                url = png_url(tex)
                if url:
                    entry["channels"][channel] = url
        for key in ("g_vColorTint1", "g_vHighlightTint1", "g_vSolidOutlineTint",
                    "g_vSolidOutlineAdditive", "g_flHighlightCoverage1",
                    "g_flHighlightHardness1", "g_flHighlightTintBrightness1"):
            if key in props:
                v = vec4(props[key])
                entry["params"][key] = v if v is not None else props[key]
        if entry["channels"] or entry["nprLighting"]:
            materials.append(entry)

    if materials:
        mod["nprMaterials"] = materials
        print(mod_id, "->", len(materials), "materials,",
              sum(len(m["channels"]) for m in materials), "texture channels")

json.dump(mpm, open(manifest_path, "w"), indent=2, ensure_ascii=False)
print("manifest updated")
