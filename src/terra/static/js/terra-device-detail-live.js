/**
 * Optional live polling from SD-WAN Manager for device detail (interfaces + cellular tables).
 * Also handles "More…" expansion for interface tables (inventory + live).
 */
(function () {
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function pillToneClass(tone) {
    if (tone === "success" || tone === "error" || tone === "warning") {
      return "terra-m3-chip terra-m3-chip--pill terra-m3-chip--" + tone;
    }
    return "terra-m3-chip terra-m3-chip--pill terra-m3-chip--neutral";
  }

  function ifaceSortKey(r) {
    const tun = r.is_tunnel === "1" ? 1 : 0;
    let vid = parseInt(String(r.vpn_id || "-1"), 10);
    if (Number.isNaN(vid)) {
      vid = -1;
    }
    const wanBucket = vid === 0 ? 0 : 1;
    const sortVid = vid >= 0 ? vid : 999999;
    return [tun, wanBucket, sortVid, String(r.interface || "").toLowerCase()];
  }

  function sortIfaceRows(rows) {
    return rows.slice().sort(function (a, b) {
      const ka = ifaceSortKey(a);
      const kb = ifaceSortKey(b);
      for (let i = 0; i < 4; i++) {
        if (ka[i] < kb[i]) {
          return -1;
        }
        if (ka[i] > kb[i]) {
          return 1;
        }
      }
      return 0;
    });
  }

  function partitionIfaceRows(rows) {
    const ordered = sortIfaceRows(rows);
    const primary = [];
    const deferred = [];
    for (let i = 0; i < ordered.length; i++) {
      if (ordered[i].row_defer === "1") {
        deferred.push(ordered[i]);
      } else {
        primary.push(ordered[i]);
      }
    }
    return [primary, deferred];
  }

  function renderInterfaceCellPill(tone, label) {
    return (
      '<span class="' +
      escapeHtml(pillToneClass(tone)) +
      '">' +
      escapeHtml(String(label || "")) +
      "</span>"
    );
  }

  function renderInterfaceTable(iface) {
    const parts = [];
    const rows = Array.isArray(iface) ? iface : [];
    if (!rows.length) {
      return "";
    }
    const split = partitionIfaceRows(rows);
    const primary = split[0];
    const deferred = split[1];

    parts.push('<h2 class="terra-section-title">Network interfaces (live)</h2>');
    parts.push(
      '<div class="terra-table-wrap terra-detail-if-table"><table class="terra-table terra-if-summary-table"><thead><tr>',
    );
    parts.push("<th>Interface</th>");
    parts.push("<th>Administrative status</th>");
    parts.push("<th>Line state</th>");
    parts.push("<th>IPv4 (CIDR)</th>");
    parts.push("<th>Speed</th>");
    parts.push("<th>Service VPN</th>");
    parts.push("<th>VRF / VPN</th>");
    parts.push("<th>Notes</th>");
    parts.push("</tr></thead>");

    parts.push("<tbody>");
    for (let i = 0; i < primary.length; i++) {
      const r = primary[i];
      parts.push("<tr>");
      parts.push('<td class="terra-table-mono">' + escapeHtml(r.interface || "") + "</td>");
      parts.push("<td>" + renderInterfaceCellPill(r.admin_tone, r.admin_status) + "</td>");
      parts.push("<td>" + renderInterfaceCellPill(r.oper_tone, r.oper_status) + "</td>");
      parts.push(
        '<td class="terra-table-mono">' + escapeHtml(r.ip_cidr && r.ip_cidr !== "—" ? r.ip_cidr : "—") + "</td>",
      );
      parts.push("<td>" + escapeHtml(r.speed || "—") + "</td>");
      parts.push("<td>" + escapeHtml(r.service_vpn || "—") + "</td>");
      parts.push("<td>" + escapeHtml(r.vrf || "—") + "</td>");
      parts.push(
        '<td class="terra-table-clip" title="' +
          escapeHtml(r.detail || "") +
          '">' +
          escapeHtml(r.detail || "—") +
          "</td>",
      );
      parts.push("</tr>");
    }
    if (deferred.length) {
      parts.push(
        '<tr class="terra-if-more-row"><td colspan="8"><button type="button" class="terra-btn terra-btn--inline terra-btn--text terra-if-more-btn" aria-expanded="false">More…</button></td></tr>',
      );
    }
    parts.push("</tbody>");

    if (deferred.length) {
      parts.push('<tbody class="terra-if-deferred-tbody" hidden>');
      for (let j = 0; j < deferred.length; j++) {
        const r = deferred[j];
        parts.push('<tr class="terra-if-row--deferred">');
        parts.push('<td class="terra-table-mono">' + escapeHtml(r.interface || "") + "</td>");
        parts.push("<td>" + renderInterfaceCellPill(r.admin_tone, r.admin_status) + "</td>");
        parts.push("<td>" + renderInterfaceCellPill(r.oper_tone, r.oper_status) + "</td>");
        parts.push(
          '<td class="terra-table-mono">' + escapeHtml(r.ip_cidr && r.ip_cidr !== "—" ? r.ip_cidr : "—") + "</td>",
        );
        parts.push("<td>" + escapeHtml(r.speed || "—") + "</td>");
        parts.push("<td>" + escapeHtml(r.service_vpn || "—") + "</td>");
        parts.push("<td>" + escapeHtml(r.vrf || "—") + "</td>");
        parts.push(
          '<td class="terra-table-clip" title="' +
            escapeHtml(r.detail || "") +
            '">' +
            escapeHtml(r.detail || "—") +
            "</td>",
        );
        parts.push("</tr>");
      }
      parts.push("</tbody>");
    }

    parts.push("</table></div>");
    return parts.join("");
  }

  function renderTables(payload, panelEl) {
    const iface = payload.interfaces || [];
    const tables = payload.cellular_tables || [];
    let html = renderInterfaceTable(iface);

    for (let t = 0; t < tables.length; t++) {
      const tbl = tables[t];
      const title = escapeHtml(tbl.title || "");
      const cols = tbl.columns || [];
      const rows = tbl.rows || [];
      html += '<h2 class="terra-section-title">' + title + "</h2>";
      html += '<div class="terra-table-wrap terra-detail-if-table terra-detail-live-table"><table class="terra-table"><thead><tr>';
      for (let c = 0; c < cols.length; c++) {
        html += "<th>" + escapeHtml(String(cols[c])) + "</th>";
      }
      html += "</tr></thead><tbody>";
      for (let r = 0; r < rows.length; r++) {
        const line = rows[r];
        if (!Array.isArray(line)) {
          continue;
        }
        html += "<tr>";
        for (let c = 0; c < line.length; c++) {
          html += "<td>" + escapeHtml(String(line[c])) + "</td>";
        }
        html += "</tr>";
      }
      html += "</tbody></table></div>";
    }

    if (!html || !String(html).trim()) {
      html =
        '<p class="terra-muted terra-detail-hint">No live interface or cellular rows in this response. ' +
        (payload.note ? escapeHtml(payload.note) : "") +
        "</p>";
    }

    panelEl.innerHTML = html;
  }

  document.body.addEventListener("click", function (ev) {
    const btn = ev.target && ev.target.closest ? ev.target.closest(".terra-if-more-btn") : null;
    if (!btn) {
      return;
    }
    const table = btn.closest("table");
    if (!table) {
      return;
    }
    const defBody = table.querySelector(".terra-if-deferred-tbody");
    if (!defBody) {
      return;
    }
    const expanded = btn.getAttribute("aria-expanded") === "true";
    const next = !expanded;
    btn.setAttribute("aria-expanded", next ? "true" : "false");
    defBody.hidden = !next;
    btn.textContent = next ? "Show less" : "More…";
  });

  const root = document.getElementById("terra-device-live-root");
  if (!root) {
    return;
  }
  const url = root.getAttribute("data-live-url");
  const streamUrl = root.getAttribute("data-live-stream-url") || (url ? url + "/stream" : "");
  const pollMs = Math.max(3000, parseInt(String(root.getAttribute("data-poll-ms") || "5000"), 10) || 5000);
  const btn = document.getElementById("terra-live-toggle");
  const label = document.getElementById("terra-live-toggle-label");
  const statusEl = document.getElementById("terra-live-status");
  const panel = document.getElementById("terra-live-panel");
  const progressRoot = document.getElementById("terra-live-progress");
  const progressFill = document.getElementById("terra-live-progress-fill");
  const progressPct = document.getElementById("terra-live-progress-pct");
  const progressBar = progressRoot ? progressRoot.querySelector(".terra-live-progress-bar") : null;
  const stepsList = document.getElementById("terra-live-steps");
  if (!btn || !panel || !url || !label || !statusEl) {
    return;
  }

  const LIVE_STEP_ORDER = [
    { step_id: "connect", label: "Connect to SD-WAN Manager" },
    { step_id: "resolve_id", label: "Resolve device identifier" },
    { step_id: "interfaces", label: "Network interfaces" },
    { step_id: "cellular_device_cellular_modem", label: "Cellular modem" },
    { step_id: "cellular_device_cellular_network", label: "Cellular network" },
    { step_id: "cellular_device_cellular_radio", label: "Cellular radio" },
    { step_id: "cellular_device_cellular_status", label: "Cellular status" },
    { step_id: "cellular_device_cellular_sessions", label: "Cellular sessions" },
    { step_id: "cellular_device_cellular_profiles", label: "Cellular profiles" },
    { step_id: "wan_device_control_waninterface", label: "WAN (control)" },
  ];

  let active = false;
  let timer = null;
  let pollGeneration = 0;
  let stepState = {};
  let tickTimer = null;

  function formatElapsed(ms) {
    const n = Math.max(0, Number(ms) || 0);
    if (n < 1000) {
      return n.toFixed(0) + " ms";
    }
    return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + " s";
  }

  function resetProgressUi() {
    stepState = {};
    if (stepsList) {
      stepsList.innerHTML = "";
      for (let i = 0; i < LIVE_STEP_ORDER.length; i++) {
        const def = LIVE_STEP_ORDER[i];
        stepState[def.step_id] = {
          label: def.label,
          status: "pending",
          elapsed_ms: 0,
          detail: "",
          started_at: null,
        };
        const li = document.createElement("li");
        li.className = "terra-live-step terra-live-step--pending";
        li.setAttribute("data-step-id", def.step_id);
        li.innerHTML =
          '<span class="terra-live-step__icon" aria-hidden="true"></span>' +
          '<span class="terra-live-step__label">' +
          escapeHtml(def.label) +
          "</span>" +
          '<span class="terra-live-step__elapsed">—</span>' +
          '<span class="terra-live-step__detail" hidden></span>';
        stepsList.appendChild(li);
      }
    }
    if (progressFill) {
      progressFill.style.width = "0%";
    }
    if (progressPct) {
      progressPct.textContent = "0%";
    }
    if (progressBar) {
      progressBar.setAttribute("aria-valuenow", "0");
    }
  }

  function progressPercent() {
    const ids = LIVE_STEP_ORDER.map(function (s) {
      return s.step_id;
    });
    let done = 0;
    for (let i = 0; i < ids.length; i++) {
      const st = stepState[ids[i]];
      if (st && st.status === "done") {
        done += 1;
      }
    }
    return Math.round((done / Math.max(1, ids.length)) * 100);
  }

  function applyProgressPercent() {
    const pct = progressPercent();
    if (progressFill) {
      progressFill.style.width = pct + "%";
    }
    if (progressPct) {
      progressPct.textContent = pct + "%";
    }
    if (progressBar) {
      progressBar.setAttribute("aria-valuenow", String(pct));
    }
  }

  function renderStepRow(stepId) {
    if (!stepsList) {
      return;
    }
    const st = stepState[stepId];
    if (!st) {
      return;
    }
    const li = stepsList.querySelector('[data-step-id="' + stepId + '"]');
    if (!li) {
      return;
    }
    li.className = "terra-live-step terra-live-step--" + st.status;
    const elapsedEl = li.querySelector(".terra-live-step__elapsed");
    const detailEl = li.querySelector(".terra-live-step__detail");
    if (elapsedEl) {
      if (st.status === "pending") {
        elapsedEl.textContent = "—";
      } else if (st.status === "running") {
        elapsedEl.textContent = formatElapsed(st.elapsed_ms);
      } else {
        elapsedEl.textContent = formatElapsed(st.elapsed_ms);
      }
    }
    if (detailEl) {
      if (st.detail) {
        detailEl.textContent = st.detail;
        detailEl.hidden = false;
      } else {
        detailEl.textContent = "";
        detailEl.hidden = true;
      }
    }
    applyProgressPercent();
  }

  function startProgressTick() {
    if (tickTimer) {
      window.clearInterval(tickTimer);
    }
    tickTimer = window.setInterval(function () {
      const now = Date.now();
      let anyRunning = false;
      for (const stepId in stepState) {
        if (!Object.prototype.hasOwnProperty.call(stepState, stepId)) {
          continue;
        }
        const st = stepState[stepId];
        if (st.status === "running" && st.started_at) {
          st.elapsed_ms = now - st.started_at;
          renderStepRow(stepId);
          anyRunning = true;
        }
      }
      if (!anyRunning && tickTimer) {
        window.clearInterval(tickTimer);
        tickTimer = null;
      }
    }, 100);
  }

  function stopProgressTick() {
    if (tickTimer) {
      window.clearInterval(tickTimer);
      tickTimer = null;
    }
  }

  function applyStepEvent(ev) {
    if (!ev || ev.type !== "step") {
      return;
    }
    const stepId = String(ev.step_id || "");
    if (!stepState[stepId]) {
      stepState[stepId] = {
        label: String(ev.label || stepId),
        status: "pending",
        elapsed_ms: 0,
        detail: "",
        started_at: null,
      };
    }
    const st = stepState[stepId];
    if (ev.label) {
      st.label = String(ev.label);
    }
    const status = String(ev.status || "running");
    if (status === "running") {
      st.status = "running";
      st.started_at = Date.now();
      st.elapsed_ms = 0;
      startProgressTick();
    } else if (status === "done") {
      st.status = "done";
      st.elapsed_ms = typeof ev.elapsed_ms === "number" ? ev.elapsed_ms : st.elapsed_ms;
      st.started_at = null;
      if (ev.detail) {
        st.detail = String(ev.detail);
      }
    }
    renderStepRow(stepId);
  }

  function showProgressUi() {
    if (progressRoot) {
      progressRoot.hidden = false;
    }
    resetProgressUi();
    statusEl.textContent = "Collecting live data from Manager…";
  }

  function hideProgressUi() {
    stopProgressTick();
    if (progressRoot) {
      progressRoot.hidden = true;
    }
  }

  function scheduleNext() {
    if (!active) {
      return;
    }
    if (timer) {
      window.clearTimeout(timer);
    }
    timer = window.setTimeout(runPoll, pollMs);
  }

  async function consumeNdjsonStream(response, generation) {
    if (!response.body) {
      throw new Error("Streaming not supported");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalPayload = null;

    while (true) {
      const chunk = await reader.read();
      if (chunk.done) {
        break;
      }
      if (!active || generation !== pollGeneration) {
        try {
          await reader.cancel();
        } catch (_e) {}
        return null;
      }
      buffer += decoder.decode(chunk.value, { stream: true });
      let lineBreak = buffer.indexOf("\n");
      while (lineBreak >= 0) {
        const line = buffer.slice(0, lineBreak).trim();
        buffer = buffer.slice(lineBreak + 1);
        if (line) {
          const ev = JSON.parse(line);
          if (ev.type === "step") {
            applyStepEvent(ev);
          } else if (ev.type === "complete") {
            finalPayload = ev.payload || null;
          } else if (ev.type === "error") {
            throw new Error(ev.message || "Live fetch failed");
          }
        }
        lineBreak = buffer.indexOf("\n");
      }
    }
    const tail = buffer.trim();
    if (tail) {
      const ev = JSON.parse(tail);
      if (ev.type === "step") {
        applyStepEvent(ev);
      } else if (ev.type === "complete") {
        finalPayload = ev.payload || null;
      } else if (ev.type === "error") {
        throw new Error(ev.message || "Live fetch failed");
      }
    }
    return finalPayload;
  }

  async function runPoll() {
    if (!active) {
      return;
    }
    const generation = ++pollGeneration;
    showProgressUi();
    try {
      const fetchUrl = streamUrl || url;
      const r = await fetch(fetchUrl, { credentials: "same-origin" });
      if (!r.ok) {
        throw new Error("HTTP " + r.status);
      }
      const j = await consumeNdjsonStream(r, generation);
      if (!active || generation !== pollGeneration) {
        return;
      }
      if (!j) {
        throw new Error("Empty live response");
      }
      stopProgressTick();
      for (const stepId in stepState) {
        if (Object.prototype.hasOwnProperty.call(stepState, stepId) && stepState[stepId].status === "running") {
          stepState[stepId].status = "done";
          renderStepRow(stepId);
        }
      }
      applyProgressPercent();
      renderTables(j, panel);
      const note = j.note ? String(j.note) : "";
      const when = j.fetched_at ? " · " + j.fetched_at : "";
      statusEl.textContent = (j.ok ? "Live data updated" : "Live request incomplete") + when + (note ? " — " + note : "");
    } catch (e) {
      if (active && generation === pollGeneration) {
        statusEl.textContent = "Live request failed: " + String(e);
      }
    } finally {
      stopProgressTick();
      if (active && generation === pollGeneration) {
        scheduleNext();
      }
    }
  }

  btn.addEventListener("click", function () {
    active = !active;
    if (active) {
      btn.setAttribute("aria-pressed", "true");
      label.textContent = "Hide live data";
      panel.hidden = false;
      void runPoll();
    } else {
      pollGeneration += 1;
      btn.setAttribute("aria-pressed", "false");
      label.textContent = "Show live data";
      panel.hidden = true;
      hideProgressUi();
      if (timer) {
        window.clearTimeout(timer);
        timer = null;
      }
      statusEl.textContent = "";
      panel.innerHTML = "";
    }
  });
})();
