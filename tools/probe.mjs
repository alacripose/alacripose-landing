// Web UI verification probe — per web-ui-verification skill ladder step 3.
// Headless Edge over CDP; assert LIVE state, drive real interactions.
// Usage: node probe.mjs <url>
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const URL = process.argv[2] || "http://127.0.0.1:8910";
const PORT = 9333;
const edge = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";

const profile = mkdtempSync(join(tmpdir(), "edge-probe-"));
const child = spawn(edge, [
  "--headless=new", "--no-first-run", "--disable-extensions", "--window-size=1400,3000",
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, URL,
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
        // readiness ping with reconnect: the first socket can die mid-nav
        const ping = await raw("1+1");
        if (ping && ping.result && ping.result.result && ping.result.result.value === 2) return;
        ws.close();
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
      params: { expression, returnByValue: true } }));
  });
}
async function val(expression) {
  const r = await raw(expression);
  const res = r && r.result;
  if (res && res.exceptionDetails) throw new Error(JSON.stringify(res.exceptionDetails).slice(0, 200));
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
  await sleep(1500); // let scripts wire

  // ── render ──
  check("title", String(await val("document.title")).includes("alacripose"));
  const h1 = String(await val("document.querySelector('h1').textContent"));
  check("h1 name spelled CRIPOSE", h1 === "ALACRIPOSE", h1);
  const c = JSON.parse(await val(`JSON.stringify({
    pub: document.querySelectorAll('#pubgrid .mod-card').length,
    drive: document.querySelectorAll('#drivegrid .mod-card').length,
    nsfw: document.querySelectorAll('#nsfwgrid .mod-card').length,
    imgs: [...document.images].filter(i => i.complete && i.naturalWidth > 0).length,
    imgTotal: document.images.length,
  })`));
  check("published cards render", c.pub >= 27, `pub=${c.pub}`);
  check("drive cards render", c.drive >= 25, `drive=${c.drive}`);
  check("nsfw cards render", c.nsfw === 4, `nsfw=${c.nsfw}`);
  const previewButtons = await val(`document.querySelectorAll('.preview-btn').length`);
  const drivePreviewButtons = await val(`document.querySelectorAll('#drivegrid .preview-btn').length`);
  check("source preview controls render", previewButtons >= 3, `preview buttons=${previewButtons}`);
  check("all Drive cards have preview controls", drivePreviewButtons === c.drive, `drive previews=${drivePreviewButtons}/${c.drive}`);
  await val(`document.querySelector('.preview-btn').click()`);
  await sleep(200);
  const previewState = JSON.parse(await val(`JSON.stringify({hidden: document.getElementById('model-preview').hidden, title: document.getElementById('model-preview-title').textContent, status: document.getElementById('model-preview-status').textContent})`));
  check("source preview fallback opens", !previewState.hidden && /Ava|Mayu|Weiss/.test(previewState.title) && /fallback/.test(previewState.status), JSON.stringify(previewState));
  await val(`document.getElementById('model-preview-close').click()`);
  const okinaControl = await val(`Boolean(document.querySelector('[data-preview-id="okina-matara"]'))`);
  check("Okina preview control renders", okinaControl === true);
  // trigger lazy loads: scroll to bottom in steps
  await val(`(() => { return new Promise(res => { let y = 0; const step = () => { y += 600; window.scrollTo(0, y); if (y < document.body.scrollHeight) setTimeout(step, 120); else res(); }; step(); }); })()`);
  await sleep(1500);
  const imgs2 = await val(`[...document.images].filter(i => i.complete && i.naturalWidth > 0).length`);
  check("images load", imgs2 >= Math.floor(c.imgTotal * 0.85), `${imgs2}/${c.imgTotal}`);

  // ── attribution badges ──
  const badges = JSON.parse(await val(`JSON.stringify({
    collab: document.querySelectorAll('.badge.collab').length,
    commission: document.querySelectorAll('.badge.commission').length,
  })`));
  check("collab badges present", badges.collab >= 3, `collab=${badges.collab}`);
  check("commission badges present", badges.commission >= 2, `commission=${badges.commission}`);

  // ── filters ──
  await val(`document.querySelector('.chip[data-filter="sound"]').click()`);
  let visible = await val(`[...document.querySelectorAll('#pubgrid .mod-card')].filter(x => x.style.display !== 'none').length`);
  check("sound filter narrows", visible < c.pub, `visible=${visible} of ${c.pub}`);
  await val(`document.querySelector('.chip[data-filter="all"]').click()`);
  visible = await val(`[...document.querySelectorAll('#pubgrid .mod-card')].filter(x => x.style.display !== 'none').length`);
  check("all filter restores", visible === c.pub, `visible=${visible}`);

  // ── hover popover ──
  const popShown = String(await val(`(() => {
    const card = document.querySelector('#pubgrid .mod-card');
    card.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
    return document.getElementById('pop').style.display;
  })()`));
  check("popover shows on hover", popShown === "block", `display=${popShown}`);
  const popText = String(await val(`document.getElementById('pop-name').textContent`));
  check("popover has mod name", popText.length > 3, popText);
  await val(`document.body.dispatchEvent(new MouseEvent('mouseover', {bubbles: true, clientX: 5, clientY: 5}))`);
  await sleep(200);

  // ── 18+ gate ──
  const blurredBefore = await val(`document.getElementById('nsfwgrid').classList.contains('blurred')`);
  await val(`document.getElementById('nsfw-ok').click()`);
  await sleep(200);
  const gateAfter = JSON.parse(await val(`JSON.stringify({
    gateHidden: document.getElementById('nsfw-gate').style.display === 'none',
    blurred: document.getElementById('nsfwgrid').classList.contains('blurred'),
  })`));
  check("18+ gate was blurred before", blurredBefore === true);
  check("18+ gate reveals on click", gateAfter.gateHidden && !gateAfter.blurred, JSON.stringify(gateAfter));


  console.log(`\n${PASS.length} passed, ${FAIL.length} failed`);
  child.kill();
  process.exit(FAIL.length ? 1 : 0);
}

main().catch(e => { console.error("PROBE ERROR:", e.message); child.kill(); process.exit(2); });
