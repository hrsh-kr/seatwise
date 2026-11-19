"use strict";
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const LV = [{ k: "l0", key: "seats", n: 1 }, { k: "l1", key: "standing", n: 2 }, { k: "l2", key: "crowded", n: 3 }];
const lk = l => (l === null || l === undefined ? "lN" : LV[l].k);
const toMin = tt => { const [h, m] = tt.split(":").map(Number); return h * 60 + m; };
const fromMin = m => { m = ((m % 1440) + 1440) % 1440; return String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0"); };
const sampling = () => (+$("#pf").value / 100).toFixed(4);
const routeName = r => r.replace(/^METRO-/, "").replace(/(UP|DOWN)$/, "");
const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* blocked */ } } };
const dayWord = d => t(d);

/* ---------- map ---------- */
const map = L.map("map", { zoomControl: true, attributionControl: true }).setView([28.63, 77.22], 11);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap contributors", className: "calm" }).addTo(map);
const layer = L.layerGroup().addTo(map);
const COL = ["#4caf7a", "#e8a33d", "#d9534a"], UNK = "#8a97a3", METRO = "#7b61d9";
const dot = cls => L.divIcon({ className: "", html: `<div class="mk ${cls}"></div>`, iconSize: [14, 14], iconAnchor: [7, 7] });
function draw(o, res) {
  layer.clearLayers(); const pts = [];
  const casing = getComputedStyle(document.documentElement).getPropertyValue("--casing").trim() || "#fff";
  L.marker([res.from.lat, res.from.lon], { icon: dot("") }).addTo(layer).bindTooltip(res.from.name);
  L.marker([res.to.lat, res.to.lon], { icon: dot("end") }).addTo(layer).bindTooltip(res.to.name);
  o.legs.forEach(l => {
    if (l.type === "metro") {
      L.polyline(l.path, { color: casing, weight: 11, opacity: 1, lineCap: "round" }).addTo(layer);
      L.polyline(l.path, { color: METRO, weight: 6, opacity: 1, dashArray: "2 10", lineCap: "round" }).addTo(layer);
    } else for (let i = 0; i < l.path.length - 1; i++) {
      const s = l.stretches[i], c = s && s.level !== null && s.level !== undefined ? COL[s.level] : UNK, seg = [l.path[i], l.path[i + 1]];
      L.polyline(seg, { color: casing, weight: 11, opacity: 1, lineCap: "round" }).addTo(layer);
      L.polyline(seg, { color: c, weight: 6, opacity: 1, lineCap: "round" }).addTo(layer);
    }
    pts.push(...l.path);
  });
  pts.push([res.from.lat, res.from.lon], [res.to.lat, res.to.lon]);
  setTimeout(() => { map.invalidateSize(); map.fitBounds(pts, { padding: [36, 36] }); }, 60);
}

/* ---------- words ---------- */
function levelText(c, type, whole) {
  if (c.level !== null && c.level !== undefined) return t(LV[c.level].key);
  if (type === "metro") return t("metro_nm");
  if (whole && /Metro only/.test(c.label || "")) return t("metro_only");
  return t("nodata");
}
function says(c, type) {
  if (type === "metro") return t("s_metro");
  if (c.level === null || c.level === undefined) return /Metro only/.test(c.label || "") ? t("metro_only") : t("s_none");
  const w = c.worst ? t("busiest_from", esc(c.worst.from), esc(c.worst.to)) : "";
  let s = c.level === 0 ? t("s_seat") : c.level === 1 ? t("s_stand", w) : t("s_crowd", w);
  if (c.confidence === "low") s += t("s_low");
  return s;
}
function tagText(g) {
  if (g === "Fastest") return t("tag_fastest");
  if (g === "Most comfortable") return t("tag_comfort");
  if (g === "Uses metro") return t("tag_metro");
  const m = /^Leave (\d+) min later/.exec(g); return m ? t("tag_later", m[1]) : g;
}
function badge(c, type, whole) {
  const n = c.level === null || c.level === undefined ? 0 : LV[c.level].n;
  const bars = [8, 11, 14].map((h, i) => `<i style="height:${h}px" class="${i < n ? "on" : ""}"></i>`).join("");
  return `<span class="badge ${lk(c.level)}"><span class="meter" aria-hidden="true">${bars}</span>${esc(levelText(c, type, whole))}</span>`;
}
function strip(st) {
  const tot = st.reduce((a, s) => a + s.min, 0) || 1;
  return `<div class="strip" role="img" aria-label="${esc(t("day_chart"))}">` + st.map((s, i) =>
    `<b class="${lk(s.level)}" style="flex:${Math.max(s.min, .3) / tot * 100};animation-delay:${reduce ? 0 : Math.min(i * 18, 400)}ms" title="${esc(s.from)} → ${esc(s.to)}${s.load !== undefined ? ": " + Math.round(s.load) : ""}"></b>`).join("") + `</div>`;
}
function confText(c) { return !c || c === "none" ? "" : " · " + t("conf", t(c === "high" ? "hi" : c)); }

/* ---------- through-the-day chart ---------- */
function chart(pr, here) {
  const W = 320, H = 96, n = pr.points.length, bw = W / n;
  const mx = Math.max(0, ...pr.points.map(p => p.load || 0)), cap = Math.max(mx * 1.18, 20);
  const near = pr.points.reduce((b, p, i) => Math.abs(toMin(p.time) - toMin(here)) < Math.abs(toMin(pr.points[b].time) - toMin(here)) ? i : b, 0);
  let bars = "", rows = "";
  pr.points.forEach((p, i) => {
    const k = lk(p.level), h = p.load == null ? 3 : Math.max(4, Math.min(p.load, cap) / cap * (H - 22));
    const fill = { l0: "var(--seat-fill)", l1: "var(--stand-fill)", l2: "var(--crowd-fill)", lN: "var(--unk-fill)" }[k];
    bars += `<rect class="bar" data-time="${p.time}" x="${(i * bw + 1).toFixed(1)}" y="${(H - 14 - h).toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${h.toFixed(1)}" rx="2" fill="${fill}" opacity="${p.confidence === 0 ? .45 : 1}" style="animation-delay:${reduce ? 0 : i * 14}ms"><title>${p.time}${p.load != null ? ": " + p.load : ""}</title></rect>`;
    if (i % 2 === 0) rows += `<tr><td>${p.time}</td><td>${p.load == null ? "–" : p.load}</td><td>${p.level == null ? "–" : esc(t(LV[p.level].key))}</td></tr>`;
  });
  const showSeats = pr.seats <= cap, seatY = H - 14 - pr.seats / cap * (H - 22), px = near * bw + bw / 2;
  let ticks = "";
  [6, 9, 12, 15, 18, 21].forEach(hh => { const i = pr.points.findIndex(p => toMin(p.time) >= hh * 60); if (i >= 0) ticks += `<text x="${(i * bw).toFixed(0)}" y="${H - 2}" font-size="9" class="ax">${String(hh).padStart(2, "0")}</text>`; });
  return `<figure class="chart" style="margin:12px 0 0"><h4>${esc(t("day_chart"))}</h4>
   <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t("day_chart"))}">
    ${showSeats ? `<line x1="0" x2="${W}" y1="${seatY.toFixed(1)}" y2="${seatY.toFixed(1)}" class="gl" stroke-dasharray="3 3" stroke-width="1"/><text x="${W - 2}" y="${(seatY - 3).toFixed(1)}" font-size="9" class="ax" text-anchor="end">${esc(t("all_seats"))}</text>` : ""}
    ${bars}${ticks}
    <line x1="${px.toFixed(1)}" x2="${px.toFixed(1)}" y1="10" y2="${H - 14}" class="you" stroke-width="1" stroke-dasharray="2 2"/>
    <text x="${px.toFixed(1)}" y="8" font-size="9" class="you" font-weight="700" text-anchor="middle">${esc(t("you"))}</text>
   </svg>
   <div class="legend"><span><i style="background:var(--seat-fill)"></i>${esc(t("seats"))}</span><span><i style="background:var(--stand-fill)"></i>${esc(t("standing"))}</span><span><i style="background:var(--crowd-fill)"></i>${esc(t("crowded"))}</span><span>${esc(t("legend_faded"))}</span></div>
   <div class="cap">${esc(t("chart_cap", here))} ${showSeats ? "" : esc(t("chart_seats_note", pr.seats))}</div>
   <details class="vals"><summary>${esc(t("show_values"))}</summary><table><tbody>${rows}</tbody></table></details></figure>`;
}

/* ---------- results ---------- */
let results = [], current = null, selected = 0, prio = "balanced", lastQuery = null;
function animateNum(el, to) {
  setTimeout(() => { el.firstChild.nodeValue = to; }, 800);      // always end on the true value, even if frames are throttled
  if (reduce) { el.firstChild.nodeValue = to; return; }
  const t0 = performance.now();
  (function f(now) { const k = Math.min(1, (now - t0) / 600), e = 1 - Math.pow(1 - k, 3); el.firstChild.nodeValue = Math.round(to * e); if (k < 1) requestAnimationFrame(f); })(t0);
}
function sensLine(o) {
  const ks = Object.keys(o.sensitivity || {}); if (!ks.length || ks.every(k => o.sensitivity[k] === null)) return "";
  const parts = ks.map(k => t("sens_at", (+k * 100).toFixed(1).replace(".0", "") + "%", o.sensitivity[k] === null ? "–" : t(LV[o.sensitivity[k]].key)));
  return `<p class="meta sens"><span>${esc(t("sens"))}:</span> ${parts.map(esc).join(" · ")}</p>`;
}
function card(o, i, res) {
  const tags = o.tags.map(g => `<span class="pill tag">${esc(tagText(g))}</span>`).join("");
  const chg = o.transfers === 0 ? t("direct") : o.transfers === 1 ? t("change", 1) : t("changes", o.transfers);
  const legs = o.legs.map((l, li) => `
    <div class="leg ${lk(l.crowding.level)} ${l.type === "metro" ? "metroleg" : ""}">
      <h3><span class="routechip ${l.type}">${l.type === "metro" ? esc(l.line || "Metro") : esc(routeName(l.route))}</span> ${l.board_time} → ${l.alight_time}</h3>
      <div class="stops"><b>${esc(l.board)}</b> → <b>${esc(l.alight)}</b></div>
      <div class="sub">${esc(t("ride", l.ride_min, l.stops))}</div>
      ${l.type === "bus" ? strip(l.stretches) : ""}
      <div>${badge(l.crowding, l.type)}</div>
      <div class="sub" style="margin-top:6px">${says(l.crowding, l.type)}</div>
      ${l.type === "bus" ? `<button type="button" class="linkbtn why" data-i="${i}" data-l="${li}">${esc(t("why"))}</button><div class="whybox" hidden></div><div class="profile" data-i="${i}" data-l="${li}"></div>` : ""}
    </div>${li < o.legs.length - 1 ? `<div class="walk">${esc(t("changeat", l.alight))}</div>` : ""}`).join("");
  const sel = i === selected;
  return `<article class="opt ${lk(o.crowding.level)}" data-i="${i}" aria-expanded="${sel}" tabindex="0">
    <div class="hero">
      <div class="top"><div class="pills">${tags || `<span class="pill">${esc(t("option"))}</span>`}</div><span class="times">${o.leave_at} → ${o.arrive_at}</span></div>
      <div class="big"><span class="num" data-to="${o.duration_min}">0<small>${esc(t("min"))}</small></span>${badge(o.crowding, "bus", true)}</div>
      <p class="says">${says(o.crowding, o.has_metro && !o.legs.some(l => l.type === "bus") ? "metro" : "bus")}</p>
      <p class="meta">${esc(t("walk"))} ${o.walk_min} ${esc(t("min"))} · ${esc(t("wait"))} ${o.wait_min} ${esc(t("min"))} · ${esc(chg)}</p>
      <p class="meta"><span class="pill src">${esc(t("modelled"))} · ${esc(t("basis", res.basis.split(" ")[0], t(res.daytype).toLocaleLowerCase()))}${esc(confText(o.crowding.confidence))}</span></p>
      ${sensLine(o)}
    </div>
    <div class="body">${legs}</div></article>`;
}
function skeleton() { return `<div class="skel" aria-hidden="true"><i></i><i></i><i></i></div><p class="hint" role="status">${esc(t("loading"))}</p>`; }
function errorBox(msg) { return `<div class="err" role="alert"><p>${esc(msg)}</p><button type="button" class="chip" id="retry">${esc(t("retry"))}</button></div>`; }
function renderResults(j) {
  const out = $("#out"); results = j.options; current = j;
  if (!results.length) {
    const n = j.note || "", msg = /within a few minutes/.test(n) ? t("same_place") : /No bus stops/.test(n) ? t("no_stops") : t("nojourney");
    out.innerHTML = `<div class="hint" role="status">${esc(msg)}</div>`; $("#win").innerHTML = ""; return;
  }
  out.innerHTML = `<div class="rowbar"><span class="muted">${esc(j.from.name)} → ${esc(j.to.name)}</span><button type="button" class="chip" id="share">${esc(t("copy"))}</button></div>` + results.map((o, i) => card(o, i, j)).join("");
  $$(".opt", out).forEach(a => {
    const pick = () => { selected = +a.dataset.i; $$(".opt", out).forEach(x => x.setAttribute("aria-expanded", x === a)); fill(a); draw(results[selected], j); };
    a.onclick = e => { if (e.target.closest("rect.bar,button,summary")) return; pick(); };
    a.onkeydown = e => { if (e.key === "Enter" && e.target === a) pick(); };
  });
  $$("button.why", out).forEach(b => b.onclick = e => { e.stopPropagation(); whyPanel(b); });
  $("#share").onclick = copyLink;
  selected = 0; fill($(".opt", out)); draw(results[0], j);
  $$(".num", out).forEach(n => animateNum(n, +n.dataset.to));
  $("#win").innerHTML = `<div class="card winbox"><h3>${esc(t("win_title"))}</h3><button type="button" class="chip" id="winbtn">${esc(t("win_btn"))}</button><div id="wincontent"></div></div>`;
  $("#winbtn").onclick = loadWindow;
}
async function fill(a) {
  const o = results[+a.dataset.i];
  for (const slot of $$(".profile", a)) {
    if (slot.dataset.done) continue; slot.dataset.done = 1;
    const l = o.legs[+slot.dataset.l];
    try {
      const r = await fetch(`/routes/${encodeURIComponent(l.route)}/profile?board=${l.board_idx}&alight=${l.alight_idx}&daytype=${current.daytype}&p=${sampling()}`);
      if (!r.ok) continue; const pr = await r.json();
      slot.innerHTML = chart(pr, l.board_time);
      $$("rect.bar", slot).forEach(b => b.onclick = ev => { ev.stopPropagation();
        const delta = toMin(l.board_time) - toMin(o.leave_at), leave = fromMin(Math.round((toMin(b.dataset.time) - delta) / 5) * 5);      // snap to 5 minutes
        $("#when").value = `${$("#when").value.slice(0, 10)}T${leave}`; go(); });
    } catch (e) { /* chart is optional */ }
  }
}
async function whyPanel(btn) {
  const box = btn.nextElementSibling;
  if (!box.hidden) { box.hidden = true; return; }
  box.hidden = false; box.innerHTML = `<span class="muted">${esc(t("why_loading"))}</span>`;
  const l = results[+btn.dataset.i].legs[+btn.dataset.l];
  try {
    const r = await fetch(`/routes/${encodeURIComponent(l.route)}/why?board=${l.board_idx}&alight=${l.alight_idx}&time=${l.board_time}&daytype=${current.daytype}&p=${sampling()}`);
    const w = await r.json();
    if (!w.available) { box.innerHTML = `<p>${esc(t("why_none"))}</p>`; return; }
    const a = w.assumptions, e = w.evidence, es = w.estimate;
    box.innerHTML = `<ul>
      <li>${esc(t("why_load", es.load_p50, es.load_90pct_interval[0], es.load_90pct_interval[1], Math.round(es.p_crowded * 100)))}</li>
      <li>${esc(t("why_tix", e.approx_tickets_behind_it))}</li>
      <li>${esc(t("why_trips", e.bus_trips_per_day_in_band, e.days))}</li>
      <li>${esc(t("why_samp", e.sampled_passengers_per_bus))}</li>
      <li>${esc(t("why_share", (a.assumed_ticket_share * 100).toFixed(1) + "%"))}${a.capacity_floor_applied ? " (" + esc(t("why_floor", (a.share_used * 100).toFixed(1) + "%")) + ")" : ""}</li>
      <li class="muted">${esc(t("why_formula"))}</li></ul>`;
  } catch (e) { box.innerHTML = `<p>${esc(t("offline"))}</p>`; }
}
async function loadWindow() {
  const c = $("#wincontent"); c.innerHTML = `<p class="muted">${esc(t("win_loading"))}</p>`;
  const [d, tm] = $("#when").value.split("T"), m0 = toMin(tm);
  const q = new URLSearchParams({ from: $("#from").value, to: $("#to").value, date: d, start: fromMin(Math.max(300, Math.round((m0 - 30) / 5) * 5)), end: fromMin(Math.min(1380, Math.round((m0 + 150) / 5) * 5)), step: 30, priority: prio, p: sampling(), metro: $("#metro").checked });
  try {
    const r = await fetch("/journeys/window?" + q), j = await r.json();
    if (!r.ok || !j.options.length) { c.innerHTML = `<p class="muted">${esc(t("nojourney"))}</p>`; return; }
    const mx = Math.max(...j.options.map(o => o.duration_min)), H = 70, W = 320, bw = W / j.options.length;
    c.innerHTML = `<p class="winbest">${esc(t("win_best", j.best_leave))}</p><svg viewBox="0 -14 ${W} ${H + 32}" role="img" aria-label="${esc(t("win_title"))}">` + j.options.map((o, i) => {
      const h = Math.max(8, o.duration_min / mx * H), f = { 0: "var(--seat-fill)", 1: "var(--stand-fill)", 2: "var(--crowd-fill)" }[o.level] || "var(--unk-fill)", best = o.leave === j.best_leave;
      return `<g class="wbar" data-t="${o.leave}" tabindex="0" role="button" aria-label="${o.leave}, ${o.duration_min} ${esc(t("min"))}, ${esc(o.level === null ? t("nodata") : t(LV[o.level].key))}"><rect x="${(i * bw + 4).toFixed(1)}" y="${(H - h).toFixed(1)}" width="${(bw - 8).toFixed(1)}" height="${h.toFixed(1)}" rx="4" fill="${f}" ${best ? 'stroke="var(--ink)" stroke-width="2"' : ""}/><text x="${(i * bw + bw / 2).toFixed(1)}" y="${H + 12}" font-size="10" text-anchor="middle" class="ax">${o.leave}</text><text x="${(i * bw + bw / 2).toFixed(1)}" y="${(H - h - 3).toFixed(1)}" font-size="10" text-anchor="middle" class="you" font-weight="700">${o.duration_min}</text></g>`;
    }).join("") + `</svg><p class="cap">${esc(t("win_cap"))}</p>`;
    $$(".wbar", c).forEach(g => { const f = () => { $("#when").value = `${d}T${g.dataset.t}`; go(); }; g.onclick = f; g.onkeydown = e => { if (e.key === "Enter") f(); }; });
  } catch (e) { c.innerHTML = errorBox(t("offline")); }
}
async function go() {
  const out = $("#out"); out.innerHTML = skeleton(); $("#win").innerHTML = "";
  lastQuery = { from: $("#from").value, to: $("#to").value, depart: $("#when").value, priority: prio, p: sampling(), metro: $("#metro").checked };
  const q = new URLSearchParams(lastQuery);
  try {
    const r = await fetch("/journeys?" + q), j = await r.json();
    if (!r.ok) { out.innerHTML = errorBox(/unknown place/i.test(j.detail || "") ? t("unknown_place") : (j.detail || t("nojourney"))); $("#retry").onclick = go; return; }
    renderResults(j); writeHash(); collapseForm(true); out.focus({ preventScroll: true });
  } catch (e) { out.innerHTML = errorBox(t("offline")); $("#retry").onclick = go; }
}

/* ---------- form, examples, links ---------- */
function collapseForm(on) {
  const f = $("#form"); f.dataset.state = on ? "done" : "open";
  if (on) $("#sum").innerHTML = `<div><b>${esc($("#from").value)}</b> → <b>${esc($("#to").value)}</b><span>${esc($("#when").value.replace("T", " "))} · ${esc(t(prio === "fastest" ? "p_fast" : prio === "comfortable" ? "p_comf" : "p_bal"))}</span></div><button type="button" class="chip" id="edit">${esc(t("edit"))}</button>`;
  const e = $("#edit"); if (e) e.onclick = () => collapseForm(false);
}
function writeHash() {
  const h = new URLSearchParams({ v: document.body.dataset.view, from: $("#from").value, to: $("#to").value, t: $("#when").value, prio, p: sampling(), metro: $("#metro").checked ? 1 : 0 });
  history.replaceState(null, "", "#" + h);
}
function copyLink() {
  const done = () => { const b = $("#share"); if (b) { b.textContent = t("copied"); setTimeout(() => { b.textContent = t("copy"); }, 1800); } };
  if (navigator.clipboard) navigator.clipboard.writeText(location.href).then(done, done); else done();
}
const EXAMPLES = [["ex1", "Anand Vihar Isbt", "Connaught Place", "2026-10-20T18:30"], ["ex2", "Kashmere Gate Isbt", "Nehru Place", "2026-10-20T08:30"],
  ["ex3", "Dwarka Sector 21", "Connaught Place", "2026-10-20T09:00"], ["ex4", "Saket Metro Station", "Lajpat Nagar Crossing", "2026-10-25T12:00"]];
function renderExamples() {
  $("#exchips").innerHTML = EXAMPLES.map((e, i) => `<button type="button" class="chip" data-ex="${i}">${esc(t(e[0]))}</button>`).join("");
  $$("#exchips .chip").forEach(b => b.onclick = () => { const e = EXAMPLES[+b.dataset.ex]; $("#from").value = e[1]; $("#to").value = e[2]; $("#when").value = e[3]; collapseForm(false); go(); });
}
function readHash() {
  const h = new URLSearchParams(location.hash.slice(1)); if (!h.get("from") || !h.get("to")) return false;
  $("#from").value = h.get("from"); $("#to").value = h.get("to"); if (h.get("t")) $("#when").value = h.get("t");
  if (h.get("prio")) { prio = h.get("prio"); $$("#prio button").forEach(x => x.setAttribute("aria-pressed", x.dataset.v === prio)); }
  if (h.get("p")) { $("#pf").value = (+h.get("p") * 100); $("#pfv").textContent = (+$("#pf").value).toFixed(1) + "%"; }
  $("#metro").checked = h.get("metro") === "1"; if (h.get("v") && h.get("v") !== "plan") view(h.get("v")); return true;
}
$("#form").onsubmit = e => { e.preventDefault(); go(); };
$$("#prio button").forEach(b => b.onclick = () => { prio = b.dataset.v; $$("#prio button").forEach(x => x.setAttribute("aria-pressed", x === b)); if (results.length) go(); });
$("#swap").onclick = () => { const a = $("#from").value; $("#from").value = $("#to").value; $("#to").value = a; if (results.length) go(); };
$("#metro").onchange = () => { if (results.length) go(); };
$$(".chip[data-t]").forEach(c => c.onclick = () => { $("#when").value = $("#when").value.slice(0, 10) + "T" + c.dataset.t; $$(".chip[data-t]").forEach(x => x.setAttribute("aria-pressed", x === c)); if (results.length) go(); });
$("#pf").oninput = () => { $("#pfv").textContent = (+$("#pf").value).toFixed(1) + "%"; };
$("#pf").onchange = () => { if (results.length) go(); if (document.body.dataset.view === "ops") loadOps(); };
let tmr; ["from", "to"].forEach(id => $("#" + id).addEventListener("input", e => { clearTimeout(tmr); const v = e.target.value; if (v.length < 3) return;
  tmr = setTimeout(async () => { try { const r = await fetch("/stops?q=" + encodeURIComponent(v)); if (r.ok) $("#stopsList").innerHTML = (await r.json()).map(s => `<option value="${esc(s.name)}">`).join(""); } catch (e) { /* autocomplete is optional */ } }, 200); }));

/* ---------- navigation ---------- */
function view(v) {
  document.body.dataset.view = v;
  $$("nav.tabs button").forEach(b => b.setAttribute("aria-current", b.dataset.go === v ? "page" : "false"));
  setTimeout(() => map.invalidateSize(), 80);
  if (v === "ops") loadOps(); if (v === "about") loadAbout();
  $("#main").scrollTop = 0;
}
$$("nav.tabs button").forEach(b => b.onclick = () => view(b.dataset.go));

/* ---------- operators ---------- */
let odt = "weekday";
$$("#odt button").forEach(b => b.onclick = () => { odt = b.dataset.v; $$("#odt button").forEach(x => x.setAttribute("aria-pressed", x === b)); loadOps(); });
$("#otime").onchange = () => loadRank();
async function loadOps() {
  const h = $("#heat"); h.innerHTML = `<div class="hint">${esc(t("loading_ops"))}</div>`;
  try {
    const r = await fetch(`/operators/heatmap?daytype=${odt}&top=22&p=${sampling()}`), j = await r.json();
    const hdr = j.bands.map((b, i) => `<th scope="col">${i % 4 === 0 ? b.slice(0, 2) : ""}</th>`).join("");
    const rows = j.rows.map(row => `<tr><td class="r"><b>${esc(routeName(row.route))} <small>${row.route.endsWith("UP") ? "up" : "down"}</small></b><span>${esc(row.from)} → ${esc(row.to)}</span></td>` +
      row.cells.map((v, i) => { const l = v === null ? "lN" : v <= .47 ? "l0" : v <= .8 ? "l1" : "l2"; return `<td class="c ${l}${v !== null && v >= 1 ? " hi" : ""}" role="button" data-r="${esc(row.route)}" data-t="${j.bands[i]}" data-v="${v === null ? "" : v}" tabindex="0" aria-label="${esc(routeName(row.route))} ${j.bands[i]}: ${v === null ? esc(t("hm_none")) : Math.round(v * 100) + "%"}"></td>`; }).join("") + "</tr>").join("");
    h.innerHTML = `<table><thead><tr><th class="r"></th>${hdr}</tr></thead><tbody>${rows}</tbody></table>
      <div class="legend" style="padding:8px 4px 2px"><span><i class="hz hz0"></i>${esc(t("hm_seats"))}</span><span><i class="hz hz1"></i>${esc(t("hm_stand"))}</span><span><i class="hz hz2"></i>${esc(t("hm_crowd"))}</span><span><i class="hz hz3"></i>${esc(t("hm_full"))}</span><span><i class="hz hzn"></i>${esc(t("hm_none"))}</span></div>`;
    $$("td.c", h).forEach(c => { const f = () => { $$("td.c.sel", h).forEach(x => x.classList.remove("sel")); c.classList.add("sel");
        const v = c.dataset.v; $("#opsd").innerHTML = v === "" ? esc(t("ops_nodata", routeName(c.dataset.r), c.dataset.t)) : esc(t("ops_cell", routeName(c.dataset.r), c.dataset.t, Math.round(v * 100))); };
      c.onclick = f; c.onkeydown = e => { if (e.key === "Enter") f(); }; });
  } catch (e) { h.innerHTML = errorBox(t("offline")); $("#retry").onclick = loadOps; }
  loadRank();
}
async function loadRank() {
  const tm = $("#otime").value || "18:00"; $("#rankh").textContent = t("rank_h", tm); $("#extrah").textContent = t("extra_h", tm);
  try {
    const [a, b] = await Promise.all([fetch(`/operators/overloaded?daytype=${odt}&time=${tm}&top=12&p=${sampling()}`).then(r => r.json()),
      fetch(`/operators/extra-bus?daytype=${odt}&time=${tm}&top=10&p=${sampling()}`).then(r => r.json())]);
    $("#rank").innerHTML = a.rows.map(x => { const k = Math.min(1, x.load_over_crush / 1.5);
      return `<li class="card"><b>${esc(routeName(x.route))} ${x.route.endsWith("UP") ? "up" : "down"}</b><span>${esc(x.from)} → ${esc(x.to)}</span>
        <span class="sub">${esc(t("on_board", x.load_p50, x.load_90pct_interval[0], x.load_90pct_interval[1], Math.round(x.p_crowded * 100)))}</span>
        <div class="bar2"><i style="width:${k * 100}%;background:${k > .66 ? "var(--crowd-fill)" : k > .4 ? "var(--stand-fill)" : "var(--seat-fill)"}"></i></div></li>`; }).join("");
    $("#extra").innerHTML = b.rows.map(x => `<li class="card"><b>${esc(routeName(x.route))} ${x.route.endsWith("UP") ? "up" : "down"} <em class="relief">${esc(t("extra_relief", x.relief_per_extra_trip.toLocaleString()))}</em></b>
        <span class="sub">${esc(t("extra_row", x.trips_in_band_per_day, x.crowded_stretches, x.busiest))}</span></li>`).join("");
  } catch (e) { /* lists are optional */ }
}

/* ---------- about ---------- */
let aboutLoaded = false;
async function loadAbout() {
  if (aboutLoaded) return; aboutLoaded = true;
  try {
    const v = await (await fetch("/validation")).json(), hz = await (await fetch("/health")).json();
    const w = v.heldout_by_phi && v.heldout_by_phi["2.0"], pk = v.city_average_load_per_bus_stretch || {}, we = v.weekend_vs_weekday_ratio || {};
    const S = [[w ? Math.round(w.coverage_80pct_interval * 1000) / 10 + "%" : "–", "st_cov"], [pk.weekday_am_peak || "–", "st_am"], [pk.weekday_pm_peak || "–", "st_pm"],
      [we.sunday ? we.sunday + "×" : "–", "st_sun"], ["2.56M", "st_tix"], [hz.route_daytypes_modelled ? hz.route_daytypes_modelled.toLocaleString() : "–", "st_models"]];
    $("#stats").innerHTML = S.map(s => `<div class="card stat"><b>${esc(s[0])}</b><span data-i18n="${s[1]}">${esc(t(s[1]))}</span></div>`).join("");
  } catch (e) { /* stats are optional */ }
}

/* ---------- language and theme ---------- */
function applyLang() {
  document.documentElement.lang = LANG;
  $$("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
  $$("[data-i18n-html]").forEach(el => { el.innerHTML = t(el.dataset.i18nHtml); });
  $("#langtxt").textContent = t("lang_btn"); $("#lang").setAttribute("aria-label", LANG === "hi" ? "Switch to English" : "हिन्दी में बदलें");
  $("#swap").setAttribute("aria-label", t("swap"));
  const dk = document.documentElement.dataset.theme === "dark"; $("#theme").setAttribute("aria-label", t(dk ? "theme_light" : "theme_dark"));
  renderExamples();
  if ($("#form").dataset.state === "done") collapseForm(true);
  if (current && results.length) renderResults(current);
  if (document.body.dataset.view === "ops") loadOps();
  if (aboutLoaded) { aboutLoaded = false; loadAbout(); }
}
$("#lang").onclick = () => { LANG = LANG === "hi" ? "en" : "hi"; store.set("seatwise-lang", LANG); applyLang(); };
const root = document.documentElement;
function setTheme(tm, save) {
  root.dataset.theme = tm;
  const b = $("#theme"); if (b) { b.setAttribute("aria-label", t(tm === "dark" ? "theme_light" : "theme_dark")); b.setAttribute("aria-pressed", tm === "dark"); }
  document.querySelector("meta[name=theme-color]").setAttribute("content", tm === "dark" ? "#0f161c" : "#f4f7fb");
  if (save) store.set("seatwise-theme", tm);
  if (current && results.length) draw(results[selected], current);
}
$("#theme").onclick = () => setTheme(root.dataset.theme === "dark" ? "light" : "dark", true);

/* ---------- start ---------- */
LANG = store.get("seatwise-lang") === "hi" ? "hi" : "en";
setTheme(root.dataset.theme || "light", false);
applyLang();
if (readHash()) go();
