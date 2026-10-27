/** 档案表面：紧凑统计 + 地图主导 + 可折叠图表 */

import { api } from "../api.js";
import { getState, theme, setSurface, subscribe } from "../store.js";
import { bars, esc } from "../util.js";
import { disconnectCopy, loginUrl } from "../connection.js";
import { loadLeaflet } from "../leaflet-loader.js";

let map = null;
let tileLayer = null;
let overlays = [];
let refOverlays = [];
let unsub = null;
let lastTheme = null;
let showRefRoutes = localStorage.getItem("fl-map-ref") === "1";
let refFetchToken = 0;

/** Esri Canvas：免 key；Carto 公共底图已要求 API Key。 */
function tileLayerOpts() {
  const dark = theme() !== "light";
  const url = dark
    ? "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
    : "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}";
  return {
    url,
    opts: {
      maxZoom: 16,
      attribution: "Esri",
    },
  };
}

function addBaseTiles() {
  const { url, opts } = tileLayerOpts();
  if (tileLayer) map.removeLayer(tileLayer);
  tileLayer = L.tileLayer(url, opts).addTo(map);
  lastTheme = theme();
  // 底图失败时给一次提示（不打断航迹层）
  tileLayer.once("tileerror", () => {
    const meta = document.getElementById("mapMeta");
    if (meta && !meta.dataset.tileWarn) {
      meta.dataset.tileWarn = "1";
      meta.textContent = (meta.textContent || "") + " · 底图加载受阻";
    }
  });
}

async function ensureMap() {
  const el = document.getElementById("map");
  if (!el || map) return;
  await loadLeaflet();
  map = L.map("map", {
    center: [34, 108],
    zoom: 4,
    minZoom: 2,
    maxZoom: 12,
    attributionControl: false,
    worldCopyJump: true,
  });
  addBaseTiles();
}

function syncTiles() {
  if (!map || !tileLayer) return;
  if (theme() === lastTheme) return;
  map.removeLayer(tileLayer);
  addBaseTiles();
}

function routePath(r) {
  if (r && Array.isArray(r.path)) return { coords: r.path, w: r.weight || 1 };
  if (Array.isArray(r) && r.length === 2 && typeof r[1] === "number") {
    return { coords: r[0], w: r[1] };
  }
  return null;
}

async function renderMap(airports, routes) {
  await ensureMap();
  if (!map) return;
  syncTiles();
  overlays.forEach((l) => map.removeLayer(l));
  overlays = [];

  const accent =
    getComputedStyle(document.documentElement)
      .getPropertyValue("--accent")
      .trim() || "#2ec4b6";
  const amber =
    getComputedStyle(document.documentElement)
      .getPropertyValue("--amber")
      .trim() || "#e8a838";

  airports.forEach((a) => {
    const m = L.circleMarker([a[2], a[3]], {
      radius: 5,
      color: accent,
      weight: 1.5,
      fillColor: accent,
      fillOpacity: 0.9,
    })
      .addTo(map)
      .bindPopup(`<b>${esc(a[0])}</b> ${esc(a[1])}`);
    overlays.push(m);
  });

  routes.forEach((r) => {
    const parsed = routePath(r);
    if (!parsed || !parsed.coords || parsed.coords.length < 2) return;
    const w = parsed.w;
    const line = L.polyline(parsed.coords, {
      color: w > 1 ? amber : accent,
      weight: Math.min(1.5 + w * 0.5, 4),
      opacity: 0.4 + Math.min(w * 0.12, 0.35),
      dashArray: "6 5",
      className: "route-line",
    }).addTo(map);
    overlays.push(line);
  });

  if (airports.length) {
    const bounds = L.latLngBounds(airports.map((a) => [a[2], a[3]]));
    map.fitBounds(bounds.pad(0.18), { padding: [28, 28], maxZoom: 6 });
  }

  const meta = document.getElementById("mapMeta");
  if (meta) {
    meta.textContent = airports.length
      ? `${airports.length} 机场 · ${routes.length} 航线`
      : "等待第一条航迹";
  }

  loadRefRoutes(airports);
  requestAnimationFrame(() => map.invalidateSize());
}

function clearRefRoutes() {
  refOverlays.forEach((l) => map && map.removeLayer(l));
  refOverlays = [];
}

async function loadRefRoutes(airports) {
  clearRefRoutes();
  if (!map || !showRefRoutes || !airports?.length) return;
  const codes = airports.map((a) => a[0]).filter(Boolean);
  const token = ++refFetchToken;
  try {
    const data = await api.fleetNetwork(codes, "", 160);
    if (token !== refFetchToken || !showRefRoutes) return;
    const faint =
      getComputedStyle(document.documentElement)
        .getPropertyValue("--text3")
        .trim() || "#5a6a80";
    (data.routes || []).forEach((r) => {
      if (!r.path || r.path.length < 2) return;
      const line = L.polyline(r.path, {
        color: faint,
        weight: 1,
        opacity: 0.22,
        className: "ref-route-line",
      }).addTo(map);
      if (r.airline) {
        line.bindPopup(
          `${esc(r.airline)} ${esc(r.from)}→${esc(r.to)}` +
            (r.equipment ? ` · ${esc(r.equipment)}` : "") +
            "<br><small>OpenFlights 参考航线</small>"
        );
      }
      refOverlays.push(line);
    });
    const meta = document.getElementById("mapMeta");
    if (meta && data.count) {
      meta.textContent =
        (meta.textContent || "") + ` · 参考 ${data.count}`;
    }
  } catch {
    /* 参考层失败不影响主地图 */
  }
}

function renderHeroStory(state) {
  const el = document.getElementById("heroStory");
  if (!el) return;
  if (state.needsLogin) {
    el.innerHTML =
      '<p class="hero-story">登录后继续查看你的航迹与里程。</p>' +
      `<a class="btn btn-primary btn-sm" href="${esc(loginUrl())}">登录</a>`;
    return;
  }
  if (!state.connected) {
    el.innerHTML =
      '<p class="hero-story muted">暂时连不上服务，稍后再打开试试。</p>';
    return;
  }
  const stats = state.stats;
  const total = stats?.total || 0;
  if (!total) {
    el.innerHTML =
      '<p class="hero-story">从一段航班开始——查航班号最快，订票短信也能一键解析。</p>' +
      '<button type="button" class="btn btn-primary btn-sm" id="heroStartCapture">录入第一程</button>';
    document.getElementById("heroStartCapture")?.addEventListener("click", () =>
      setSurface("capture")
    );
    return;
  }
  const parts = [];
  if (stats.km != null) {
    const laps = (stats.km / 40075).toFixed(1);
    parts.push(`累计约绕地球 ${laps} 圈`);
  }
  const topRoute = Object.entries(stats.routes || {}).sort(
    (a, b) => b[1] - a[1]
  )[0];
  if (topRoute) {
    const [key, n] = topRoute;
    const [from, to] = key.split("-");
    parts.push(`最爱航线 ${from} ↔ ${to}（${n} 次）`);
  }
  const recent = [...(state.flights || [])].sort((a, b) =>
    (b.date || "").localeCompare(a.date || "")
  )[0];
  if (recent) {
    parts.push(
      `最近 ${recent.date} · ${recent.flight} ${recent.from}→${recent.to}`
    );
  }
  el.innerHTML = `<p class="hero-story">${esc(parts.join(" · "))}</p>`;
}

function renderEmpty(state) {
  const empty = document.getElementById("mapEmpty");
  if (!empty) return;
  const card = empty.querySelector(".card");
  if (state.needsLogin) {
    empty.classList.add("show");
    if (card) {
      const copy = disconnectCopy(state);
      card.innerHTML =
        '<div class="map-empty-illus" aria-hidden="true"></div>' +
        `<h3>${esc(copy.title)}</h3><p>${esc(copy.sub)}</p>` +
        `<a class="btn btn-primary" href="${esc(loginUrl())}">${esc(copy.cta?.label || "登录")}</a>`;
    }
    return;
  }
  if (!state.connected) {
    empty.classList.add("show");
    if (card) {
      const copy = disconnectCopy(state);
      const cta = copy.cta;
      let action = "";
      if (cta?.href) {
        action = `<a class="btn btn-primary" href="${esc(cta.href)}">${esc(cta.label)}</a>`;
      } else if (cta?.action === "api") {
        action = `<button type="button" class="btn btn-primary" id="btnOpenApi">配置 API</button>`;
      }
      card.innerHTML =
        '<div class="map-empty-illus" aria-hidden="true"></div>' +
        `<h3>${esc(copy.title)}</h3><p>${esc(copy.sub)}</p>${action}`;
    }
    return;
  }
  if (state.loading) {
    empty.classList.remove("show");
    return;
  }
  const emptyMap = !(state.map?.airports || []).length;
  empty.classList.toggle("show", emptyMap);
  if (!emptyMap || !card) return;
  card.innerHTML =
    '<div class="map-empty-illus" aria-hidden="true"></div>' +
    "<h3>画上第一条航迹</h3>" +
    "<p>录入一程航班，机场与弧线会落在这片地图上。</p>" +
    '<button type="button" class="btn btn-primary" id="btnGoCapture">去录入</button>';
  document.getElementById("btnGoCapture")?.addEventListener("click", () => {
    setSurface("capture");
  });
}

function renderStats(stats, state) {
  const set = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  };
  if (!state.connected) {
    ["stTotal", "stKm", "stEarth", "stAirports", "stAircraft"].forEach((id) =>
      set(id, "–")
    );
    ["yearChart", "airChart", "acChart"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = '<div class="hint">后端未连接</div>';
    });
    return;
  }
  if (!stats) {
    if (state.loading) return;
    ["yearChart", "airChart", "acChart"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = '<div class="hint">暂无数据</div>';
    });
    return;
  }
  set("stTotal", stats.total ?? "–");
  set(
    "stKm",
    stats.km != null ? Math.round(stats.km).toLocaleString() : "–"
  );
  set(
    "stEarth",
    stats.km != null ? (stats.km / 40075).toFixed(2) : "–"
  );
  set("stAirports", stats.airports ?? "–");
  set("stAircraft", stats.aircraft_types ?? "–");
  bars(document.getElementById("yearChart"), stats.years || {}, false);
  bars(document.getElementById("airChart"), stats.airlines || {}, true);
  bars(document.getElementById("acChart"), stats.aircraft || {}, true);
  bars(document.getElementById("cabinChart"), stats.cabin_class || {}, true);
  bars(document.getElementById("seatChart"), stats.seat_type || {}, true);
  bars(document.getElementById("contChart"), stats.continents || {}, true);
  const countries = {};
  Object.entries(stats.countries || {}).forEach(([code, v]) => {
    const label = typeof v === "object" ? v.name || code : code;
    countries[label] = typeof v === "object" ? v.count : v;
  });
  bars(document.getElementById("countryChart"), countries, true);
}

function render(state) {
  if (state.surface !== "atlas") return;
  renderHeroStory(state);
  renderStats(state.stats, state);
  void renderMap(state.map.airports, state.map.routes);
  renderEmpty(state);
}

export function mountAtlas() {
  const panel = document.getElementById("chartsPanel");
  document.getElementById("chartsToggle")?.addEventListener("click", () => {
    panel?.classList.toggle("open");
  });
  document.getElementById("mapEmpty")?.addEventListener("click", (e) => {
    if (e.target?.id === "btnGoCapture") setSurface("capture");
    if (e.target?.id === "btnOpenApi") {
      document.getElementById("apiAdvanced")?.classList.add("open");
      document.getElementById("apiBase")?.focus();
    }
  });
  const refChk = document.getElementById("mapRefRoutes");
  if (refChk) {
    refChk.checked = showRefRoutes;
    refChk.addEventListener("change", () => {
      showRefRoutes = !!refChk.checked;
      localStorage.setItem("fl-map-ref", showRefRoutes ? "1" : "0");
      const st = getState();
      if (showRefRoutes) loadRefRoutes(st.map?.airports || []);
      else {
        clearRefRoutes();
        const meta = document.getElementById("mapMeta");
        if (meta) meta.textContent = meta.textContent.replace(/ · 参考 \d+/, "");
      }
    });
  }
  unsub = subscribe(render);
  render(getState());
}

export function invalidateMap() {
  if (map) requestAnimationFrame(() => map.invalidateSize());
}
