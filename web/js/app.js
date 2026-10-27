/** FlightLog 入口：表面切换 + 启动 */

import {
  bootstrap,
  getState,
  setSurface,
  subscribe,
  toggleTheme,
  refresh,
} from "./store.js";
import { setBase, getBase, initApiBase, api } from "./api.js";
import { toast, esc } from "./util.js";
import { disconnectCopy, loginUrl } from "./connection.js";
import { mountAtlas, invalidateMap } from "./views/atlas.js";
import { mountLogbook } from "./views/logbook.js";
import { mountCapture } from "./views/capture.js";

async function refreshProviderPill() {
  const el = document.getElementById("provPill");
  if (!el) return;
  try {
    const c = await api.config();
    if (c.live_lookup) {
      el.textContent = "实时+航线";
      el.title = "已配置实时 API，并启用免费航线库";
    } else {
      el.textContent = "免费航线库";
      el.title = "adsbdb 零配置；可在「录入 → 智能配置」增强";
    }
  } catch {
    el.textContent = "航线库";
  }
}

function renderStatusBanner(state) {
  const bar = document.getElementById("statusBanner");
  if (!bar) return;
  if (state.connected && !state.error) {
    bar.hidden = true;
    bar.innerHTML = "";
    return;
  }
  if (state.loading) {
    bar.hidden = true;
    return;
  }
  const copy = disconnectCopy(state);
  const cta = copy.cta;
  let ctaHtml = "";
  if (cta?.href) {
    ctaHtml = `<a class="btn btn-sm btn-primary" href="${esc(cta.href)}">${esc(cta.label)}</a>`;
  } else if (cta?.action === "api") {
    ctaHtml = `<button type="button" class="btn btn-sm btn-primary" data-status-action="api">${esc(cta.label)}</button>`;
  }
  bar.hidden = false;
  bar.innerHTML =
    `<div class="status-banner-inner" role="status">` +
    `<strong>${esc(copy.title)}</strong>` +
    `<span>${esc(copy.sub)}</span>` +
    `<div class="status-banner-actions">${ctaHtml}` +
    `<button type="button" class="btn btn-sm btn-ghost" data-status-action="retry">重试</button>` +
    `</div></div>`;
  bar.querySelector('[data-status-action="api"]')?.addEventListener("click", () => {
    document.getElementById("apiAdvanced")?.classList.add("open");
    document.getElementById("apiBase")?.focus();
  });
  bar.querySelector('[data-status-action="retry"]')?.addEventListener("click", () => {
    void refresh();
  });
}

function syncAuthChrome(state) {
  const logout = document.getElementById("logoutBtn");
  if (logout) {
    const show = state.auth?.oidc && state.auth?.authenticated;
    logout.hidden = !show;
    logout.setAttribute("aria-hidden", show ? "false" : "true");
    if (show) logout.href = `${getBase()}/api/auth/logout`;
  }
}

function syncChrome(state) {
  document.querySelectorAll("[data-surface]").forEach((btn) => {
    const on = btn.dataset.surface === state.surface;
    btn.classList.toggle("active", on);
    if (on) btn.setAttribute("aria-current", "page");
    else btn.removeAttribute("aria-current");
  });
  document.querySelectorAll(".surface").forEach((el) => {
    el.classList.toggle("active", el.id === "surface-" + state.surface);
  });
  const pill = document.getElementById("apiPill");
  const txt = document.getElementById("apiTxt");
  if (pill) {
    if (state.needsLogin) {
      pill.className = "pill off";
    } else {
      pill.className = "pill " + (state.connected ? "on" : "off");
    }
  }
  if (txt) {
    txt.textContent = state.needsLogin
      ? "待登录"
      : state.connected
        ? "已连接"
        : "未连接";
  }

  const themeBtn = document.getElementById("themeBtn");
  if (themeBtn) {
    themeBtn.textContent =
      document.documentElement.dataset.theme === "light" ? "深色" : "浅色";
    themeBtn.title =
      document.documentElement.dataset.theme === "light"
        ? "切换到深色"
        : "切换到浅色";
  }

  renderStatusBanner(state);
  syncAuthChrome(state);

  if (state.surface === "atlas") {
    invalidateMap();
    setTimeout(invalidateMap, 80);
    setTimeout(invalidateMap, 280);
  }
}

function mountShell() {
  document.querySelectorAll("[data-surface]").forEach((btn) => {
    btn.addEventListener("click", () => setSurface(btn.dataset.surface));
  });

  document.getElementById("themeBtn")?.addEventListener("click", () => {
    toggleTheme();
  });

  document.getElementById("btnApiToggle")?.addEventListener("click", () => {
    document.getElementById("apiAdvanced")?.classList.toggle("open");
  });

  const apiInput = document.getElementById("apiBase");
  if (apiInput) {
    apiInput.value = initApiBase();
    apiInput.setAttribute("aria-label", "API 根地址");
    apiInput.addEventListener("change", async () => {
      setBase(apiInput.value);
      await refresh();
      const s = getState();
      if (!s.connected && !s.needsLogin) {
        toast("无法连接：" + getBase(), { err: true });
      }
    });
  }

  window.addEventListener("hashchange", () => {
    const h = (location.hash || "").replace(/^#/, "");
    if (["atlas", "logbook", "capture"].includes(h)) {
      setSurface(h);
    }
  });

  window.addEventListener("fl-config-changed", () => {
    refreshProviderPill();
  });
}

function fillAirportDatalist(state) {
  const list = document.getElementById("airportList");
  if (!list || !state.airportList?.length) return;
  list.innerHTML = state.airportList
    .map((a) => `<option value="${esc(a.code)}">${esc(a.name)}</option>`)
    .join("");
}

async function main() {
  mountShell();
  mountAtlas();
  mountLogbook();
  mountCapture();
  subscribe(syncChrome);
  subscribe(fillAirportDatalist);
  await bootstrap();
  syncChrome(getState());
  fillAirportDatalist(getState());
  const s = getState();
  if (s.connected) {
    await refreshProviderPill();
  } else if (s.needsLogin) {
    toast("登录后即可加载档案", {
      action: { label: "去登录", onClick: () => { location.href = loginUrl(); } },
    });
  } else if (!s.loading) {
    toast("无法连接后端", { err: true });
  }
}

main();
