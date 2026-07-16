import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ActiveChip } from "./cells/ActiveChip";
import { LocalTimeCell } from "./cells/LocalTimeCell";
import { SeverityChip, SeverityFilterButton } from "./cells/SeverityChip";
import { StreamChip } from "./cells/StreamChip";
import { COLUMN_META, RANGE_PRESETS, SEVERITY_OPTIONS, SORTABLE_COLUMN_IDS, STREAM_OPTIONS } from "./columnMeta";
import { useEventsList } from "./hooks/useEventsList";
import { useGridPreferences } from "./hooks/useGridPreferences";
import type { GovernanceEventRow } from "./types";

function readDeviceFilterFromUrl(): number | null {
  try {
    const p = new URLSearchParams(window.location.search);
    const raw = p.get("device_id");
    if (!raw) {
      return null;
    }
    const n = parseInt(raw, 10);
    return Number.isNaN(n) ? null : n;
  } catch {
    return null;
  }
}

export function EventsGrid() {
  const { prefs, update, setColumnVisible } = useGridPreferences();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [pageIndex, setPageIndex] = useState(0);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [activeOnly, setActiveOnly] = useState(false);
  const [clusterFilter] = useState<number | null>(null);
  const [deviceFilter] = useState<number | null>(() => readDeviceFilterFromUrl());
  const [detail, setDetail] = useState<GovernanceEventRow | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(search), 300);
    return () => window.clearTimeout(t);
  }, [search]);

  useEffect(() => {
    setPageIndex(0);
  }, [debouncedSearch, prefs.pageSize, prefs.sortId, prefs.sortDesc, prefs.rangeHours, prefs.streams, prefs.severities, activeOnly, clusterFilter, deviceFilter]);

  const query = useMemo(
    () => ({
      limit: prefs.pageSize,
      offset: pageIndex * prefs.pageSize,
      q: debouncedSearch,
      sort: prefs.sortId,
      sortDesc: prefs.sortDesc,
      rangeHours: prefs.rangeHours,
      streams: prefs.streams,
      severities: prefs.severities,
      sdwanInstanceId: clusterFilter,
      deviceId: deviceFilter,
      activeOnly,
    }),
    [prefs.pageSize, pageIndex, debouncedSearch, prefs.sortId, prefs.sortDesc, prefs.rangeHours, prefs.streams, prefs.severities, clusterFilter, deviceFilter, activeOnly],
  );

  const { items, total, loading, error, refresh } = useEventsList(query);

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
        update({ sortId: columnId, sortDesc: columnId === "entry_time_utc" });
      }
    },
    [prefs.sortId, prefs.sortDesc, update],
  );

  const toggleStream = useCallback(
    (id: string) => {
      const set = new Set(prefs.streams);
      if (set.has(id)) {
        set.delete(id);
      } else {
        set.add(id);
      }
      update({ streams: [...set] });
    },
    [prefs.streams, update],
  );

  const toggleSeverity = useCallback(
    (sev: string) => {
      const set = new Set(prefs.severities);
      if (set.has(sev)) {
        set.delete(sev);
      } else {
        set.add(sev);
      }
      update({ severities: [...set] });
    },
    [prefs.severities, update],
  );

  const columns = useMemo<ColumnDef<GovernanceEventRow>[]>(() => {
    const defs: ColumnDef<GovernanceEventRow>[] = [];
    for (const meta of COLUMN_META) {
      if (prefs.columnVisibility[meta.id] === false) {
        continue;
      }
      defs.push({
        id: meta.id,
        accessorKey: meta.id,
        header: meta.label,
        cell: ({ row }) => {
          const r = row.original;
          switch (meta.id) {
            case "entry_time_utc":
              return <LocalTimeCell iso={r.entry_time_utc} />;
            case "severity_norm":
              return <SeverityChip value={r.severity_norm} />;
            case "stream_kind":
              return <StreamChip value={r.stream_kind} />;
            case "active":
              return <ActiveChip active={r.active} streamKind={r.stream_kind} />;
            case "title":
              return <span className="terra-eg-clip" title={r.title}>{r.title || "—"}</span>;
            case "summary":
              return <span className="terra-eg-clip" title={r.summary}>{r.summary || "—"}</span>;
            case "device_hostname":
              if (r.device_id) {
                return (
                  <a className="terra-eg-link" href={`/devices/${r.device_id}`}>
                    {r.device_hostname || r.system_ip}
                  </a>
                );
              }
              return r.device_hostname || r.system_ip || "—";
            default:
              return String((r as Record<string, unknown>)[meta.id] ?? "—");
          }
        },
      });
    }
    return defs;
  }, [prefs.columnVisibility]);

  const table = useReactTable({
    data: items,
    columns,
    state: { sorting },
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
  });

  const pageCount = Math.max(1, Math.ceil(total / prefs.pageSize));

  return (
    <div className="terra-dg-root terra-eg-root">
      {deviceFilter != null ? (
        <p className="terra-eg-filter-banner" role="status">
          Filtered to device id <strong>{deviceFilter}</strong>.{" "}
          <a href="/events">Clear device filter</a>
        </p>
      ) : null}

      <div className="terra-dg-toolbar terra-eg-toolbar">
        <div className="terra-eg-presets" role="group" aria-label="Time range">
          {RANGE_PRESETS.map((p) => (
            <button
              key={p.hours}
              type="button"
              className={`terra-dg-btn terra-dg-btn--outlined${prefs.rangeHours === p.hours ? " terra-dg-btn--active" : ""}`}
              onClick={() => update({ rangeHours: p.hours })}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="terra-eg-streams" role="group" aria-label="Streams">
          {STREAM_OPTIONS.map((s) => (
            <label key={s.id} className="terra-eg-toggle">
              <input
                type="checkbox"
                checked={prefs.streams.includes(s.id)}
                onChange={() => toggleStream(s.id)}
              />
              {s.label}
            </label>
          ))}
        </div>
        <label className="terra-eg-toggle">
          <input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} />
          Active alarms only
        </label>
        <label className="terra-dg-search">
          <span className="terra-dg-sr-only">Search events</span>
          <input
            type="search"
            placeholder="Search title, summary, user, IP…"
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
              {COLUMN_META.map((col) => (
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
        <button type="button" className="terra-dg-btn terra-dg-btn--outlined" onClick={() => void refresh()}>
          Refresh
        </button>
      </div>

      <div className="terra-eg-severity-bar" role="group" aria-label="Severity filters">
        {SEVERITY_OPTIONS.map((sev) => (
          <SeverityFilterButton
            key={sev}
            value={sev}
            active={prefs.severities.includes(sev)}
            onClick={() => toggleSeverity(sev)}
          />
        ))}
        {prefs.severities.length ? (
          <button type="button" className="terra-dg-btn terra-dg-btn--text" onClick={() => update({ severities: [] })}>
            Clear severity
          </button>
        ) : null}
      </div>

      {error ? (
        <p className="terra-dg-error" role="alert">
          Could not load events: {error}
        </p>
      ) : null}

      <div className="terra-dg-table-wrap" aria-busy={loading}>
        <table className="terra-dg-table">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => {
                  const sortable = SORTABLE_COLUMN_IDS.has(h.column.id);
                  const sorted = prefs.sortId === h.column.id;
                  return (
                    <th key={h.id} scope="col">
                      {sortable ? (
                        <button
                          type="button"
                          className="terra-dg-sort-btn"
                          onClick={() => toggleSort(h.column.id)}
                          aria-sort={sorted ? (prefs.sortDesc ? "descending" : "ascending") : "none"}
                        >
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {sorted ? (prefs.sortDesc ? " ↓" : " ↑") : ""}
                        </button>
                      ) : (
                        flexRender(h.column.columnDef.header, h.getContext())
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
                <td colSpan={columns.length} className="terra-eg-empty">
                  No events in this window. The collector syncs alarms, events, and audit on a timer.
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => (
                <tr key={row.id} className="terra-eg-row" onClick={() => setDetail(row.original)}>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="terra-dg-pager">
        <button
          type="button"
          className="terra-dg-btn terra-dg-btn--outlined"
          disabled={pageIndex <= 0}
          onClick={() => setPageIndex((p) => Math.max(0, p - 1))}
        >
          Previous
        </button>
        <span>
          Page {pageIndex + 1} of {pageCount} · {total} row{total === 1 ? "" : "s"}
        </span>
        <button
          type="button"
          className="terra-dg-btn terra-dg-btn--outlined"
          disabled={(pageIndex + 1) * prefs.pageSize >= total}
          onClick={() => setPageIndex((p) => p + 1)}
        >
          Next
        </button>
      </div>

      {detail ? (
        <div className="terra-eg-detail" role="dialog" aria-modal="true" aria-label="Event detail">
          <div className="terra-eg-detail__panel">
            <div className="terra-eg-detail__head">
              <h2 className="terra-eg-detail__title">{detail.title || "Event"}</h2>
              <button type="button" className="terra-dg-btn terra-dg-btn--outlined" onClick={() => setDetail(null)}>
                Close
              </button>
            </div>
            <p className="terra-eg-detail__summary">{detail.summary}</p>
            <dl className="terra-eg-detail__meta">
              <div><dt>Stream</dt><dd><StreamChip value={detail.stream_kind} /></dd></div>
              <div><dt>Severity</dt><dd><SeverityChip value={detail.severity_norm} /></dd></div>
              <div><dt>Time</dt><dd><LocalTimeCell iso={detail.entry_time_utc} /></dd></div>
              <div><dt>Cluster</dt><dd>{detail.cluster}</dd></div>
              <div><dt>Device</dt><dd>{detail.device_hostname}</dd></div>
              <div><dt>System IP</dt><dd>{detail.system_ip}</dd></div>
              {detail.loguser !== "—" ? <div><dt>Audit user</dt><dd>{detail.loguser}</dd></div> : null}
            </dl>
          </div>
        </div>
      ) : null}
    </div>
  );
}
