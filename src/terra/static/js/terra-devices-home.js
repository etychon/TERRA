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
  const LS_SHOW_CONTROL = showOwner
    ? "terra-devices-show-sdwan-control-v1-owner"
    : "terra-devices-show-sdwan-control-v1";
  /* Long-press for bulk; CLICK_MS must be > LONG_MS so a slow tap (hold then release before bulk) still navigates. */
  const LONG_MS = 750;
  const CLICK_MS = 950;
  const NAV_FLASH_MS = 260;
  const MOVE_PX = 12;

  let data = [];
  try {
    data = JSON.parse(jsonEl.textContent);
  } catch (e) {
    console.warn("terra-devices: invalid JSON", e);
    return;
  }

  let bulkMode = false;
  let columnPickerWired = false;
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

  /** Match ``crud_sdwan._is_controller_inventory_row`` (vManage / vSmart / vBond, etc.). */
  function isControlPlaneRow(row) {
    const rawType = String(row.device_type || "").trim();
    const dt = rawType.toLowerCase();
    if (!dt) {
      return false;
    }
    if (
      dt === "vmanage" ||
      dt === "vsmart" ||
      dt === "vbond" ||
      dt === "vcontainer" ||
      dt === "vmanage-system" ||
      dt.startsWith("vmanage")
    ) {
      return true;
    }
    const host = String(row.hostname || "").trim().toLowerCase();
    return host === "vmanage" || host === "vbond" || host === "vsmart" || host === "vsmart2";
  }

  /** Return true to keep the row visible (used with Tabulator ``addFilter``). */
  function filterHideControlPlaneRows(data) {
    return !isControlPlaneRow(data);
  }

  let showControlPlaneDevices = false;
  try {
    showControlPlaneDevices = window.localStorage.getItem(LS_SHOW_CONTROL) === "1";
  } catch (_e) {
    showControlPlaneDevices = false;
  }

  function syncControlPlaneToggleButton() {
    const btn = document.getElementById("terra-devices-control-plane-btn");
    if (!btn) {
      return;
    }
    btn.setAttribute("aria-pressed", showControlPlaneDevices ? "true" : "false");
    btn.textContent = showControlPlaneDevices ? "Hide control plane" : "Show control plane";
    btn.title = showControlPlaneDevices
      ? "Showing vManage, vSmart, vBond, and related controllers. Click to hide them and show WAN edges only."
      : "WAN edges only. Click to include SD-WAN control-plane nodes (vManage, vSmart, vBond).";
    btn.classList.toggle("terra-devices-control-plane-btn--active", showControlPlaneDevices);
  }

  function persistShowControlPlane() {
    try {
      window.localStorage.setItem(LS_SHOW_CONTROL, showControlPlaneDevices ? "1" : "0");
    } catch (_e) {
      /* ignore */
    }
  }

  function applyControlPlaneRowFilter() {
    try {
      table.removeFilter(filterHideControlPlaneRows);
    } catch (_e) {
      /* filter may not be registered yet */
    }
    if (!showControlPlaneDevices) {
      try {
        table.addFilter(filterHideControlPlaneRows);
      } catch (_e2) {
        /* ignore */
      }
    }
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

  /** Tabulator column persistence can restore _terra_sel as visible after tableBuilt; keep it in sync. */
  function setSelectableRowsEnabled(enabled) {
    try {
      /* Use a high numeric cap: some Tabulator builds treat boolean true like a small limit for rolling selection. */
      table.setOption("selectableRows", enabled ? 9999 : false);
    } catch (_e) {
      /* older Tabulator builds */
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
    setSelectableRowsEnabled(true);
    updateBulkBanner();
    if (firstRow && firstRow.select) {
      firstRow.select();
    }
  }

  function exitBulkMode() {
    try {
      if (typeof table.deselectRow === "function") {
        table.deselectRow();
      }
    } catch (_e) {
      try {
        const rows = table.getSelectedRows ? table.getSelectedRows() : [];
        for (let i = 0; i < rows.length; i++) {
          const r = rows[i];
          if (r && typeof r.deselect === "function") {
            r.deselect();
          }
        }
      } catch (_e2) {
        /* ignore */
      }
    }
    selectedIds.clear();
    selectedOrder.length = 0;
    bulkMode = false;
    setSelectableRowsEnabled(false);
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
    if (!bulkMode) {
      return;
    }
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
    {
      title: "Tenant",
      field: "tenant",
      headerFilter: "input",
      minWidth: 100,
      visible: true,
    },
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
    /* Off until long-press bulk mode; avoids taps being eaten by row selection / double-toggle with our handler. */
    selectableRows: false,
    selectableRowsRollingSelection: true,
    selectableRowsPersistence: false,
    initialSort: [{ column: "hostname", dir: "asc" }],
    persistence: { columns: true, sort: true },
    persistenceID: showOwner ? "terra-devices-grid-v9-owner" : "terra-devices-grid-v9",
    columns: baseColumns,
  });

  table.on("rowSelected", function (row) {
    trackSelected(row, true);
  });
  table.on("rowDeselected", function (row) {
    trackSelected(row, false);
  });

  table.on("columnsLoaded", function () {
    syncSelectionColumn();
    refreshColumnPickerCheckboxes();
  });

  function refreshColumnPickerCheckboxes() {
    const panel = document.getElementById("terra-devices-columns-panel");
    if (!panel) {
      return;
    }
    panel.querySelectorAll('input[type="checkbox"][data-terra-col-field]').forEach(function (cb) {
      const f = cb.getAttribute("data-terra-col-field");
      if (!f) {
        return;
      }
      try {
        const col = table.getColumn(f);
        cb.checked = !!(col && typeof col.isVisible === "function" && col.isVisible());
      } catch (_e) {
        cb.checked = false;
      }
    });
  }

  function wireColumnPicker() {
    const panel = document.getElementById("terra-devices-columns-panel");
    const btn = document.getElementById("terra-devices-columns-btn");
    if (!panel || !btn) {
      return;
    }
    if (columnPickerWired) {
      refreshColumnPickerCheckboxes();
      return;
    }
    columnPickerWired = true;

    panel.innerHTML = "";
    table.getColumns().forEach(function (col) {
      const def = col.getDefinition();
      const f = def.field;
      if (!f || f === "_terra_sel") {
        return;
      }
      const title = def.title != null ? String(def.title) : f;
      const label = document.createElement("label");
      label.className = "terra-devices-columns-item";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.setAttribute("data-terra-col-field", f);
      try {
        cb.checked = typeof col.isVisible === "function" ? col.isVisible() : true;
      } catch (_e) {
        cb.checked = true;
      }
      cb.addEventListener("change", function () {
        try {
          const c = table.getColumn(f);
          if (!c) {
            return;
          }
          if (cb.checked && typeof c.show === "function") {
            c.show();
          } else if (!cb.checked && typeof c.hide === "function") {
            c.hide();
          }
        } catch (_e2) {
          /* ignore */
        }
        refreshColumnPickerCheckboxes();
      });
      const span = document.createElement("span");
      span.textContent = title;
      label.appendChild(cb);
      label.appendChild(span);
      panel.appendChild(label);
    });

    function setOpen(open) {
      panel.hidden = !open;
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    }

    btn.addEventListener("click", function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      setOpen(panel.hidden);
      if (!panel.hidden) {
        refreshColumnPickerCheckboxes();
      }
    });

    document.addEventListener(
      "click",
      function (ev) {
        if (panel.hidden) {
          return;
        }
        if (btn.contains(ev.target) || panel.contains(ev.target)) {
          return;
        }
        setOpen(false);
      },
      true,
    );

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && !panel.hidden) {
        setOpen(false);
        btn.focus();
      }
    });
  }

  table.on("columnVisibilityChanged", function () {
    refreshColumnPickerCheckboxes();
    syncSelectionColumn();
  });

  table.on("pageLoaded", function () {
    reapplySelectionForVisibleRows();
  });

  table.on("tableBuilt", function () {
    syncSelectionColumn();
    applyControlPlaneRowFilter();
    syncControlPlaneToggleButton();
    const root = table.element;
    if (!root) {
      return;
    }

    /* Tabulator can restore header filters from persistence that hide every row; recover automatically. */
    try {
      if (data.length > 0 && table.getRows().length === 0) {
        table.clearHeaderFilter();
      }
    } catch (_e) {
      /* ignore */
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
          /* Tabulator handles row/checkbox selection when selectableRows is enabled. */
          return;
        }
        if (dt < CLICK_MS && st.longArmed) {
          const id = row.getData().id;
          if (id) {
            const url = "/devices/" + id;
            const el = typeof row.getElement === "function" ? row.getElement() : null;
            if (el) {
              el.classList.add("terra-devices-row--navigating");
              void el.offsetWidth;
            }
            window.setTimeout(function () {
              window.location.assign(url);
            }, NAV_FLASH_MS);
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
    wireColumnPicker();
  });

  queueMicrotask(function () {
    updateBulkBanner();
    applyControlPlaneRowFilter();
    syncControlPlaneToggleButton();
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
    bulkExitBtn.addEventListener(
      "click",
      function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        exitBulkMode();
      },
      true,
    );
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

  const controlPlaneBtn = document.getElementById("terra-devices-control-plane-btn");
  if (controlPlaneBtn) {
    syncControlPlaneToggleButton();
    controlPlaneBtn.addEventListener("click", function () {
      showControlPlaneDevices = !showControlPlaneDevices;
      persistShowControlPlane();
      syncControlPlaneToggleButton();
      applyControlPlaneRowFilter();
      try {
        if (data.length > 0 && table.getRows().length === 0) {
          table.clearHeaderFilter();
        }
      } catch (_e) {
        /* ignore */
      }
    });
  }
})();
