import { useCallback, useEffect, useState } from "react";

import type { DeviceHomeRow, DevicesListResponse } from "../types";

export type DevicesQuery = {
  limit: number;
  offset: number;
  q: string;
  sort: string;
  sortDesc: boolean;
  hideControl: boolean;
};

export function useDevicesList(query: DevicesQuery) {
  const [items, setItems] = useState<DeviceHomeRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchList = useCallback(async () => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      limit: String(query.limit),
      offset: String(query.offset),
      sort: query.sort,
      dir: query.sortDesc ? "desc" : "asc",
      hide_control: String(query.hideControl),
    });
    if (query.q.trim()) {
      params.set("q", query.q.trim());
    }
    try {
      const r = await fetch(`/api/v1/me/devices?${params}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!r.ok) {
        throw new Error(`HTTP ${r.status}`);
      }
      const body = (await r.json()) as DevicesListResponse;
      setItems(body.items);
      setTotal(body.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load devices");
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    void fetchList();
  }, [fetchList]);

  return { items, total, loading, error, refresh: fetchList };
}
