"""Scan a public Google Drive folder tree and index every entry, not just VPKs.

The landing page previously only knew about .vpk releases because
tools/vpk_targets.json was maintained by hand. This walks the whole tree so
modpacks, archives, docs and nested folders show up too, and reports which
entries the catalog has not seen yet.

Usage:
    python tools/drive_scan.py [--depth 3] [--out tools/drive_index.json]
"""
import argparse
import html
import io
import json
import os
import re
import sys
import urllib.request

CONFIG = os.path.join(os.path.dirname(__file__), "drive_sync_config.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
ENTRY = re.compile(r'<div class="flip-entry"')
# Folders link to /drive/folders/<id>; files link to /drive/file/<id>/view.
# The icon class is not a reliable marker — public folder listings vary.
FOLDER_LINK = re.compile(r'href="https://drive\.google\.com/drive/folders/')


def list_folder(folder_id: str) -> list:
    """Return [{id,name,is_dir}] for one folder via the public folder view."""
    url = "https://drive.google.com/embeddedfolderview?id=%s#list" % folder_id
    req = urllib.request.Request(url, headers=UA)
    body = urllib.request.urlopen(req, timeout=45).read().decode("utf-8", "replace")
    out = []
    for chunk in ENTRY.split(body)[1:]:
        fid = re.search(r'id="entry-([^"]+)"', chunk)
        title = re.search(r'class="flip-entry-title">(.*?)</div>', chunk, re.S)
        if not (fid and title):
            continue
        name = html.unescape(re.sub("<[^>]+>", "", title.group(1)).strip())
        out.append({"id": fid.group(1), "name": name,
                    "is_dir": bool(FOLDER_LINK.search(chunk))})
    return out


def walk(folder_id: str, path: str, depth: int, max_depth: int, seen: set):
    files, folders = [], []
    try:
        entries = list_folder(folder_id)
    except Exception as e:
        return files, folders, "%s: %s" % (path or "/", e)
    for e in entries:
        here = (path + "/" + e["name"]) if path else e["name"]
        if e["is_dir"]:
            folders.append({"id": e["id"], "name": e["name"], "path": here})
            if depth < max_depth and e["id"] not in seen:
                seen.add(e["id"])
                f2, d2, err = walk(e["id"], here, depth + 1, max_depth, seen)
                files += f2
                folders += d2
                if err:
                    print("  ! " + err, file=sys.stderr)
        else:
            ext = os.path.splitext(e["name"])[1].lower()
            files.append({
                "id": e["id"], "name": e["name"], "path": here, "ext": ext,
                "download": "https://drive.google.com/uc?export=download&id=%s" % e["id"],
                "view": "https://drive.google.com/file/d/%s/view" % e["id"],
            })
    return files, folders, None


def known_ids() -> set:
    p = os.path.join(os.path.dirname(__file__), "catalog.json")
    if not os.path.exists(p):
        return set()
    cat = json.load(io.open(p, encoding="utf-8"))
    ids = set()
    for v in cat.values():
        if isinstance(v, list):
            for it in v:
                if isinstance(it, dict) and it.get("id"):
                    ids.add(it["id"])
    return ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "drive_index.json"))
    args = ap.parse_args()

    cfg = json.load(io.open(CONFIG, encoding="utf-8"))
    root = cfg["folderId"]
    ignored = set(cfg.get("ignore") or [])
    print("scanning Drive folder %s (depth %d)" % (root, args.depth))

    files, folders, _ = walk(root, "", 1, args.depth, {root})
    files.sort(key=lambda f: f["path"].lower())
    folders.sort(key=lambda f: f["path"].lower())

    index = {"root": root, "rootUrl": cfg.get("folderUrl"), "files": files, "folders": folders}
    io.open(args.out, "w", encoding="utf-8").write(json.dumps(index, indent=1, ensure_ascii=False))

    by_ext = {}
    for f in files:
        by_ext[f["ext"] or "(none)"] = by_ext.get(f["ext"] or "(none)", 0) + 1
    print("\n%d files, %d folders" % (len(files), len(folders)))
    for ext, n in sorted(by_ext.items(), key=lambda kv: -kv[1]):
        print("   %-12s %d" % (ext, n))

    kn = known_ids()
    new = [f for f in files
           if f["id"] not in kn and f["name"] not in ignored and f["path"] not in ignored]
    print("\n%d files are neither catalogued nor deliberately ignored:" % len(new))
    for f in new:
        print("   %-56s %s" % (f["path"][:56], f["id"]))
    print("\nindex ->", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
