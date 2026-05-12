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
      renderTables(j, panel);
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
