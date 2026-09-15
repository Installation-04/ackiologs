(() => {
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

  function showApp() {
    $("#login-screen").hidden = true;
    $("#app-screen").hidden = false;
    connectWs();
    loadTags();
    loadAlarms();
    loadConnections();
    setInterval(loadAlarms, 15000);
    setInterval(loadConnections, 15000);
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
      $("#login-error").textContent = "Invalid username or password.";
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
    trendSelect.innerHTML = "";
    for (const t of tags) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${t.name}</td><td class="v">${fmt(t.live_value)}</td><td>${t.engineering_units || ""}</td>
        <td class="q quality-${t.live_quality || "uncertain"}">${t.live_quality || "-"}</td>
        <td class="ts">${t.live_ts ? new Date(t.live_ts).toLocaleTimeString() : "-"}</td>
        <td><button class="small-link" data-tag="${t.name}">Trend</button></td>`;
      tbody.appendChild(tr);
      liveRows.set(t.name, tr);

      const opt = document.createElement("option");
      opt.value = t.name;
      opt.textContent = t.name;
      trendSelect.appendChild(opt);
    }
    tbody.querySelectorAll("button[data-tag]").forEach((b) =>
      b.addEventListener("click", () => {
        $("#trend-tag").value = b.dataset.tag;
        document.querySelector('.nav-btn[data-view="trend"]').click();
      })
    );
  }

  function fmt(v) {
    if (v === null || v === undefined) return "-";
    if (typeof v === "number") return Number.isInteger(v) ? v : v.toFixed(3);
    return String(v);
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
      row.querySelector(".q").textContent = msg.quality;
      row.querySelector(".q").className = `q quality-${msg.quality}`;
      row.querySelector(".ts").textContent = new Date(msg.ts).toLocaleTimeString();
    };
  }

  async function loadTrend() {
    const tag = $("#trend-tag").value;
    if (!tag) return;
    const rangeSec = Number($("#trend-range").value);
    const end = new Date();
    const start = new Date(end.getTime() - rangeSec * 1000);
    const bucket = rangeSec > 7200 ? Math.max(10, Math.round(rangeSec / 500)) : 0;
    const url = `/api/history/${encodeURIComponent(tag)}?start=${start.toISOString()}&end=${end.toISOString()}&interval_seconds=${bucket}`;
    const data = await api(url);
    const labels = data.points.map((p) => new Date(p.ts));
    const values = data.points.map((p) => (data.mode === "bucketed" ? p.avg : p.value));

    if (state.chart) state.chart.destroy();
    state.chart = new Chart($("#trend-chart"), {
      type: "line",
      data: { labels, datasets: [{ label: tag, data: values, borderColor: "#2563eb", pointRadius: 0, tension: 0.15 }] },
      options: {
        responsive: true,
        animation: false,
        scales: { x: { type: "time", time: { tooltipFormat: "PP p" } } },
        plugins: { legend: { display: true } },
      },
    });
  }
  $("#trend-refresh").addEventListener("click", loadTrend);
  $("#trend-tag").addEventListener("change", loadTrend);
  $("#trend-range").addEventListener("change", loadTrend);

  async function loadAlarms() {
    try {
      const events = await api("/api/alarms/events?limit=100");
      const tbody = $("#alarms-table tbody");
      tbody.innerHTML = "";
      for (const e of events) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${new Date(e.ts).toLocaleString()}</td><td class="state-${e.state}">${e.state}</td>
          <td>${e.tag_id}</td><td>${fmt(e.value)}</td><td>${e.message || ""}</td>`;
        tbody.appendChild(tr);
      }
    } catch (e) { /* ignore transient errors */ }
  }

  async function loadConnections() {
    try {
      const conns = await api("/api/connections");
      const tbody = $("#connections-table tbody");
      tbody.innerHTML = "";
      for (const c of conns) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${c.name}</td><td>${c.protocol}</td>
          <td class="quality-${c.connected ? "good" : "bad"}">${c.connected ? "connected" : "disconnected"}</td>
          <td>${c.tag_count}</td>`;
        tbody.appendChild(tr);
      }
    } catch (e) { /* ignore transient errors */ }
  }

  if (state.token) showApp();
})();
