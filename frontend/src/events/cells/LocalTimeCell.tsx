type Props = { iso: string };

export function LocalTimeCell({ iso }: Props) {
  const raw = String(iso || "").trim();
  if (!raw) {
    return <span>—</span>;
  }
  let text = raw;
  try {
    const d = new Date(raw.includes("T") ? raw : raw.replace(" ", "T") + "Z");
    if (!Number.isNaN(d.getTime())) {
      text = d.toLocaleString(undefined, {
        year: "numeric",
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    }
  } catch {
    /* keep raw */
  }
  return <time dateTime={raw}>{text}</time>;
}
