import { useEffect, useState } from "react";

import type { SparklineItem } from "../types";

/** EIOLTE buckets are 15 min apart and can lag hours behind wall clock; match detail chart (24h). */
export const SPARKLINE_LOOKBACK_MINUTES = 1440;

export function useSparklines(deviceIds: number[]) {
  const [byId, setById] = useState<Map<number, SparklineItem>>(new Map());

  useEffect(() => {
    if (!deviceIds.length) {
      setById(new Map());
      return;
    }
    const key = deviceIds.join(",");
    let cancelled = false;
    const url = `/api/v1/me/devices/cellular/sparklines?ids=${encodeURIComponent(key)}&minutes=${SPARKLINE_LOOKBACK_MINUTES}`;
    fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then((r) => {
        if (!r.ok) {
          throw new Error(String(r.status));
        }
        return r.json() as Promise<{ items: SparklineItem[] }>;
      })
      .then((body) => {
        if (cancelled) {
          return;
        }
        const map = new Map<number, SparklineItem>();
        for (const item of body.items || []) {
          map.set(item.device_id, item);
        }
        setById(map);
      })
      .catch(() => {
        if (!cancelled) {
          setById(new Map());
        }
      });
    return () => {
      cancelled = true;
    };
  }, [deviceIds.join(",")]);

  return byId;
}
