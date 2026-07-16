import { useCallback, useEffect, useState } from "react";

import type { GovernanceEventsListResponse } from "../types";

export type EventsQuery = {
  limit: number;
  offset: number;
  q: string;
  sort: string;
  sortDesc: boolean;
  rangeHours: number;
  streams: string[];
  severities: string[];
  sdwanInstanceId: number | null;
  deviceId: number | null;
  activeOnly: boolean;
};

export function useEventsList(query: EventsQuery) {
  const [items, setItems] = useState<GovernanceEventsListResponse["items"]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchList = useCallback(async () => {
    setLoading(true);
    setError(null);
    const end = Math.floor(Date.now() / 1000);
    const start = end - query.rangeHours * 3600;
    const params = new URLSearchParams({
      limit: String(query.limit),
      offset: String(query.offset),
      sort: query.sort,
      dir: query.sortDesc ? "desc" : "asc",
      start: String(start),
      end: String(end),
    });
    if (query.q.trim()) {
      params.set("q", query.q.trim());
    }
    if (query.streams.length) {
      params.set("stream", query.streams.join(","));
    }
    if (query.severities.length) {
      params.set("severity", query.severities.join(","));
    }
    if (query.sdwanInstanceId != null) {
      params.set("sdwan_instance_id", String(query.sdwanInstanceId));
    }
    if (query.deviceId != null) {
      params.set("device_id", String(query.deviceId));
    }
    if (query.activeOnly) {
      params.set("active", "true");
    }
    try {
      const r = await fetch(`/api/v1/me/governance/events?${params}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!r.ok) {
        throw new Error(`HTTP ${r.status}`);
      }
      const body = (await r.json()) as GovernanceEventsListResponse;
      setItems(body.items);
      setTotal(body.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load events");
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
