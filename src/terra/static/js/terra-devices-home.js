/**
 * Tabulator device grid: short tap opens detail, long-press enters bulk selection (cross-page),
 * compare uses accumulated selection. Durations use browser local time from UTC ISO fields.
 */
(function () {
  const jsonEl = document.getElementById("terra-devices-json");
  const mount = document.getElementById("terra-devices-table");
  const bulkBanner = document.getElementById("terra-devices-bulk-banner");
  const bulkExitBtn = document.getElementById("terra-devices-bulk-exit");
  const compareBtn = document.getElementById("terra-devices-compare-btn");
  const compareLabel = document.getElementById("terra-devices-compare-label");
  if (!jsonEl || !mount || typeof Tabulator === "undefined") {
    return;
  }
  const showOwner = mount.getAttribute("data-show-owner") === "true";
  const LONG_MS = 550;
  const CLICK_MS = 420;
  const MOVE_PX = 12;

  let data = [];
  try {
    data = JSON.parse(jsonEl.textContent);
  } catch (e) {
    console.warn("terra-devices: invalid JSON", e);
    return;
  }

  let bulkMode = false;
  /** @type {Set<number>} */
  const selectedIds = new Set();
  /** @type {number[]} preserve selection order for compare */
  const selectedOrder = [];
  let longPressTimer = null;
  let pointerState = null;
  let suppressNextRowTap = false;

  /** Parse backend UTC ISO (…Z or naive assumed UTC) for correct local-relative math. */
  function utcDate(iso) {
    let s = String(iso || "").trim();
    if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(s) && !/[zZ+]|[+-]\d{2}:?\d{2}$/.test(s)) {
      s = s.replace(" ", "T") + "Z";
    }
    return new Date(s);
  }

  function formatSince(_cell) {
    const row = _cell.getRow().getData();
    const iso = row.state_changed_at_utc;
    const reach = String(row.reachability || "").toLowerCase();
    if (!iso) {
      return "—";
    }
    const t = utcDate(iso);
    if (Number.isNaN(t.getTime())) {
      return "—";
    }
    const ms = Date.now() - t.getTime();
    const parts = [];
    const sec = Math.max(0, Math.floor(ms / 1000));
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    if (d) {
      parts.push(`${d}d`);
    }
    if (h && parts.length < 2) {
      parts.push(`${h}h`);
    }
    if (m && parts.length < 2) {
      parts.push(`${m}m`);
    }
    const rel = parts.length ? parts.join(" ") : "<1m";
    const label = reach === "reachable" ? "Online" : "Offline";
    return `${label} · ${rel}`;
  }

  function formatLocalSync(_cell) {
    const row = _cell.getRow().getData();
    const iso = row.synced_at_utc;
    if (!iso) {
      return "—";
    }
    const t = utcDate(iso);
    if (Number.isNaN(t.getTime())) {
      return "—";
    }
    return t.toLocaleString(undefined, { hour12: false });
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function reachFormatter(cell) {
    const raw = cell.getValue() || "—";
    const v = String(raw).toLowerCase();
    let tone = "neutral";
    if (v === "reachable") {
      tone = "success";
    } else if (v === "unreachable") {
      tone = "warning";
    }
    const label = escapeHtml(raw);
    return `<span class="terra-m3-chip terra-m3-chip--${tone}" role="status">${label}</span>`;
  }

  function findRowFromPointer(table, target) {
    if (!target || !target.closest) {
      return null;
    }
    const rowEl = target.closest(".tabulator-row");
    if (!rowEl || !table || !table.getRows) {
      return null;
    }
    const rows = table.getRows();
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      const el = r.getElement();
      if (el && (el === rowEl || el.contains(rowEl))) {
        return r;
      }
    }
    return null;
  }

  function syncSelectionColumn() {
    try {
      if (bulkMode) {
        table.showColumn("_terra_sel");
      } else {
        table.hideColumn("_terra_sel");
      }
    } catch (_e) {
      /* column API may vary by Tabulator build */
    }
  }

  function updateBulkBanner() {
    if (bulkBanner) {
      bulkBanner.hidden = !bulkMode;
    }
    document.body.classList.toggle("terra-devices--bulk-mode", bulkMode);
    syncSelectionColumn();
  }

  function enterBulkMode(firstRow) {
    if (bulkMode) {
      return;
    }
    bulkMode = true;
    updateBulkBanner();
    if (firstRow && firstRow.select) {
      firstRow.select();
    }
  }

  function exitBulkMode() {
    bulkMode = false;
    table.deselectRow();
    selectedIds.clear();
    selectedOrder.length = 0;
    updateBulkBanner();
    updateCompareButton();
    flashCompareButton();
  }

  function updateCompareButton() {
    if (!compareBtn || !compareLabel) {
      return;
    }
    const n = selectedIds.size;
    compareLabel.textContent = n === 0 ? "Compare selected" : `Compare selected (${n})`;
    compareBtn.classList.toggle("terra-devices-compare-btn--ready", n >= 2);
  }

  function flashCompareButton() {
    if (!compareBtn) {
      return;
    }
    compareBtn.classList.remove("terra-devices-compare-btn--flash");
    void compareBtn.offsetWidth;
    compareBtn.classList.add("terra-devices-compare-btn--flash");
    function onFlashEnd(e) {
      if (e.animationName !== "terra-devices-compare-flash-once") {
        return;
      }
      compareBtn.classList.remove("terra-devices-compare-btn--flash");
      compareBtn.removeEventListener("animationend", onFlashEnd);
    }
    compareBtn.addEventListener("animationend", onFlashEnd);
  }

  function trackSelected(row, selected) {
    const id = row.getData().id;
    if (selected) {
      selectedIds.add(id);
      if (!selectedOrder.includes(id)) {
        selectedOrder.push(id);
      }
    } else {
      selectedIds.delete(id);
      const ix = selectedOrder.indexOf(id);
      if (ix >= 0) {
        selectedOrder.splice(ix, 1);
      }
    }
    updateCompareButton();
    flashCompareButton();
  }

  function reapplySelectionForVisibleRows() {
    selectedOrder.forEach(function (id) {
      const row = table.getRow(id);
      if (row && row.select) {
        row.select();
      }
    });
  }

  const baseColumns = [
    {
      formatter: "rowSelection",
      titleFormatter: "rowSelection",
      field: "_terra_sel",
      headerSort: false,
      hozAlign: "center",
      width: 40,
      visible: false,
    },
    { title: "Manager", field: "manager", headerFilter: "input", minWidth: 110 },
  ];
  if (showOwner) {
    baseColumns.push({
      title: "Account",
      field: "owner_email",
      headerFilter: "input",
      minWidth: 160,
      visible: false,
    });
  }
  baseColumns.push(
    { title: "Hostname", field: "hostname", headerFilter: "input", minWidth: 130 },
    { title: "Serial", field: "serial_number", headerFilter: "input", minWidth: 110 },
    { title: "Model", field: "model", headerFilter: "input", minWidth: 110 },
    { title: "Software", field: "software_version", headerFilter: "input", minWidth: 110 },
    { title: "Type", field: "device_type", headerFilter: "input", width: 100, visible: false },
    { title: "Site", field: "site_id", headerFilter: "input", width: 90 },
    { title: "Reachability", field: "reachability", formatter: reachFormatter, width: 120 },
    { title: "Since status (local)", field: "state_changed_at_utc", formatter: formatSince, minWidth: 150 },
    { title: "Last inventory (local)", field: "synced_at_utc", formatter: formatLocalSync, minWidth: 150 },
  );

  const table = new Tabulator("#terra-devices-table", {
    data,
    index: "id",
    layout: "fitDataStretch",
    pagination: "local",
    paginationSize: 25,
    paginationSizeSelector: [10, 25, 50, 100],
    movableColumns: true,
    resizableColumns: true,
    selectableRows: true,
    initialSort: [{ column: "hostname", dir: "asc" }],
    persistence: { columns: true, sort: true },
    persistenceID: showOwner ? "terra-devices-grid-v4-owner" : "terra-devices-grid-v4",
    columns: baseColumns,
  });

  table.on("rowSelected", function (row) {
    trackSelected(row, true);
  });
  table.on("rowDeselected", function (row) {
    trackSelected(row, false);
  });

  table.on("pageLoaded", function () {
    reapplySelectionForVisibleRows();
  });

  table.on("tableBuilt", function () {
    syncSelectionColumn();
    const root = table.element;
    if (!root) {
      return;
    }

    root.addEventListener(
      "pointerdown",
      function (e) {
        if (e.button !== 0) {
          return;
        }
        if (e.target.closest && e.target.closest("input[type='checkbox']")) {
          return;
        }
        const row = findRowFromPointer(table, e.target);
        if (!row) {
          return;
        }
        pointerState = {
          row,
          x: e.clientX,
          y: e.clientY,
          t: Date.now(),
          longArmed: true,
        };
        if (longPressTimer) {
          clearTimeout(longPressTimer);
        }
        longPressTimer = setTimeout(function () {
          longPressTimer = null;
          if (!pointerState || !pointerState.longArmed) {
            return;
          }
          pointerState.longArmed = false;
          suppressNextRowTap = true;
          enterBulkMode(pointerState.row);
        }, LONG_MS);
      },
      true,
    );

    root.addEventListener(
      "pointerup",
      function (e) {
        if (longPressTimer) {
          clearTimeout(longPressTimer);
          longPressTimer = null;
        }
        if (!pointerState) {
          return;
        }
        const st = pointerState;
        pointerState = null;
        const row = findRowFromPointer(table, e.target);
        if (!row || row !== st.row) {
          return;
        }
        if (suppressNextRowTap) {
          suppressNextRowTap = false;
          return;
        }
        const dt = Date.now() - st.t;
        const dx = e.clientX - st.x;
        const dy = e.clientY - st.y;
        if (Math.abs(dx) > MOVE_PX || Math.abs(dy) > MOVE_PX) {
          return;
        }
        if (bulkMode) {
          row.toggleSelect();
          return;
        }
        if (dt < CLICK_MS && st.longArmed) {
          const id = row.getData().id;
          if (id) {
            window.location.assign(`/devices/${id}`);
          }
        }
      },
      true,
    );

    root.addEventListener(
      "pointercancel",
      function () {
        if (longPressTimer) {
          clearTimeout(longPressTimer);
          longPressTimer = null;
        }
        pointerState = null;
      },
      true,
    );
    updateCompareButton();
  });

  if (compareBtn) {
    compareBtn.addEventListener("click", function () {
      const ids =
        selectedOrder.length >= 2
          ? selectedOrder.slice()
          : table.getSelectedData().map(function (r) {
              return r.id;
            });
      const uniq = [];
      const seen = new Set();
      ids.forEach(function (id) {
        if (id != null && !seen.has(id)) {
          seen.add(id);
          uniq.push(id);
        }
      });
      if (uniq.length < 2) {
        window.alert("Select at least two devices (long-press a row for bulk mode, then select rows), then click Compare.");
        return;
      }
      window.location.assign(`/devices/compare?ids=${encodeURIComponent(uniq.join(","))}`);
    });
  }

  if (bulkExitBtn) {
    bulkExitBtn.addEventListener("click", function () {
      exitBulkMode();
    });
  }

  const syncBtn = document.getElementById("terra-devices-sync-btn");
  if (syncBtn) {
    syncBtn.addEventListener("click", async function () {
      syncBtn.setAttribute("disabled", "disabled");
      try {
        const r = await fetch("/api/v1/me/sync-sdwan-devices", { method: "POST", credentials: "same-origin" });
        if (!r.ok) {
          const t = await r.text();
          throw new Error(t || r.statusText);
        }
        window.location.reload();
      } catch (err) {
        window.alert("Sync failed: " + err);
        syncBtn.removeAttribute("disabled");
      }
    });
  }
})();
