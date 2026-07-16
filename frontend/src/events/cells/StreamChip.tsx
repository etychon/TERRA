type Props = { value: string };

const LABELS: Record<string, string> = {
  alarm: "Alarm",
  event: "Event",
  audit: "Audit",
};

export function StreamChip({ value }: Props) {
  const raw = (value || "").toLowerCase();
  let tone = "neutral";
  if (raw === "alarm") {
    tone = "warning";
  } else if (raw === "event") {
    tone = "success";
  } else if (raw === "audit") {
    tone = "neutral";
  }
  return (
    <span className={`terra-dg-chip terra-dg-chip--${tone}`} role="status">
      {LABELS[raw] || value || "—"}
    </span>
  );
}
