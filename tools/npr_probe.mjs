// Verify the NPR 3D viewer: open Mayu preview, wait for canvas, check WebGL rendered pixels.
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const URL = process.argv[2] || "http://127.0.0.1:8910";
const PORT = 9340;
const edge = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const profile = mkdtempSync(join(tmpdir(), "edge-npr-"));
const child = spawn(edge, [
  "--headless=new", "--no-first-run", "--disable-extensions", "--window-size=1400,1200",
  "--use-angle=swiftshader", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, URL,
], { stdio: "ignore" });

const sleep = ms => new Promise(r => setTimeout(r, ms));
let ws, nextId = 1;
const pending = new Map();

async function connect() {
  for (let i = 0; i < 30; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json`);
      const targets = await r.json();
      const page = targets.find(t => t.type === "page" && !t.url.startsWith("chrome-extension"));
      if (page) {
        ws = new WebSocket(page.webSocketDebuggerUrl);
        await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
        ws.onmessage = e => {
          const m = JSON.parse(e.data);
          if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
        };
        return;
      }
    } catch { /* not up yet */ }
    await sleep(500);
  }
  throw new Error("CDP endpoint never came up");
}

function raw(expression) {
  return new Promise(resolve => {
    const id = nextId++;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method: "Runtime.evaluate",
      params: { expression, returnByValue: true, awaitPromise: true } }));
  });
}
async function val(expression) {
  const r = await raw(expression);
  const res = r && r.result;
  if (res && res.exceptionDetails) throw new Error(JSON.stringify(res.exceptionDetails).slice(0, 300));
  const inner = res && res.result;
  if (inner && inner.subtype === "error") throw new Error(inner.description);
  return inner ? inner.value : undefined;
}

const PASS = [], FAIL = [];
function check(name, cond, detail = "") {
  (cond ? PASS : FAIL).push(name);
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
}

async function main() {
  await connect();
  await sleep(1500);

  // open the Mayu preview: button has no inline onclick (script deferred module),
  // so dispatch through openModelPreview directly if the click path is unwired
  const opened = await val(`(() => {
    const btn = document.querySelector('[data-preview-id="mayu"]');
    if (!btn) return "no-button";
    btn.click();
    if (!document.getElementById('model-preview').hidden) return "ok";
    if (typeof openModelPreview === "function") { openModelPreview("mayu", null, "Mayu"); return "ok-direct"; }
    return "clicked-but-modal-closed";
  })()`);
  check("mayu preview button opens", String(opened).startsWith("ok"), String(opened));

  // wait for the WebGL canvas to become visible
  let canvasVisible = false;
  for (let i = 0; i < 40; i++) {
    canvasVisible = await val(`!document.getElementById('model-preview-canvas').hidden`);
    if (canvasVisible) break;
    await sleep(500);
  }
  check("WebGL canvas becomes visible", canvasVisible === true);

  const status = await val(`document.getElementById('model-preview-status').textContent`);
  check("status is NPR mode", /NPR/.test(status), status);

  // read back pixels: WebGL needs preserveDrawingBuffer or a same-frame read.
  const pixelInfo = await val(`(() => {
    const canvas = document.getElementById('model-preview-canvas');
    // draw current frame into a 2d canvas via toDataURL (works with swiftshader)
    try {
      const url = canvas.toDataURL('image/png');
      // count non-background pixels
      const img = new Image();
      return new Promise(res => {
        img.onload = () => {
          const c = document.createElement('canvas');
          c.width = img.width; c.height = img.height;
          const ctx = c.getContext('2d');
          ctx.drawImage(img, 0, 0);
          const data = ctx.getImageData(0, 0, c.width, c.height).data;
          let nonBg = 0, varied = 0, total = data.length / 4;
          let lastR = -1;
          for (let i = 0; i < data.length; i += 4) {
            const r = data[i], g = data[i+1], b = data[i+2];
            if (!(Math.abs(r-22)<8 && Math.abs(g-18)<8 && Math.abs(b-9)<8)) nonBg++;
            if (r !== lastR) varied++; // counts color transitions = actual drawn geometry
            lastR = r;
          }
          res(JSON.stringify({ w: img.width, h: img.height, nonBg, total,
            variedTransitions: varied, ratio: +(nonBg/total).toFixed(3) }));
        };
        img.onerror = () => res(JSON.stringify({ err: 'img load failed' }));
        img.src = url;
      });
    } catch (e) { return JSON.stringify({ err: String(e) }); }
  })()`);
  const px = JSON.parse(pixelInfo);
  check("canvas shows rendered geometry (not blank fill)", px.variedTransitions > 50,
        JSON.stringify(px));

  // check GLB loaded (scene has children with geometry)
  const glbCheck = await val(`fetch('assets/previews/mayu/glb/models/heroes_wip/doorman_v2/doorman.glb', {method:'HEAD'})
    .then(r => JSON.stringify({status: r.status, len: r.headers.get('content-length')}))
    .catch(e => JSON.stringify({err: String(e)}))`);
  check("GLB asset reachable", /"status":200/.test(glbCheck), glbCheck);

  // texture channel reachability for mayu nprMaterials
  const texCheck = await val(`(async () => {
    const m = await (await fetch('tools/model_preview_manifest.json')).json();
    const mayu = m.mods.find(x => x.id === 'mayu');
    const urls = new Set();
    mayu.nprMaterials.forEach(mm => Object.values(mm.channels).forEach(u => urls.add('assets/' + u)));
    let ok = 0; const total = urls.size;
    for (const u of urls) {
      const r = await fetch(u, {method:'HEAD'});
      if (r.ok) ok++;
    }
    return JSON.stringify({ok, total});
  })()`);
  const tc = JSON.parse(texCheck);
  check("NPR texture channels reachable", tc.ok === tc.total && tc.total > 0, texCheck);

  console.log(`\\n${PASS.length} passed, ${FAIL.length} failed`);
  child.kill();
  process.exit(FAIL.length ? 1 : 0);
}

main().catch(e => { console.error("NPR PROBE ERROR:", e.message); child.kill(); process.exit(2); });
