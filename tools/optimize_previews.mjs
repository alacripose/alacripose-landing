#!/usr/bin/env node
/**
 * Convert the 3D preview textures referenced by tools/model_preview_manifest.json
 * into KTX2 (Basis Universal), downscaling to a sane maximum dimension.
 *
 * Why: raw VRF extraction ships 4096x4096 RGBA PNGs (up to 30 MB each) - about
 * 119 MB for two mods, which would pass the 1 GB GitHub Pages limit long before
 * the catalog is covered. KTX2 also keeps textures compressed in VRAM instead of
 * expanding to full RGBA on the GPU.
 *
 * UASTC is used for normal/roughness maps and ETC1S for everything else: ETC1S is
 * a block-codebook format that visibly destroys tangent-space normals, while it is
 * fine (and much smaller) for albedo, AO and masks.
 *
 * Requires ffmpeg/ffprobe for decode + downscale, and ktx2-encoder for the WASM
 * Basis encoder - so no native KTX-Software binary is needed.
 *
 * Writes <source>.ktx2 beside each PNG and rewrites the manifest to match.
 *
 * Usage: node tools/optimize_previews.mjs [--max=2048] [--force] [--dry]
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { encodeToKTX2 } from "ktx2-encoder";

const MANIFEST = "tools/model_preview_manifest.json";
const args = process.argv.slice(2);
const getArg = (name, fallback) => {
  const hit = args.find((a) => a === `--${name}` || a.startsWith(`--${name}=`));
  if (!hit) return fallback;
  const [, value] = hit.split("=");
  return value === undefined ? true : value;
};
const MAX = Number(getArg("max", 2048));
const FORCE = Boolean(getArg("force", false));
const DRY = Boolean(getArg("dry", false));
const UASTC_ROLES = new Set(["normalRoughness"]);

function dimensions(file) {
  const out = execFileSync(
    "ffprobe",
    ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", file],
    { maxBuffer: 1 << 20 }
  ).toString().trim();
  const [w, h] = out.split(",").map(Number);
  if (!w || !h) throw new Error(`could not read dimensions: ${file}`);
  return { w, h };
}

/** ffmpeg reads the PNG on stdin and emits raw RGBA at the target size. */
function makeDecoder(tw, th) {
  return async (buf) => {
    const raw = execFileSync(
      "ffmpeg",
      ["-v", "error", "-i", "pipe:0", "-vf", `scale=${tw}:${th}`, "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
      { input: buf, maxBuffer: 1 << 30 }
    );
    return { data: new Uint8Array(raw), width: tw, height: th };
  };
}

const mb = (n) => (n / 1048576).toFixed(2).padStart(7) + "MB";
const manifest = JSON.parse(readFileSync(MANIFEST, "utf8"));

// Collect every texture a channel points at, remembering if any use needs UASTC.
const targets = new Map();
for (const mod of manifest.mods) {
  for (const mat of mod.nprMaterials ?? []) {
    for (const [role, value] of Object.entries(mat.channels ?? {})) {
      if (typeof value !== "string" || !/\.(png|jpe?g)$/i.test(value)) continue;
      if (!existsSync(value)) continue;
      const prev = targets.get(value);
      targets.set(value, { uastc: (prev?.uastc ?? false) || UASTC_ROLES.has(role) });
    }
  }
}
console.log(`textures: ${targets.size}  max dimension: ${MAX}${DRY ? "  (dry run)" : ""}\n`);

let before = 0;
let after = 0;
const converted = new Map();

for (const [src, { uastc }] of targets) {
  const { w, h } = dimensions(src);
  const scale = Math.min(1, MAX / Math.max(w, h));
  const tw = Math.max(1, Math.round(w * scale));
  const th = Math.max(1, Math.round(h * scale));
  const out = src.replace(/\.(png|jpe?g)$/i, ".ktx2");
  const srcBytes = statSync(src).size;
  before += srcBytes;
  converted.set(src, out);

  if (DRY) {
    console.log(`${uastc ? "UASTC" : "ETC1S"}  ${w}x${h} -> ${tw}x${th}  ${mb(srcBytes)}  ${src}`);
    continue;
  }

  let outBytes;
  if (existsSync(out) && !FORCE) {
    outBytes = statSync(out).size;
  } else {
    const png = new Uint8Array(readFileSync(src));
    const ktx2 = await encodeToKTX2(png, {
      isUASTC: uastc,
      generateMipmap: true,
      imageDecoder: makeDecoder(tw, th),
    });
    writeFileSync(out, ktx2);
    outBytes = ktx2.length;
  }
  after += outBytes;
  const ratio = ((1 - outBytes / srcBytes) * 100).toFixed(0);
  console.log(
    `${uastc ? "UASTC" : "ETC1S"}  ${w}x${h} -> ${tw}x${th}  ${mb(srcBytes)} -> ${mb(outBytes)}  -${ratio}%  ${out}`
  );
}

if (DRY) process.exit(0);

// Point every channel at the .ktx2 file we just produced.
let rewrites = 0;
for (const mod of manifest.mods) {
  for (const mat of mod.nprMaterials ?? []) {
    for (const [role, value] of Object.entries(mat.channels ?? {})) {
      if (typeof value !== "string") continue;
      const out = converted.get(value);
      if (out && out !== value) {
        if (!existsSync(out)) throw new Error(`missing encoded output for ${value}`);
        mat.channels[role] = out;
        rewrites++;
      }
    }
  }
}
writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2) + "\n");

console.log(`\nrewrote ${rewrites} channel paths`);
console.log(`textures ${mb(before)} -> ${mb(after)}  (${((1 - after / before) * 100).toFixed(1)}% smaller)`);
