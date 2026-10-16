/** 明细表面：筛选、表格、导出导入、编辑删除 */

import { api } from "../api.js";
import {
  getState,
  setFilters,
  setSurface,
  setEditing,
  refresh,
  subscribe,
} from "../store.js";
import { esc, toast } from "../util.js";

let pendingImport = null;
let unsub = null;
let filterTimer = null;

function hasActiveFilters(f) {
  return !!(f.q || f.year || f.airline || f.airport);
}

function renderTable(state) {
  const tb = document.getElementById("tbody");
  const cnt = document.getElementById("cntInfo");
  if (!tb) return;
  const flights = state.flights || [];
  if (cnt) cnt.textContent = flights.length ? `${flights.length} 条` : "";

  if (state.loading && !flights.length) {
    tb.innerHTML =
      '<tr><td colspan="8" class="hint"><span class="spin"></span>加载中…</td></tr>';
    return;
  }
  if (!state.connected) {
    tb.innerHTML =
      '<tr><td colspan="8" class="empty"><span class="icon">⚠</span>' +
      "无法连接后端<br><small>请先启动服务后再查看明细</small></td></tr>";
    return;
  }
  if (!flights.length) {
    if (hasActiveFilters(state.filters)) {
      tb.innerHTML =
        '<tr><td colspan="8" class="empty"><span class="icon">⌕</span>' +
        "无匹配结果<br><small>试试清空筛选条件</small></td></tr>";
    } else {
      tb.innerHTML =
        '<tr><td colspan="8" class="empty"><span class="icon">✈</span>' +
        "暂无航班记录<br><small>切换到「录入」添加第一段航程</small></td></tr>";
    }
    return;
  }

  tb.innerHTML = flights
    .map(
      (f) =>
        `<tr>
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
        <button class="btn btn-sm btn-ghost" data-edit="${f.id}">编辑</button>
        <button class="btn btn-sm btn-danger" data-del="${f.id}">删除</button>
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
    await refresh();
  } catch (e) {
    toast("删除失败：" + e.message, { err: true });
  }
}

function onEdit(id) {
  const f = (getState().flights || []).find((x) => x.id === id);
  setEditing(id, f || null);
  setSurface("capture");
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
      // 先 dry-run 预览条数
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
    }
  });

  document.getElementById("tbody")?.addEventListener("click", (e) => {
    const edit = e.target.closest("[data-edit]");
    const del = e.target.closest("[data-del]");
    if (edit) onEdit(+edit.dataset.edit);
    if (del) onDelete(+del.dataset.del);
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
