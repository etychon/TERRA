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
  let maxDbId = 0;
  let playing = true;
  let searchActive = false;
  let pollTimer = null;
  let statusTimer = null;

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

  function formatLocalTs(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) {
      return esc(iso);
    }
    return esc(d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "medium" }));
  }

  function formatLocalTsPlain(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) {
      return String(iso ?? "");
    }
    return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "medium" });
  }

  function renderRow(e) {
    const localTs = formatLocalTs(e.ts);
    const http = e.http_status != null && e.http_status !== "" ? esc(String(e.http_status)) : "—";
    const detail = e.detail ? `<div class="terra-log-detail">${esc(e.detail)}</div>` : "";
    const persisted = e.source === "collector" ? " terra-log-row--persisted" : "";
    const rowKey = e.db_id != null ? `db-${e.db_id}` : `seq-${e.seq}`;
    return (
      `<div class="terra-log-row ${levelClass(e.level)}${persisted}" data-row-key="${rowKey}">` +
      `<span class="terra-log-ts">${localTs}</span>` +
      `<span class="terra-log-level">${esc(e.level)}</span>` +
      `<span class="terra-log-component" title="${esc(e.component)}">${esc(e.component)}</span>` +
      `<span class="terra-log-msg">${esc(e.message)}</span>` +
      `<span class="terra-log-http">${http}</span>` +
      detail +
      `</div>`
    );
  }

  function updateCursorsFromEntries(entries) {
    for (const e of entries || []) {
      if (e.db_id != null) {
        maxDbId = Math.max(maxDbId, Number(e.db_id));
      } else if (typeof e.seq === "number" && e.seq < 1000000000) {
        maxSeq = Math.max(maxSeq, e.seq);
      }
    }
  }

  /** With newest-at-top layout, "live" edge is the top of the scroll area. */
  function scrollToLiveEdgeIfPlaying() {
    const el = streamEl();
    if (!el || !playing) {
      return;
    }
    el.scrollTop = 0;
  }

  function isNewEntry(e) {
    if (e.db_id != null) {
      return Number(e.db_id) > maxDbId;
    }
    return typeof e.seq === "number" && e.seq > maxSeq && e.seq < 1000000000;
  }

  async function fetchTail() {
    if (searchActive) {
      return;
    }
    const r = await fetch(`/api/v1/admin/logs?since=${maxSeq}&since_db=${maxDbId}&limit=200`, {
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
      if (!isNewEntry(e)) {
        continue;
      }
      const rowKey = e.db_id != null ? `db-${e.db_id}` : `seq-${e.seq}`;
      if (el.querySelector(`[data-row-key="${rowKey}"]`)) {
        continue;
      }
      el.insertAdjacentHTML("afterbegin", renderRow(e));
      added = true;
    }
    if (typeof data.tail_seq === "number") {
      maxSeq = Math.max(maxSeq, data.tail_seq);
    }
    if (typeof data.tail_db_id === "number") {
      maxDbId = Math.max(maxDbId, data.tail_db_id);
    }
    updateCursorsFromEntries(batch);
    if (added) {
      scrollToLiveEdgeIfPlaying();
    }
  }

  async function initialLoad() {
    const el = streamEl();
    if (!el) {
      return;
    }
    const r = await fetch("/api/v1/admin/logs?since=0&since_db=0&limit=400", { credentials: "same-origin" });
    if (!r.ok) {
      el.textContent = r.status === 403 ? "Admin role required to view logs." : "Could not load logs.";
      return;
    }
    const data = await r.json();
    const rows = data.entries || [];
    el.innerHTML = rows.map(renderRow).join("");
    maxSeq = 0;
    maxDbId = 0;
    if (typeof data.tail_seq === "number") {
      maxSeq = data.tail_seq;
    }
    if (typeof data.tail_db_id === "number") {
      maxDbId = data.tail_db_id;
    }
    updateCursorsFromEntries(rows);
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
    maxSeq = typeof data.tail_seq === "number" ? data.tail_seq : 0;
    maxDbId = typeof data.tail_db_id === "number" ? data.tail_db_id : 0;
    scrollToLiveEdgeIfPlaying();
  }

  function stateChipClass(state) {
    if (state === "alive") return "terra-chip terra-chip--ok";
    if (state === "stale") return "terra-chip terra-chip--warn";
    return "terra-chip terra-chip--muted";
  }

  function stateLabel(state) {
    if (state === "alive") return "Alive";
    if (state === "stale") return "Stale";
    return "No heartbeat";
  }

  async function fetchCollectorStatus() {
    const r = await fetch("/api/v1/admin/collector-status", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!r.ok) {
      return;
    }
    const data = await r.json();
    const stateEl = document.getElementById("terra-collector-state");
    if (stateEl) {
      stateEl.className = stateChipClass(data.state);
      stateEl.textContent = stateLabel(data.state);
    }
    const hb = document.getElementById("terra-collector-heartbeat");
    if (hb) {
      hb.textContent = data.last_heartbeat_at_utc ? formatLocalTsPlain(data.last_heartbeat_at_utc) : "—";
    }
    const interval = document.getElementById("terra-collector-interval");
    if (interval) {
      interval.textContent = data.interval_seconds ? `${data.interval_seconds}s` : "—";
    }
    const batch = document.getElementById("terra-collector-batch");
    if (batch) {
      const lb = data.last_batch || {};
      if (lb.finished_at_utc) {
        const parts = [
          formatLocalTsPlain(lb.finished_at_utc),
          lb.ok != null ? `ok=${lb.ok}` : "",
          lb.warn != null ? `warn=${lb.warn}` : "",
          lb.err != null ? `err=${lb.err}` : "",
          lb.rows != null ? `rows=${lb.rows}` : "",
        ].filter(Boolean);
        batch.textContent = parts.join(" · ");
      } else if (lb.started_at_utc) {
        batch.textContent = `Running since ${formatLocalTsPlain(lb.started_at_utc)}`;
      } else {
        batch.textContent = "—";
      }
    }
    const cell = document.getElementById("terra-collector-cellular");
    if (cell) {
      const lb = data.last_batch || {};
      if (lb.cellular_buckets != null || lb.cellular_errors != null) {
        cell.textContent = `buckets=${lb.cellular_buckets ?? 0} errors=${lb.cellular_errors ?? 0}`;
      } else {
        cell.textContent = "—";
      }
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    initialLoad();
    fetchCollectorStatus();
    pollTimer = window.setInterval(fetchTail, 850);
    statusTimer = window.setInterval(fetchCollectorStatus, 30000);

    document.getElementById("terra-collector-filter-btn")?.addEventListener("click", function () {
      const inp = qInput();
      if (inp) {
        inp.value = "*sdwan_sync_batch*";
      }
      runSearch();
    });

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
    if (statusTimer) {
      window.clearInterval(statusTimer);
    }
  });
})();
