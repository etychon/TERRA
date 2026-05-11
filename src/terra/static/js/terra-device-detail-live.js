/**
 * Optional live polling from SD-WAN Manager for device detail (interfaces + cellular tables).
 */
(function () {
  const root = document.getElementById("terra-device-live-root");
  if (!root) {
    return;
  }
  const url = root.getAttribute("data-live-url");
  const pollMs = Math.max(3000, parseInt(String(root.getAttribute("data-poll-ms") || "5000"), 10) || 5000);
  const btn = document.getElementById("terra-live-toggle");
  const label = document.getElementById("terra-live-toggle-label");
  const statusEl = document.getElementById("terra-live-status");
  const panel = document.getElementById("terra-live-panel");
  if (!btn || !panel || !url || !label || !statusEl) {
    return;
  }

  let active = false;
  let timer = null;

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderTables(payload) {
    const iface = payload.interfaces || [];
    const tables = payload.cellular_tables || [];
    const parts = [];

    if (iface.length) {
      parts.push('<h2 class="terra-section-title">Network interfaces (live)</h2>');
      parts.push('<div class="terra-table-wrap terra-detail-if-table"><table class="terra-table"><thead><tr>');
      parts.push("<th>Interface</th><th>IP</th><th>VRF</th><th>Notes</th></tr></thead><tbody>");
      for (let i = 0; i < iface.length; i++) {
        const r = iface[i];
        parts.push(
          "<tr><td>" +
            escapeHtml(r.interface || "") +
            "</td><td>" +
            escapeHtml(r.ip || "") +
            "</td><td>" +
            escapeHtml(r.vrf || "") +
            "</td><td>" +
            escapeHtml(r.detail || "") +
            "</td></tr>",
        );
      }
      parts.push("</tbody></table></div>");
    }

    for (let t = 0; t < tables.length; t++) {
      const tbl = tables[t];
      const title = escapeHtml(tbl.title || "");
      const cols = tbl.columns || [];
      const rows = tbl.rows || [];
      parts.push('<h2 class="terra-section-title">' + title + "</h2>");
      parts.push('<div class="terra-table-wrap terra-detail-if-table terra-detail-live-table"><table class="terra-table"><thead><tr>');
      for (let c = 0; c < cols.length; c++) {
        parts.push("<th>" + escapeHtml(String(cols[c])) + "</th>");
      }
      parts.push("</tr></thead><tbody>");
      for (let r = 0; r < rows.length; r++) {
        const line = rows[r];
        if (!Array.isArray(line)) {
          continue;
        }
        parts.push("<tr>");
        for (let c = 0; c < line.length; c++) {
          parts.push("<td>" + escapeHtml(String(line[c])) + "</td>");
        }
        parts.push("</tr>");
      }
      parts.push("</tbody></table></div>");
    }

    if (!parts.length) {
      parts.push(
        '<p class="terra-muted terra-detail-hint">No live interface or cellular rows in this response. ' +
          (payload.note ? escapeHtml(payload.note) : "") +
          "</p>",
      );
    }

    panel.innerHTML = parts.join("");
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

  async function runPoll() {
    if (!active) {
      return;
    }
    try {
      const r = await fetch(url, { credentials: "same-origin" });
      const j = await r.json();
      if (!active) {
        return;
      }
      renderTables(j);
      const note = j.note ? String(j.note) : "";
      const when = j.fetched_at ? " · " + j.fetched_at : "";
      statusEl.textContent = (j.ok ? "Live data updated" : "Live request incomplete") + when + (note ? " — " + note : "");
    } catch (e) {
      if (active) {
        statusEl.textContent = "Live request failed: " + String(e);
      }
    } finally {
      if (active) {
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
      statusEl.textContent = "Fetching…";
      void runPoll();
    } else {
      btn.setAttribute("aria-pressed", "false");
      label.textContent = "Show live data";
      panel.hidden = true;
      if (timer) {
        window.clearTimeout(timer);
        timer = null;
      }
      statusEl.textContent = "";
      panel.innerHTML = "";
    }
  });
})();
