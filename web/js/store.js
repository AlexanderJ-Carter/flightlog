/** 单一数据源：flights / stats / map / filters / theme / surface */

import { api, initApiBase } from "./api.js";

const listeners = new Set();

const state = {
  connected: false,
  needsLogin: false,
  auth: { oidc: false, authenticated: true },
  surface: "atlas",
  flights: [],
  stats: null,
  map: { airports: [], routes: [] },
  airportCodes: new Set(),
  filters: { q: "", year: "", airline: "", airport: "" },
  editingId: null,
  editingFlight: null,
  airportList: [],
  loading: false,
  error: null,
};

export function getState() {
  return state;
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function emit() {
  listeners.forEach((fn) => fn(state));
}

export function setSurface(name) {
  state.surface = name;
  location.hash = name;
  emit();
}

export function initTheme() {
  const saved = localStorage.getItem("fl-theme");
  const sys = matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
  document.documentElement.dataset.theme = saved || sys;
  matchMedia("(prefers-color-scheme: light)").addEventListener("change", (e) => {
    if (!localStorage.getItem("fl-theme")) {
      document.documentElement.dataset.theme = e.matches ? "light" : "dark";
      emit();
    }
  });
}

export function toggleTheme() {
  const cur =
    document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = cur;
  localStorage.setItem("fl-theme", cur);
  emit();
}

export function theme() {
  return document.documentElement.dataset.theme || "dark";
}

export async function bootstrap() {
  initApiBase();
  initTheme();
  const hash = (location.hash || "").replace(/^#/, "");
  if (["atlas", "logbook", "capture"].includes(hash)) {
    state.surface = hash;
  }
  await refresh();
}

function clearData() {
  state.stats = null;
  state.map = { airports: [], routes: [] };
  state.flights = [];
  state.airportList = [];
  state.airportCodes = new Set();
}

export async function refresh() {
  state.loading = true;
  emit();
  try {
    const auth = await api.authStatus();
    state.auth = auth;
    if (auth.oidc && !auth.authenticated) {
      state.needsLogin = true;
      state.connected = false;
      state.error = null;
      clearData();
      return;
    }
    state.needsLogin = false;

    const [stats, map, flights, airports] = await Promise.all([
      api.stats(),
      api.map(),
      api.flights(state.filters),
      api.airports("", 500),
    ]);
    state.stats = stats;
    state.map = {
      airports: map.airports || [],
      routes: map.routes || [],
    };
    state.flights = flights.flights || [];
    state.airportList = airports.airports || [];
    state.airportCodes = new Set(state.airportList.map((a) => a.code));
    state.connected = true;
    state.error = null;
  } catch (e) {
    state.connected = false;
    if (e.authRequired || e.status === 401) {
      state.needsLogin = true;
      state.auth = { oidc: true, authenticated: false };
      state.error = null;
    } else {
      state.needsLogin = false;
      state.error = e.message || "无法连接后端";
    }
    clearData();
  } finally {
    state.loading = false;
    emit();
  }
}

export async function setFilters(partial) {
  Object.assign(state.filters, partial);
  if (state.needsLogin) {
    emit();
    return;
  }
  try {
    const data = await api.flights(state.filters);
    state.flights = data.flights || [];
    state.connected = true;
    state.error = null;
  } catch (e) {
    state.connected = false;
    if (e.authRequired) {
      state.needsLogin = true;
      state.error = e.message || "需要登录";
    } else {
      state.needsLogin = false;
      state.error = e.message || "无法连接后端";
    }
  }
  emit();
}

export function setEditing(id, flight = null) {
  state.editingId = id;
  state.editingFlight =
    flight || (state.flights || []).find((x) => x.id === id) || null;
  emit();
}

export function clearEditing() {
  state.editingId = null;
  state.editingFlight = null;
  emit();
}

export function isKnownAirport(code) {
  return state.airportCodes.has((code || "").toUpperCase());
}
