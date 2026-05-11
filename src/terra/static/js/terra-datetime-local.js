/**
 * Fill elements carrying UTC ISO in data-utc with the browser's locale string.
 */
(function () {
  function parseUtcMs(iso) {
    if (!iso) {
      return NaN;
    }
    var s = String(iso).trim();
    if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(s) && !/[zZ+]|[+-]\d{2}:?\d{2}$/.test(s)) {
      s = s.replace(" ", "T") + "Z";
    }
    var t = new Date(s);
    return t.getTime();
  }

  function render(el) {
    var iso = el.getAttribute("data-utc");
    var ms = parseUtcMs(iso);
    if (Number.isNaN(ms)) {
      return;
    }
    var d = new Date(ms);
    el.textContent = d.toLocaleString(undefined, { hour12: false });
    el.setAttribute("title", iso || "");
  }

  document.querySelectorAll("time[data-utc].terra-local-time").forEach(render);
})();
