/**
 * Home dashboard — Leaflet map: hover name, click detail panel + More, telemetry poll ripples.
 */
(function () {
  var mount = document.getElementById("terra-home-map");
  var jsonEl = document.getElementById("terra-home-map-markers");
  var detailEl = document.getElementById("terra-home-map-detail");
  var detailBody = document.getElementById("terra-home-map-detail-body");
  var detailMore = document.getElementById("terra-home-map-detail-more");
  var detailClose = document.getElementById("terra-home-map-detail-close");
  var detailTitle = document.getElementById("terra-home-map-detail-title");
  if (!mount || !jsonEl || typeof L === "undefined") {
    return;
  }
  var markers = [];
  try {
    markers = JSON.parse(jsonEl.textContent);
  } catch (e) {
    return;
  }
  if (!markers.length) {
    return;
  }

  var reduceMotion =
    typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function utcDate(iso) {
    var s = String(iso || "").trim();
    if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(s) && !/[zZ+]|[+-]\d{2}:?\d{2}$/.test(s)) {
      s = s.replace(" ", "T") + "Z";
    }
    return new Date(s);
  }

  function formatLocal(iso) {
    var t = utcDate(iso);
    if (Number.isNaN(t.getTime())) {
      return "—";
    }
    return t.toLocaleString(undefined, { hour12: false });
  }

  function telemetrySig(m) {
    return (
      String(m.synced_at_utc || "") +
      "|" +
      String(m.state_changed_at_utc || "") +
      "|" +
      String(m.reachability || "")
    );
  }

  function buildPinHtml(m) {
    var name = escapeHtml(m.name);
    var online = m.online ? "terra-map-pin__dot--online" : "terra-map-pin__dot--offline";
    return (
      '<div class="terra-map-pin" data-device-id="' +
      String(m.id) +
      '" role="button" tabindex="0" aria-label="' +
      escapeHtml("Device: " + String(m.name)) +
      '">' +
      '<span class="terra-map-pin__ripples" aria-hidden="true"></span>' +
      '<span class="terra-map-pin__name">' +
      name +
      "</span>" +
      '<div class="terra-map-pin__dot ' +
      online +
      '" aria-hidden="true"></div>' +
      "</div>"
    );
  }

  function triggerRipple(deviceId) {
    if (reduceMotion) {
      return;
    }
    var pin = mount.querySelector('.terra-map-pin[data-device-id="' + String(deviceId) + '"]');
    if (!pin) {
      return;
    }
    var host = pin.querySelector(".terra-map-pin__ripples");
    if (!host) {
      return;
    }
    var ring = document.createElement("span");
    var dm = markersById[deviceId];
    var on = dm && dm.online;
    ring.className = "terra-map-ripple-burst " + (on ? "terra-map-ripple-burst--online" : "terra-map-ripple-burst--offline");
    host.appendChild(ring);
    ring.addEventListener("animationend", function () {
      ring.remove();
    });
  }

  var markersById = {};
  var lastTelemetry = {};
  markers.forEach(function (m) {
    markersById[m.id] = m;
    lastTelemetry[m.id] = telemetrySig(m);
  });

  function applyTelemetryRow(row) {
    var id = row.id;
    var sig = telemetrySig(row);
    var prev = lastTelemetry[id];
    lastTelemetry[id] = sig;
    var m = markersById[id];
    if (!m) {
      return;
    }
    m.reachability = row.reachability;
    m.synced_at_utc = row.synced_at_utc;
    m.state_changed_at_utc = row.state_changed_at_utc;
    m.online = String(row.reachability || "").toLowerCase() === "reachable";
    var pin = mount.querySelector('.terra-map-pin[data-device-id="' + String(id) + '"]');
    if (pin) {
      var dot = pin.querySelector(".terra-map-pin__dot");
      if (dot) {
        dot.classList.toggle("terra-map-pin__dot--online", m.online);
        dot.classList.toggle("terra-map-pin__dot--offline", !m.online);
      }
    }
    if (prev !== undefined && prev !== sig) {
      triggerRipple(id);
    }
  }

  function pollTelemetry() {
    fetch("/api/v1/me/map-devices-telemetry", { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) {
          return null;
        }
        return r.json();
      })
      .then(function (body) {
        if (!body || !Array.isArray(body.devices)) {
          return;
        }
        body.devices.forEach(applyTelemetryRow);
      })
      .catch(function () {});
  }

  function hideDetail() {
    if (detailEl) {
      detailEl.hidden = true;
    }
  }

  function showDetail(m) {
    if (!detailEl || !detailBody || !detailMore) {
      return;
    }
    var reach = escapeHtml(String(m.reachability || "—"));
    var rows = [
      "<dt>Name</dt><dd>" + escapeHtml(String(m.name || "—")) + "</dd>",
      "<dt>Reachability</dt><dd>" + reach + "</dd>",
      "<dt>Model</dt><dd>" + escapeHtml(String(m.model || "—")) + "</dd>",
      "<dt>Site</dt><dd>" + escapeHtml(String(m.site || "—")) + "</dd>",
      "<dt>Serial</dt><dd>" + escapeHtml(String(m.serial || "—")) + "</dd>",
      "<dt>Software</dt><dd>" + escapeHtml(String(m.software_version || "—")) + "</dd>",
      "<dt>Last inventory (your time)</dt><dd>" + escapeHtml(formatLocal(m.synced_at_utc)) + "</dd>",
      "<dt>Status since (your time)</dt><dd>" + escapeHtml(formatLocal(m.state_changed_at_utc)) + "</dd>",
    ];
    detailBody.innerHTML = '<dl class="terra-home-map-detail__dl">' + rows.join("") + "</dl>";
    detailMore.href = "/devices/" + encodeURIComponent(String(m.id));
    if (detailTitle) {
      detailTitle.textContent = m.name || "Device";
    }
    detailEl.hidden = false;
  }

  if (detailClose) {
    detailClose.addEventListener("click", hideDetail);
  }
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      hideDetail();
    }
  });

  var map = L.map(mount, { scrollWheelZoom: true });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(map);

  map.on("click", function () {
    hideDetail();
  });

  var fg = L.featureGroup();
  var PIN_W = 100;
  var PIN_H = 44;

  markers.forEach(function (m) {
    var icon = L.divIcon({
      className: "terra-map-pin-wrap",
      html: buildPinHtml(m),
      iconSize: [PIN_W, PIN_H],
      iconAnchor: [PIN_W / 2, PIN_H],
    });
    var marker = L.marker([m.lat, m.lng], { icon: icon });
    marker.on("click", function (ev) {
      if (ev && ev.originalEvent) {
        ev.originalEvent.stopPropagation();
      }
      showDetail(markersById[m.id] || m);
    });
    fg.addLayer(marker);
  });

  fg.addTo(map);
  if (markers.length === 1) {
    map.setView([markers[0].lat, markers[0].lng], 11);
  } else {
    map.fitBounds(fg.getBounds().pad(0.12));
  }

  setInterval(pollTelemetry, 12000);
})();
