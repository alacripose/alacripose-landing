"""Sync tools/model_preview_manifest.json with assets/previews/* extracted assets
and tools/vpk_scan_results.json. Run after drive_vpk_scan.py + VRF extraction."""
import json
import os

mpm = json.load(open("tools/model_preview_manifest.json"))
scan = {r["file"]: r for r in json.load(open("tools/vpk_scan_results.json"))}
# manifest id -> VPK filename (hyphens vs underscores, and legacy aliases)
VPK_FOR_ID = {
    "ava-headed-calico": "ava_headed_calico.vpk",
    "okina-matara": "matara_magician.vpk",
}
# manifest id -> extracted preview dir under assets/previews (defaults to id with '_' for '-')
PREVIEW_DIR_FOR_ID = {
    "okina-matara": "matara_magician",
}


def list_files(root, exts):
    out = []
    for dirpath, _, files in os.walk(root):
        for f in sorted(files):
            if f.lower().endswith(exts):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


for m in mpm["mods"]:
    mod_id = m["id"]
    s = scan.get(VPK_FOR_ID.get(mod_id, mod_id + ".vpk"))
    if not s:
        continue
    entry = dict(m)
    model = m["model"]
    vmdl_dec = model.replace(".vmdl_c", ".vmdl")

    # browserModel: decompiled .vmdl extracted by VRF, if present
    preview_dir = PREVIEW_DIR_FOR_ID.get(mod_id, mod_id.replace("-", "_"))
    # browserModel must be a .glb: the viewer loads it with GLTFLoader, which
    # cannot parse a .vmdl. Only fall back to the decompiled .vmdl when no .glb
    # has been exported yet - the entry still lists files, just without 3D.
    if not (m.get("browserModel") or "").lower().endswith(".glb"):
        if os.path.exists(os.path.join("assets/previews", preview_dir, *vmdl_dec.split("/"))):
            entry["browserModel"] = f"assets/previews/{preview_dir}/{vmdl_dec}"

    # files: real extracted assets for the modal file list
    pd = os.path.join("assets/previews", preview_dir)
    if os.path.isdir(pd):
        files = []
        if os.path.exists(os.path.join(pd, *vmdl_dec.split("/"))):
            files.append(vmdl_dec)
        mdir = os.path.join(pd, *os.path.dirname(model).split("/"), "materials")
        if os.path.isdir(mdir):
            files += [os.path.dirname(model) + "/materials/" + f
                      for f in sorted(os.listdir(mdir)) if f.endswith(".vmat")]
        # card art (png extracted from panorama) — may live anywhere in the preview dir
        for p in list_files(pd, (".png",)):
            rel = os.path.relpath(p, pd).replace(os.sep, "/")
            if "panorama/images/heroes" in rel:
                files.append(rel)
        if files:
            entry["files"] = files

    # texture inventory from the VPK scan
    entry["textureCount"] = sum(1 for f in s.get("files", []) if f.endswith(".vtex_c"))

    mpm["mods"][mpm["mods"].index(m)] = entry


# ── Normalize nprMaterials channel references ─────────────────────────────
# Two writers disagree on the URL base: this script writes browserModel as
# "assets/previews/...", but the Blender exporter writes channel URLs as bare
# "previews/...". The page fetches channel URLs verbatim, so the bare form
# 404s. Normalize every channel to the "assets/..." form.
#
# VRF writes a 1x1 PNG wherever the .vmat declares a constant vector
# (TextureNormal1, TextureAmbientOcclusion1, TextureRoughness1, ...). Those are
# constants, not textures - but a 1x1 load succeeds, so the viewer's "channel
# missing" fallbacks never fire and it samples a single pixel instead. Most are
# harmless no-ops (a flat normal, AO=1); some are not (AO=0 renders the model
# black). Emit the literal value so the viewer gets the exact constant and no
# stub images need to ship.


def png_1x1_rgba(path):
    """Return [r, g, b, a] for a 1x1 PNG, else None."""
    import struct
    import zlib
    try:
        with open(path, "rb") as fh:
            b = fh.read()
    except OSError:
        return None
    if b[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", b[16:24]) != (1, 1):
        return None
    off, idat = 8, bytearray()
    while off + 8 <= len(b):
        ln = struct.unpack(">I", b[off:off + 4])[0]
        typ = b[off + 4:off + 8]
        if typ == b"IDAT":
            idat += b[off + 8:off + 8 + ln]
        elif typ == b"IEND":
            break
        off += 12 + ln
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error:
        return None
    nch = {0: 1, 2: 3, 4: 2, 6: 4}.get(b[25], 4)
    px = list(raw[1:1 + nch])
    if nch == 1:
        px = px * 3 + [255]
    elif nch == 2:
        px = px[:1] * 3 + [px[1]]
    elif nch == 3:
        px = px + [255]
    return px


def normalize_channels(mods):
    """Prefix channel URLs with assets/ and inline 1x1 placeholders as constants."""
    changed = consts = 0
    for m in mods:
        for mat in (m.get("nprMaterials") or []):
            ch = mat.get("channels") or {}
            for role, val in list(ch.items()):
                if not isinstance(val, str) or not val:
                    continue
                rel = val.replace("\\", "/").lstrip("/")
                norm = rel if rel.startswith("assets/") else "assets/" + rel
                px = png_1x1_rgba(norm) if os.path.exists(norm) else None
                if px:
                    ch[role] = {"const": px}
                    consts += 1
                elif ch[role] != norm:
                    ch[role] = norm
                changed += 1
            mat["channels"] = ch
    return changed, consts


_normalized, _consts = normalize_channels(mpm["mods"])
print("normalized channel refs:", _normalized, "| inlined 1x1 constants:", _consts)


json.dump(mpm, open("tools/model_preview_manifest.json", "w"), indent=2, ensure_ascii=False)
for m in mpm["mods"]:
    print(m["id"], "| browserModel:", m.get("browserModel", "-"),
          "| files:", len(m.get("files", [])), "| textures:", m.get("textureCount"))
