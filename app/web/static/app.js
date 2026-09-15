(() => {
  const { t, tSetting, tCategory, applyStaticTranslations, SUPPORTED_LOCALES, detectBrowserLocale, getStoredLocale, setStoredLocale, loadLocale } = window.AckiologsI18n;

  const state = { token: localStorage.getItem("ackiologs_token") || null, ws: null, chart: null, tags: [] };

  const $ = (sel) => document.querySelector(sel);
  const api = async (path, opts = {}) => {
    const headers = opts.headers || {};
    if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
    const res = await fetch(path, { ...opts, headers });
    if (res.status === 401) {
      logout();
      throw new Error("unauthorized");
    }
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  };

  // --- Language selector ---
  function populateLangSelect(select) {
    select.innerHTML = "";
    for (const loc of SUPPORTED_LOCALES) {
      const opt = document.createElement("option");
      opt.value = loc;
      opt.textContent = t(`languages.${loc}`);
      select.appendChild(opt);
    }
  }

  async function switchLocale(loc, persist) {
    await loadLocale(loc);
    if (persist) setStoredLocale(loc);
    applyStaticTranslations();
    $("#login-lang-select").value = loc;
    $("#lang-select").value = loc;
    // re-render every currently-loaded dynamic view so translated text refreshes too
    if (!$("#app-screen").hidden) {
      loadTags();
      loadAlarms();
      loadConnections();
      loadOpcuaServerStatus();
      loadModbusServerStatus();
      if (document.querySelector('.nav-btn[data-view="settings"]').classList.contains("active")) loadSettings();
      if (document.querySelector('.nav-btn[data-view="history"]').classList.contains("active")) loadHistory();
    }
  }

  function wireLangSelectors() {
    populateLangSelect($("#login-lang-select"));
    populateLangSelect($("#lang-select"));
    $("#login-lang-select").value = window.AckiologsI18n.locale;
    $("#lang-select").value = window.AckiologsI18n.locale;
    $("#login-lang-select").addEventListener("change", (e) => switchLocale(e.target.value, true));
    $("#lang-select").addEventListener("change", (e) => switchLocale(e.target.value, true));
  }

  async function showApp() {
    $("#login-screen").hidden = true;
    $("#app-screen").hidden = false;
    connectWs();
    loadTags();
    loadAlarms();
    loadConnections();
    loadOpcuaServerStatus();
    loadModbusServerStatus();
    setInterval(loadAlarms, 15000);
    setInterval(loadConnections, 15000);
    setInterval(loadOpcuaServerStatus, 15000);
    setInterval(loadModbusServerStatus, 15000);

    // if the user hasn't picked their own language, adopt the site's default once logged in
    if (!getStoredLocale()) {
      try {
        const settings = await api("/api/settings");
        const siteLang = settings.find((s) => s.key === "display.language");
        if (siteLang && siteLang.value && siteLang.value !== window.AckiologsI18n.locale) {
          await switchLocale(siteLang.value, false);
        }
      } catch (e) {
        /* not fatal — keep the browser-detected language */
      }
    }
  }

  function logout() {
    state.token = null;
    localStorage.removeItem("ackiologs_token");
    $("#app-screen").hidden = true;
    $("#login-screen").hidden = false;
    if (state.ws) state.ws.close();
  }

  $("#login-btn").addEventListener("click", async () => {
    const username = $("#login-user").value.trim();
    const password = $("#login-pass").value;
    const body = new URLSearchParams({ username, password });
    try {
      const res = await fetch("/api/auth/token", { method: "POST", body });
      if (!res.ok) throw new Error("bad credentials");
      const data = await res.json();
      state.token = data.access_token;
      localStorage.setItem("ackiologs_token", state.token);
      $("#login-error").hidden = true;
      showApp();
    } catch (e) {
      $("#login-error").textContent = t("login.error");
      $("#login-error").hidden = false;
    }
  });
  $("#logout-btn").addEventListener("click", logout);

  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
      btn.classList.add("active");
      $(`#view-${btn.dataset.view}`).classList.add("active");
      if (btn.dataset.view === "trend") loadTrend();
      if (btn.dataset.view === "settings") loadSettings();
      if (btn.dataset.view === "connections") { loadOpcuaServerStatus(); loadModbusServerStatus(); }
      if (btn.dataset.view === "history") loadHistory({ resetOffset: true });
    });
  });

  const liveRows = new Map();

  async function loadTags() {
    const tags = await api("/api/tags");
    state.tags = tags;
    const tbody = $("#live-table tbody");
    tbody.innerHTML = "";
    liveRows.clear();
    const trendSelect = $("#trend-tag");
    const prevTrendTag = trendSelect.value;
    trendSelect.innerHTML = "";
    for (const tag of tags) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${tag.name}</td><td class="v">${fmt(tag.live_value)}</td><td>${tag.engineering_units || ""}</td>
        <td class="q quality-${tag.live_quality || "uncertain"}">${qualityLabel(tag.live_quality)}</td>
        <td class="ts">${tag.live_ts ? new Date(tag.live_ts).toLocaleTimeString() : t("common.dash")}</td>
        <td><button class="small-link" data-tag="${tag.name}">${t("live.trendBtn")}</button></td>`;
      tbody.appendChild(tr);
      liveRows.set(tag.name, tr);

      const opt = document.createElement("option");
      opt.value = tag.name;
      opt.textContent = tag.name;
      trendSelect.appendChild(opt);
    }
    if (prevTrendTag && tags.some((tag) => tag.name === prevTrendTag)) trendSelect.value = prevTrendTag;
    tbody.querySelectorAll("button[data-tag]").forEach((b) =>
      b.addEventListener("click", () => {
        $("#trend-tag").value = b.dataset.tag;
        document.querySelector('.nav-btn[data-view="trend"]').click();
      })
    );

    const historyTagSelect = $("#history-tag");
    const prevHistoryTag = historyTagSelect.value;
    historyTagSelect.innerHTML = `<option value="">${t("history.allTags")}</option>`;
    for (const tag of tags) {
      const opt = document.createElement("option");
      opt.value = tag.name;
      opt.textContent = tag.name;
      historyTagSelect.appendChild(opt);
    }
    if (prevHistoryTag && tags.some((tag) => tag.name === prevHistoryTag)) historyTagSelect.value = prevHistoryTag;
  }

  function fmt(v) {
    if (v === null || v === undefined) return t("common.dash");
    if (typeof v === "number") return Number.isInteger(v) ? v : v.toFixed(3);
    return String(v);
  }

  function qualityLabel(q) {
    if (!q) return t("quality.uncertain");
    return t(`quality.${q}`) === `quality.${q}` ? q : t(`quality.${q}`);
  }

  function connectWs() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const query = state.token ? `?token=${encodeURIComponent(state.token)}` : "";
    const ws = new WebSocket(`${proto}://${location.host}/ws/live${query}`);
    state.ws = ws;
    ws.onopen = () => $("#conn-dot").classList.add("on");
    ws.onclose = () => {
      $("#conn-dot").classList.remove("on");
      setTimeout(() => { if (!$("#app-screen").hidden) connectWs(); }, 3000);
    };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      const row = liveRows.get(msg.tag);
      if (!row) return;
      row.querySelector(".v").textContent = fmt(msg.value);
      row.querySelector(".q").textContent = qualityLabel(msg.quality);
      row.querySelector(".q").className = `q quality-${msg.quality}`;
      row.querySelector(".ts").textContent = new Date(msg.ts).toLocaleTimeString();
    };
  }

  // Crosshair cursor (FactoryTalk/PI-Vision-style): a vertical line that follows the
  // mouse and a readout of the exact time/value at the nearest sample. Registered once
  // globally; per-chart state lives on chart.$crosshair since the chart instance is
  // recreated on every loadTrendData() call.
  const crosshairPlugin = {
    id: "ackiologsCrosshair",
    afterInit(chart) {
      chart.$crosshair = { x: null };
    },
    afterEvent(chart, args) {
      const event = args.event;
      if (event.type === "mousemove" || event.type === "mouseover") {
        chart.$crosshair.x = event.x;
        args.changed = true;
      } else if (event.type === "mouseout") {
        chart.$crosshair.x = null;
        args.changed = true;
        const readout = $("#trend-cursor-readout");
        if (readout) readout.hidden = true;
      }
    },
    afterDraw(chart) {
      const x = chart.$crosshair && chart.$crosshair.x;
      const readout = $("#trend-cursor-readout");
      if (x == null) {
        if (readout) readout.hidden = true;
        return;
      }
      const { ctx, chartArea, scales } = chart;
      if (!chartArea || x < chartArea.left || x > chartArea.right) {
        if (readout) readout.hidden = true;
        return;
      }
      const dataset = chart.data.datasets[0];
      const labels = chart.data.labels;
      if (!dataset || !labels || !labels.length) return;

      ctx.save();
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(100,116,139,0.6)";
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.restore();

      const targetTime = scales.x.getValueForPixel(x);
      let nearestIdx = 0;
      let minDiff = Infinity;
      for (let i = 0; i < labels.length; i++) {
        const labelTime = labels[i].getTime();
        const diff = Math.abs(labelTime - targetTime);
        if (diff < minDiff) {
          minDiff = diff;
          nearestIdx = i;
        }
      }
      const value = dataset.data[nearestIdx];
      const time = labels[nearestIdx];
      if (value === null || value === undefined) {
        if (readout) readout.hidden = true;
        return;
      }

      const px = scales.x.getPixelForValue(time.getTime());
      const py = scales.y.getPixelForValue(value);
      ctx.save();
      ctx.beginPath();
      ctx.arc(px, py, 4, 0, Math.PI * 2);
      ctx.fillStyle = dataset.borderColor || "#2563eb";
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = "#fff";
      ctx.stroke();
      ctx.restore();

      if (readout) {
        readout.hidden = false;
        readout.innerHTML =
          `<div class="readout-time">${time.toLocaleString()}</div>` +
          `<div class="readout-value">${fmt(value)}</div>`;
        const wrapWidth = readout.parentElement.clientWidth;
        const readoutWidth = readout.offsetWidth || 150;
        let left = px + 12;
        if (left + readoutWidth > wrapWidth) left = Math.max(8, px - readoutWidth - 12);
        readout.style.left = `${left}px`;
      }
    },
  };
  let pluginsRegistered = false;
  function ensurePluginsRegistered() {
    if (pluginsRegistered) return;
    if (window.ChartZoom) Chart.register(window.ChartZoom);
    Chart.register(crosshairPlugin);
    pluginsRegistered = true;
  }

  async function loadTrendData(tag, start, end) {
    const rangeSec = (end.getTime() - start.getTime()) / 1000;
    const bucket = rangeSec > 7200 ? Math.max(10, Math.round(rangeSec / 500)) : 0;
    const url = `/api/history/${encodeURIComponent(tag)}?start=${start.toISOString()}&end=${end.toISOString()}&interval_seconds=${bucket}`;
    const data = await api(url);
    const labels = data.points.map((p) => new Date(p.ts));
    const values = data.points.map((p) => (data.mode === "bucketed" ? p.avg : p.value));

    ensurePluginsRegistered();
    if (state.chart) state.chart.destroy();
    state.chart = new Chart($("#trend-chart"), {
      type: "line",
      data: { labels, datasets: [{ label: tag, data: values, borderColor: "#2563eb", pointRadius: 0, tension: 0.15 }] },
      options: {
        responsive: true,
        animation: false,
        interaction: { intersect: false, mode: "nearest", axis: "x" },
        scales: { x: { type: "time", time: { tooltipFormat: "PP p" } } },
        plugins: {
          legend: { display: true },
          tooltip: { enabled: false }, // the crosshair readout replaces the built-in tooltip
          zoom: {
            pan: { enabled: true, mode: "x", modifierKey: "shift" },
            zoom: {
              wheel: { enabled: true },
              drag: { enabled: true, backgroundColor: "rgba(37,99,235,0.15)" },
              mode: "x",
            },
            limits: { x: { min: "original", max: "original" } },
          },
        },
      },
    });
  }

  function loadTrend() {
    const tag = $("#trend-tag").value;
    if (!tag) return;
    const rangeSec = Number($("#trend-range").value);
    const end = new Date();
    const start = new Date(end.getTime() - rangeSec * 1000);
    return loadTrendData(tag, start, end);
  }

  function jumpToHour() {
    const tag = $("#trend-tag").value;
    const raw = $("#trend-jump-time").value;
    if (!tag || !raw) return;
    // datetime-local gives "YYYY-MM-DDTHH:mm" in the browser's local time zone.
    const start = new Date(raw);
    if (Number.isNaN(start.getTime())) return;
    const end = new Date(start.getTime() + 3600 * 1000);
    return loadTrendData(tag, start, end);
  }

  $("#trend-refresh").addEventListener("click", loadTrend);
  $("#trend-tag").addEventListener("change", loadTrend);
  $("#trend-range").addEventListener("change", loadTrend);
  $("#trend-jump-btn").addEventListener("click", jumpToHour);
  $("#trend-zoom-reset").addEventListener("click", () => {
    if (state.chart) state.chart.resetZoom();
  });

  async function loadAlarms() {
    try {
      const events = await api("/api/alarms/events?limit=100");
      const tbody = $("#alarms-table tbody");
      tbody.innerHTML = "";
      for (const e of events) {
        const tr = document.createElement("tr");
        const needsAck = e.state !== "acked" ? `<button class="small-link" data-ack="${e.alarm_id}">${t("alarms.ackBtn")}</button>` : (e.acked_by ? t("alarms.ackedBy", { name: e.acked_by }) : "");
        const stateLabel = t(`alarmState.${e.state}`) === `alarmState.${e.state}` ? e.state : t(`alarmState.${e.state}`);
        tr.innerHTML = `<td>${new Date(e.ts).toLocaleString()}</td><td class="state-${e.state}">${stateLabel}</td>
          <td>${e.tag_name || e.tag_id}</td><td>${fmt(e.value)}</td><td>${e.message || ""}</td><td>${needsAck}</td>`;
        tbody.appendChild(tr);
      }
      tbody.querySelectorAll("button[data-ack]").forEach((b) =>
        b.addEventListener("click", async () => {
          try {
            await api(`/api/alarms/events/${b.dataset.ack}/ack`, { method: "POST" });
            loadAlarms();
          } catch (e) { /* ignore */ }
        })
      );
    } catch (e) { /* ignore transient errors */ }
  }

  // --- Alarm History page ---
  const historyState = { offset: 0, limit: 50, hasMore: false };

  function alarmStateLabel(s) {
    const translated = t(`alarmState.${s}`);
    return translated === `alarmState.${s}` ? s : translated;
  }

  async function loadHistory(opts = {}) {
    if (opts.resetOffset) historyState.offset = 0;
    const tbody = $("#history-table tbody");
    const params = new URLSearchParams({ limit: String(historyState.limit), offset: String(historyState.offset) });
    const startRaw = $("#history-start").value;
    const endRaw = $("#history-end").value;
    const tagRaw = $("#history-tag").value;
    const stateRaw = $("#history-state").value;
    if (startRaw) params.set("start", new Date(startRaw).toISOString());
    if (endRaw) params.set("end", new Date(endRaw).toISOString());
    if (tagRaw) params.set("tag_name", tagRaw);
    if (stateRaw) params.set("state", stateRaw);

    try {
      const data = await api(`/api/alarms/history?${params.toString()}`);
      historyState.hasMore = data.has_more;
      tbody.innerHTML = "";
      for (const e of data.events) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${new Date(e.ts).toLocaleString()}</td><td class="state-${e.state}">${alarmStateLabel(e.state)}</td>
          <td>${e.tag_name || e.tag_id}</td><td>${e.alarm_name || t("common.dash")}</td>
          <td>${e.condition || t("common.dash")}</td><td>${e.priority ?? t("common.dash")}</td>
          <td>${fmt(e.value)}</td><td>${e.message || ""}</td><td>${e.acked_by || t("common.dash")}</td>`;
        tbody.appendChild(tr);
      }
      const from = data.events.length ? historyState.offset + 1 : 0;
      const to = historyState.offset + data.events.length;
      $("#history-page-label").textContent = `${from}–${to}`;
      $("#history-prev-btn").disabled = historyState.offset === 0;
      $("#history-next-btn").disabled = !historyState.hasMore;
    } catch (e) {
      tbody.innerHTML = "";
      $("#history-page-label").textContent = t("common.couldNotLoadStatus");
    }
  }

  $("#history-search-btn").addEventListener("click", () => loadHistory({ resetOffset: true }));
  $("#history-reset-btn").addEventListener("click", () => {
    $("#history-start").value = "";
    $("#history-end").value = "";
    $("#history-tag").value = "";
    $("#history-state").value = "";
    loadHistory({ resetOffset: true });
  });
  $("#history-prev-btn").addEventListener("click", () => {
    if (historyState.offset === 0) return;
    historyState.offset = Math.max(0, historyState.offset - historyState.limit);
    loadHistory();
  });
  $("#history-next-btn").addEventListener("click", () => {
    if (!historyState.hasMore) return;
    historyState.offset += historyState.limit;
    loadHistory();
  });

  function fmtConnConfig(cfg) {
    if (!cfg) return t("common.dash");
    const parts = [];
    for (const key of ["host", "url", "endpoint_url", "broker", "port"]) {
      if (cfg[key] !== undefined) parts.push(`${key}=${cfg[key]}`);
    }
    return parts.length ? parts.join(", ") : t("common.dash");
  }

  async function loadConnections() {
    try {
      const conns = await api("/api/connections");
      const tbody = $("#connections-table tbody");
      tbody.innerHTML = "";
      for (const c of conns) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${c.name}</td><td>${c.protocol}</td>
          <td class="quality-${c.connected ? "good" : "bad"}">${c.connected ? t("connections.connected") : t("connections.disconnected")}</td>
          <td>${c.tag_count}</td><td>${fmtConnConfig(c.config)}</td>`;
        tbody.appendChild(tr);
      }
    } catch (e) { /* ignore transient errors */ }
  }

  async function loadOpcuaServerStatus() {
    const el = $("#opcua-server-status");
    try {
      const s = await api("/api/settings/opcua-server/status");
      el.innerHTML = s.running
        ? `<span class="quality-good">● ${t("opcua.running")}</span> ${t("opcua.runningDetail", { endpoint: `<code>${s.endpoint}</code>`, count: s.tag_count, auth: s.require_auth ? t("opcua.authRequired") : t("opcua.anonAllowed") })}`
        : `<span class="quality-bad">● ${t("opcua.stopped")}</span> — ${t("opcua.stoppedDetail")}`;
    } catch (e) {
      el.textContent = t("common.couldNotLoadStatus");
    }
  }

  async function loadModbusServerStatus() {
    const el = $("#modbus-server-status");
    const mappingEl = $("#modbus-server-mapping");
    try {
      const s = await api("/api/settings/modbus-server/status");
      el.innerHTML = s.running
        ? `<span class="quality-good">● ${t("modbus.running")}</span> ${t("modbus.runningDetail", { endpoint: `<code>${s.endpoint}</code>`, count: s.tag_count })}`
        : `<span class="quality-bad">● ${t("modbus.stopped")}</span> — ${t("modbus.stoppedDetail")}`;
      if (s.running && s.mapping && Object.keys(s.mapping).length) {
        let html = `<table id="modbus-mapping-table"><thead><tr><th>${t("modbus.tag")}</th><th>${t("modbus.table")}</th><th>${t("modbus.address")}</th></tr></thead><tbody>`;
        for (const [tag, entry] of Object.entries(s.mapping)) {
          const tableLabel = entry.table === "discrete_input" ? t("modbus.discreteInput") : t("modbus.inputRegister");
          html += `<tr><td>${tag}</td><td>${tableLabel}</td><td>${entry.address}${entry.table === "input_register" ? "-" + (entry.address + 1) : ""}</td></tr>`;
        }
        html += `</tbody></table>`;
        mappingEl.innerHTML = html;
      } else {
        mappingEl.innerHTML = "";
      }
    } catch (e) {
      el.textContent = t("common.couldNotLoadStatus");
    }
  }

  // --- Settings page ---
  let settingsSchema = [];
  const pendingSettingChanges = {};

  function settingInputHtml(s) {
    const id = `setting-${s.key}`;
    if (s.type === "bool") {
      return `<input type="checkbox" id="${id}" data-key="${s.key}" ${s.value ? "checked" : ""} />`;
    }
    if (s.type === "enum") {
      const opts = s.choices.map((c) => `<option value="${c}" ${c === s.value ? "selected" : ""}>${c}</option>`).join("");
      return `<select id="${id}" data-key="${s.key}">${opts}</select>`;
    }
    if (s.type === "int" || s.type === "float") {
      const step = s.type === "float" ? "any" : "1";
      const minAttr = s.min !== null && s.min !== undefined ? `min="${s.min}"` : "";
      const maxAttr = s.max !== null && s.max !== undefined ? `max="${s.max}"` : "";
      return `<input type="number" step="${step}" ${minAttr} ${maxAttr} id="${id}" data-key="${s.key}" value="${s.value}" />`;
    }
    return `<input type="text" id="${id}" data-key="${s.key}" value="${s.value}" />`;
  }

  async function loadSettings() {
    const container = $("#settings-form");
    try {
      settingsSchema = await api("/api/settings");
      const byCategory = {};
      for (const s of settingsSchema) {
        (byCategory[s.category] = byCategory[s.category] || []).push(s);
      }
      let html = "";
      for (const [category, items] of Object.entries(byCategory)) {
        html += `<fieldset class="settings-group"><legend>${tCategory(category)}</legend>`;
        for (const s of items) {
          const label = tSetting(s.key, "label") || s.label;
          const desc = tSetting(s.key, "description") || s.description || "";
          html += `<div class="settings-row">
            <label for="setting-${s.key}">${label}</label>
            ${settingInputHtml(s)}
            <p class="settings-desc">${desc}</p>
          </div>`;
        }
        html += `</fieldset>`;
      }
      container.innerHTML = html;
      container.querySelectorAll("[data-key]").forEach((input) => {
        input.addEventListener("change", () => {
          const key = input.dataset.key;
          const schema = settingsSchema.find((s) => s.key === key);
          let value;
          if (schema.type === "bool") value = input.checked;
          else if (schema.type === "int") value = parseInt(input.value, 10);
          else if (schema.type === "float") value = parseFloat(input.value);
          else value = input.value;
          pendingSettingChanges[key] = value;
        });
      });
    } catch (e) {
      container.textContent = t("settingsPage.couldNotLoad");
    }
  }

  $("#settings-save-btn").addEventListener("click", async () => {
    const msg = $("#settings-save-msg");
    if (Object.keys(pendingSettingChanges).length === 0) {
      msg.textContent = t("settingsPage.noChanges");
      msg.hidden = false;
      return;
    }
    try {
      const res = await api("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values: pendingSettingChanges }) });
      msg.textContent = t("settingsPage.saved", { count: res.changed.length });
      msg.hidden = false;
      for (const k of Object.keys(pendingSettingChanges)) delete pendingSettingChanges[k];
      loadSettings();
    } catch (e) {
      msg.textContent = t("settingsPage.saveFailed", { msg: e.message });
      msg.hidden = false;
    }
  });

  (async () => {
    const initialLocale = getStoredLocale() || detectBrowserLocale();
    await loadLocale(initialLocale);
    applyStaticTranslations();
    wireLangSelectors();
    if (state.token) showApp();
  })();
})();
