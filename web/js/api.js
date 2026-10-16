/** API 封装：同源默认，可覆盖 base */

let _base = "";

export function initApiBase() {
  const saved = localStorage.getItem("fl-api");
  _base =
    saved ||
    (location.protocol.startsWith("http")
      ? location.origin
      : "http://localhost:8321");
  return _base;
}

export function getBase() {
  return _base.replace(/\/+$/, "");
}

export function setBase(v) {
  _base = (v || "").replace(/\/+$/, "");
  localStorage.setItem("fl-api", _base);
}

async function request(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (opts.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const r = await fetch(getBase() + path, {
    ...opts,
    headers,
    credentials: "same-origin",
  });
  if (r.status === 401 && !path.startsWith("/api/auth/")) {
    location.href = "/api/auth/login";
    throw new Error("需要登录");
  }
  let data = null;
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    data = await r.json();
  }
  if (!r.ok) {
    const msg =
      (data && (data.detail?.message || data.detail || data.message)) ||
      `HTTP ${r.status}`;
    const err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    err.status = r.status;
    err.data = data;
    throw err;
  }
  return data;
}

export const api = {
  stats: () => request("/api/stats"),
  map: () => request("/api/map"),
  flights: (params = {}) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v != null && v !== "") q.set(k, v);
    });
    const s = q.toString();
    return request("/api/flights" + (s ? "?" + s : ""));
  },
  airports: (q = "", limit = 20) =>
    request(`/api/airports?q=${encodeURIComponent(q)}&limit=${limit}`),
  addFlight: (body) =>
    request("/api/flights", { method: "POST", body: JSON.stringify(body) }),
  updateFlight: (id, body) =>
    request("/api/flights/" + id, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteFlight: (id) =>
    request("/api/flights/" + id, { method: "DELETE" }),
  lookup: (flight, date) =>
    request("/api/lookup", {
      method: "POST",
      body: JSON.stringify({ flight, date }),
    }),
  extract: (text) =>
    request("/api/extract", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  importRows: (rows, replace = false) =>
    request("/api/import", {
      method: "POST",
      body: JSON.stringify({ rows, replace }),
    }),
  importFile: async (file, { source = "auto", replace = false, dryRun = false } = {}) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("source", source);
    fd.append("replace", replace ? "true" : "false");
    fd.append("dry_run", dryRun ? "true" : "false");
    const r = await fetch(getBase() + "/api/import/file", {
      method: "POST",
      body: fd,
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const msg = data.detail || data.message || `HTTP ${r.status}`;
      const err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
      err.status = r.status;
      throw err;
    }
    return data;
  },
  countries: () => request("/api/countries"),
  getTrack: (id) => request(`/api/flights/${id}/track`),
  putTrack: (id, body) =>
    request(`/api/flights/${id}/track`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  exportUrl: (format = "json", year = "") => {
    const q = new URLSearchParams({ format });
    if (year) q.set("year", year);
    return getBase() + "/api/export?" + q.toString();
  },
  config: () => request("/api/config"),
  saveKeys: (body) =>
    request("/api/config/keys", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  fleet: () => request("/api/fleet"),
  fleetSettings: (body) =>
    request("/api/fleet/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  fleetHarvest: () =>
    request("/api/fleet/harvest", { method: "POST", body: "{}" }),
  fleetNetwork: (airports = [], airline = "", limit = 180) => {
    const q = new URLSearchParams();
    if (airports?.length) q.set("airports", airports.join(","));
    if (airline) q.set("airline", airline);
    q.set("limit", String(limit));
    return request("/api/fleet/network?" + q.toString());
  },
};
