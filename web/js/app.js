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
    pill.className = "pill " + (state.connected ? "on" : "off");
  }
  if (txt) txt.textContent = state.connected ? "已连接" : "未连接";

  const themeBtn = document.getElementById("themeBtn");
  if (themeBtn) {
    // 按钮表示「切换到」的目标主题
    themeBtn.textContent =
      document.documentElement.dataset.theme === "light" ? "深色" : "浅色";
    themeBtn.title =
      document.documentElement.dataset.theme === "light"
        ? "切换到深色"
        : "切换到浅色";
  }

  if (state.surface === "atlas") {
    // 从 display:none 切回时容器尺寸为 0，需多次 invalidate
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
    apiInput.addEventListener("change", async () => {
      setBase(apiInput.value);
      await refresh();
      const s = getState();
      if (!s.connected) {
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
  if (getState().connected) {
    await refreshProviderPill();
  } else {
    toast("无法连接后端，请先 docker compose up -d", { err: true });
  }
}

main();
