/** 明细表面：筛选、表格/卡片、详情、导出导入、编辑删除 */

import { api } from "../api.js";
import {
  getState,
  setFilters,
  setSurface,
  setEditing,
  refresh,
  subscribe,
} from "../store.js";
import {
  esc,
  toast,
  labelCabin,
  labelSeatType,
  labelReason,
  formatKm,
  skeletonTableRows,
  skeletonFlightCards,
} from "../util.js";
import { disconnectCopy } from "../connection.js";

let pendingImport = null;
let unsub = null;
let filterTimer = null;
let sheetFlightId = null;

function hasActiveFilters(f) {
  return !!(f.q || f.year || f.airline || f.airport);
}

function emptyMessage(state) {
  if (state.needsLogin) {
    const copy = disconnectCopy(state);
    return { icon: "◇", title: copy.title, sub: copy.sub };
  }
  if (!state.connected) {
    const copy = disconnectCopy(state);
    return { icon: "⚠", title: copy.title, sub: copy.sub };
  }
  if (hasActiveFilters(state.filters)) {
    return { icon: "⌕", title: "无匹配结果", sub: "试试清空筛选条件" };
  }
  return {
    icon: "✈",
    title: "暂无航班记录",
    sub: "切换到「录入」添加第一段航程",
  };
}

function detailHtml(f) {
  const rows = [];
  const row = (label, value) => {
    if (!value) return;
    rows.push(
      `<div class="detail-row"><span class="detail-k">${esc(label)}</span>` +
        `<span class="detail-v">${value}</span></div>`
    );
  };
  row("日期", esc(f.date));
  row("航班", `<strong>${esc(f.flight)}</strong>`);
  row("航线", `${esc(f.from)} → ${esc(f.to)}`);
  row("里程", formatKm(f.distance_km));
  if (f.aircraft) row("机型", esc(f.aircraft));
  if (f.registration) row("注册号", esc(f.registration));
  if (f.seat) row("座位", esc(f.seat));
  const seatType = labelSeatType(f.seat_type);
  if (seatType) row("座位类型", esc(seatType));
  const cabin = labelCabin(f.cabin_class);
  if (cabin) row("舱位", esc(cabin));
  const reason = labelReason(f.flight_reason);
  if (reason) row("事由", esc(reason));
  if (f.dep_time || f.arr_time) {
    row(
      "时刻",
      esc([f.dep_time, f.arr_time].filter(Boolean).join(" → "))
    );
  }
  if (f.dep_terminal || f.arr_terminal) {
    row(
      "航站楼",
      esc([f.dep_terminal, f.arr_terminal].filter(Boolean).join(" → "))
    );
  }
  if (f.dep_gate || f.arr_gate) {
    row(
      "登机口",
      esc([f.dep_gate, f.arr_gate].filter(Boolean).join(" → "))
    );
  }
  if (f.trip_id) row("行程", esc(f.trip_id));
  if (f.note) row("备注", esc(f.note));
  return rows.join("") || '<p class="muted">暂无更多字段</p>';
}

function openSheet(f) {
  sheetFlightId = f.id;
  const sheet = document.getElementById("flightSheet");
  if (!sheet) return;
  document.getElementById("flightSheetRoute").textContent =
    `${f.from} → ${f.to}`;
  document.getElementById("flightSheetTitle").textContent = f.flight;
  document.getElementById("flightSheetBody").innerHTML = detailHtml(f);
  sheet.classList.add("open");
  sheet.setAttribute("aria-hidden", "false");
  document.getElementById("flightSheetClose")?.focus();
}

function closeSheet() {
  sheetFlightId = null;
  const sheet = document.getElementById("flightSheet");
  sheet?.classList.remove("open");
  sheet?.setAttribute("aria-hidden", "true");
}

function renderCards(state, flights) {
  const wrap = document.getElementById("flightCards");
  if (!wrap) return;

  if (state.loading && !flights.length) {
    wrap.innerHTML = skeletonFlightCards(4);
    return;
  }
  if (!flights.length) {
    const m = emptyMessage(state);
    wrap.innerHTML =
      `<div class="empty"><span class="icon">${m.icon}</span>` +
      `${esc(m.title)}<br><small>${esc(m.sub)}</small></div>`;
    return;
  }

  wrap.innerHTML = flights
    .map(
      (f) =>
        `<article class="flight-card" data-flight-id="${f.id}" tabindex="0">` +
        `<div class="flight-card-top">` +
        `<time datetime="${esc(f.date)}">${esc(f.date)}</time>` +
        `<span class="flight-card-no">${esc(f.flight)}</span>` +
        `</div>` +
        `<p class="flight-card-route">${esc(f.from)} <span aria-hidden="true">→</span> ${esc(f.to)}</p>` +
        `<div class="flight-card-meta">` +
        (f.aircraft
          ? `<span class="ac-badge">${esc(f.aircraft)}</span>`
          : "") +
        (f.seat ? `<span>${esc(f.seat)}</span>` : "") +
        (f.distance_km
          ? `<span class="muted">${esc(formatKm(f.distance_km))}</span>`
          : "") +
        `</div></article>`
    )
    .join("");
}

function renderTable(state) {
  const tb = document.getElementById("tbody");
  const cnt = document.getElementById("cntInfo");
  if (!tb) return;
  const flights = state.flights || [];
  if (cnt) cnt.textContent = flights.length ? `${flights.length} 条` : "";

  renderCards(state, flights);

  if (state.loading && !flights.length) {
    tb.innerHTML = skeletonTableRows(6);
    return;
  }
  if (!flights.length) {
    const m = emptyMessage(state);
    tb.innerHTML =
      `<tr><td colspan="8" class="empty"><span class="icon">${m.icon}</span>` +
      `${esc(m.title)}<br><small>${esc(m.sub)}</small></td></tr>`;
    return;
  }

  tb.innerHTML = flights
    .map(
      (f) =>
        `<tr class="flight-row" data-flight-id="${f.id}" tabindex="0">
      <td>${esc(f.date)}</td>
      <td class="fl">${esc(f.flight)}</td>
      <td class="route">${esc(f.from)} → ${esc(f.to)}</td>
      <td>${
        f.aircraft
          ? `<span class="ac-badge">${esc(f.aircraft)}</span>`
          : '<span class="muted">–</span>'
      }</td>
      <td class="muted">${esc(f.registration) || "–"}</td>
      <td>${esc(f.seat) || '<span class="muted">–</span>'}</td>
      <td class="muted">${esc(f.note)}</td>
      <td class="row-actions">
        <button type="button" class="btn btn-sm btn-ghost" data-edit="${f.id}">编辑</button>
        <button type="button" class="btn btn-sm btn-danger" data-del="${f.id}">删除</button>
      </td>
    </tr>`
    )
    .join("");
}

function syncFilterInputs(state) {
  const f = state.filters;
  const q = document.getElementById("flSearch");
  const year = document.getElementById("flYear");
  const airline = document.getElementById("flAirline");
  const airport = document.getElementById("flAirport");
  if (q && q.value !== f.q) q.value = f.q;
  if (year && year.value !== f.year) year.value = f.year;
  if (airline && airline.value !== f.airline) airline.value = f.airline;
  if (airport && airport.value !== f.airport) airport.value = f.airport;
}

function fillYearOptions(stats) {
  const sel = document.getElementById("flYear");
  if (!sel || !stats?.years) return;
  const cur = sel.value;
  const years = Object.keys(stats.years).sort().reverse();
  sel.innerHTML =
    '<option value="">全部年份</option>' +
    years.map((y) => `<option value="${esc(y)}">${esc(y)}</option>`).join("");
  sel.value = cur;
}

function scheduleFilter(partial) {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => setFilters(partial), 220);
}

async function onDelete(id) {
  if (!confirm("确认删除这条航班记录？")) return;
  try {
    await api.deleteFlight(id);
    toast("已删除");
    if (sheetFlightId === id) closeSheet();
    await refresh();
  } catch (e) {
    toast("删除失败：" + e.message, { err: true });
  }
}

function onEdit(id) {
  const f = (getState().flights || []).find((x) => x.id === id);
  closeSheet();
  setEditing(id, f || null);
  setSurface("capture");
}

function openFlightFromTarget(target) {
  const el = target.closest("[data-flight-id]");
  if (!el || target.closest("[data-edit],[data-del]")) return;
  const id = +el.dataset.flightId;
  const f = (getState().flights || []).find((x) => x.id === id);
  if (f) openSheet(f);
}

async function doImport(replace) {
  const dialog = document.getElementById("importDialog");
  dialog?.classList.remove("open");
  if (!pendingImport) return;
  try {
    let res;
    if (pendingImport.file) {
      const source =
        document.getElementById("importSource")?.value || "auto";
      res = await api.importFile(pendingImport.file, { source, replace });
    } else {
      res = await api.importRows(pendingImport.rows || pendingImport, replace);
    }
    const skip = res.skipped?.length
      ? `，跳过 ${res.skipped.length} 条`
      : "";
    const upd = res.updated ? `，补全 ${res.updated} 条` : "";
    const src = res.source ? `（${res.source}）` : "";
    toast(
      (replace ? "已覆盖导入 " : "已追加 ") +
        res.added +
        " 条" +
        src +
        upd +
        skip
    );
    await refresh();
  } catch (e) {
    toast("导入失败：" + e.message, { err: true });
  }
  pendingImport = null;
}

export function mountLogbook() {
  document.getElementById("flSearch")?.addEventListener("input", (e) => {
    scheduleFilter({ q: e.target.value.trim() });
  });
  document.getElementById("flYear")?.addEventListener("change", (e) => {
    setFilters({ year: e.target.value });
  });
  document.getElementById("flAirline")?.addEventListener("input", (e) => {
    scheduleFilter({ airline: e.target.value.trim().toUpperCase() });
  });
  document.getElementById("flAirport")?.addEventListener("input", (e) => {
    e.target.value = e.target.value.toUpperCase();
    scheduleFilter({ airport: e.target.value.trim() });
  });

  document.getElementById("btnExportCsv")?.addEventListener("click", () => {
    const y = getState().filters.year || "";
    window.open(api.exportUrl("csv", y), "_blank");
  });
  document.getElementById("btnExportJson")?.addEventListener("click", () => {
    const y = getState().filters.year || "";
    window.open(api.exportUrl("json", y), "_blank");
  });

  document.getElementById("importFile")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const source =
      document.getElementById("importSource")?.value || "auto";
    try {
      const preview = await api.importFile(file, {
        source,
        dryRun: true,
      });
      pendingImport = { file, preview };
      const msg = document.getElementById("importDialogMsg");
      if (msg) {
        msg.textContent = `识别为 ${preview.source}，解析 ${preview.parsed} 条。选择追加或覆盖写入。`;
      }
      document.getElementById("importDialog")?.classList.add("open");
    } catch (err) {
      toast("无法解析：" + err.message, { err: true });
    }
  });

  document.getElementById("importAppend")?.addEventListener("click", () =>
    doImport(false)
  );
  document.getElementById("importReplace")?.addEventListener("click", () => {
    if (!confirm("覆盖将清空现有全部记录，再写入备份。确定？")) return;
    doImport(true);
  });
  document.getElementById("importCancel")?.addEventListener("click", () => {
    pendingImport = null;
    document.getElementById("importDialog")?.classList.remove("open");
  });
  document.getElementById("importDialog")?.addEventListener("click", (e) => {
    if (e.target?.id === "importDialog") {
      pendingImport = null;
      e.target.classList.remove("open");
    }
  });
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const dialog = document.getElementById("importDialog");
    if (dialog?.classList.contains("open")) {
      pendingImport = null;
      dialog.classList.remove("open");
      return;
    }
    if (document.getElementById("flightSheet")?.classList.contains("open")) {
      closeSheet();
    }
  });

  document.getElementById("tbody")?.addEventListener("click", (e) => {
    const edit = e.target.closest("[data-edit]");
    const del = e.target.closest("[data-del]");
    if (edit) onEdit(+edit.dataset.edit);
    else if (del) onDelete(+del.dataset.del);
    else openFlightFromTarget(e.target);
  });
  document.getElementById("tbody")?.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    openFlightFromTarget(e.target);
  });

  document.getElementById("flightCards")?.addEventListener("click", (e) => {
    openFlightFromTarget(e.target);
  });
  document.getElementById("flightCards")?.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    openFlightFromTarget(e.target);
  });

  document.getElementById("flightSheetClose")?.addEventListener("click", closeSheet);
  document.getElementById("flightSheetScrim")?.addEventListener("click", closeSheet);
  document.getElementById("flightSheetEdit")?.addEventListener("click", () => {
    if (sheetFlightId != null) onEdit(sheetFlightId);
  });
  document.getElementById("flightSheetDelete")?.addEventListener("click", () => {
    if (sheetFlightId != null) onDelete(sheetFlightId);
  });

  unsub = subscribe((state) => {
    if (state.surface !== "logbook") return;
    syncFilterInputs(state);
    fillYearOptions(state.stats);
    renderTable(state);
  });
  renderTable(getState());
  fillYearOptions(getState().stats);
}
