/**
 * Home dashboard — Leaflet map for devices that include lat/lng in Manager JSON.
 */
(function () {
  var mount = document.getElementById("terra-home-map");
  var jsonEl = document.getElementById("terra-home-map-markers");
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

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  var map = L.map(mount, { scrollWheelZoom: true });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(map);

  var fg = L.featureGroup();

  markers.forEach(function (m) {
    var ok = !!m.online;
    var cls = ok ? "terra-map-marker-dot--online" : "terra-map-marker-dot--offline";
    var icon = L.divIcon({
      className: "terra-map-marker-wrap",
      html: '<div class="terra-map-marker-dot ' + cls + '" aria-hidden="true"></div>',
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    });
    var marker = L.marker([m.lat, m.lng], { icon: icon, title: m.name });
    var lines = [
      "<strong>" + escapeHtml(m.name) + "</strong>",
      "Reachability: " + escapeHtml(String(m.reachability || "—")),
    ];
    if (m.model) {
      lines.push("Model: " + escapeHtml(String(m.model)));
    }
    if (m.site) {
      lines.push("Site: " + escapeHtml(String(m.site)));
    }
    if (m.serial) {
      lines.push("Serial: " + escapeHtml(String(m.serial)));
    }
    marker.bindPopup('<div class="terra-map-popup">' + lines.join("<br/>") + "</div>");
    fg.addLayer(marker);
  });

  fg.addTo(map);
  if (markers.length === 1) {
    map.setView([markers[0].lat, markers[0].lng], 11);
  } else {
    map.fitBounds(fg.getBounds().pad(0.12));
  }
})();
