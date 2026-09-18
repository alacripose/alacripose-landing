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

json.dump(mpm, open("tools/model_preview_manifest.json", "w"), indent=2, ensure_ascii=False)
for m in mpm["mods"]:
    print(m["id"], "| browserModel:", m.get("browserModel", "-"),
          "| files:", len(m.get("files", [])), "| textures:", m.get("textureCount"))
