/* TerraMind AI — single-page platform. All numbers come from the local TerraMind API. */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const el = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    for (const k of kids) if (k != null) n.append(k);
    return n;
  };
  const fmt = (v, d = 2) => (v == null || Number.isNaN(v) ? "—" : Number(v).toFixed(d));
  const api = async (path, opts) => {
    const r = await fetch(path, opts);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
    return j;
  };

  // Sequential ramp for dark backgrounds: higher similarity = lighter.
  const RAMP = ["#184f95", "#2a78d6", "#5598e7", "#86b6ef", "#cde2fb"];
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const rampColor = (t) => {
    t = Math.max(0, Math.min(1, t));
    const x = t * (RAMP.length - 1), i = Math.min(Math.floor(x), RAMP.length - 2), f = x - i;
    const a = hex(RAMP[i]), b = hex(RAMP[i + 1]);
    return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * f)).join(",")})`;
  };
  const LIGHT_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"];
  const lightColor = (t) => {
    t = Math.max(0, Math.min(1, t));
    const x = t * (LIGHT_RAMP.length - 1), i = Math.min(Math.floor(x), LIGHT_RAMP.length - 2), f = x - i;
    const a = hex(LIGHT_RAMP[i]), b = hex(LIGHT_RAMP[i + 1]);
    return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * f)).join(",")})`;
  };

  let OV = null, map = null, cellLayer = null, leadLayer = null, siteLayer = null, current = null;

  // ---------- tabs ----------
  function show(page) {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.page === page));
    document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === page));
    if (page === "explorer" && map) setTimeout(() => map.invalidateSize(), 50);
  }
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => show(t.dataset.page)));

  // ---------- map ----------
  function initMap() {
    map = L.map("map", { preferCanvas: true, worldCopyJump: true }).setView([41.5, 62], 5);
    const sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 17, attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
    });
    const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 17, attribution: "© OpenStreetMap contributors",
    });
    const gibs = L.tileLayer("https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg", {
      maxZoom: 8, attribution: "NASA GIBS Blue Marble",
    });
    sat.addTo(map);
    L.control.layers({ "Satellite (Esri)": sat, "Map (OpenStreetMap)": osm, "NASA Blue Marble": gibs }, {}, { position: "topright" }).addTo(map);
    L.control.scale({ imperial: false }).addTo(map);
    $("#showCells").addEventListener("change", (e) => {
      if (!cellLayer) return;
      e.target.checked ? cellLayer.addTo(map) : map.removeLayer(cellLayer);
    });
  }

  function leadPin(i, verdict) {
    return L.divIcon({ className: "", html: `<div class="pin ${verdict || ""}">${i}</div>`, iconSize: [24, 24], iconAnchor: [12, 12] });
  }

  async function loadSearch(id) {
    if (!id) return;
    const s = await api(`/api/search?id=${encodeURIComponent(id)}`);
    current = s;
    const key = "overall_" + Object.keys(OV.weights)[0];
    const scores = s.windows.map((w) => w[2]).sort((a, b) => a - b);
    const lo = Math.max(0, Math.floor(scores[Math.floor(scores.length * 0.02)] * 20) / 20);
    const hi = Math.min(1, Math.ceil(scores[scores.length - 1] * 20) / 20) || 1;
    const span = Math.max(hi - lo, 0.1);

    if (cellLayer) map.removeLayer(cellLayer);
    if (leadLayer) map.removeLayer(leadLayer);
    cellLayer = L.layerGroup();
    const dLat = s.stride_km / 111.32;
    for (const [lat, lon, v] of s.windows) {
      const dLon = s.stride_km / (111.32 * Math.cos((lat * Math.PI) / 180));
      L.rectangle([[lat - dLat / 2, lon - dLon / 2], [lat + dLat / 2, lon + dLon / 2]], {
        stroke: false, fillColor: rampColor((v - lo) / span), fillOpacity: 0.55, interactive: true,
      }).bindTooltip(`similarity ${v.toFixed(3)}<br>${lat.toFixed(3)}, ${lon.toFixed(3)}`, { sticky: true }).addTo(cellLayer);
    }
    if ($("#showCells").checked) cellLayer.addTo(map);

    leadLayer = L.layerGroup().addTo(map);
    s.top.forEach((t, i) => {
      const rv = s.reviews[`${t.lat.toFixed(5)},${t.lon.toFixed(5)}`];
      L.marker([t.lat, t.lon], { icon: leadPin(i + 1, rv && rv.verdict) })
        .bindTooltip(`#${i + 1} · ${t[key].toFixed(3)}`).on("click", () => flyTo(t)).addTo(leadLayer);
    });
    for (const k of s.known_sites) {
      L.marker([k.nearest_window.lat, k.nearest_window.lon], {
        icon: L.divIcon({ className: "", html: '<div class="site-pin"></div>', iconSize: [14, 14], iconAnchor: [7, 7] }),
      }).bindTooltip(`${k.name}: rank ${k.rank} of ${k.of}`).addTo(leadLayer);
    }
    const [w, so, e, n] = s.region.bbox;
    map.fitBounds([[so, w], [n, e]]);

    // side panel
    $("#searchHint").textContent = `${s.region.name} vs ${s.reference.name}. 25 km windows every ${s.stride_km} km, NASA SRTM.`;
    const d = s.score_distribution || {};
    $("#stats").replaceChildren(
      ...[["windows scored", s.counts.scored], ["water (excluded)", s.counts.water], ["median", fmt(d.median, 3)],
          ["best", fmt(d.max, 3)]].map(([lbl, v]) => el("div", { class: "stat" }, el("b", { text: String(v) }), el("span", { text: lbl }))),
    );
    $("#legend").replaceChildren(
      el("div", { text: "similarity (color range of this search)" }),
      el("div", { class: "bar", style: `background:linear-gradient(90deg,${RAMP.join(",")})` }),
      el("div", { class: "ends" }, el("span", { text: lo.toFixed(2) }), el("span", { text: hi.toFixed(2) })),
    );
    $("#known").replaceChildren(...s.known_sites.map((k) => el("div", { class: "known",
      text: `${k.name}: its window ranks ${k.rank} of ${k.of} (top ${k.top_percent}%), score ${fmt(k.score, 3)}` })));
    renderLeads(s, key);
  }

  function flyTo(t) {
    map.flyTo([t.lat, t.lon], 11, { duration: 0.8 });
  }

  function renderLeads(s, key) {
    const list = $("#leads");
    list.replaceChildren();
    s.top.forEach((t, i) => {
      const k = `${t.lat.toFixed(5)},${t.lon.toFixed(5)}`;
      const rv = s.reviews[k];
      const badge = rv
        ? el("span", { class: `badge ${rv.verdict === "accepted" ? "ok" : "no"}`, text: rv.verdict === "accepted" ? "✓ accepted" : "✗ rejected" })
        : el("span", { class: "badge wait", text: "● to review" });
      const review = async (verdict) => {
        const note = verdict === "rejected" ? (prompt("Why is this lead rejected? (e.g. open-pit mine, fields, town)") || "") : "";
        try {
          const r = await api("/api/review", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ search_id: `${s.reference.id}__${s.region.id}`, lat: t.lat, lon: t.lon, verdict, note }) });
          s.reviews = r.reviews;
          loadSearch(`${s.reference.id}__${s.region.id}`);
        } catch (e) { alert(e.message); }
      };
      list.append(el("li", { class: `lead ${rv ? rv.verdict : ""}` },
        el("div", { class: "lead-top" },
          el("span", { class: "num", text: String(i + 1) }),
          el("span", { class: "coords", text: `${t.lat.toFixed(4)}, ${t.lon.toFixed(4)}` }),
          el("span", { class: "score", text: fmt(t[key], 3) })),
        el("div", { class: "metrics", text: `slope ${fmt(t.slope_deg)} · relief ${fmt(t.relief_m)} · roughness ${fmt(t.tri_m)}` +
          (t.slope_median != null ? ` · median slope ${fmt(t.slope_median, 1)}°` : "") }),
        rv && rv.note ? el("div", { class: "metrics", text: `note: ${rv.note}` }) : null,
        el("div", { class: "actions" },
          badge,
          el("button", { class: "btn", text: "View imagery", onclick: () => flyTo(t) }),
          el("button", { class: "btn", text: "Accept", onclick: () => review("accepted") }),
          el("button", { class: "btn", text: "Reject", onclick: () => review("rejected") }),
          rv ? el("button", { class: "btn", text: "Clear", onclick: () => review("clear") }) : null),
      ));
    });
  }

  // ---------- matrix ----------
  function renderMatrix() {
    const m = OV.matrix;
    const box = $("#matrixTable");
    if (!m) { box.replaceChildren(el("p", { class: "muted", text: "No matrix yet. Run: python -m terramind matrix" })); return; }
    const wkey = Object.keys(OV.weights)[0];
    const head = el("tr", {}, el("th", { text: "" }), ...m.references.map((r) => el("th", { text: r.name })));
    const rows = m.earth_sites.map((s) => el("tr", {},
      el("th", { text: `${s.name} (${s.role})` }),
      ...m.references.map((r) => {
        const c = m.cells[`${r.id}__${s.id}`];
        const v = c.overall[wkey];
        return el("td", { class: "cell", style: `background:${lightColor(v)};color:${v >= 0.55 ? "#fff" : "#111"}`, text: v.toFixed(2),
          onclick: () => matrixDetail(r, s, c) });
      })));
    box.replaceChildren(el("table", { class: "mx" }, head, ...rows));
    const st = Object.entries(m.rank_stability || {}).map(([k, v]) => `${k}: ${v.spearman_rho == null ? "n/a" : "ρ = " + v.spearman_rho}`);
    box.append(el("p", { class: "hint", text: `Rank stability between weight sets A and B (Spearman): ${st.join(" · ")}` }));
  }
  function matrixDetail(r, s, c) {
    const pair = `${r.id}__${s.id}`;
    $("#matrixDetail").replaceChildren(
      el("h3", { class: "h3", text: `${r.name} vs ${s.name}` }),
      el("p", { class: "muted", text: `Slope ${fmt(c.per_metric.slope_deg)} · relief ${fmt(c.per_metric.relief_m)} · roughness ${fmt(c.per_metric.tri_m)} · overall A ${fmt(c.overall.A)} · B ${fmt(c.overall.B)}` }),
      el("img", { src: `/files/results/${pair}/histograms.png`, alt: `Histograms ${pair}` }),
    );
  }

  // ---------- sites ----------
  function renderSites() {
    const stateBadge = (st) => st === "approved" ? el("span", { class: "badge ok", text: "✓ approved" })
      : el("span", { class: "badge wait", text: st.replace("_", " ") });
    $("#siteCards").replaceChildren(...OV.sites.filter((s) => s.center[0] != null).map((s) => {
      const ms = s.metric_summary || {};
      return el("div", { class: "card" },
        el("span", { class: `tag ${s.body}`, text: s.body }), el("span", { class: "tag", text: s.role }), stateBadge(s.state),
        el("h4", { text: s.name }),
        el("div", { class: "kv", text: `center ${s.center[0]}, ${s.center[1]}` }),
        s.params_hash ? el("div", { class: "kv" }, "params ", el("code", { text: s.params_hash }), ` · approved ${s.approved_at || ""}`) : null,
        ms.slope_deg ? el("div", { class: "kv", text: `median slope ${fmt(ms.slope_deg.median, 1)}° · median roughness ${fmt(ms.tri_m.median, 1)} m · relief ${fmt(ms.relief_m.p5, 0)}…${fmt(ms.relief_m.p95, 0)} m` }) : null,
        s.quicklook ? el("img", { src: s.quicklook, alt: `Quick-look ${s.name}`, onclick: (e) => lightbox(e.target.src) }) : null,
      );
    }));
  }
  function lightbox(src) {
    const lb = $("#lightbox");
    lb.querySelector("img").src = src;
    lb.hidden = false;
  }
  $("#lightbox").addEventListener("click", () => ($("#lightbox").hidden = true));

  // ---------- ask ----------
  const EXAMPLES = [
    "Why does Ustyurt resemble Meridiani Planum but not Gale crater?",
    "Find places in western Uzbekistan that look like Meridiani Planum",
    "Find places in western Uzbekistan that look like the Moon's Mons Mouton plateau",
    "Is MDRS in Utah a good analog for Gale crater according to TerraMind?",
    "Nega Ustyurt Gale'ga emas, Meridiani'ga o'xshaydi?",
  ];
  $("#chips").replaceChildren(...EXAMPLES.map((q) => el("button", { class: "chip", type: "button", text: q, onclick: () => { $("#q").value = q; } })));
  $("#askForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = $("#q").value.trim();
    if (!q) return;
    const out = $("#answer"), btn = $("#askBtn");
    btn.disabled = true; out.hidden = false; out.textContent = "Thinking… (a search can take a minute the first time)";
    try {
      const r = await api("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q }) });
      out.replaceChildren(el("div", { text: r.answer }));
      out.append(r.unverified_numbers.length
        ? el("div", { class: "verify warn", text: `⚠ Not found in TerraMind's results, do not trust: ${r.unverified_numbers.join(", ")}` })
        : el("div", { class: "verify ok", text: "✓ Every number in this answer matches TerraMind's computed results." }));
      out.append(el("div", { class: "hint", text: `model: ${r.model}` }));
      if (r.search_id) {
        out.append(el("button", { class: "btn", text: "Open these leads on the map", onclick: async () => {
          OV = await api("/api/overview"); fillSearchSelect(r.search_id); show("explorer"); loadSearch(r.search_id);
        } }));
      }
    } catch (err) {
      out.textContent = `Error: ${err.message}`;
    } finally { btn.disabled = false; }
  });

  // ---------- boot ----------
  function fillSearchSelect(selected) {
    const sel = $("#searchSel");
    sel.replaceChildren(...OV.searches.map((s) => el("option", { value: s.id, text: `${s.reference.name} → ${s.region.name}` })));
    if (!OV.searches.length) sel.append(el("option", { value: "", text: "No searches yet — run: python -m terramind search …" }));
    if (selected) sel.value = selected;
  }
  async function boot() {
    initMap();
    try { OV = await api("/api/overview"); } catch (e) { $("#searchHint").textContent = `Cannot reach the TerraMind API: ${e.message}`; return; }
    fillSearchSelect();
    $("#searchSel").addEventListener("change", (e) => loadSearch(e.target.value));
    const pref = OV.searches.find((s) => s.id.startsWith("meridiani__uzbekistan")) || OV.searches[0];
    if (pref) { $("#searchSel").value = pref.id; loadSearch(pref.id); }
    renderMatrix();
    renderSites();
    if (!OV.ai_available) $("#askBtn").title = "Set OPENROUTER_API_KEY in .env to enable answers";
  }
  boot();
})();
