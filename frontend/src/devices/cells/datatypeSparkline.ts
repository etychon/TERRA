/** RSSI dBm range mapped to Datatype 0–100 sparkline heights (see datatypeSparkline.ts). */
export const RSSI_FLOOR_DBM = -120;
export const RSSI_CEILING_DBM = -50;

/** Map RSSI (dBm) to a 0–100 height for [Datatype](https://franktisellano.github.io/datatype/) `{l:…}` sparklines. */
export function rssiToSparkHeight(dbm: number): number {
  const clamped = Math.max(RSSI_FLOOR_DBM, Math.min(RSSI_CEILING_DBM, dbm));
  return Math.round(((clamped - RSSI_FLOOR_DBM) / (RSSI_CEILING_DBM - RSSI_FLOOR_DBM)) * 100);
}

/** Build a Datatype sparkline expression from time-series RSSI samples (max 20 points). */
export function datatypeSparklineExpression(points: { v: number }[]): string | null {
  if (!points.length) {
    return null;
  }
  const vals = points.slice(-20).map((p) => rssiToSparkHeight(p.v));
  return `{l:${vals.join(",")}}`;
}
