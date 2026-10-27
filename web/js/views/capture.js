/** 录入表面：手动 / 查询 / 短信；机场校验；成功后回地图 */

import { api } from "../api.js";
import {
  getState,
  setSurface,
  clearEditing,
  refresh,
  isKnownAirport,
  subscribe,
} from "../store.js";
import { esc, toast, todayISO } from "../util.js";

function notifyConfigChanged() {
  window.dispatchEvent(new CustomEvent("fl-config-changed"));
}

let unsub = null;
let extractRows = [];

function bindAirportHint(inputId, hintId) {
  const input = document.getElementById(inputId);
  const hint = document.getElementById(hintId);
  const field = input?.closest(".field");
  if (!input) return;
  const check = () => {
    const v = input.value.trim().toUpperCase();
    input.value = v;
    if (!v || v.length < 3) {
      field?.classList.remove("unknown");
      if (hint) hint.textContent = "";
      return;
    }
    if (!isKnownAirport(v)) {
      field?.classList.add("unknown");
      if (hint)
        hint.textContent = "未收录：可入库，但里程不计、不进地图";
    } else {
      field?.classList.remove("unknown");
      if (hint) hint.textContent = "";
    }
  };
  input.addEventListener("blur", check);
  input.addEventListener("input", () => {
    input.value = input.value.toUpperCase();
  });
}

function fillManualFromFlight(f) {
  document.getElementById("mDate").value = f.date || "";
  document.getElementById("mFlight").value = f.flight || "";
  document.getElementById("mFrom").value = f.from || "";
  document.getElementById("mTo").value = f.to || "";
  document.getElementById("mSeat").value = f.seat || "";
  document.getElementById("mAircraft").value = f.aircraft || "";
  const st = document.getElementById("mSeatType");
  if (st) st.value = f.seat_type || "";
  const cab = document.getElementById("mCabin");
  if (cab) cab.value = f.cabin_class || "";
  const reason = document.getElementById("mReason");
  if (reason) reason.value = f.flight_reason || "";
  const reg = document.getElementById("mReg");
  if (reg) reg.value = f.registration || "";
  const set = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.value = v || "";
  };
  set("mDepTime", f.dep_time);
  set("mArrTime", f.arr_time);
  set("mDepTerm", f.dep_terminal);
  set("mArrTerm", f.arr_terminal);
  set("mDepGate", f.dep_gate);
  set("mArrGate", f.arr_gate);
  set("mTrip", f.trip_id);
  document.getElementById("mNote").value = f.note || "";
}

function syncEditMode(state) {
  const btn = document.getElementById("mSubmit");
  const cancel = document.getElementById("mCancel");
  const hint = document.getElementById("mHint");
  if (state.editingId) {
    const f =
      state.editingFlight ||
      (state.flights || []).find((x) => x.id === state.editingId);
    if (f) fillManualFromFlight(f);
    if (btn) btn.textContent = "保存修改";
    if (cancel) cancel.style.display = "";
    if (hint) hint.textContent = "正在编辑 #" + state.editingId;
    showTab("manual");
  } else {
    if (btn) btn.textContent = "录入档案";
    if (cancel) cancel.style.display = "none";
    if (hint) hint.textContent = "";
  }
}

function showTab(name) {
  document.querySelectorAll(".capture-tabs .tab").forEach((t) => {
    const on = t.dataset.tab === name;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on ? "true" : "false");
    t.tabIndex = on ? 0 : -1;
  });
  document.querySelectorAll(".tab-panel").forEach((p) => {
    const on = p.id === "panel-" + name;
    p.classList.toggle("active", on);
    if (on) p.removeAttribute("hidden");
    else p.setAttribute("hidden", "");
  });
}

function afterSave(msg = "航迹已落档") {
  toast(msg, {
    action: {
      label: "在地图上查看",
      onClick: () => setSurface("atlas"),
    },
  });
  clearEditing();
  [
    "mDate", "mFlight", "mFrom", "mTo", "mSeat", "mNote", "mAircraft", "mReg",
    "mDepTime", "mArrTime", "mDepTerm", "mArrTerm", "mDepGate", "mArrGate", "mTrip",
    "mSeatType", "mCabin", "mReason",
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  refresh();
}

async function submitManual() {
  const date = document.getElementById("mDate").value.trim();
  const flight = document.getElementById("mFlight").value.trim().toUpperCase();
  const from = document.getElementById("mFrom").value.trim().toUpperCase();
  const to = document.getElementById("mTo").value.trim().toUpperCase();
  const seat = document.getElementById("mSeat").value.trim();
  const note = document.getElementById("mNote").value.trim();
  const aircraft = document.getElementById("mAircraft").value.trim();
  const registration = (
    document.getElementById("mReg")?.value || ""
  )
    .trim()
    .toUpperCase();
  if (!date || !flight || !from || !to) {
    return toast("请填写日期、航班号、出发、到达", { err: true });
  }
  const seat_type = document.getElementById("mSeatType")?.value || "";
  const cabin_class = document.getElementById("mCabin")?.value || "";
  const flight_reason = document.getElementById("mReason")?.value || "";
  const body = {
    date, flight, from, to, seat, note, aircraft, registration,
    seat_type, cabin_class, flight_reason,
    dep_time: document.getElementById("mDepTime")?.value || "",
    arr_time: document.getElementById("mArrTime")?.value || "",
    dep_terminal: document.getElementById("mDepTerm")?.value || "",
    arr_terminal: document.getElementById("mArrTerm")?.value || "",
    dep_gate: document.getElementById("mDepGate")?.value || "",
    arr_gate: document.getElementById("mArrGate")?.value || "",
    trip_id: document.getElementById("mTrip")?.value || "",
  };
  const editingId = getState().editingId;
  try {
    if (editingId) {
      await api.updateFlight(editingId, body);
      afterSave("已保存修改");
    } else {
      await api.addFlight(body);
      afterSave();
    }
  } catch (e) {
    if (e.status === 409) {
      toast("已存在相同航班记录", { err: true });
    } else {
      toast((editingId ? "保存" : "录入") + "失败：" + e.message, {
        err: true,
      });
    }
  }
}

function renderLookupHit(j, date) {
  window._lk = j;
  const src =
    j.source === "adsbdb"
      ? "航线库"
      : j.source === "aviationstack"
        ? "实时"
        : j.source || "";
  const times =
    j.dep_time || j.arr_time
      ? ` · ${esc(j.dep_time || "")} ~ ${esc(j.arr_time || "")}`
      : "";
  const ac = j.aircraft ? ` · 机型 ${esc(j.aircraft)}` : "";
  const reg = j.registration ? ` · ${esc(j.registration)}` : "";
  const names =
    j.from_name || j.to_name
      ? `<div class="sub">${esc(j.from_name || j.from)} → ${esc(
          j.to_name || j.to
        )}</div>`
      : "";
  const note = j.note ? ` · ${esc(j.note)}` : "";
  const photo = j.photo
    ? `<img class="ac-thumb" src="${esc(j.photo)}" alt="" loading="lazy">`
    : "";
  return `<div class="result">${photo}<div class="info"><b>${esc(
    j.flight
  )}</b> · ${esc(j.date || date)}${
    src ? ` <span class="ac-badge">${esc(src)}</span>` : ""
  }
    <div class="sub">${esc(j.from)} → ${esc(j.to)} · ${esc(
    j.airline || ""
  )}${times}${ac}${reg}${note}</div>${names}</div>
    <button class="btn btn-primary btn-sm" id="btnSaveLk">存入档案</button></div>`;
}

function renderLookupCandidates(j, date) {
  window._lkCandidates = j.candidates || [];
  const setup = j.setup_required
    ? `<button type="button" class="btn btn-sm btn-ghost" id="btnGoSmart">打开高级设置</button>`
    : "";
  const rows = window._lkCandidates
    .map((c, i) => {
      const route =
        c.from && c.to
          ? `${esc(c.from)} → ${esc(c.to)}`
          : "选择后查询实时详情";
      const ac = c.aircraft ? ` · 机型 ${esc(c.aircraft)}` : "";
      const tag =
        c.source === "ai" || c.suggested
          ? "AI"
          : c.source === "aviationstack"
            ? "实时"
            : c.source === "adsbdb"
              ? "航线库"
              : "候选";
      return `<div class="result">
        <div class="info"><b>${esc(c.flight)}</b> · ${esc(c.airline || "")}
          <span class="ac-badge" style="margin-left:.35rem">${tag}</span>
          <div class="sub">${route}${ac}${
            c.note ? " · " + esc(c.note) : ""
          }</div></div>
        <button class="btn btn-primary btn-sm" data-pick="${i}">选择</button>
      </div>`;
    })
    .join("");
  return `<div class="result"><div class="info" style="color:var(--text2)">${esc(
    j.reason || "请选择航班"
  )} ${setup}</div></div>${rows}`;
}

async function doLookup() {
  const flight = document
    .getElementById("lkFlight")
    .value.trim()
    .toUpperCase();
  const date = document.getElementById("lkDate").value;
  if (!flight || !date) return toast("请输入航班号和日期", { err: true });
  const el = document.getElementById("lkResult");
  el.innerHTML = '<div class="hint"><span class="spin"></span>查询中…</div>';
  try {
    const j = await api.lookup(flight, date);
    if (j.found) {
      el.innerHTML = renderLookupHit(j, date);
      document.getElementById("btnSaveLk")?.addEventListener("click", saveLk);
      return;
    }
    if (j.candidates?.length) {
      el.innerHTML = renderLookupCandidates(j, date);
      el.querySelectorAll("[data-pick]").forEach((btn) => {
        btn.addEventListener("click", () => onPickCandidate(+btn.dataset.pick, date));
      });
      document.getElementById("btnGoSmart")?.addEventListener("click", () => {
        showTab("smart");
        refreshSmartStatus();
      });
      return;
    }
    const setupBtn = j.setup_required
      ? ` <button type="button" class="btn btn-sm btn-primary" id="btnGoSmart2">去配置</button>`
      : "";
    el.innerHTML = `<div class="result"><div class="info" style="color:var(--text2)">未查到${
      j.reason ? "：" + esc(j.reason) : ""
    }${setupBtn}
      <div class="sub">实时查询需 AviationStack；纯数字消歧可再配 LLM。免费档多覆盖近期航班。</div></div></div>`;
    document.getElementById("btnGoSmart2")?.addEventListener("click", () => {
      showTab("smart");
      refreshSmartStatus();
    });
  } catch (e) {
    const net =
      !e.status &&
      /failed to fetch|networkerror|load failed/i.test(e.message || "");
    const tip = net
      ? "无法连接后端。请先启动服务，并确认顶栏显示「已连接」。"
      : "查询失败：" + (e.message || "未知错误");
    el.innerHTML = `<div class="result"><div class="info" style="color:var(--red)">${esc(
      tip
    )}</div></div>`;
  }
}

async function onPickCandidate(i, date) {
  const c = (window._lkCandidates || [])[i];
  if (!c) return;
  document.getElementById("lkFlight").value = c.flight;
  // 实时或免费航线库命中（有起降）可直接存
  if (c.from && c.to && (c.source === "aviationstack" || c.source === "adsbdb")) {
    const el = document.getElementById("lkResult");
    el.innerHTML = renderLookupHit({ ...c, found: true, date: c.date || date }, date);
    document.getElementById("btnSaveLk")?.addEventListener("click", saveLk);
    return;
  }
  // AI 候选：若已有起降，允许核对后直接存；否则再查实时
  if (c.from && c.to && (c.source === "ai" || c.suggested)) {
    if (
      !confirm(
        `${c.flight} ${c.from}→${c.to} 来自 AI 推断，尚未被实时数据核实。确认按此入库？`
      )
    ) {
      return;
    }
    const el = document.getElementById("lkResult");
    el.innerHTML = renderLookupHit({ ...c, found: true, date: c.date || date }, date);
    document.getElementById("btnSaveLk")?.addEventListener("click", saveLk);
    return;
  }
  await doLookup();
}

function fmtTime(ts) {
  if (!ts) return "尚未采集";
  const d = new Date(ts * 1000);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString();
}

async function refreshFleetStatus() {
  const box = document.getElementById("fleetStatus");
  if (!box) return;
  try {
    const f = await api.fleet();
    const fl = f.fleet || {};
    box.innerHTML = [
      ["机尾库", fl.aircraft ?? "–"],
      ["呼号观测", fl.sightings ?? "–"],
      ["参考航线", fl.routes ?? "–"],
      ["定时", f.auto ? `${f.interval_hours}h` : "关"],
    ]
      .map(
        ([lbl, num]) =>
          `<div class="stat-item"><span class="num accent">${esc(
            String(num)
          )}</span><span class="lbl">${lbl}</span></div>`
      )
      .join("");
    const auto = document.getElementById("fleetAuto");
    const interval = document.getElementById("fleetInterval");
    if (auto) auto.value = f.auto ? "1" : "0";
    if (interval && !interval.dataset.touched)
      interval.value = String(f.interval_hours || 6);
    const hint = document.getElementById("fleetHint");
    if (hint) {
      hint.textContent =
        (f.busy ? "采集中… · " : "") +
        "上次：" +
        fmtTime(f.last_harvest_at) +
        (f.last_harvest_msg ? ` · ${f.last_harvest_msg}` : "");
    }
  } catch {
    box.innerHTML =
      '<div class="stat-item"><span class="lbl">飞友库不可用</span></div>';
  }
}

async function refreshSmartStatus() {
  const box = document.getElementById("smartStatus");
  if (!box) return;
  try {
    const s = await api.config();
    box.innerHTML = [
      ["免费航线库", true],
      ["实时 API", s.live_lookup],
      ["LLM", s.llm],
    ]
      .map(
        ([n, on]) =>
          `<div class="stat-item"><span class="num ${on ? "accent" : ""}">${
            on ? "已启用" : "未配置"
          }</span><span class="lbl">${n}</span></div>`
      )
      .join("");
    const base = document.getElementById("cfgLlmBase");
    const model = document.getElementById("cfgLlmModel");
    if (base && !base.dataset.touched) {
      base.placeholder = s.llm_base
        ? "已设置（输入新值覆盖）"
        : "https://api.openai.com/v1";
    }
    if (model && !model.dataset.touched) {
      model.placeholder = s.llm
        ? "已设置（输入新值覆盖）"
        : "gpt-4o-mini";
    }
    const avHint = document.getElementById("cfgAviationHint");
    if (avHint) {
      avHint.textContent = s.aviationstack
        ? "已配置 · 输入新 key 覆盖，或点清除"
        : "注册：https://aviationstack.com/signup/free";
    }
    await refreshFleetStatus();
  } catch {
    box.innerHTML = '<div class="stat-item"><span class="lbl">无法读取配置</span></div>';
  }
}

async function saveFleetSettings() {
  const auto = document.getElementById("fleetAuto")?.value === "1";
  const hours = parseFloat(document.getElementById("fleetInterval")?.value || "6");
  try {
    await api.fleetSettings({ auto, interval_hours: hours });
    toast(auto ? `已开启自动采集 · 每 ${hours} 小时` : "已关闭自动采集");
    await refreshFleetStatus();
  } catch (e) {
    toast("保存失败：" + e.message, { err: true });
  }
}

async function triggerHarvest() {
  try {
    const r = await api.fleetHarvest();
    if (r.busy) return toast("采集正在进行中", { err: true });
    toast("已开始采集（约 1 分钟）");
    setTimeout(refreshFleetStatus, 8000);
    setTimeout(refreshFleetStatus, 35000);
  } catch (e) {
    toast("无法启动采集：" + e.message, { err: true });
  }
}

async function saveSmartKeys() {
  const body = {};
  const av = document.getElementById("cfgAviation")?.value ?? "";
  const llm = document.getElementById("cfgLlm")?.value ?? "";
  const base = document.getElementById("cfgLlmBase")?.value ?? "";
  const model = document.getElementById("cfgLlmModel")?.value ?? "";
  if (document.getElementById("cfgAviation").dataset.touched === "1")
    body.aviationstack = av.trim();
  if (document.getElementById("cfgLlm").dataset.touched === "1")
    body.llm = llm.trim();
  if (document.getElementById("cfgLlmBase").dataset.touched === "1")
    body.llm_base = base.trim();
  if (document.getElementById("cfgLlmModel").dataset.touched === "1")
    body.llm_model = model.trim();
  if (!Object.keys(body).length) {
    return toast("请先修改至少一个配置项", { err: true });
  }
  try {
    const r = await api.saveKeys(body);
    toast(
      "已保存 · 实时 " +
        (r.live_lookup ? "✓" : "✗") +
        " · LLM " +
        (r.llm ? "✓" : "✗")
    );
    ["cfgAviation", "cfgLlm", "cfgLlmBase", "cfgLlmModel"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) {
        el.value = "";
        el.dataset.touched = "";
      }
    });
    await refreshSmartStatus();
    notifyConfigChanged();
  } catch (e) {
    toast("保存失败：" + e.message, { err: true });
  }
}

async function clearKey(field) {
  try {
    await api.saveKeys({ [field]: "" });
    toast("已清除 " + field);
    await refreshSmartStatus();
    notifyConfigChanged();
  } catch (e) {
    toast("清除失败：" + e.message, { err: true });
  }
}

function dateFallback() {
  return document.getElementById("lkDate")?.value || todayISO();
}

async function saveLk() {
  const d = window._lk;
  if (!d) return;
  try {
    await api.addFlight({
      date: d.date || dateFallback(),
      flight: d.flight,
      from: d.from,
      to: d.to,
      seat: d.seat || "",
      note: d.note || "",
      aircraft: d.aircraft || "",
      registration: d.registration || "",
    });
    document.getElementById("lkResult").innerHTML = "";
    afterSave();
  } catch (e) {
    toast(
      e.status === 409 ? "已存在相同记录" : "保存失败：" + e.message,
      { err: true }
    );
  }
}

async function doExtract() {
  const text = document.getElementById("imText").value.trim();
  if (!text) return toast("请粘贴文本", { err: true });
  const el = document.getElementById("imResult");
  el.innerHTML = '<div class="hint"><span class="spin"></span>解析中…</div>';
  try {
    const j = await api.extract(text);
    if (!j.rows?.length) {
      el.innerHTML =
        '<div class="result"><div class="info" style="color:var(--text2)">未解析出航班信息' +
        '<div class="sub">试试包含「航班号 + 日期 + 城市」的完整文本</div></div></div>';
      return;
    }
    extractRows = j.rows;
    el.innerHTML =
      j.rows
        .map(
          (row, i) => `
      <div class="result" data-row="${i}">
        <label style="display:flex;align-items:flex-start;padding-top:.35rem">
          <input type="checkbox" checked data-i="${i}" style="accent-color:var(--accent);width:16px;height:16px">
        </label>
        <div class="info" style="width:100%">
          <b>${esc(row.flight) || "（补航班号）"}</b>
          <div class="result-edit">
            <input data-f="date" value="${esc(row.date)}" placeholder="日期" type="date">
            <input data-f="flight" value="${esc(row.flight)}" placeholder="航班号" style="text-transform:uppercase">
            <input data-f="from" value="${esc(row.from)}" placeholder="出发" maxlength="3" style="text-transform:uppercase">
            <input data-f="to" value="${esc(row.to)}" placeholder="到达" maxlength="3" style="text-transform:uppercase">
            <input data-f="seat" value="${esc(row.seat)}" placeholder="座位">
            <input data-f="aircraft" value="${esc(row.aircraft || "")}" placeholder="机型">
          </div>
        </div>
      </div>`
        )
        .join("") +
      '<button class="btn btn-primary" id="btnBatchImport">批量入库</button>';
    document
      .getElementById("btnBatchImport")
      ?.addEventListener("click", batchImport);
  } catch (e) {
    el.innerHTML = `<div class="result"><div class="info" style="color:var(--red)">解析失败：${esc(
      e.message
    )}</div></div>`;
  }
}

function readEditedRow(i) {
  const box = document.querySelector(`.result[data-row="${i}"]`);
  if (!box) return extractRows[i];
  const get = (f) =>
    (box.querySelector(`[data-f="${f}"]`)?.value || "").trim();
  return {
    date: get("date"),
    flight: get("flight").toUpperCase(),
    from: get("from").toUpperCase(),
    to: get("to").toUpperCase(),
    seat: get("seat"),
    aircraft: get("aircraft"),
    note: extractRows[i]?.note || "",
  };
}

async function batchImport() {
  const sel = [
    ...document.querySelectorAll("#imResult input[type=checkbox]:checked"),
  ].map((c) => +c.dataset.i);
  let ok = 0;
  let dup = 0;
  for (const i of sel) {
    const row = readEditedRow(i);
    if (!row.date || !row.flight || !row.from || !row.to) continue;
    try {
      await api.addFlight(row);
      ok++;
    } catch (e) {
      if (e.status === 409) dup++;
    }
  }
  document.getElementById("imResult").innerHTML = "";
  document.getElementById("imText").value = "";
  if (ok) {
    toast(
      `已入库 ${ok}/${sel.length}` + (dup ? `，重复跳过 ${dup}` : ""),
      {
        action: {
          label: "在地图上查看",
          onClick: () => setSurface("atlas"),
        },
      }
    );
    clearEditing();
    refresh();
  } else {
    toast(
      dup ? `全部重复，跳过 ${dup} 条` : "没有成功入库的记录",
      { err: true }
    );
    refresh();
  }
}

export function mountCapture() {
  document.querySelectorAll(".tab").forEach((t) => {
    t.addEventListener("click", () => {
      showTab(t.dataset.tab);
      if (t.dataset.tab === "smart") refreshSmartStatus();
    });
  });
  document.getElementById("mSubmit")?.addEventListener("click", submitManual);
  document.getElementById("mCancel")?.addEventListener("click", () => {
    clearEditing();
    ["mDate", "mFlight", "mFrom", "mTo", "mSeat", "mNote", "mAircraft", "mReg"].forEach(
      (id) => {
        const el = document.getElementById(id);
        if (el) el.value = "";
      }
    );
  });
  document.getElementById("btnLookup")?.addEventListener("click", doLookup);
  document.getElementById("mReg")?.addEventListener("input", (e) => {
    e.target.value = e.target.value.toUpperCase();
  });
  document.getElementById("lkFlight")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      doLookup();
    }
  });
  document.getElementById("lkDate")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      doLookup();
    }
  });
  document.getElementById("btnExtract")?.addEventListener("click", doExtract);
  document.getElementById("btnSaveKeys")?.addEventListener("click", saveSmartKeys);
  document
    .getElementById("btnRefreshCfg")
    ?.addEventListener("click", refreshSmartStatus);
  document.getElementById("btnFleetSave")?.addEventListener("click", saveFleetSettings);
  document.getElementById("btnFleetHarvest")?.addEventListener("click", triggerHarvest);
  document.getElementById("fleetInterval")?.addEventListener("input", (e) => {
    e.target.dataset.touched = "1";
  });
  document
    .getElementById("btnClearAviation")
    ?.addEventListener("click", () => clearKey("aviationstack"));
  document
    .getElementById("btnClearLlm")
    ?.addEventListener("click", () => clearKey("llm"));
  ["cfgAviation", "cfgLlm", "cfgLlmBase", "cfgLlmModel"].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", (e) => {
      e.target.dataset.touched = "1";
    });
  });

  bindAirportHint("mFrom", "mFromHint");
  bindAirportHint("mTo", "mToHint");

  const mDate = document.getElementById("mDate");
  const lkDate = document.getElementById("lkDate");
  if (mDate && !mDate.value) mDate.value = todayISO();
  if (lkDate && !lkDate.value) lkDate.value = todayISO();

  document.getElementById("mFlight")?.addEventListener("input", (e) => {
    e.target.value = e.target.value.toUpperCase();
  });

  unsub = subscribe((state) => {
    if (state.surface !== "capture") return;
    syncEditMode(state);
  });
  syncEditMode(getState());
}
