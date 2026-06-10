import { useCallback, useMemo, useState } from "react";

import {
  DEFAULT_COLUMN_VISIBILITY,
  GRID_PREFS_KEY,
  type GridPreferences,
} from "../types";

function loadPrefs(): GridPreferences {
  const fallback: GridPreferences = {
    schemaVersion: 1,
    columnVisibility: { ...DEFAULT_COLUMN_VISIBILITY },
    pageSize: 25,
    hideControl: true,
    sortId: "hostname",
    sortDesc: false,
  };
  try {
    const raw = localStorage.getItem(GRID_PREFS_KEY);
    if (!raw) {
      return fallback;
    }
    const parsed = JSON.parse(raw) as Partial<GridPreferences>;
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
      hideControl: typeof parsed.hideControl === "boolean" ? parsed.hideControl : true,
      sortId: typeof parsed.sortId === "string" ? parsed.sortId : "hostname",
      sortDesc: Boolean(parsed.sortDesc),
    };
  } catch {
    return fallback;
  }
}

function savePrefs(prefs: GridPreferences): void {
  try {
    localStorage.setItem(GRID_PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* ignore quota */
  }
}

export function useGridPreferences() {
  const [prefs, setPrefs] = useState<GridPreferences>(() => loadPrefs());

  const update = useCallback((patch: Partial<GridPreferences>) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch };
      savePrefs(next);
      return next;
    });
  }, []);

  const setColumnVisible = useCallback((id: string, visible: boolean) => {
    setPrefs((prev) => {
      const next: GridPreferences = {
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
