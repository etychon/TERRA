/**
 * Admin Logs: tail stream with optional wildcard search; newest entries at the top.
 */
(function () {
  function streamEl() {
    return document.getElementById("terra-logs-stream");
  }

  function qInput() {
    return document.getElementById("terra-logs-q");
  }

  let maxSeq = 0;
  let playing = true;
  let searchActive = false;
  let pollTimer = null;

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function levelClass(level) {
    const l = String(level || "INFO").toUpperCase();
    if (l === "DEBUG") return "terra-log-row--debug";
    if (l === "WARNING" || l === "WARN") return "terra-log-row--warning";
    if (l === "ERROR" || l === "CRITICAL") return "terra-log-row--error";
    return "terra-log-row--info";
  }

  function renderRow(e) {
    const d = new Date(e.ts);
    const localTs = Number.isNaN(d.getTime())
      ? esc(e.ts)
      : esc(d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "medium" }));
    const http = e.http_status != null && e.http_status !== "" ? esc(String(e.http_status)) : "—";
    const detail = e.detail ? `<div class="terra-log-detail">${esc(e.detail)}</div>` : "";
    return (
      `<div class="terra-log-row ${levelClass(e.level)}" data-seq="${e.seq}">` +
      `<span class="terra-log-ts">${localTs}</span>` +
      `<span class="terra-log-level">${esc(e.level)}</span>` +
      `<span class="terra-log-component" title="${esc(e.component)}">${esc(e.component)}</span>` +
      `<span class="terra-log-msg">${esc(e.message)}</span>` +
      `<span class="terra-log-http">${http}</span>` +
      detail +
      `</div>`
    );
  }

  /** With newest-at-top layout, "live" edge is the top of the scroll area. */
  function scrollToLiveEdgeIfPlaying() {
    const el = streamEl();
    if (!el || !playing) {
      return;
    }
    el.scrollTop = 0;
  }

  async function fetchTail() {
    if (searchActive) {
      return;
    }
    const r = await fetch(`/api/v1/admin/logs?since=${maxSeq}&limit=200`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!r.ok) {
      return;
    }
    const data = await r.json();
    const el = streamEl();
    if (!el) {
      return;
    }
    const batch = data.entries || [];
    let added = false;
    for (let i = batch.length - 1; i >= 0; i--) {
      const e = batch[i];
      if (e.seq <= maxSeq) {
        continue;
      }
      if (el.querySelector(`[data-seq="${e.seq}"]`)) {
        continue;
      }
      el.insertAdjacentHTML("afterbegin", renderRow(e));
      maxSeq = Math.max(maxSeq, e.seq);
      added = true;
    }
    if (typeof data.tail_seq === "number") {
      maxSeq = Math.max(maxSeq, data.tail_seq);
    }
    if (added) {
      scrollToLiveEdgeIfPlaying();
    }
  }

  async function initialLoad() {
    const el = streamEl();
    if (!el) {
      return;
    }
    const r = await fetch("/api/v1/admin/logs?since=0&limit=400", { credentials: "same-origin" });
    if (!r.ok) {
      el.textContent = r.status === 403 ? "Admin role required to view logs." : "Could not load logs.";
      return;
    }
    const data = await r.json();
    const rows = data.entries || [];
    el.innerHTML = rows.map(renderRow).join("");
    maxSeq = 0;
    for (const e of rows) {
      maxSeq = Math.max(maxSeq, e.seq);
    }
    scrollToLiveEdgeIfPlaying();
  }

  async function runSearch() {
    const q = (qInput()?.value || "").trim();
    const el = streamEl();
    if (!el) {
      return;
    }
    if (!q) {
      searchActive = false;
      await initialLoad();
      return;
    }
    searchActive = true;
    const r = await fetch(`/api/v1/admin/logs?q=${encodeURIComponent(q)}&limit=400`, { credentials: "same-origin" });
    if (!r.ok) {
      return;
    }
    const data = await r.json();
    el.innerHTML = (data.entries || []).map(renderRow).join("");
    maxSeq = 0;
    for (const e of data.entries || []) {
      maxSeq = Math.max(maxSeq, e.seq);
    }
    scrollToLiveEdgeIfPlaying();
  }

  document.addEventListener("DOMContentLoaded", function () {
    initialLoad();
    pollTimer = window.setInterval(fetchTail, 850);

    const scrollBtn = document.getElementById("terra-logs-scroll-toggle");
    if (scrollBtn) {
      scrollBtn.addEventListener("click", function () {
        playing = !playing;
        scrollBtn.setAttribute("aria-pressed", playing ? "true" : "false");
        scrollBtn.textContent = playing ? "Pause scroll" : "Resume scroll";
        if (playing) {
          scrollToLiveEdgeIfPlaying();
        }
      });
    }

    document.getElementById("terra-logs-search-btn")?.addEventListener("click", runSearch);
    document.getElementById("terra-logs-clear-btn")?.addEventListener("click", function () {
      const inp = qInput();
      if (inp) {
        inp.value = "";
      }
      searchActive = false;
      initialLoad();
    });
    qInput()?.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") {
        runSearch();
      }
    });
  });

  window.addEventListener("beforeunload", function () {
    if (pollTimer) {
      window.clearInterval(pollTimer);
    }
  });
})();
