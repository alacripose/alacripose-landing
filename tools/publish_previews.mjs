#!/usr/bin/env node
/**
 * Assemble the publishable 3D preview set.
 *
 * assets/previews/ holds the full VRF extraction and is gitignored (hundreds of
 * MB of raw source). This copies only what the viewer actually fetches into
 * assets/preview-models/, which is a normal tracked directory, so publishing
 * needs no gitignore negation gymnastics.
 *
 * GLBs are rewritten to drop materials/textures/images/samplers. The viewer
 * replaces every material with its own ShaderMaterial and reads channel
 * textures from the manifest, so the GLB's texture sidecars are dead weight -
 * and because GLTFLoader resolves them eagerly, leaving them in would 404 and
 * fail the whole model load.
 *
 * Usage: node tools/publish_previews.mjs [--dry]
 */
import { execSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

const MANIFEST = "tools/model_preview_manifest.json";
const SRC_ROOT = "assets/previews/";
const DST_ROOT = "assets/preview-models/";
const DRY = process.argv.includes("--dry");
const JSON_CHUNK = 0x4e4f534a;
const BIN_CHUNK = 0x004e4942;

function stripGlb(buf) {
  if (buf.slice(0, 4).toString("ascii") !== "glTF") throw new Error("not a GLB");
  let off = 12;
  let json = null;
  let bin = null;
  while (off + 8 <= buf.length) {
    const len = buf.readUInt32LE(off);
    const type = buf.readUInt32LE(off + 4);
    const data = buf.slice(off + 8, off + 8 + len);
    if (type === JSON_CHUNK) json = JSON.parse(data.toString("utf8"));
    else if (type === BIN_CHUNK) bin = data;
    off += 8 + len;
  }
  if (!json) throw new Error("no JSON chunk");
  const dropped = {
    materials: json.materials?.length ?? 0,
    textures: json.textures?.length ?? 0,
    images: json.images?.length ?? 0,
  };
  delete json.materials;
  delete json.textures;
  delete json.images;
  delete json.samplers;
  for (const mesh of json.meshes ?? []) {
    for (const prim of mesh.primitives ?? []) delete prim.material;
  }
  let js = Buffer.from(JSON.stringify(json), "utf8");
  const pad = (4 - (js.length % 4)) % 4;
  if (pad) js = Buffer.concat([js, Buffer.alloc(pad, 0x20)]);
  const header = Buffer.alloc(12);
  header.write("glTF", 0, "ascii");
  header.writeUInt32LE(2, 4);
  const c0 = Buffer.alloc(8);
  c0.writeUInt32LE(js.length, 0);
  c0.writeUInt32LE(JSON_CHUNK, 4);
  const parts = [header, c0, js];
  if (bin) {
    const c1 = Buffer.alloc(8);
    c1.writeUInt32LE(bin.length, 0);
    c1.writeUInt32LE(BIN_CHUNK, 4);
    parts.push(c1, bin);
  }
  const out = Buffer.concat(parts);
  out.writeUInt32LE(out.length, 8);
  return { out, dropped };
}

const manifest = JSON.parse(readFileSync(MANIFEST, "utf8"));
const files = new Set();
for (const mod of manifest.mods) {
  if (mod.browserModel) files.add(mod.browserModel);
  for (const mat of mod.nprMaterials ?? []) {
    for (const v of Object.values(mat.channels ?? {})) {
      if (typeof v === "string") files.add(v);
    }
  }
}

let copied = 0;
let glbs = 0;
const remap = new Map();
for (const src of files) {
  if (!src.startsWith(SRC_ROOT)) throw new Error(`unexpected path outside ${SRC_ROOT}: ${src}`);
  if (!existsSync(src)) throw new Error(`missing: ${src}`);
  // Slugify the tail: VRF emits names like "t_big hoodie_normalmap.png", and a
  // raw space in an asset URL needs %20 encoding everywhere it is used, which is
  // an easy thing to get wrong later.
  const rel = src.slice(SRC_ROOT.length).split("/").map((seg) => seg.replace(/\s+/g, "_")).join("/");
  const dst = DST_ROOT + rel;
  remap.set(src, dst);
  if (DRY) {
    console.log(`  ${src} -> ${dst}`);
    continue;
  }
  mkdirSync(dirname(dst), { recursive: true });
  if (src.toLowerCase().endsWith(".glb")) {
    const { out, dropped } = stripGlb(readFileSync(src));
    writeFileSync(dst, out);
    glbs++;
    console.log(`  glb ${src} -> ${dst}  (dropped ${dropped.materials} materials, ${dropped.textures} textures, ${dropped.images} images, ${statSync(src).size} -> ${out.length} bytes)`);
  } else {
    copyFileSync(src, dst);
    copied++;
  }
}

if (!DRY) {
  let rewrites = 0;
  for (const mod of manifest.mods) {
    if (mod.browserModel) {
      mod.browserModel = remap.get(mod.browserModel);
      rewrites++;
    }
    for (const mat of mod.nprMaterials ?? []) {
      for (const [role, v] of Object.entries(mat.channels ?? {})) {
        if (typeof v === "string") {
          mat.channels[role] = remap.get(v);
          rewrites++;
        }
      }
    }
  }
  writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2) + "\n");
  console.log(`\ncopied ${copied} textures, stripped ${glbs} GLBs, rewrote ${rewrites} references`);
}
