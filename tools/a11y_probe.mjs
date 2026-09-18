// Accessibility audit over CDP: axe-core (WCAG 2.2 A/AA) plus checks axe
// cannot make — carousel overlap and control reachability.
// Usage: node tools/a11y_probe.mjs <url> [<url> ...]
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const URLS = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const PORT = 9355;
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const AXE = readFileSync("node_modules/axe-core/axe.min.js", "utf8");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const profile = mkdtempSync(join(tmpdir(), "edge-a11y-"));
const child = spawn(EDGE, [
  "--headless=new", "--no-first-run", "--disable-extensions", "--window-size=1400,1000",
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "about:blank",
], { stdio: "ignore" });

let ws, nextId = 1;
const pending = new Map();
ws = null;
async function connect() {
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json`);
      const targets = await r.json();
      const page = targets.find((t) => t.type === "page" && !t.url.startsWith("chrome-extension"));
      if (page) {
        ws = new WebSocket(page.webSocketDebuggerUrl);
        await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
        ws.onmessage = (e) => {
          const m = JSON.parse(e.data);
          if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
        };
        const pong = await val("1+1");
        if (pong === 2) return;
        ws.close();
      }
    } catch { /* not up yet */ }
    await sleep(500);
  }
  throw new Error("CDP endpoint never came up");
}
function cmd(method, params) {
  return new Promise((resolve) => {
    const id = nextId++;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });
}
async function val(expression) {
  const r = await cmd("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  const res = r && r.result;
  if (res && res.exceptionDetails) return { __error: JSON.stringify(res.exceptionDetails).slice(0, 300) };
  const inner = res && res.result;
  return inner ? inner.value : undefined;
}

const CHECKS = [];
function check(name, cond, detail = "") {
  CHECKS.push({ name, ok: !!cond, detail });
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
}

const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function audit(url) {
  console.log("\n" + "=".repeat(72) + "\n" + url + "\n" + "=".repeat(72));
  await cmd("Page.enable", {});
  await cmd("Page.addScriptToEvaluateOnNewDocument", { source: AXE });
  await cmd("Page.navigate", { url });
  await sleep(4000);

  const raw = await val(`(async () => {
    const res = await axe.run(document, {
      runOnly: { type: "tag", values: ${JSON.stringify(AXE_TAGS)} },
      resultTypes: ["violations"],
    });
    return JSON.stringify(res.violations.map(v => ({
      id: v.id, impact: v.impact, help: v.help, count: v.nodes.length,
      nodes: v.nodes.slice(0, 3).map(n => ({ t: n.target.join(" "), m: (n.failureSummary || "").replace(/\s+/g, " ").slice(0, 200) })),
    })));
  })()`);
  if (raw && raw.__error) { console.log("axe error:", raw.__error); return; }
  const violations = JSON.parse(raw);
  console.log(`\naxe-core: ${violations.length} violation type(s)`);
  for (const v of violations) {
    console.log(`\n  [${v.impact}] ${v.id} — ${v.help}  (${v.count} node(s))`);
    for (const n of v.nodes) console.log(`      ${n.t}\n        ${n.m}`);
  }
}

// ── checks axe cannot make: layout intrusion + control reachability ──
async function layoutChecks() {
  const spill = await val(`(() => {
    const flow = document.getElementById('heroflow');
    const stage = document.getElementById('cf-stage');
    if (!flow || !stage) return JSON.stringify({ skipped: true });
    const f = flow.getBoundingClientRect();
    const text = document.querySelector('.hero-grid > div:first-child');
    const t = text ? text.getBoundingClientRect() : null;
    const cols = [...document.querySelectorAll('.hero-grid > *')].map(e => ({
      tag: e.className || e.tagName, l: Math.round(e.getBoundingClientRect().left), r: Math.round(e.getBoundingClientRect().right) }));

    // getBoundingClientRect ignores ancestor clipping, so intersect every slide
    // with the rect its nearest clipping ancestor actually paints.
    const painted = el => {
      const r = el.getBoundingClientRect();
      let box = { left: 0, top: 0, right: innerWidth, bottom: innerHeight };
      for (let p = el.parentElement; p; p = p.parentElement) {
        const cs = getComputedStyle(p);
        if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') {
          const b = p.getBoundingClientRect();
          box = { left: Math.max(box.left, b.left), top: Math.max(box.top, b.top),
                  right: Math.min(box.right, b.right), bottom: Math.min(box.bottom, b.bottom) };
        }
        if (cs.position === 'fixed') break;
      }
      return { left: Math.max(r.left, box.left), right: Math.min(r.right, box.right),
               top: Math.max(r.top, box.top), bottom: Math.min(r.bottom, box.bottom),
               wanted: { left: r.left, right: r.right } };
    };

    let spillLeft = 0, spillRight = 0, overText = 0, hidden = 0, paintLeft = 0, paintRight = 0;
    const front = stage.querySelector('.cf-slide.front');
    let frontTop = null, frontBottom = null;
    if (front) { const fr = painted(front); frontTop = Math.round(fr.top - f.top); frontBottom = Math.round(fr.bottom - f.bottom); }
    for (const s of stage.querySelectorAll('.cf-slide')) {
      if (s.classList.contains('hidden')) { hidden++; continue; }
      const r = painted(s);
      spillLeft = Math.max(spillLeft, f.left - r.wanted.left);
      spillRight = Math.max(spillRight, r.wanted.right - f.right);
      paintLeft = Math.min(paintLeft, r.left - f.left);
      paintRight = Math.max(paintRight, r.right - f.right);
      if (t && r.left < t.right && r.right > t.left && r.top < t.bottom && r.bottom > t.top) overText++;
    }
    return JSON.stringify({
      overflowX: getComputedStyle(flow).overflowX,
      flow: { l: Math.round(f.left), r: Math.round(f.right), w: Math.round(f.width) },
      cols, spillLeft: Math.round(spillLeft), spillRight: Math.round(spillRight),
      paintLeft: Math.round(paintLeft), paintRight: Math.round(paintRight),
      slidesOverTextColumn: overText, hiddenSlides: hidden, frontTop, frontBottom,
      navInside: [...flow.querySelectorAll('.cf-nav')].every(b => { const r = b.getBoundingClientRect(); return r.left >= f.left - 1 && r.right <= f.right + 1; }),
    });
  })()`);
  const s = typeof spill === "string" ? JSON.parse(spill) : spill;
  if (s.skipped) console.log("(no coverflow on this page)");
  else {
  check("coverflow clips its own overflow", s.overflowX === "hidden" || s.overflowX === "clip", `overflow-x=${s.overflowX}`);
  check("nothing painted outside the coverflow column", s.paintLeft >= -1 && s.paintRight <= 1,
    `painted ${s.paintLeft}..${s.paintRight} (wanted ${-s.spillLeft}..${s.spillRight})`);
  check("no slide overlaps the hero text column", s.slidesOverTextColumn === 0, `overlapping slides=${s.slidesOverTextColumn}`);
  check("front slide is not clipped at the top", s.frontTop === null || s.frontTop >= -1, `front top=${s.frontTop}px`);
  check("front slide fits inside the frame", s.frontBottom === null || s.frontBottom <= 1, `front bottom=${s.frontBottom}px`);
  check("carousel arrows stay inside the frame", s.navInside === true);
  console.log(`      coverflow ${s.flow.w}px  columns: ${s.cols.map(c => `${c.tag}(${c.r - c.l})`).join(", ")}`);
  }

  const ctl = await val(`JSON.stringify({
    pause: Boolean(document.querySelector('[data-cf-toggle]')),
    liveRegion: Boolean(document.querySelector('[data-cf-live]')),
    ariaHiddenFocusable: [...document.querySelectorAll('.cf-slide[aria-hidden="true"] a, .cf-slide[aria-hidden="true"] button')].length,
    newTabHint: [...document.querySelectorAll('a[target="_blank"]')].filter(a => /new (tab|window)/i.test(a.textContent + (a.getAttribute('aria-label') || ''))).length,
    newTabTotal: document.querySelectorAll('a[target="_blank"]').length,
    skipLink: Boolean(document.querySelector('a[href^="#"][class*="skip"], .skip-link, a[href="#main"]')),
    scrollPaddingTop: getComputedStyle(document.documentElement).scrollPaddingTop,
  })`);
  const c = typeof ctl === "string" ? JSON.parse(ctl) : ctl;
  if (!s.skipped) {
    check("carousel has a pause/play control (WCAG 2.2.2)", c.pause, c.pause ? "" : "no [data-cf-toggle] found");
    check("carousel change is announced (WCAG 4.1.3)", c.liveRegion, c.liveRegion ? "" : "no [data-cf-live] found");
    check("hidden slides expose nothing focusable", c.ariaHiddenFocusable === 0, `found ${c.ariaHiddenFocusable}`);
  }
  check("new-tab links are announced", c.newTabTotal === 0 || c.newTabHint > 0, `${c.newTabHint}/${c.newTabTotal}`);
  check("skip link present (WCAG 2.4.1)", c.skipLink, c.skipLink ? "" : "no in-page skip link");
  check("scroll-padding clears the sticky bar (WCAG 2.4.11)", parseFloat(c.scrollPaddingTop) >= 60, `scroll-padding-top=${c.scrollPaddingTop}`);
}

const TABS = process.argv.includes("--tabs");

// Tab panels hide their content until activated, so audit each one in turn.
async function auditTabs() {
  const n = await val(`document.querySelectorAll('.tab[role="tab"]').length`);
  if (!n) return;
  for (let i = 0; i < n; i++) {
    const name = await val(`(() => { const t = document.querySelectorAll('.tab[role="tab"]')[${i}]; t.click(); return t.textContent.trim(); })()`);
    await sleep(700);
    const raw = await val(`(async () => {
      const res = await axe.run(document, {
        runOnly: { type: "tag", values: ${JSON.stringify(AXE_TAGS)} },
        resultTypes: ["violations"],
      });
      return JSON.stringify(res.violations.map(v => ({ id: v.id, impact: v.impact, count: v.nodes.length,
        m: (v.nodes[0] && v.nodes[0].failureSummary || "").replace(/\s+/g, " ").slice(0, 160) })));
    })()`);
    const v = raw && raw.__error ? [{ id: "axe-error", m: raw.__error }] : JSON.parse(raw);
    check(`tab "${name}" has no violations`, v.length === 0, v.map(x => x.id).join(", "));
  }
}

(async () => {
  try {
    await connect();
    for (const url of URLS) {
      await audit(url);
      await layoutChecks();
      if (TABS) await auditTabs();
    }
    const failed = CHECKS.filter((c) => !c.ok);
    console.log(`\n${CHECKS.length - failed.length} passed, ${failed.length} failed`);
    child.kill();
    process.exit(failed.length ? 1 : 0);
  } catch (e) {
    console.error("PROBE ERROR:", e.message);
    child.kill();
    process.exit(2);
  }
})();
