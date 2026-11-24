/* gnss-ntp-graphs static UI. Reads data/*.json written by the collector. */
(function () {
  "use strict";

  /* ColorBrewer Paired 12-class; used only until data/config.json loads. Qualitative
     ColorBrewer schemes are prefixes of their largest class, so slicing gives any count. */
  const FALLBACK_PAIRED = ["#a6cee3", "#1f78b4", "#b2df8a", "#33a02c", "#fb9a99", "#e31a1c",
                           "#fdbf6f", "#ff7f00", "#cab2d6", "#6a3d9a", "#ffff99", "#b15928"];
  /* Line styles for series beyond the palette's class count. */
  const DASHES = [undefined, [6, 4], [2, 3], [8, 3, 2, 3]];
  const CONSTELLATIONS = ["gps", "galileo", "glonass", "beidou", "qzss", "sbas", "navic"];
  const GNSS_IDS = ["gps", "sbas", "galileo", "beidou", "imes", "qzss", "glonass", "navic"];
  const SECTION_LABELS = { ntp: "NTP", peers: "Peers", gps: "GNSS", stats: "Stats" };
  const THEMES = ["auto", "light", "dark"];
  const REFRESH_MS = 60000;

  /* Defaults mirror config.py [web]; data/config.json overrides them. */
  let CFG = {
    web: { title: "GNSS NTP", header: "", theme: "auto", layout: "tabs",
           sections: ["ntp", "peers", "gps", "stats"], hide_graphs: [], ranges: ["2h", "8h", "24h", "7d", "30d", "1y"],
           default_range: "24h", graph_height: 220, columns: "auto", font_size: 14, timezone: "local",
           offset_unit: "ms", offset_lines: [], offset_warn_ms: 1, offset_bad_ms: 10,
           stale_warn_s: 120, stale_bad_s: 300, palette: "Paired", colourblind_safe: false, cursor: "hover",
           repo_url: "https://github.com/ToledoEM/gnss-ntp-graphs",
           docs_url: "https://toledoem.github.io/gnss-ntp-graphs/" },
    graphs: {},
    palette: { classes: { 12: FALLBACK_PAIRED }, safe: 4 },
  };

  /* Colours and dash patterns for a plot with n series.
     Class count = n, at least 3, at most the scheme's largest class (or its
     colourblind-safe maximum). Series beyond it reuse the colours with dashes. */
  function colours(n) {
    const p = CFG.palette;
    const counts = Object.keys(p.classes).map(Number);
    const largest = Math.max(...counts);
    const cap = CFG.web.colourblind_safe && p.safe ? p.safe : largest;
    const k = Math.max(3, Math.min(n, cap));
    const list = (p.classes[k] || p.classes[largest]).slice(0, k);
    if (n === 1) return [{ colour: list[1], dash: undefined }];  // darker of the first pair
    return Array.from({ length: n }, (_, i) =>
      ({ colour: list[i % k], dash: DASHES[Math.floor(i / k) % DASHES.length] }));
  }

  function constellationColours() {
    const c = colours(CONSTELLATIONS.length);
    return Object.fromEntries(CONSTELLATIONS.map((name, i) => [name, c[i]]));
  }

  const state = { range: null, tab: null, window: "24h", theme: null, current: null, stats: null,
                  lastRange: null, plots: {} };

  const $ = (id) => document.getElementById(id);
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const fmt = (v, d = 3) => (v === null || v === undefined || Number.isNaN(v)) ? "–" : Number(v).toFixed(d);
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } },
  };

  /* --- units ------------------------------------------------------------- */

  const unit = () => CFG.web.offset_unit === "us" ? "µs" : "ms";
  const K = () => CFG.web.offset_unit === "us" ? 1000 : 1;        // ms -> display unit
  const DIG = () => CFG.web.offset_unit === "us" ? 1 : 4;
  const scale = (arr) => arr ? arr.map((v) => v === null || v === undefined ? v : v * K()) : arr;
  const sv = (v) => v === null || v === undefined ? v : v * K();

  async function getJSON(name) {
    const r = await fetch("data/" + name + "?_=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error(name + ": " + r.status);
    return r.json();
  }

  /* --- plotting ---------------------------------------------------------- */

  function axes() {
    const grid = { stroke: css("--grid"), width: 1 };
    return { stroke: css("--muted"), grid, ticks: grid, font: `${Math.round(CFG.web.font_size * 0.8)}px system-ui, sans-serif` };
  }

  function widthOf(node) {
    return Math.max(260, node.clientWidth || (node.parentNode.clientWidth - 20));
  }

  function tzDate() {
    const tz = CFG.web.timezone;
    if (!tz || tz === "local") return undefined;
    const name = tz === "UTC" ? "Etc/UTC" : tz;
    return (ts) => uPlot.tzDate(new Date(ts * 1e3), name);
  }

  /* Horizontal reference lines in display units. */
  function refLines(values) {
    return (u) => {
      const ctx = u.ctx;
      ctx.save();
      ctx.strokeStyle = css("--refline");
      ctx.setLineDash([6, 4]);
      ctx.lineWidth = 1 * devicePixelRatio;
      values.forEach((v) => {
        const y = u.valToPos(v, "y", true);
        if (y < u.bbox.top || y > u.bbox.top + u.bbox.height) return;
        ctx.beginPath(); ctx.moveTo(u.bbox.left, y); ctx.lineTo(u.bbox.left + u.bbox.width, y); ctx.stroke();
      });
      ctx.restore();
    };
  }

  /* Index of the newest x with a value in any series, or -1. */
  function lastIndex(data) {
    for (let i = data[0].length - 1; i >= 0; i--) {
      if (data.slice(1).some((ys) => ys && ys[i] !== null && ys[i] !== undefined)) return i;
    }
    return -1;
  }

  /* Dashed vertical line at x value t. */
  function lastLine(t) {
    return (u) => {
      const x = u.valToPos(t, "x", true);
      if (x < u.bbox.left || x > u.bbox.left + u.bbox.width) return;
      const ctx = u.ctx;
      ctx.save();
      ctx.strokeStyle = css("--muted");
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1 * devicePixelRatio;
      ctx.beginPath(); ctx.moveTo(x, u.bbox.top); ctx.lineTo(x, u.bbox.top + u.bbox.height); ctx.stroke();
      ctx.restore();
    };
  }

  /* Replace the plot for graph id. series: [{label, colour?, dash?, scale?}], data: [x, ...ys] */
  function plot(id, series, data, opts = {}) {
    const node = $("p-" + id);
    if (!node || node.closest("[hidden]")) return;
    if (state.plots[id]) { state.plots[id].destroy(); delete state.plots[id]; }
    const hasData = data.slice(1).some((ys) => ys && ys.some((v) => v !== null && v !== undefined));
    node.innerHTML = "";
    if (!hasData) { node.innerHTML = '<div class="empty">No data in this range</div>'; return; }
    const a = axes();
    const scales = opts.scales || { x: { time: true }, y: {} };
    const lim = CFG.graphs[id] || {};
    if (lim.y_min !== undefined || lim.y_max !== undefined) {
      scales.y = { ...(scales.y || {}),
        range: (u, mn, mx) => [lim.y_min ?? mn, lim.y_max ?? mx] };
    }
    const ax = [{ ...a, ...(opts.xAxis || {}) }, { ...a, size: 64, ...(opts.yAxis || {}) }];
    if (series.some((s) => s.scale === "y2")) ax.push({ ...a, side: 1, scale: "y2", size: 60, grid: { show: false } });
    const hooks = { draw: [], ready: [], setCursor: [] };
    if (opts.lines && opts.lines.length) hooks.draw.push(refLines(opts.lines));
    if (CFG.web.cursor === "last" && opts.time !== false) {
      const last = lastIndex(data);
      if (last >= 0) {
        // Legend shows the newest values whenever the pointer is not over the plot
        const atLast = (u) => { if (u.cursor.idx === null || u.cursor.idx === undefined) u.setLegend({ idx: last }); };
        hooks.ready.push(atLast);
        hooks.setCursor.push(atLast);
        hooks.draw.push(lastLine(data[0][last]));
      }
    }
    const pal = colours(series.length);
    const u = new uPlot({
      width: widthOf(node), height: opts.height || CFG.web.graph_height,
      scales, axes: ax, hooks, tzDate: opts.time === false ? undefined : tzDate(),
      cursor: { drag: { x: true, y: false } },
      legend: { live: true },
      series: [{ label: opts.xLabel || "time" }].concat(series.map((s, i) => ({
        label: s.label,
        stroke: s.colour || pal[i].colour,
        dash: s.colour ? s.dash : pal[i].dash,
        width: s.width || 1.5,
        scale: s.scale || "y",
        fill: s.fill,
        paths: s.paths,
        points: s.points || { show: false },
        spanGaps: false,
        value: s.value || ((u, v) => fmt(v, s.digits === undefined ? 3 : s.digits)),
      }))),
    }, data, node);
    state.plots[id] = u;
  }

  /* --- header ------------------------------------------------------------ */

  function applyConfig() {
    const w = CFG.web;
    document.documentElement.style.setProperty("--font-size", w.font_size + "px");
    document.body.classList.add("layout-" + w.layout);
    if (w.columns !== "auto") document.body.classList.add("cols-" + w.columns);
    $("title").textContent = w.title;
    document.title = w.title + " graphs";
    $("subtitle").textContent = w.header || "";
    $("subtitle").hidden = !w.header;
    [["repo-link", w.repo_url], ["docs-link", w.docs_url]].forEach(([id, url]) => {
      $(id).hidden = !url;
      if (url) $(id).href = url;
    });
    document.querySelectorAll(".unit").forEach((n) => { n.textContent = unit(); });
    document.querySelectorAll(".section").forEach((s) => { s.hidden = !w.sections.includes(s.dataset.section); });
    document.querySelectorAll("figure[data-graph]").forEach((f) => { f.hidden = w.hide_graphs.includes(f.dataset.graph); });
    $("tabs").innerHTML = w.sections.map((s) => `<button data-tab="${s}">${SECTION_LABELS[s]}</button>`).join("");
    state.range = store.get("gng.range");
    if (!w.ranges.includes(state.range)) state.range = w.default_range;
    $("ranges").innerHTML = w.ranges.map((n) => `<button data-range="${n}">${n}</button>`).join("");
    markOn("#ranges button", "range", state.range);
  }

  /* Single layout: sections scroll to just below the sticky header. */
  function setTopHeight() {
    document.documentElement.style.setProperty("--top-h", ($("top").offsetHeight + 8) + "px");
  }

  function markOn(sel, key, val) {
    document.querySelectorAll(sel).forEach((b) => b.classList.toggle("on", b.dataset[key] === val));
  }

  function setTheme(theme) {
    state.theme = theme;
    if (theme === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    $("theme").textContent = "theme: " + theme;
  }

  function renderStatus(cur) {
    const w = CFG.web, s = cur.system || {}, g = cur.gps || {};
    const age = Math.round(Date.now() / 1000 - cur.generated);
    const stale = age > w.stale_bad_s ? "bad" : age > w.stale_warn_s ? "warn" : "ok";
    const off = s.offset, offAbs = Math.abs(off || 0);
    const offCls = off === null || off === undefined ? "" : offAbs < w.offset_warn_ms ? "ok" : offAbs < w.offset_bad_ms ? "warn" : "bad";
    const sync = cur.peers && cur.peers.find((p) => p.tally === "*");
    $("status").innerHTML = [
      `refid <b>${s.refid ?? "–"}</b>`,
      `stratum <b>${s.stratum ?? "–"}</b>`,
      `offset <b class="${offCls}">${fmt(sv(off), DIG())} ${unit()}</b>`,
      `sync peer <b>${sync ? sync.remote : "none"}</b>`,
      `leap <b>${s.leap ?? "–"}</b>`,
      `sats <b>${g.used ?? "–"}/${g.total ?? "–"}</b>`,
      ...(cur.host && cur.host.cpu_temp !== null && cur.host.cpu_temp !== undefined
        ? [`cpu <b>${fmt(cur.host.cpu_temp, 1)} °C</b>`] : []),
      `updated <b class="${stale}">${age}s ago</b>`,
    ].map((x) => `<span>${x}</span>`).join("");
    $("footer").textContent = `gnss-ntp-graphs ${cur.version} · source: ${cur.source} · ` +
      new Date(cur.generated * 1000).toLocaleString();
  }

  /* --- sections ---------------------------------------------------------- */

  /* CPU temperature graphs only appear once the collector has recorded a temperature. */
  function showHostGraphs(cur) {
    const has = !!(cur && cur.host);
    document.querySelectorAll("figure[data-host]").forEach((f) => {
      f.hidden = !has || CFG.web.hide_graphs.includes(f.dataset.graph);
    });
  }

  /* Scatter of y against CPU temperature with its least-squares line. */
  function thermalScatter(id, label, temp, ys, fit, k, digits, yUnit) {
    const pts = temp.map((t, i) => [t, ys[i] === null || ys[i] === undefined ? null : ys[i] * k])
      .filter((p) => p[0] !== null && p[1] !== null).sort((a, b) => a[0] - b[0]);
    const cap = $("fit-" + id);
    if (cap) cap.textContent = fit ? `(slope ${fmt(fit.slope * k, digits)} ${yUnit}/°C, r ${fmt(fit.r, 2)}, n ${fit.n})` : "";
    if (!pts.length) return plot(id, [], [[]]);
    const x = pts.map((p) => p[0]);
    const pc = colours(2);
    const series = [{ label, digits, colour: pc[1].colour, paths: () => null,
                      points: { show: true, size: 4, stroke: pc[1].colour, fill: pc[1].colour } }];
    const data = [x, pts.map((p) => p[1])];
    if (fit) {
      series.push({ label: "fit", digits, colour: pc[0].colour, dash: [6, 4] });
      data.push(x.map((t) => (fit.slope * t + fit.intercept) * k));
    }
    plot(id, series, data, { scales: { x: { time: false }, y: {} }, xLabel: "CPU °C", time: false });
  }

  function renderNtp(sys, host) {
    const t = sys.t, d = DIG();
    plot("offset", [{ label: "offset", digits: d }], [t, scale(sys.offset)],
      { lines: CFG.web.offset_lines.map((v) => v * K()) });
    plot("jitter", [{ label: "sys_jitter", digits: d }, { label: "clk_jitter", digits: d }],
      [t, scale(sys.sys_jitter), scale(sys.clk_jitter)]);
    plot("freq", [{ label: "frequency" }, { label: "wander", scale: "y2" }], [t, sys.frequency, sys.wander],
      { scales: { x: { time: true }, y: {}, y2: {} } });
    plot("root", [{ label: "root delay", digits: d }, { label: "root dispersion", digits: d }],
      [t, scale(sys.rootdelay), scale(sys.rootdisp)]);
    plot("stratum", [{ label: "stratum", digits: 0 }], [t, sys.stratum],
      { height: Math.round(CFG.web.graph_height * 0.75) });
    if (host) {
      plot("temp", [{ label: "CPU °C", digits: 1 }, { label: "frequency", scale: "y2" }],
        [t, host.cpu_temp, sys.frequency], { scales: { x: { time: true }, y: {}, y2: {} } });
    }
  }

  function renderPeers(peers) {
    const names = Object.keys(peers);
    const peerPlot = (id, key, digits, scaled) => {
      if (!names.length) return plot(id, [], [[]]);
      plot(id, names.map((n) => ({ label: n, digits })),
        [peers[names[0]].t].concat(names.map((n) => scaled ? scale(peers[n][key]) : peers[n][key])));
    };
    peerPlot("peer-offset", "offset", DIG(), true);
    peerPlot("peer-delay", "delay", DIG(), true);
    peerPlot("peer-jitter", "jitter", DIG(), true);
    peerPlot("peer-reach", "reach", 0, false);
  }

  function renderGps(gps) {
    const gt = gps.t;
    plot("sats", [{ label: "used", digits: 1 }, { label: "visible", digits: 1 }], [gt, gps.used, gps.total]);
    const cc = constellationColours();
    const shown = CONSTELLATIONS.filter((c) => (gps["vis_" + c] || []).some((v) => v));
    plot("const", shown.map((c) => ({ label: c, colour: cc[c].colour, dash: cc[c].dash, digits: 1 })),
      [gt].concat(shown.map((c) => gps["used_" + c])));
    plot("ss", [{ label: "avg SNR", digits: 1 }], [gt, gps.avg_ss]);
    plot("dop", ["hdop", "vdop", "pdop", "tdop", "gdop"].map((d) => ({ label: d, digits: 2 })),
      [gt, gps.hdop, gps.vdop, gps.pdop, gps.tdop, gps.gdop]);
  }

  function drawSky(gps) {
    const c = $("sky");
    if (c.closest("[hidden]")) return;
    const ctx = c.getContext("2d");
    const dpr = window.devicePixelRatio || 1, size = c.clientWidth || 420;
    c.width = size * dpr; c.height = size * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const R = size / 2 - 22, cx = size / 2, cy = size / 2;
    ctx.clearRect(0, 0, size, size);
    ctx.strokeStyle = css("--line"); ctx.fillStyle = css("--muted");
    ctx.font = "11px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    [0, 30, 60].forEach((el) => { ctx.beginPath(); ctx.arc(cx, cy, R * (90 - el) / 90, 0, 2 * Math.PI); ctx.stroke(); });
    ctx.beginPath(); ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy); ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R); ctx.stroke();
    [["N", 0], ["E", 90], ["S", 180], ["W", 270]].forEach(([l, az]) => {
      const a = (az - 90) * Math.PI / 180;
      ctx.fillText(l, cx + (R + 12) * Math.cos(a), cy + (R + 12) * Math.sin(a));
    });
    const sats = (gps && gps.satellites) || [];
    skyLegend(gps, sats);
    if (!sats.length) { ctx.fillText("no satellite data", cx, cy); return; }
    sats.forEach((s) => {
      if (s.el === null || s.az === null || s.el === undefined || s.el < 0) return;
      const r = R * (90 - s.el) / 90, a = (s.az - 90) * Math.PI / 180;
      const x = cx + r * Math.cos(a), y = cy + r * Math.sin(a);
      const cc = constellationColours()[GNSS_IDS[s.gnssid]];
      const col = cc ? cc.colour : css("--muted");
      const rad = 4 + Math.max(0, Math.min(1, ((s.ss || 0) - 10) / 40)) * 6;
      ctx.beginPath(); ctx.arc(x, y, rad, 0, 2 * Math.PI);
      ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.stroke();
      if (s.used) { ctx.fillStyle = col; ctx.fill(); }
      ctx.fillStyle = css("--text"); ctx.fillText(String(s.PRN ?? ""), x, y - rad - 7);
    });
    ctx.lineWidth = 1;
  }

  /* Colour key and used/visible counts under the sky plot. */
  function skyLegend(gps, sats) {
    const node = $("sky-legend");
    if (!sats.length) { node.innerHTML = ""; return; }
    const cc = constellationColours(), counts = {};
    sats.forEach((s) => {
      const name = GNSS_IDS[s.gnssid];
      if (!name) return;
      const c = counts[name] || (counts[name] = { used: 0, vis: 0 });
      c.vis += 1;
      if (s.used) c.used += 1;
    });
    const items = CONSTELLATIONS.filter((n) => counts[n]).map((n) => {
      const col = cc[n] ? cc[n].colour : css("--muted");
      return `<span><i class="fill" style="color:${col}"></i>${n} <b>${counts[n].used}/${counts[n].vis}</b></span>`;
    });
    items.push('<span><i class="fill"></i>used</span>', "<span><i></i>visible only</span>");
    const used = gps && gps.used, total = gps && gps.total;
    items.push(`<span class="sum">used <b>${used ?? "–"}</b> of <b>${total ?? "–"}</b> satellites</span>`);
    node.innerHTML = items.join("");
  }

  function renderPeerTable(peers) {
    const u = unit(), d = DIG();
    const rows = (peers || []).map((p) =>
      `<tr><td>${p.tally || "&nbsp;"} ${p.remote}</td><td>${p.refid}</td><td>${p.stratum ?? "–"}</td>` +
      `<td>${p.type}</td><td>${p.poll ?? "–"}</td><td>${p.reach === null ? "–" : p.reach.toString(8)}</td>` +
      `<td>${fmt(sv(p.delay), d)}</td><td>${fmt(sv(p.offset), d)}</td><td>${fmt(sv(p.jitter), d)}</td></tr>`).join("");
    $("peer-table").innerHTML = "<caption>Peers now</caption><tr><th>remote</th><th>refid</th><th>st</th>" +
      `<th>t</th><th>poll</th><th>reach</th><th>delay ${u}</th><th>offset ${u}</th><th>jitter ${u}</th></tr>` + rows;
  }

  function renderStats() {
    const st = state.stats;
    if (!st || $("sec-stats").hidden) return;
    const names = Object.keys(st.windows);
    if (!names.includes(state.window)) state.window = names[0];
    $("windows").innerHTML = names.map((n) =>
      `<button data-window="${n}" class="${n === state.window ? "on" : ""}">${n}</button>`).join("");
    const w = st.windows[state.window], u = unit(), d = DIG();
    const origins = { polled: "polled samples", chrony_tracking: "chrony tracking.log", ntpd_loopstats: "ntpd loopstats" };
    $("stats-origin").textContent = `offset source: ${origins[w.origin] || w.origin}, sample spacing ${w.tau0}s · ` +
      `computed ${new Date(st.generated * 1000).toLocaleTimeString()}`;

    if (w.offset_hist) {
      const hc = colours(1)[0].colour;
      plot("hist", [{ label: "count", digits: 0, colour: hc, fill: hc + "88", paths: uPlot.paths.bars({ size: [0.95, 100] }) }],
        [scale(w.offset_hist.x), w.offset_hist.count],
        { scales: { x: { time: false }, y: { range: (u, mn, mx) => [0, mx] } }, xLabel: "offset " + u, time: false });
    } else plot("hist", [], [[]]);

    if (w.adev && w.adev.tau.length) {
      plot("adev", [{ label: "ADEV", value: (u, v) => (v === null || v === undefined) ? "–" : v.toExponential(2) }],
        [w.adev.tau, w.adev.adev],
        { scales: { x: { time: false, distr: 3 }, y: { distr: 3 } }, xLabel: "tau s", time: false,
          yAxis: { values: (u, vs) => vs.map((v) => (v === null || v === undefined) ? "" : v.toExponential(0)) } });
    } else plot("adev", [], [[]]);

    const th = w.thermal;
    if (th) {
      thermalScatter("temp-freq", "frequency ppm", th.temp, th.frequency, th.fit_frequency, 1, 3, "ppm");
      thermalScatter("temp-offset", `offset ${u}`, th.temp, th.offset, th.fit_offset, K(), d, u);
    } else {
      plot("temp-freq", [], [[]]); plot("temp-offset", [], [[]]);
      ["fit-temp-freq", "fit-temp-offset"].forEach((id) => { $(id).textContent = ""; });
    }

    const cols = ["n", "mean", "stddev", "p1", "p5", "p50", "p95", "p99", "range90", "range98"];
    const row = (label, s, dg, k = 1) => s ? `<tr><td>${label}</td>` + cols.map((c) =>
      `<td>${c === "n" ? s[c] : fmt(s[c] * k, dg)}</td>`).join("") + "</tr>" : "";
    const g = w.gps || {};
    $("stats-table").innerHTML = "<caption>System and GNSS</caption><tr><th></th>" +
      cols.map((c) => `<th>${c}</th>`).join("") + "</tr>" +
      row(`offset ${u}`, w.offset, d, K()) + row(`sys jitter ${u}`, w.sys_jitter, d, K()) +
      row("frequency ppm", w.frequency, 3) +
      row(`root delay ${u}`, w.rootdelay, d, K()) + row(`root disp ${u}`, w.rootdisp, d, K()) +
      row("CPU temp °C", w.cpu_temp, 1) + row("sats used", g.used, 1) + row("avg SNR dB-Hz", g.avg_ss, 1) + row("TDOP", g.tdop, 2) + row("HDOP", g.hdop, 2);

    const pr = Object.entries(w.peers || {}).map(([n, p]) =>
      `<tr><td>${n}</td><td>${p.offset ? p.offset.n : "–"}</td>` +
      `<td>${fmt(sv(p.offset && p.offset.p50), d)}</td><td>${fmt(sv(p.offset && p.offset.range90), d)}</td>` +
      `<td>${fmt(sv(p.delay && p.delay.p50), d)}</td><td>${fmt(sv(p.jitter && p.jitter.p50), d)}</td>` +
      `<td>${p.reach_full_pct ?? "–"}</td></tr>`).join("");
    $("peer-stats-table").innerHTML = `<caption>Peers</caption><tr><th>remote</th><th>n</th><th>offset p50 ${u}</th>` +
      `<th>offset 90% range</th><th>delay p50 ${u}</th><th>jitter p50 ${u}</th><th>reach 377 %</th></tr>` + pr;
  }

  /* --- wiring ------------------------------------------------------------ */

  const visible = (sec) => CFG.web.sections.includes(sec) && (CFG.web.layout === "single" || state.tab === sec);

  function setTab(tab) {
    state.tab = tab;
    markOn("#tabs button", "tab", tab);
    if (CFG.web.layout === "tabs") {
      store.set("gng.tab", tab);
      document.querySelectorAll(".section").forEach((s) => s.classList.toggle("on", s.dataset.section === tab));
      $("ranges").hidden = tab === "stats";
      if (location.hash !== "#" + tab) history.replaceState(null, "", "#" + tab);
      refresh();
    } else {
      $("sec-" + tab).scrollIntoView({ behavior: "smooth" });
    }
  }

  async function refresh() {
    try {
      const cur = await getJSON("current.json");
      state.current = cur;
      renderStatus(cur);
      showHostGraphs(cur);
      setTopHeight();
      const needRange = ["ntp", "peers", "gps"].some(visible);
      if (needRange) {
        const r = await getJSON("range_" + state.range + ".json");
        state.lastRange = r;
        if (visible("ntp")) renderNtp(r.system, r.host);
        if (visible("peers")) { renderPeers(r.peers); renderPeerTable(cur.peers); }
        if (visible("gps")) { renderGps(r.gps); drawSky(cur.gps); }
      }
      if (visible("stats")) {
        state.stats = await getJSON("stats.json");
        renderStats();
      }
    } catch (e) {
      $("status").innerHTML = `<span class="bad">No data yet: ${e.message}</span>`;
    }
  }

  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    if (b.id === "theme") {
      const next = THEMES[(THEMES.indexOf(state.theme) + 1) % THEMES.length];
      store.set("gng.theme", next);
      setTheme(next);
      refresh();
    }
    if (b.dataset.tab) setTab(b.dataset.tab);
    if (b.dataset.range) {
      state.range = b.dataset.range;
      store.set("gng.range", state.range);
      markOn("#ranges button", "range", state.range);
      refresh();
    }
    if (b.dataset.window) { state.window = b.dataset.window; renderStats(); }
  });

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      setTopHeight();
      Object.entries(state.plots).forEach(([id, u]) => {
        const node = $("p-" + id);
        if (node && !node.closest("[hidden]") && node.offsetParent) u.setSize({ width: widthOf(node), height: u.height });
      });
      if (visible("gps") && state.current) drawSky(state.current.gps);
    }, 200);
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (state.theme === "auto") refresh();
  });

  async function init() {
    try { CFG = await getJSON("config.json"); } catch (e) { /* built-in defaults */ }
    applyConfig();
    const saved = store.get("gng.theme");
    setTheme(THEMES.includes(saved) ? saved : CFG.web.theme);
    const secs = CFG.web.sections, hash = location.hash.slice(1), savedTab = store.get("gng.tab");
    let tab = secs.includes(hash) ? hash : secs.includes(savedTab) ? savedTab : secs[0];
    if (CFG.web.layout === "single") {
      state.tab = tab;
      markOn("#tabs button", "tab", tab);
      await refresh();
      if (secs.includes(hash)) $("sec-" + hash).scrollIntoView();
    } else {
      setTab(tab);
    }
    setInterval(refresh, REFRESH_MS);
  }

  init();
})();
