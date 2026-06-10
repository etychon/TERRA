type Props = { value: string };

export function ReachabilityChip({ value }: Props) {
  const raw = value || "—";
  const v = raw.toLowerCase();
  let tone = "neutral";
  if (v === "reachable") {
    tone = "success";
  } else if (v === "unreachable") {
    tone = "warning";
  }
  return (
    <span className={`terra-dg-chip terra-dg-chip--${tone}`} role="status">
      {raw}
    </span>
  );
}
