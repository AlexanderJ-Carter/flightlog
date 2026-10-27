/** DOM / 格式 / Toast 工具 */

export function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const CABIN = {
  economy: "经济舱",
  "economy+": "超级经济舱",
  business: "公务舱",
  first: "头等舱",
};
const SEAT = { window: "靠窗", aisle: "过道", middle: "中间" };
const REASON = { leisure: "休闲", business: "公务", other: "其他" };

export function labelCabin(v) {
  return CABIN[v] || v || "";
}

export function labelSeatType(v) {
  return SEAT[v] || v || "";
}

export function labelReason(v) {
  return REASON[v] || v || "";
}

export function formatKm(km) {
  if (km == null || km === "") return "";
  const n = Number(km);
  if (!Number.isFinite(n)) return "";
  return `${Math.round(n).toLocaleString()} km`;
}

export function toast(msg, { err = false, action } = {}) {
  const t = document.getElementById("toast");
  t.className = "show" + (err ? " err" : " ok");
  t.innerHTML = "";
  t.append(document.createTextNode(msg));
  if (action) {
    const a = document.createElement("a");
    a.textContent = action.label;
    a.onclick = (e) => {
      e.preventDefault();
      action.onClick();
    };
    t.append(a);
  }
  clearTimeout(t._h);
  t._h = setTimeout(() => {
    t.className = "";
    t.innerHTML = "";
  }, action ? 4200 : 2600);
}

export function bars(el, obj, alt = false) {
  if (!el) return;
  const es = Object.entries(obj || {}).sort((a, b) =>
    alt ? b[1] - a[1] : a[0].localeCompare(b[0])
  );
  if (!es.length) {
    el.innerHTML = '<div class="hint">暂无数据</div>';
    return;
  }
  const mx = Math.max(...es.map((e) => e[1]));
  el.innerHTML = es
    .map(
      ([k, v]) =>
        `<div class="brow"><span class="bl">${esc(k)}</span>` +
        `<div class="bt"><div class="bf${alt ? " alt" : ""}" style="width:0"></div></div>` +
        `<span class="bv">${v}</span></div>`
    )
    .join("");
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      el.querySelectorAll(".bf").forEach((f, i) => {
        f.style.width = (es[i][1] / mx) * 100 + "%";
      });
    })
  );
}

export function skeletonTableRows(count = 6) {
  return Array.from({ length: count }, () =>
    "<tr class=\"skeleton-row\">" +
    "<td><span class=\"sk sk-sm\"></span></td>" +
    "<td><span class=\"sk sk-md\"></span></td>" +
    "<td><span class=\"sk sk-lg\"></span></td>" +
    "<td><span class=\"sk sk-sm\"></span></td>" +
    "<td><span class=\"sk sk-sm\"></span></td>" +
    "<td><span class=\"sk sk-xs\"></span></td>" +
    "<td><span class=\"sk sk-md\"></span></td>" +
    "<td></td></tr>"
  ).join("");
}

export function skeletonFlightCards(count = 4) {
  return Array.from({ length: count }, () =>
    '<article class="flight-card skeleton-card">' +
    '<div class="sk sk-sm" style="width:40%"></div>' +
    '<div class="sk sk-lg" style="width:70%;margin-top:.5rem"></div>' +
    '<div class="sk sk-md" style="width:55%;margin-top:.45rem"></div>' +
    "</article>"
  ).join("");
}

export function todayISO() {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}
