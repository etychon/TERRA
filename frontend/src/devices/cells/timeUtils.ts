export function utcDate(iso: string): Date {
  let s = String(iso || "").trim();
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(s) && !/[zZ+]|[+-]\d{2}:?\d{2}$/.test(s)) {
    s = s.replace(" ", "T") + "Z";
  }
  return new Date(s);
}

export function formatSince(iso: string, reachability: string): string {
  if (!iso) {
    return "—";
  }
  const t = utcDate(iso);
  if (Number.isNaN(t.getTime())) {
    return "—";
  }
  const ms = Date.now() - t.getTime();
  const sec = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const parts: string[] = [];
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
  const label = String(reachability || "").toLowerCase() === "reachable" ? "Online" : "Offline";
  return `${label} · ${rel}`;
}

export function formatLocalSync(iso: string): string {
  if (!iso) {
    return "—";
  }
  const t = utcDate(iso);
  if (Number.isNaN(t.getTime())) {
    return "—";
  }
  return t.toLocaleString(undefined, { hour12: false });
}
