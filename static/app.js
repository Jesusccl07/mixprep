"use strict";
const $ = (s, r = document) => r.querySelector(s);
const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtT = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const app = $("#app");
let teardown = null;

async function api(path, opt = {}) {
  const r = await fetch("/api" + path, {
    ...opt,
    headers: opt.body && !(opt.body instanceof FormData) ? { "Content-Type": "application/json" } : undefined,
    body: opt.body && !(opt.body instanceof FormData) ? JSON.stringify(opt.body) : opt.body,
  });
  if (!r.ok) {
    let m = `${r.status}`;
    try { const j = await r.json(); m = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
    throw new Error(m);
  }
  return r.json();
}
let toastT;
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => (t.hidden = true), 3200);
}
async function waitJob(id, onProg) {
  for (;;) {
    const j = await api(`/jobs/${id}`);
    onProg?.(j);
    if (j.status === "done" || j.status === "failed") return j;
    await new Promise((r) => setTimeout(r, 700));
  }
}

/* ============================================================ router */
function route() {
  teardown?.(); teardown = null;
  const m = location.hash.match(/^#\/p\/([\w-]+)/);
  m ? studio(m[1]) : library();
}
addEventListener("hashchange", route);
api("/capabilities").then((c) => {
  $("#cap").textContent = c.separation === "ai"
    ? `Separación con IA · ${c.gpu ? "GPU" : "CPU (más lento)"}`
    : "Separación básica sin IA — instala demucs para mejor calidad";
}).catch(() => {});

/* ============================================================ biblioteca */
async function library() {
  app.innerHTML = `
    <div class="grid2">
      <div>
        <h1>Tu canción,<br><span style="color:var(--accent)">lista para pinchar.</span></h1>
        <p class="lead">Sube una canción y llévate la versión que necesitas: LiveMashup, Extended, acapella o instrumental. Cuadrada a la rejilla, con el BPM y la tonalidad en el nombre del archivo.</p>
        <div class="row" style="margin-bottom:12px">
          <button class="btn sm on" id="m-mix">Canción completa</button>
          <button class="btn sm" id="m-stems">Voz + instrumental ya separadas</button>
        </div>
        <div id="dz"></div>
        <div id="up"></div>
      </div>
      <div class="panel">
        <h2>Una canción, todas las versiones</h2>
        <div class="steps" style="margin:0;padding:0;border:0;grid-template-columns:1fr 1fr">
          <div><div class="n">LiveMashup</div><p>8 compases de melodía, la voz entra en el compás 9 y acapella limpia desde el estribillo.</p></div>
          <div><div class="n">Extended</div><p>Intro de 8 compases con batería que cambia cada 4, la canción entera y final original, acapella u outro.</p></div>
          <div><div class="n">Acapella</div><p>Solo la voz, separada con IA, MP3 320.</p></div>
          <div><div class="n">Instrumental</div><p>La canción sin voz, a la misma calidad.</p></div>
        </div>
      </div>
    </div>
    <h2 style="margin-top:34px">Biblioteca</h2>
    <div id="lib" class="panel" style="padding:6px 8px"></div>
    <div class="steps">
      <div><div class="n">01</div><h3>Sube la canción</h3><p>FLAC, WAV, MP3, M4A, OGG o AIFF. Separamos voz e instrumental.</p></div>
      <div><div class="n">02</div><h3>La analizamos</h3><p>BPM, rejilla de beats, compás 1, tonalidad Camelot y estructura.</p></div>
      <div><div class="n">03</div><h3>Pinchas</h3><p>MP3 320 con BPM y tonalidad en el nombre y en las etiquetas.</p></div>
    </div>`;
  let mode = "mix", files = {};
  const dz = $("#dz");
  const drawDz = () => {
    const fileLine = (k, label) => `<div class="drop" data-k="${k}"><strong>${files[k] ? esc(files[k].name) : label}</strong><span>${files[k] ? "Haz clic para cambiar" : "Arrastra o haz clic"}</span></div>`;
    dz.innerHTML = mode === "mix"
      ? fileLine("mix", "Arrastra una canción aquí")
      : `<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">${fileLine("vocals", "Voz")}${fileLine("instrumental", "Instrumental")}</div>
         <div class="row" style="margin-top:12px"><button class="btn primary" id="go" ${files.vocals && files.instrumental ? "" : "disabled"}>Procesar</button></div>`;
    dz.querySelectorAll(".drop").forEach((d) => {
      const k = d.dataset.k;
      const pick = (f) => {
        if (!f) return;
        files[k] = f;
        if (mode === "mix") startUpload(); else drawDz();
      };
      d.onclick = () => { const i = el('<input type="file" accept="audio/*,.flac,.aif,.aiff">'); i.onchange = () => pick(i.files[0]); i.click(); };
      d.ondragover = (e) => { e.preventDefault(); d.classList.add("over"); };
      d.ondragleave = () => d.classList.remove("over");
      d.ondrop = (e) => { e.preventDefault(); d.classList.remove("over"); pick(e.dataTransfer.files[0]); };
    });
    $("#go") && ($("#go").onclick = startUpload);
  };
  const setMode = (m) => { mode = m; files = {}; $("#m-mix").classList.toggle("on", m === "mix"); $("#m-stems").classList.toggle("on", m === "stems"); drawDz(); };
  $("#m-mix").onclick = () => setMode("mix");
  $("#m-stems").onclick = () => setMode("stems");

  function startUpload() {
    const fd = new FormData();
    if (mode === "mix") fd.append("file", files.mix); else { fd.append("vocals", files.vocals); fd.append("instrumental", files.instrumental); }
    const up = $("#up");
    up.innerHTML = `<div class="panel" style="margin-top:12px"><div id="st">Subiendo…</div><div class="progress"><i id="bar" style="width:0"></i></div><div class="faint" id="sub"></div></div>`;
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/projects");
    xhr.upload.onprogress = (e) => e.lengthComputable && ($("#bar").style.width = `${(e.loaded / e.total) * 30}%`);
    xhr.onload = async () => {
      if (xhr.status >= 300) { let m = "No se ha podido subir"; try { m = JSON.parse(xhr.responseText).detail; } catch {} up.innerHTML = `<p class="err">${esc(m)}</p>`; return; }
      const r = JSON.parse(xhr.responseText);
      const j = await waitJob(r.job.id, (j) => { $("#st").textContent = j.stage; $("#bar").style.width = `${30 + j.progress * 70}%`; });
      if (j.status === "failed") { up.innerHTML = `<p class="err">Error: ${esc(j.error)}</p>`; return; }
      location.hash = `#/p/${r.project.id}`;
    };
    xhr.onerror = () => (up.innerHTML = `<p class="err">Error de red</p>`);
    xhr.send(fd);
  }
  drawDz();

  async function drawLib() {
    const list = await api("/projects");
    const lib = $("#lib");
    if (!lib) return;
    if (!list.length) { lib.innerHTML = `<p class="muted" style="padding:20px;text-align:center">Todavía no hay pistas. Sube tu primera canción y aparecerá aquí con su BPM y su tonalidad.</p>`; return; }
    lib.innerHTML = `<table class="lib"><thead><tr><th>Pista</th><th>BPM</th><th>Tono</th><th>Dur.</th><th>Estado</th><th></th></tr></thead><tbody>${list.map((p) => `
      <tr class="item" data-id="${p.id}"><td><b>${esc(p.track || p.title)}</b><div class="faint" style="font-size:12.5px">${esc(p.artist)}</div></td>
      <td class="num">${p.bpm ?? "—"}</td><td class="num">${p.camelot ? `<span>${p.camelot}</span> <span class="faint">${esc((p.key || "").replace(" min", "m").replace(" maj", ""))}</span>` : "—"}</td>
      <td class="num muted">${p.duration ? fmtT(p.duration) : "—"}</td>
      <td><span class="badge ${p.status === "ready" ? "ok" : p.status === "failed" ? "bad" : "run"}">${{ ready: "Lista", failed: "Error", processing: "Procesando" }[p.status] || p.status}</span></td>
      <td><button class="btn sm del" data-id="${p.id}">Borrar</button></td></tr>`).join("")}</tbody></table>`;
    lib.querySelectorAll("tr.item").forEach((tr) => (tr.onclick = () => (location.hash = `#/p/${tr.dataset.id}`)));
    lib.querySelectorAll(".del").forEach((b) => (b.onclick = async (e) => {
      e.stopPropagation();
      if (confirm("¿Borrar esta canción y todas sus versiones?")) { await api(`/projects/${b.dataset.id}`, { method: "DELETE" }); drawLib(); }
    }));
  }
  drawLib();
  const iv = setInterval(() => { if (document.querySelector("tr .badge.run")) drawLib(); }, 4000);
  teardown = () => clearInterval(iv);
}

/* ============================================================ estudio */
const COL = { chorus: "#ffb020", verse: "#38d5f2", intro: "#9be15d", postchorus: "#ff5fa2", section: "#a58bff" };
const LBL = { chorus: "Estribillo", verse: "Verso", intro: "Intro", postchorus: "Post-estribillo", section: "Parte" };
const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

async function studio(pid) {
  let P = await api(`/projects/${pid}`).catch(() => null);
  if (!P) { app.innerHTML = `<p class="err">Proyecto no encontrado. <a href="#/" style="text-decoration:underline">Volver</a></p>`; return; }
  if (P.status !== "ready") {
    app.innerHTML = `<p class="muted">${P.status === "failed" ? `<span class="err">Error: ${esc(P.error)}</span>` : "Este proyecto sigue procesándose…"} <a href="#/" style="text-decoration:underline">Volver</a></p>`;
    return;
  }
  const A = () => P.analysis;
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const bufs = {};
  let stop = false;

  app.innerHTML = `
    <div class="row" style="margin-bottom:14px"><a class="btn sm" href="#/">← Biblioteca</a>
      <h1 style="font-size:26px;margin:0">${esc(P.track || P.title)}</h1><span class="muted">${esc(P.artist)}</span>
      <span class="badge ${P.separation?.backend === "dsp" ? "warn" : "ok"}">${{ ai: "Separado con IA", dsp: "Separación básica", uploaded: "Pistas subidas" }[P.separation?.backend] || ""}</span></div>
    <div id="stats" class="stats"></div>
    <div class="wavebox">
      <canvas id="wave"></canvas>
      <div class="wavebar">
        <button class="btn primary" id="play">▶ Reproducir</button>
        <span class="num" id="clock">0:00.0 · 1.1.000</span>
        <span style="flex:1"></span>
        <span class="muted" style="font-size:13px">Pista:</span>
        <button class="btn sm on" data-src="stems">Voz + Inst.</button><button class="btn sm" data-src="mix">Original</button>
        <label class="chk"><input type="checkbox" id="vOn" checked> Voz</label>
        <label class="chk"><input type="checkbox" id="iOn" checked> Inst.</label>
        <label class="chk"><input type="checkbox" id="metro"> Metrónomo</label>
        <button class="btn sm" data-z="-1">−</button><button class="btn sm" data-z="1">+</button>
      </div>
    </div>
    <div class="row" style="justify-content:space-between"><div class="legend" id="legend"></div>
      <div class="row"><span class="muted" style="font-size:13px">Rejilla:</span>
        <button class="btn sm" id="setOne">Poner el 1 en el cursor</button>
        <button class="btn sm" data-nudge="-0.02">−20 ms</button><button class="btn sm" data-nudge="-0.005">−5 ms</button>
        <button class="btn sm" data-nudge="0.005">+5 ms</button><button class="btn sm" data-nudge="0.02">+20 ms</button>
        <button class="btn sm" id="beatBack" title="Mover el 1 un tiempo atrás">1 tiempo ◂</button><button class="btn sm" id="beatFwd">▸ 1 tiempo</button></div></div>
    <div class="tabs"><button class="btn on" data-tab="arr">Arreglo y exportación</button><button class="btn" data-tab="ana">Análisis y letra</button></div>
    <div id="tab"></div>`;

  /* ---------- estadísticas + correcciones */
  const stats = $("#stats");
  const pct = (x) => `${Math.round(x * 100)}%`;
  function drawStats() {
    const a = A();
    const tone = (c) => (c >= 0.75 ? "ok" : c >= 0.45 ? "warn" : "bad");
    stats.innerHTML = `
      <div class="stat"><div class="l">BPM</div><div class="v c1">${a.bpm.toFixed(2)}</div>
        <div class="h"><span class="badge ${tone(a.bpm_confidence)}">${pct(a.bpm_confidence)}</span>
        <button class="btn sm" data-bpm="0.5" title="La canción va a la mitad">½</button><button class="btn sm" data-bpm="2" title="La canción va al doble">×2</button>
        <button class="btn sm" id="bpmEdit">Editar</button></div></div>
      <div class="stat"><div class="l">Tonalidad</div><div class="v c2">${esc(a.key)}</div>
        <div class="h"><span class="badge ok" style="color:var(--violet)">${a.camelot}</span><span class="badge ${tone(a.key_confidence)}">${pct(a.key_confidence)}</span></div></div>
      <div class="stat"><div class="l">Compás</div><div class="v c3">${a.time_signature}</div>
        <div class="h"><button class="btn sm" id="sig">${a.beats_per_bar === 4 ? "Cambiar a 3/4" : "Cambiar a 4/4"}</button></div></div>
      <div class="stat"><div class="l">1.er compás</div><div class="v c4">${a.first_bar.toFixed(3)} s</div>
        <div class="h">${a.doubts.includes("uno") ? `<span class="badge warn">revisa dónde cae el 1</span>` : `<span class="faint">${a.downbeat_times.length} compases · ${a.beat_times.length} beats</span>`}</div></div>`;
    stats.querySelectorAll("[data-bpm]").forEach((b) => (b.onclick = () => patch({ bpm: +(a.bpm * +b.dataset.bpm).toFixed(2) })));
    $("#bpmEdit").onclick = () => { const v = prompt("BPM exacto:", a.bpm.toFixed(2)); if (v && +v > 0) patch({ bpm: +v }); };
    $("#sig").onclick = () => patch({ beats_per_bar: a.beats_per_bar === 4 ? 3 : 4 });
  }
  async function patch(body) {
    try { P = await api(`/projects/${pid}/analysis`, { method: "PATCH", body }); drawStats(); draw(); drawTab(); }
    catch (e) { toast(e.message); }
  }
  $("#setOne").onclick = () => patch({ first_bar: +cursor.toFixed(4) });
  document.querySelectorAll("[data-nudge]").forEach((b) => (b.onclick = () => patch({ first_bar: Math.max(0, A().first_bar + +b.dataset.nudge) })));
  $("#beatBack").onclick = () => patch({ first_bar: Math.max(0, A().first_bar - A().seconds_per_beat) });
  $("#beatFwd").onclick = () => patch({ first_bar: A().first_bar + A().seconds_per_beat });

  /* ---------- audio */
  const stems = ["vocals", "instrumental", "mix"];
  async function loadAudio() {
    await Promise.all(stems.map(async (k) => {
      const ab = await (await fetch(`/api/projects/${pid}/audio/${k}`)).arrayBuffer();
      bufs[k] = await ctx.decodeAudioData(ab);
    }));
    buildPeaks(); fit(); draw();
  }
  const BLK = 128;
  let peaks = null;
  function buildPeaks() {
    const b = bufs.mix, n = Math.ceil(b.length / BLK), p = new Float32Array(n);
    const ch = [b.getChannelData(0), b.numberOfChannels > 1 ? b.getChannelData(1) : b.getChannelData(0)];
    for (let i = 0; i < n; i++) {
      let m = 0; const e = Math.min(b.length, (i + 1) * BLK);
      for (let j = i * BLK; j < e; j++) { const v = Math.max(Math.abs(ch[0][j]), Math.abs(ch[1][j])); if (v > m) m = v; }
      p[i] = m;
    }
    peaks = p;
  }
  let playing = false, startAt = 0, offset = 0, cursor = 0, srcMode = "stems", nodes = [], gains = {};
  const dur = () => A().duration;
  const now = () => (playing ? offset + (ctx.currentTime - startAt) : cursor);
  async function play() {
    if (!bufs.mix) return;
    await ctx.resume(); // con el contexto suspendido currentTime no avanza y el reloj se desfasaría
    stopNodes();
    offset = cursor >= dur() - 0.05 ? 0 : cursor;
    startAt = ctx.currentTime + 0.03;
    const mk = (k, on) => { const s = ctx.createBufferSource(); s.buffer = bufs[k]; const g = ctx.createGain(); g.gain.value = on ? 1 : 0; s.connect(g).connect(ctx.destination); s.start(startAt, offset); nodes.push(s); gains[k] = g; };
    if (srcMode === "stems") { mk("vocals", $("#vOn").checked); mk("instrumental", $("#iOn").checked); } else mk("mix", true);
    nodes[0].onended = () => { if (playing && now() >= dur() - 0.1) { playing = false; cursor = dur(); setPlay(); } };
    playing = true; metroIdx = null; setPlay(); loop();
  }
  function stopNodes() { nodes.forEach((n) => { try { n.onended = null; n.stop(); } catch {} }); nodes = []; }
  function pause() { if (!playing) return; cursor = Math.min(dur(), now()); playing = false; stopNodes(); setPlay(); draw(); }
  function setPlay() { $("#play").textContent = playing ? "❚❚ Pausar" : "▶ Reproducir"; }
  $("#play").onclick = () => (playing ? pause() : play());
  const keyH = (e) => { if (e.code === "Space" && !/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) { e.preventDefault(); playing ? pause() : play(); } };
  addEventListener("keydown", keyH);
  document.querySelectorAll("[data-src]").forEach((b) => (b.onclick = () => {
    srcMode = b.dataset.src;
    document.querySelectorAll("[data-src]").forEach((x) => x.classList.toggle("on", x === b));
    if (playing) { cursor = now(); play(); }
  }));
  $("#vOn").onchange = () => gains.vocals && (gains.vocals.gain.value = $("#vOn").checked ? 1 : 0);
  $("#iOn").onchange = () => gains.instrumental && (gains.instrumental.gain.value = $("#iOn").checked ? 1 : 0);

  // metrónomo: clics programados sobre la rejilla detectada
  let metroIdx = null;
  const metroTimer = setInterval(() => {
    if (!playing || !$("#metro").checked) { metroIdx = null; return; }
    const bt = A().beat_times, db = A().downbeat_times, t = now(), look = t + 0.15;
    if (metroIdx === null) { metroIdx = bt.findIndex((x) => x >= t - 0.01); if (metroIdx < 0) metroIdx = bt.length; }
    while (metroIdx < bt.length && bt[metroIdx] < look) {
      const when = startAt + (bt[metroIdx] - offset);
      if (when > ctx.currentTime - 0.01) {
        const isDown = db.some((d) => Math.abs(d - bt[metroIdx]) < 0.002);
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.frequency.value = isDown ? 2000 : 1250;
        g.gain.setValueAtTime(0.0001, when); g.gain.exponentialRampToValueAtTime(0.5, when + 0.002); g.gain.exponentialRampToValueAtTime(0.0001, when + 0.05);
        o.connect(g).connect(ctx.destination); o.start(when); o.stop(when + 0.06);
      }
      metroIdx++;
    }
  }, 30);

  /* ---------- forma de onda */
  const cv = $("#wave"), c2 = cv.getContext("2d");
  let pps = 20, vstart = 0, dpr = 1;
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  function resize() { dpr = devicePixelRatio || 1; cv.width = cv.clientWidth * dpr; cv.height = cv.clientHeight * dpr; draw(); }
  function fit() { pps = Math.max(2, (cv.clientWidth - 8) / dur()); vstart = 0; }
  const W = () => cv.clientWidth, H = () => cv.clientHeight;
  const t2x = (t) => (t - vstart) * pps;
  const x2t = (x) => x / pps + vstart;
  function clampView() { vstart = Math.max(0, Math.min(vstart, Math.max(0, dur() - W() / pps))); }
  function draw() {
    if (!peaks) return;
    clampView();
    const w = W(), h = H(), a = A();
    c2.setTransform(dpr, 0, 0, dpr, 0, 0);
    c2.clearRect(0, 0, w, h);
    const top = 22, mid = top + (h - top) / 2, amp = (h - top) / 2 - 4, sr = bufs.mix.sampleRate;
    // estructura
    a.segments.forEach((s) => {
      const x0 = t2x(s.start), x1 = t2x(s.end);
      if (x1 < 0 || x0 > w) return;
      c2.fillStyle = (COL[s.label] || COL.section) + "22"; c2.fillRect(x0, top, x1 - x0, h - top);
      c2.fillStyle = (COL[s.label] || COL.section); c2.fillRect(x0, 0, Math.max(1, x1 - x0 - 1), 3);
      c2.font = "11px system-ui"; c2.fillText(LBL[s.label] || s.label, Math.max(x0, 0) + 5, 15);
    });
    // beats / compases
    c2.lineWidth = 1;
    if (a.seconds_per_beat * pps > 6) {
      c2.strokeStyle = "rgba(255,255,255,.07)"; c2.beginPath();
      a.beat_times.forEach((t) => { const x = Math.round(t2x(t)) + .5; if (x >= 0 && x <= w) { c2.moveTo(x, top); c2.lineTo(x, h); } });
      c2.stroke();
    }
    const every = [1, 2, 4, 8, 16, 32].find((e) => a.seconds_per_bar * pps * e > 46) || 32;
    c2.font = "10px ui-monospace,Consolas,monospace";
    a.downbeat_times.forEach((t, i) => {
      const x = Math.round(t2x(t)) + .5;
      if (x < -20 || x > w + 20) return;
      const major = i % every === 0;
      c2.strokeStyle = major ? "rgba(255,255,255,.28)" : "rgba(255,255,255,.12)";
      c2.beginPath(); c2.moveTo(x, major ? top : top + 14); c2.lineTo(x, h); c2.stroke();
      if (major) { c2.fillStyle = "#8d90ad"; c2.fillText(String(i + 1), x + 3, top + 10); }
    });
    // picos
    c2.fillStyle = css("--cyan"); c2.beginPath();
    const spp = 1 / pps * sr / BLK; // bloques por píxel
    for (let x = 0; x < w; x++) {
      const i0 = Math.floor(x2t(x) * sr / BLK), i1 = Math.max(i0 + 1, Math.floor(x2t(x + 1) * sr / BLK));
      let m = 0; for (let i = i0; i < Math.min(i1, peaks.length); i++) if (peaks[i] > m) m = peaks[i];
      const hh = Math.max(1, m * amp);
      c2.rect(x, mid - hh, 1, hh * 2);
    }
    c2.fill();
    // marcadores
    const mk = (t, color, label) => {
      const x = t2x(t); if (x < -5 || x > w + 5) return;
      c2.strokeStyle = color; c2.lineWidth = 2; c2.beginPath(); c2.moveTo(x, top); c2.lineTo(x, h); c2.stroke(); c2.lineWidth = 1;
      c2.fillStyle = color; c2.font = "bold 10px system-ui"; c2.fillText(label, x + 4, h - 6);
    };
    mk(a.first_bar, css("--lime"), "1");
    mk(a.vocal_entry, css("--accent"), "voz");
    // cursor
    const x = t2x(now());
    c2.strokeStyle = "#fff"; c2.beginPath(); c2.moveTo(x + .5, 0); c2.lineTo(x + .5, h); c2.stroke();
    const t = now(), q = (t - a.first_bar) / a.seconds_per_beat, bar = Math.floor(q / a.beats_per_bar), beat = Math.floor(q) - bar * a.beats_per_bar;
    $("#clock").textContent = `${fmtT(t)}.${Math.floor((t % 1) * 10)} · ${q < 0 ? "pre" : `${bar + 1}.${beat + 1}`}`;
  }
  function loop() {
    if (!playing || stop) return;
    const t = now();
    if (t < vstart || t > vstart + W() / pps * 0.9) { vstart = Math.max(0, t - 20 / pps); }
    draw(); requestAnimationFrame(loop);
  }
  let drag = null;
  cv.onpointerdown = (e) => { cv.setPointerCapture(e.pointerId); drag = { x: e.clientX, v: vstart, moved: false }; };
  cv.onpointermove = (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    if (Math.abs(dx) > 3) drag.moved = true;
    if (drag.moved) { vstart = drag.v - dx / pps; draw(); }
  };
  cv.onpointerup = (e) => {
    if (drag && !drag.moved) {
      const r = cv.getBoundingClientRect(), t = Math.max(0, Math.min(dur(), x2t(e.clientX - r.left)));
      cursor = t; if (playing) play(); else draw();
    }
    drag = null;
  };
  cv.onwheel = (e) => {
    e.preventDefault();
    const r = cv.getBoundingClientRect(), tx = x2t(e.clientX - r.left);
    if (e.ctrlKey || Math.abs(e.deltaY) >= Math.abs(e.deltaX)) {
      pps = Math.max(W() / dur() * 0.9, Math.min(1200, pps * (e.deltaY < 0 ? 1.18 : 1 / 1.18)));
      vstart = tx - (e.clientX - r.left) / pps;
    } else vstart += e.deltaX / pps;
    draw();
  };
  document.querySelectorAll("[data-z]").forEach((b) => (b.onclick = () => { const c = vstart + W() / pps / 2; pps = Math.max(W() / dur() * 0.9, Math.min(1200, pps * (+b.dataset.z > 0 ? 1.6 : 1 / 1.6))); vstart = c - W() / pps / 2; draw(); }));
  addEventListener("resize", resize);
  $("#legend").innerHTML = `<span><i style="background:var(--cyan)"></i>Audio</span><span><i style="background:var(--lime)"></i>Compás 1</span><span><i style="background:var(--accent)"></i>Entrada de voz</span><span class="faint">Clic: mover cursor · Arrastrar: desplazar · Rueda: zoom · <kbd>Espacio</kbd> reproducir</span>`;

  /* ---------- pestañas */
  let tab = "arr";
  document.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => {
    tab = b.dataset.tab; document.querySelectorAll("[data-tab]").forEach((x) => x.classList.toggle("on", x === b)); drawTab();
  }));
  const O = { target: "hybrid", version: "livemashup", ending: "acapella", intro_bars: 8, vocal_entry_bar: -1, chorus_bar: -1, drum_genre: "house",
    fx: true, fx_beats: 4, fx_highpass: 700, fx_reverb: true, fx_noise: true, semitones: 0, tempo_ratio: 1, normalize: true, name_bpm: true, name_key: false };
  function drawTab() {
    const box = $("#tab"), a = A();
    if (tab === "ana") return drawAnalysis(box, a);
    const choruses = a.segments.filter((s) => s.label === "chorus");
    const ve = O.vocal_entry_bar >= 0 ? O.vocal_entry_bar : a.vocal_entry_bar;
    box.innerHTML = `
      <div class="grid2" style="grid-template-columns:1.2fr 1fr">
      <div class="panel">
        <h2>Versión</h2>
        <div class="cards">
          ${[["hybrid:livemashup", "LiveMashup", "Intro melódica, la voz entra en el compás 9 y acaba en acapella."],
             ["hybrid:extended", "Extended", "Intro con batería que cambia cada 4 compases y la canción entera."],
             ["acapella", "Acapella", "Solo la voz, en MP3 320."], ["instrumental", "Instrumental", "La canción sin voz."]]
            .map(([k, t, d]) => `<button class="card ${(O.target === "hybrid" ? "hybrid:" + O.version : O.target) === k ? "sel" : ""}" data-v="${k}"><b>${t}</b><small>${d}</small></button>`).join("")}
        </div>
        <div id="hyb" ${O.target !== "hybrid" ? "hidden" : ""}>
          <div class="opts">
            <div class="field"><label>Compases de intro</label><select id="ib">${[4, 8, 16, 32].map((n) => `<option ${O.intro_bars === n ? "selected" : ""}>${n}</option>`).join("")}</select></div>
            <div class="field"><label>Final</label><select id="en">
              ${[["acapella", "Acapella (el instrumental se va y la voz se queda sola)"], ["outro", "Outro (8 compases de ritmo para mezclar la salida)"], ["original", "Original (acaba como el disco)"]].map(([v, t]) => `<option value="${v}" ${O.ending === v ? "selected" : ""}>${t}</option>`).join("")}</select></div>
            <div class="field"><label>La voz entra en el compás</label><input type="number" id="ve" min="1" max="${a.downbeat_times.length}" value="${ve + 1}"><small class="faint">${a.downbeat_times[ve] ? fmtT(a.downbeat_times[ve]) : ""} · pulsa «voz» en la onda para verlo</small></div>
            <div class="field" id="chF" ${O.ending !== "acapella" ? "hidden" : ""}><label>Acapella desde el estribillo</label><select id="ch"><option value="-1">Automático</option>
              ${choruses.map((s) => `<option value="${s.bar}" ${O.chorus_bar === s.bar ? "selected" : ""}>compás ${s.bar + 1} · ${fmtT(s.start)}</option>`).join("")}</select></div>
            <div class="field" id="gF" ${O.version !== "extended" && O.ending !== "outro" ? "hidden" : ""}><label>Estilo de batería</label><select id="dg">${[["house", "House / dance"], ["dembow", "Dembow / reggaetón"], ["hiphop", "Hip-hop"]].map(([v, t]) => `<option value="${v}" ${O.drum_genre === v ? "selected" : ""}>${t}</option>`).join("")}</select></div>
          </div>
          <label class="chk" style="margin:6px 0"><input type="checkbox" id="fx" ${O.fx ? "checked" : ""}> Transición con efecto (barrido de graves, reverb y riser)</label>
        </div>
      </div>
      <div class="panel">
        <h2>Exportar</h2>
        <div class="field"><label>Cambio de tonalidad: <b class="num">${O.semitones > 0 ? "+" : ""}${O.semitones} st</b>${O.semitones ? ` → ${NOTE_NAMES[(a.key_root + O.semitones + 120) % 12]} ${a.key_mode === "minor" ? "m" : ""}` : ""}</label><input type="range" id="st" min="-6" max="6" step="1" value="${O.semitones}"><small class="faint">Mantiene el tempo</small></div>
        <div class="field"><label>Cambio de tempo: <b class="num">${O.tempo_ratio.toFixed(3)}× · ${(a.bpm * O.tempo_ratio).toFixed(1)} BPM</b></label><input type="range" id="tr" min="0.85" max="1.15" step="0.005" value="${O.tempo_ratio}"><small class="faint">Mantiene la tonalidad</small></div>
        <label class="chk"><input type="checkbox" id="nm" ${O.normalize ? "checked" : ""}> Normalizar a −1 dBFS (evita saturar)</label>
        <label class="chk" style="margin-top:6px"><input type="checkbox" id="nb" ${O.name_bpm ? "checked" : ""}> BPM en el nombre del archivo</label>
        <label class="chk" style="margin:6px 0 14px"><input type="checkbox" id="nk" ${O.name_key ? "checked" : ""}> Tonalidad además del Camelot</label>
        <button class="btn primary" id="gen" style="width:100%">Generar</button>
        <div id="gp"></div>
      </div></div>
      <div class="panel" style="margin-top:20px"><h2>Tus versiones</h2><div id="exps"></div></div>`;
    box.querySelectorAll("[data-v]").forEach((b) => (b.onclick = () => {
      const [t, v] = b.dataset.v.split(":"); O.target = t; if (v) { O.version = v; if (v === "extended" && O.ending === "acapella") O.ending = "acapella"; } drawTab();
    }));
    const bind = (id, fn, ev = "onchange") => { const e = $(id); if (e) e[ev] = () => fn(e); };
    bind("#ib", (e) => (O.intro_bars = +e.value));
    bind("#en", (e) => { O.ending = e.value; drawTab(); });
    bind("#ve", (e) => { O.vocal_entry_bar = Math.max(0, +e.value - 1); const t = a.downbeat_times[O.vocal_entry_bar]; if (t != null) { cursor = t; draw(); } });
    bind("#ch", (e) => (O.chorus_bar = +e.value));
    bind("#dg", (e) => (O.drum_genre = e.value));
    bind("#fx", (e) => (O.fx = e.checked));
    bind("#st", (e) => { O.semitones = +e.value; drawTab(); });
    bind("#tr", (e) => { O.tempo_ratio = +e.value; drawTab(); });
    bind("#nm", (e) => (O.normalize = e.checked));
    bind("#nb", (e) => (O.name_bpm = e.checked));
    bind("#nk", (e) => (O.name_key = e.checked));
    $("#gen").onclick = generate;
    drawExports();
  }
  function drawExports() {
    const box = $("#exps"); if (!box) return;
    if (!P.exports.length) { box.innerHTML = `<p class="muted" style="margin:0">Todavía no has generado ninguna versión.</p>`; return; }
    box.innerHTML = P.exports.map((e) => `<div class="exp"><div><b>${esc(e.filename)}</b><div class="faint num" style="font-size:12.5px">${e.bpm} BPM · ${esc(e.key)} · ${e.camelot} · ${fmtT(e.duration)}</div></div>
      <div class="row"><a class="btn sm primary" href="/api/projects/${pid}/exports/${e.id}/file?download=true">Descargar</a><button class="btn sm" data-del="${e.id}">Borrar</button></div>
      <audio controls preload="none" src="/api/projects/${pid}/exports/${e.id}/file"></audio></div>`).join("");
    box.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { await api(`/projects/${pid}/exports/${b.dataset.del}`, { method: "DELETE" }); P = await api(`/projects/${pid}`); drawExports(); }));
  }
  async function generate() {
    const btn = $("#gen"), gp = $("#gp");
    btn.disabled = true;
    gp.innerHTML = `<div class="progress"><i id="gb" style="width:2%"></i></div><div class="faint" id="gs">En cola…</div>`;
    try {
      const j0 = await api(`/projects/${pid}/exports`, { method: "POST", body: { ...O, ending: O.ending } });
      const j = await waitJob(j0.id, (j) => { $("#gb").style.width = `${Math.max(2, j.progress * 100)}%`; $("#gs").textContent = j.stage; });
      if (j.status === "failed") throw new Error(j.error);
      P = await api(`/projects/${pid}`); gp.innerHTML = ""; drawExports(); toast("Versión generada");
    } catch (e) { gp.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
    btn.disabled = false;
  }
  function drawAnalysis(box, a) {
    const lyr = a.lyrics;
    box.innerHTML = `<div class="grid2"><div class="panel"><h2>Datos del análisis</h2>
      <table class="lib"><tbody>
      ${[["Duración", fmtT(a.duration)], ["BPM", `${a.bpm} (${pct(a.bpm_confidence)})`], ["Duración de beat", `${a.seconds_per_beat.toFixed(4)} s`], ["Duración de compás", `${a.seconds_per_bar.toFixed(4)} s`],
         ["Beats", a.beat_times.length], ["Compases", a.downbeat_times.length], ["Afinación", `${a.tuning_offset_cents} cents`], ["Primera voz", `${a.vocal_onset.toFixed(2)} s`], ["Entra en el compás", a.vocal_entry_bar + 1]]
        .map(([k, v]) => `<tr><td class="muted">${k}</td><td class="num">${v}</td></tr>`).join("")}</tbody></table>
      <h2 style="margin-top:18px">Otras tonalidades posibles</h2>
      <div class="chips">${a.key_alternatives.map((k) => `<span class="chip" data-kr="${k.root}" data-km="${k.mode}">${esc(k.key)} · ${k.camelot}</span>`).join("")}</div></div>
      <div class="panel"><h2>Estructura</h2>${a.segments.length ? a.segments.map((s) => `<div class="row" style="padding:5px 0;border-bottom:1px solid var(--line)"><span style="width:10px;height:10px;border-radius:2px;background:${COL[s.label] || COL.section}"></span>
        <b style="min-width:120px">${LBL[s.label] || s.label}</b><span class="num muted">compás ${s.bar + 1}–${s.end_bar}</span><span class="num faint">${fmtT(s.start)}</span><button class="btn sm" data-go="${s.start}">Ir</button></div>`).join("") : `<p class="muted">Sin estructura detectada.</p>`}
      </div></div>`;
    box.querySelectorAll("[data-kr]").forEach((c) => (c.onclick = () => patch({ key_root: +c.dataset.kr, key_mode: c.dataset.km })));
    box.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => { cursor = +b.dataset.go; vstart = Math.max(0, cursor - 2); playing ? play() : draw(); }));
  }

  drawStats(); drawTab(); resize();
  loadAudio().catch((e) => toast("No se ha podido cargar el audio: " + e.message));
  teardown = () => { stop = true; playing = false; stopNodes(); clearInterval(metroTimer); removeEventListener("keydown", keyH); removeEventListener("resize", resize); ctx.close(); };
}

route();
