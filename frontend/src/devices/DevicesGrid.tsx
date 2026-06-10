import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useCallback, useEffect, useMemo, useState } from "react";

import { CellularSparklineCell } from "./cells/CellularSparklineCell";
import { LocalTimeCell } from "./cells/LocalTimeCell";
import { ReachabilityChip } from "./cells/ReachabilityChip";
import { StatusSinceCell } from "./cells/StatusSinceCell";
import { COLUMN_META, SORTABLE_COLUMN_IDS } from "./columnMeta";
import { useDevicesList } from "./hooks/useDevicesList";
import { useGridPreferences } from "./hooks/useGridPreferences";
import { useSparklines } from "./hooks/useSparklines";
import type { DeviceHomeRow } from "./types";

type Props = { showOwner: boolean };

export function DevicesGrid({ showOwner }: Props) {
  const { prefs, update, setColumnVisible } = useGridPreferences();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [pageIndex, setPageIndex] = useState(0);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [selectedOrder, setSelectedOrder] = useState<number[]>([]);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(search), 300);
    return () => window.clearTimeout(t);
  }, [search]);

  useEffect(() => {
    setPageIndex(0);
  }, [debouncedSearch, prefs.hideControl, prefs.pageSize, prefs.sortId, prefs.sortDesc]);

  const query = useMemo(
    () => ({
      limit: prefs.pageSize,
      offset: pageIndex * prefs.pageSize,
      q: debouncedSearch,
      sort: prefs.sortId,
      sortDesc: prefs.sortDesc,
      hideControl: prefs.hideControl,
    }),
    [prefs.pageSize, pageIndex, debouncedSearch, prefs.sortId, prefs.sortDesc, prefs.hideControl],
  );

  const { items, total, loading, error, refresh } = useDevicesList(query);

  const cellularIds = useMemo(
    () => items.filter((d) => d.has_cellular).map((d) => d.id),
    [items],
  );
  const sparklines = useSparklines(cellularIds);

  const sorting: SortingState = useMemo(
    () => [{ id: prefs.sortId, desc: prefs.sortDesc }],
    [prefs.sortId, prefs.sortDesc],
  );

  const toggleSort = useCallback(
    (columnId: string) => {
      if (!SORTABLE_COLUMN_IDS.has(columnId)) {
        return;
      }
      if (prefs.sortId === columnId) {
        update({ sortDesc: !prefs.sortDesc });
      } else {
        update({ sortId: columnId, sortDesc: false });
      }
    },
    [prefs.sortId, prefs.sortDesc, update],
  );

  const toggleSelected = useCallback((id: number, on: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (on) {
        next.add(id);
      } else {
        next.delete(id);
      }
      return next;
    });
    setSelectedOrder((prev) => {
      if (on) {
        return prev.includes(id) ? prev : [...prev, id];
      }
      return prev.filter((x) => x !== id);
    });
  }, []);

  const exitSelectMode = useCallback(() => {
    setSelectMode(false);
    setSelectedIds(new Set());
    setSelectedOrder([]);
  }, []);

  const columns = useMemo<ColumnDef<DeviceHomeRow>[]>(() => {
    const cols: ColumnDef<DeviceHomeRow>[] = [];
    if (selectMode) {
      cols.push({
        id: "_select",
        header: () => <span className="terra-dg-sr-only">Select</span>,
        cell: ({ row }) => (
          <input
            type="checkbox"
            checked={selectedIds.has(row.original.id)}
            onChange={(e) => toggleSelected(row.original.id, e.target.checked)}
            aria-label={`Select ${row.original.hostname}`}
            onClick={(e) => e.stopPropagation()}
          />
        ),
        size: 40,
      });
    }
    const push = (id: string, header: string, cell: ColumnDef<DeviceHomeRow>["cell"]) => {
      cols.push({ id, accessorKey: id, header, cell });
    };
    push("cluster", "Cluster", (ctx) => ctx.getValue<string>());
    push("tenant", "Tenant", (ctx) => ctx.getValue<string>());
    if (showOwner) {
      push("owner_email", "Account", (ctx) => ctx.getValue<string>());
    }
    push("hostname", "Hostname", (ctx) => ctx.getValue<string>());
    push("serial_number", "Serial", (ctx) => ctx.getValue<string>());
    push("model", "Model", (ctx) => ctx.getValue<string>());
    push("software_version", "Software", (ctx) => ctx.getValue<string>());
    push("device_type", "Type", (ctx) => ctx.getValue<string>());
    push("site_name", "Site Name", (ctx) => ctx.getValue<string>());
    cols.push({
      id: "cellular",
      header: "Cellular",
      cell: ({ row }) => (
        <CellularSparklineCell
          hasCellular={row.original.has_cellular}
          item={sparklines.get(row.original.id)}
          loading={loading}
        />
      ),
    });
    cols.push({
      id: "reachability",
      accessorKey: "reachability",
      header: "Reachability",
      cell: ({ row }) => <ReachabilityChip value={row.original.reachability} />,
    });
    cols.push({
      id: "state_changed_at_utc",
      header: "Since status (local)",
      cell: ({ row }) => (
        <StatusSinceCell iso={row.original.state_changed_at_utc} reachability={row.original.reachability} />
      ),
    });
    cols.push({
      id: "synced_at_utc",
      header: "Last inventory (local)",
      cell: ({ row }) => <LocalTimeCell iso={row.original.synced_at_utc} />,
    });
    return cols;
  }, [selectMode, selectedIds, showOwner, sparklines, loading, toggleSelected]);

  const columnVisibility = useMemo(() => {
    const vis: Record<string, boolean> = { ...prefs.columnVisibility };
    if (!showOwner) {
      vis.owner_email = false;
    }
    if (selectMode) {
      vis._select = true;
    }
    return vis;
  }, [prefs.columnVisibility, showOwner, selectMode]);

  const table = useReactTable({
    data: items,
    columns,
    state: { sorting, columnVisibility },
    onSortingChange: () => undefined,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualPagination: true,
    pageCount: Math.max(1, Math.ceil(total / prefs.pageSize)),
    getRowId: (row) => String(row.id),
  });

  const pageCount = Math.max(1, Math.ceil(total / prefs.pageSize));

  const onRowClick = (row: DeviceHomeRow) => {
    if (selectMode) {
      const on = !selectedIds.has(row.id);
      toggleSelected(row.id, on);
      return;
    }
    window.location.assign(`/devices/${row.id}`);
  };

  const onCompare = () => {
    const ids = selectedOrder.length >= 2 ? selectedOrder : [...selectedIds];
    if (ids.length < 2) {
      window.alert("Select at least two devices, then click Compare selected.");
      return;
    }
    window.location.assign(`/devices/compare?ids=${encodeURIComponent(ids.join(","))}`);
  };

  const onSync = async () => {
    setSyncing(true);
    try {
      const r = await fetch("/api/v1/me/sync-sdwan-devices", { method: "POST", credentials: "same-origin" });
      if (!r.ok) {
        throw new Error(await r.text());
      }
      window.location.reload();
    } catch (e) {
      window.alert(`Sync failed: ${e instanceof Error ? e.message : e}`);
      setSyncing(false);
    }
  };

  const visibleColumnOptions = COLUMN_META.filter((c) => c.id !== "owner_email" || showOwner);

  return (
    <div className="terra-dg-root">
      {selectMode ? (
        <div className="terra-dg-bulk-banner" role="status">
          <span>Selection mode — click rows or use checkboxes. Selection persists across pages.</span>
          <button type="button" className="terra-dg-btn terra-dg-btn--outlined" onClick={exitSelectMode}>
            Done
          </button>
        </div>
      ) : null}

      <div className="terra-dg-toolbar">
        <button
          type="button"
          className="terra-dg-btn terra-dg-btn--filled"
          disabled={syncing}
          onClick={() => void onSync()}
        >
          Sync now
        </button>
        <label className="terra-dg-search">
          <span className="terra-dg-sr-only">Search devices</span>
          <input
            type="search"
            placeholder="Search hostname, serial, model…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <div className="terra-dg-columns-wrap">
          <button
            type="button"
            className="terra-dg-btn terra-dg-btn--outlined"
            aria-expanded={columnsOpen}
            onClick={() => setColumnsOpen((o) => !o)}
          >
            Columns
          </button>
          {columnsOpen ? (
            <div className="terra-dg-columns-panel" role="group" aria-label="Choose columns">
              {visibleColumnOptions.map((col) => (
                <label key={col.id} className="terra-dg-columns-item">
                  <input
                    type="checkbox"
                    checked={prefs.columnVisibility[col.id] !== false}
                    onChange={(e) => setColumnVisible(col.id, e.target.checked)}
                  />
                  <span>{col.label}</span>
                </label>
              ))}
            </div>
          ) : null}
        </div>
        <button
          type="button"
          className={`terra-dg-btn terra-dg-btn--outlined${prefs.hideControl ? "" : " terra-dg-btn--active"}`}
          aria-pressed={!prefs.hideControl}
          onClick={() => update({ hideControl: !prefs.hideControl })}
        >
          {prefs.hideControl ? "Show control elements" : "Hide control elements"}
        </button>
        <button
          type="button"
          className={`terra-dg-btn terra-dg-btn--outlined${selectMode ? " terra-dg-btn--active" : ""}`}
          aria-pressed={selectMode}
          onClick={() => (selectMode ? exitSelectMode() : setSelectMode(true))}
        >
          {selectMode ? "Browsing" : "Select"}
        </button>
        <button
          type="button"
          className={`terra-dg-btn terra-dg-btn--outlined${selectedIds.size >= 2 ? " terra-dg-btn--ready" : ""}`}
          onClick={onCompare}
        >
          Compare selected{selectedIds.size ? ` (${selectedIds.size})` : ""}
        </button>
        <button type="button" className="terra-dg-btn terra-dg-btn--outlined" onClick={() => void refresh()}>
          Refresh
        </button>
      </div>

      {error ? (
        <p className="terra-dg-error" role="alert">
          Could not load devices: {error}
        </p>
      ) : null}

      <div className="terra-dg-table-wrap" aria-busy={loading}>
        <table className="terra-dg-table">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((header) => {
                  if (!header.column.getIsVisible()) {
                    return null;
                  }
                  const colId = header.column.id;
                  const sortable = SORTABLE_COLUMN_IDS.has(colId);
                  const sorted = prefs.sortId === colId;
                  return (
                    <th key={header.id} scope="col">
                      {sortable ? (
                        <button
                          type="button"
                          className="terra-dg-th-btn"
                          onClick={() => toggleSort(colId)}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {sorted ? (prefs.sortDesc ? " ↓" : " ↑") : ""}
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {items.length === 0 && !loading ? (
              <tr>
                <td colSpan={20} className="terra-dg-empty">
                  No devices match your filters.
                </td>
              </tr>
            ) : null}
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className="terra-dg-row"
                tabIndex={0}
                onClick={() => onRowClick(row.original)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onRowClick(row.original);
                  }
                }}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="terra-dg-pager">
        <label>
          Rows per page
          <select
            value={prefs.pageSize}
            onChange={(e) => update({ pageSize: Number(e.target.value) })}
          >
            {[10, 25, 50, 100].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <span>
          {total === 0
            ? "0 devices"
            : `${pageIndex * prefs.pageSize + 1}–${Math.min(total, (pageIndex + 1) * prefs.pageSize)} of ${total}`}
        </span>
        <button
          type="button"
          className="terra-dg-btn terra-dg-btn--outlined"
          disabled={pageIndex <= 0}
          onClick={() => setPageIndex((p) => Math.max(0, p - 1))}
        >
          Previous
        </button>
        <button
          type="button"
          className="terra-dg-btn terra-dg-btn--outlined"
          disabled={pageIndex >= pageCount - 1}
          onClick={() => setPageIndex((p) => p + 1)}
        >
          Next
        </button>
      </div>
    </div>
  );
}
