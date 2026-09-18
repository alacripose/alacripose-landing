"""Download a list of Drive files (confirm-token flow), parse VPKs, dump contents."""
import concurrent.futures as cf
import io
import json
import os
import re
import sys
import urllib.request

import vpk

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
OUT = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "awa3d-vpks")


def drive_download(file_id: str, dest: str) -> str:
    """Two-step confirm download; returns 'ok' or an error string."""
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        return "cached"
    try:
        url = f"https://drive.google.com/uc?export=download&id={file_id}"
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()  # RAW bytes — never text-decode binary
        # HTML confirm page? (large-file flow) -> follow the form
        if data[:15].lower().startswith(b"<!doctype html") or b"<html" in data[:200].lower():
            html = data.decode("utf-8", "replace")
            m = re.search(r'action="([^"]+)"', html)
            if not m:
                return "no-confirm-form"
            base = m.group(1).replace("&amp;", "&")
            inputs = dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', html))
            qs = "&".join(f"{k}={v}" for k, v in inputs.items())
            req2 = urllib.request.Request(f"{base}?{qs}", headers=UA)
            with urllib.request.urlopen(req2, timeout=180) as r2:
                data = r2.read()
        with open(dest, "wb") as f:
            f.write(data)
        head = data[:4]
        if head == b"\x34\x12\xaa\x55":
            return "ok"
        if head == b"PK\x03\x04":
            return "zip"
        return f"not-vpk:{head!r}"
    except Exception as e:
        return f"error:{type(e).__name__}:{e}"


def vpk_summary(path: str) -> dict:
    """Parse a VPK: tree summary + any docs/author info + vmat names."""
    out = {"file": os.path.basename(path), "size": os.path.getsize(path)}
    try:
        p = vpk.open(path)
        entries = list(p)  # this vpk lib iterates as strings already
        out["n_entries"] = len(entries)
        # Keep the complete path index lightweight; the landing page can show it without downloading the VPK.
        out["files"] = entries
        # hero/model hints from paths
        models = [e for e in entries if "models/heroes" in e or "heroes" in e]
        mats = [e for e in entries if e.endswith("_c.vmat")]
        docs = [e for e in entries if "docs" in e or e.endswith(".txt") or e.endswith(".vcd")]
        out["heroes"] = sorted({
            re.search(r"heroes[/\\]([a-z_0-9]+)", e).group(1)
            for e in models
            if re.search(r"heroes[/\\]([a-z_0-9]+)", e)
        })
        out["vmats"] = sorted({os.path.basename(m) for m in mats})[:24]
        out["docs"] = docs[:12]
        # vmath controls / docsvalues often carry author + mod name
        texts = []
        for e in entries:
            if e.endswith((".vjsn", ".vsnd", ".vtxt", ".txt")) and len(texts) < 6:
                try:
                    data = p.get_file(e).read()
                    if data and len(data) < 60000:
                        texts.append((e, data[:120]))
                except Exception:
                    pass
        out["text_files"] = texts
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    # cryptic/unmatched vpk file ids from the Drive releases folder
    targets = json.load(open(sys.argv[1]))
    results = []
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {
            ex.submit(drive_download, fid, os.path.join(OUT, fname)): (fname, fid)
            for fname, fid in targets.items()
        }
        for fut in cf.as_completed(futs):
            fname, fid = futs[fut]
            status = fut.result()
            print(f"{fname}: {status}", flush=True)
            if status in ("ok", "cached"):
                results.append(vpk_summary(os.path.join(OUT, fname)))
            else:
                results.append({"file": fname, "status": status})
    json.dump(results, open(sys.argv[2], "w"), indent=1)
    print("summary ->", sys.argv[2])
