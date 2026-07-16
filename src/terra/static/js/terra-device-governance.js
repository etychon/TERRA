/**
 * Recent alarms/events/audit for device detail (Postgres projection; one fetch on load).
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

  function chipClass(kind, value) {
    var v = String(value || "").toLowerCase();
    if (kind === "severity") {
      if (v === "critical") return "terra-gov-chip terra-gov-chip--critical";
      if (v === "major") return "terra-gov-chip terra-gov-chip--major";
      if (v === "info") return "terra-gov-chip terra-gov-chip--info";
      return "terra-gov-chip terra-gov-chip--minor";
    }
    if (kind === "stream") {
      if (v === "alarm") return "terra-gov-chip terra-gov-chip--alarm";
      if (v === "event") return "terra-gov-chip terra-gov-chip--event";
      if (v === "audit") return "terra-gov-chip terra-gov-chip--audit";
    }
    if (kind === "active-true") return "terra-gov-chip terra-gov-chip--active";
    if (kind === "active-false") return "terra-gov-chip terra-gov-chip--cleared";
    return "terra-gov-chip terra-gov-chip--minor";
  }

  function formatLocal(iso) {
    var raw = String(iso || "").trim();
    if (!raw) return "—";
    try {
      var d = new Date(raw.indexOf("T") >= 0 ? raw : raw.replace(" ", "T") + "Z");
      if (!Number.isNaN(d.getTime())) {
        return d.toLocaleString();
      }
    } catch (_e) {}
    return raw;
  }

  function renderActive(active, stream) {
    if (stream !== "alarm") return "—";
    if (active === true) {
      return (
        '<span class="' +
        chipClass("active-true") +
        '"><span class="terra-gov-active-dot" aria-hidden="true"></span>Active</span>'
      );
    }
    if (active === false) {
      return '<span class="' + chipClass("active-false") + '">Cleared</span>';
    }
    return "—";
  }

  function renderRows(items) {
    if (!items || !items.length) {
      return '<p class="terra-muted">No recent alarms or events in TERRA for this device (last 24h). The collector syncs on a timer.</p>';
    }
    var parts = [
      '<div class="terra-governance-table-wrap"><table class="terra-governance-table"><thead><tr>',
      "<th>Time</th><th>Severity</th><th>Stream</th><th>Active</th><th>Title</th>",
      "</tr></thead><tbody>",
    ];
    for (var i = 0; i < items.length && i < 25; i++) {
      var r = items[i];
      parts.push("<tr>");
      parts.push("<td>" + escapeHtml(formatLocal(r.entry_time_utc)) + "</td>");
      parts.push(
        "<td><span class=\"" +
          chipClass("severity", r.severity_norm) +
          "\">" +
          escapeHtml(String(r.severity_norm || "unknown")) +
          "</span></td>",
      );
      parts.push(
        "<td><span class=\"" +
          chipClass("stream", r.stream_kind) +
          "\">" +
          escapeHtml(String(r.stream_kind || "")) +
          "</span></td>",
      );
      parts.push("<td>" + renderActive(r.active, r.stream_kind) + "</td>");
      parts.push('<td class="terra-table-clip" title="' + escapeHtml(r.summary || r.title || "") + '">' + escapeHtml(r.title || "—") + "</td>");
      parts.push("</tr>");
    }
    parts.push("</tbody></table></div>");
    return parts.join("");
  }

  var root = document.getElementById("terra-device-governance-root");
  if (!root) return;
  var deviceId = root.getAttribute("data-device-id");
  var body = document.getElementById("terra-device-governance-body");
  var status = document.getElementById("terra-device-governance-status");
  if (!deviceId || !body) return;

  fetch("/api/v1/me/devices/" + encodeURIComponent(deviceId) + "/events?limit=25&hours=24", {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (j) {
      body.innerHTML = renderRows(j.items || []);
      if (status) {
        status.textContent = (j.total || 0) + " row(s) in last 24h";
      }
    })
    .catch(function (e) {
      body.innerHTML = '<p class="terra-muted">Could not load recent events: ' + escapeHtml(String(e)) + "</p>";
    });
})();
