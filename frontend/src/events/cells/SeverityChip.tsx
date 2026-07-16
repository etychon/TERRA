type Props = { value: string };

function severityTone(value: string): string {
  const v = (value || "unknown").toLowerCase();
  if (v === "critical") {
    return "error";
  }
  if (v === "major") {
    return "warning";
  }
  if (v === "minor") {
    return "neutral";
  }
  if (v === "info") {
    return "success";
  }
  return "neutral";
}

function severityLabel(value: string): string {
  const v = (value || "unknown").toLowerCase();
  return v.charAt(0).toUpperCase() + v.slice(1);
}

export function SeverityChip({ value }: Props) {
  const tone = severityTone(value);
  const label = severityLabel(value);
  return (
    <span className={`terra-dg-chip terra-dg-chip--${tone}`} role="status">
      {label}
    </span>
  );
}

type FilterProps = {
  value: string;
  active: boolean;
  onClick: () => void;
};

export function SeverityFilterButton({ value, active, onClick }: FilterProps) {
  const tone = severityTone(value);
  const label = severityLabel(value);
  return (
    <button
      type="button"
      className={`terra-eg-sev-btn terra-dg-chip terra-dg-chip--${tone}${active ? ` terra-eg-sev-btn--active terra-eg-sev-btn--active-${tone}` : ""}`}
      onClick={onClick}
      aria-pressed={active}
    >
      {label}
    </button>
  );
}
