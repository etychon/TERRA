import { useCallback, useMemo, useState } from "react";

import {
  DEFAULT_COLUMN_VISIBILITY,
  EVENTS_GRID_PREFS_KEY,
  type EventsGridPreferences,
} from "../types";

function loadPrefs(): EventsGridPreferences {
  const fallback: EventsGridPreferences = {
    schemaVersion: 1,
    columnVisibility: { ...DEFAULT_COLUMN_VISIBILITY },
    pageSize: 25,
    sortId: "entry_time_utc",
    sortDesc: true,
    rangeHours: 24,
    streams: ["alarm", "event"],
    severities: [],
  };
  try {
    const raw = localStorage.getItem(EVENTS_GRID_PREFS_KEY);
    if (!raw) {
      return fallback;
    }
    const parsed = JSON.parse(raw) as Partial<EventsGridPreferences>;
    if (parsed.schemaVersion !== 1) {
      return fallback;
    }
    const vis: Record<string, boolean> = { ...DEFAULT_COLUMN_VISIBILITY };
    if (parsed.columnVisibility && typeof parsed.columnVisibility === "object") {
      for (const [key, val] of Object.entries(parsed.columnVisibility)) {
        if (key in DEFAULT_COLUMN_VISIBILITY && typeof val === "boolean") {
          vis[key] = val;
        }
      }
    }
    return {
      schemaVersion: 1,
      columnVisibility: vis,
      pageSize: typeof parsed.pageSize === "number" ? parsed.pageSize : 25,
      sortId: typeof parsed.sortId === "string" ? parsed.sortId : "entry_time_utc",
      sortDesc: typeof parsed.sortDesc === "boolean" ? parsed.sortDesc : true,
      rangeHours: typeof parsed.rangeHours === "number" ? parsed.rangeHours : 24,
      streams: Array.isArray(parsed.streams) ? parsed.streams.map(String) : ["alarm", "event"],
      severities: Array.isArray(parsed.severities) ? parsed.severities.map(String) : [],
    };
  } catch {
    return fallback;
  }
}

function savePrefs(prefs: EventsGridPreferences): void {
  try {
    localStorage.setItem(EVENTS_GRID_PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* ignore */
  }
}

export function useGridPreferences() {
  const [prefs, setPrefs] = useState<EventsGridPreferences>(() => loadPrefs());

  const update = useCallback((patch: Partial<EventsGridPreferences>) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch };
      savePrefs(next);
      return next;
    });
  }, []);

  const setColumnVisible = useCallback((id: string, visible: boolean) => {
    setPrefs((prev) => {
      const next: EventsGridPreferences = {
        ...prev,
        columnVisibility: { ...prev.columnVisibility, [id]: visible },
      };
      savePrefs(next);
      return next;
    });
  }, []);

  return useMemo(
    () => ({ prefs, update, setColumnVisible }),
    [prefs, update, setColumnVisible],
  );
}
