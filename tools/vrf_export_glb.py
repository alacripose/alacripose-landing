"""Export preview GLBs straight out of the mod VPKs with VRF — no Blender.

The original pipeline routed VPK -> Blender + SourceIO -> GLB. Source2Viewer can
emit glTF itself (--gltf_export_format glb with -d), which removes Blender and the
SourceIO addon from the path entirely.

Known limits, both real and worth reading before a full batch:
  * A mod VPK usually ships only the model. Material and texture references point
    into the base game paks, so the export reports 0 materials / 0 images and the
    viewer falls back to its shader defaults. Textures need the existing
    .vmat decompile + NPR channel pass (tools/build_npr_materials.py).
  * Geometry alone lands around 3.5 MB per hero skin. See --estimate.

Usage:
  python tools/vrf_export_glb.py --id sly_haze            # one mod
  python tools/vrf_export_glb.py --all --limit 5
  python tools/vrf_export_glb.py --estimate 52
"""
import argparse
import json
import os
import re
import struct
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VRF = os.path.join(HERE, "vrf", "Source2Viewer-CLI.exe")
INDEX = os.path.join(HERE, "drive_index.json")
SCAN = os.path.join(HERE, "vpk_scan_results.json")
INLINE_SCAN = os.path.join(HERE, "vpk_inline_scan.json")
OUT = os.path.join(ROOT, "_previews")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MODEL_RE = re.compile(r"^(models/.+\.vmdl_c)$", re.M)


def drive_download(file_id: str, dest: str, cap_mb: int = 400) -> str:
    """Two-step confirm download; returns 'cached', 'ok', or an error string."""
    if os.path.exists(dest) and os.path.getsize(dest) > 4096:
        return "cached"
    url = "https://drive.google.com/uc?export=download&id=%s" % file_id
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60)
    head = r.read(2048)
    if head[:15].lower().startswith(b"<!doctype html"):
        html = (head + r.read(200000)).decode("utf-8", "replace")
        m = re.search(r'action="([^"]+)"', html)
        if not m:
            return "no-confirm-form"
        base = m.group(1).replace("&amp;", "&")
        ins = dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', html))
        qs = "&".join("%s=%s" % (k, v) for k, v in ins.items())
        r = urllib.request.urlopen(urllib.request.Request(base + "?" + qs, headers=UA), timeout=600)
        chunks = [b""]
    else:
        chunks = [head]
    total = len(chunks[0])
    try:
        while True:
            c = r.read(1 << 20)
            if not c:
                break
            total += len(c)
            if total > cap_mb * 1024 * 1024:
                return "too-big"
            chunks.append(c)
    except Exception as e:
        return "error:%s" % type(e).__name__
    data = b"".join(chunks)
    if data[:4] != b"\x34\x12\xaa\x55":
        return "not-a-vpk:%r" % data[:4]
    with open(dest, "wb") as f:
        f.write(data)
    return "ok"


def model_paths(vpk: str):
    """Model inner paths, from the cached scan when possible, else VRF itself."""
    name = os.path.basename(vpk)
    for cache in (SCAN, INLINE_SCAN):
        if os.path.exists(cache):
            try:
                for e in json.load(open(cache, encoding="utf-8")):
                    if e.get("file") == name:
                        models = [f for f in (e.get("files") or []) if f.endswith(".vmdl_c")]
                        if models:
                            return models
            except Exception:
                pass
    out = subprocess.run([VRF, "-i", vpk, "--vpk_list"], capture_output=True, text=True, timeout=300)
    return MODEL_RE.findall(out.stdout)


def export_glb(vpk: str, inner: str, out_stem: str) -> str:
    """VRF emits <stem>.glb plus a <stem>_physics.glb sidecar; keep only the model."""
    args = [VRF, "-i", vpk, "-d", "--vpk_filepath", inner, "-o", out_stem + ".glb",
            "--gltf_export_format", "glb", "--gltf_export_materials"]
    subprocess.run(args, capture_output=True, text=True, timeout=900)
    return out_stem + ".glb"


def glb_stats(path: str) -> dict:
    if not os.path.exists(path):
        return {"error": "missing"}
    d = open(path, "rb").read()
    magic, version, length = struct.unpack_from("<4sII", d, 0)
    stats = {"bytes": len(d), "valid": magic == b"glTF" and version == 2 and length == len(d)}
    off = 12
    while off + 8 <= length:
        clen, ctype = struct.unpack_from("<I4s", d, off)
        if ctype == b"JSON":
            j = json.loads(d[off + 8:off + 8 + clen].decode("utf-8"))
            stats["meshes"] = len(j.get("meshes", []))
            stats["materials"] = len(j.get("materials", []))
            stats["images"] = len(j.get("images", []))
        off += 8 + clen
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="drive filename stem, e.g. sly_haze")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--estimate", type=int, default=0, help="print a Pages budget for N mods")
    ap.add_argument("--mb-per-mod", type=float, default=3.5, help="measured geometry size")
    ap.add_argument("--page-budget-mb", type=float, default=1024.0)
    args = ap.parse_args()

    if args.estimate:
        used = args.estimate * args.mb_per_mod
        print("%d mods x %.1f MB geometry = %.0f MB" % (args.estimate, args.mb_per_mod, used))
        print("GitHub Pages site limit is %.0f MB, so that is %.0f%% of it."
              % (args.page_budget_mb, 100.0 * used / args.page_budget_mb))
        print("Textures are on top of that; the two mods already published average ~15 MB each.")
        return 0

    index = json.load(open(INDEX, encoding="utf-8")) if os.path.exists(INDEX) else {"files": []}
    files = [f for f in index["files"] if f.get("featured", True) and f["ext"] == ".vpk"]
    if args.id:
        files = [f for f in files if os.path.splitext(f["name"])[0] == args.id]
    elif not args.all:
        print("pick one with --id, or pass --all")
        return 2
    if args.limit:
        files = files[:args.limit]
    if not files:
        print("no matching VPKs")
        return 1

    os.makedirs(OUT, exist_ok=True)
    done = []
    for f in files:
        stem = os.path.splitext(f["name"])[0]
        vpk = os.path.join(OUT, f["name"])
        status = drive_download(f["id"], vpk)
        if status not in ("ok", "cached"):
            print("%-34s download: %s" % (f["name"], status))
            continue
        models = model_paths(vpk)
        if not models:
            print("%-34s no .vmdl_c in the vpk" % f["name"])
            continue
        glb = export_glb(vpk, models[0], os.path.join(OUT, stem))
        st = glb_stats(glb)
        if not st.get("valid"):
            print("%-34s export failed: %s" % (f["name"], st))
            continue
        print("%-34s %-44s %.1f MB  meshes:%d materials:%d images:%d"
              % (f["name"], models[0], st["bytes"] / 1048576.0,
                 st.get("meshes", 0), st.get("materials", 0), st.get("images", 0)))
        done.append((stem, st))
    print("\nexported %d/%d" % (len(done), len(files)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
