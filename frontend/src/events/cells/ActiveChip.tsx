type Props = { active: boolean | null; streamKind: string };

export function ActiveChip({ active, streamKind }: Props) {
  if (streamKind !== "alarm") {
    return <span className="terra-dg-muted">—</span>;
  }
  if (active === true) {
    return (
      <span className="terra-dg-chip terra-dg-chip--success terra-eg-active-chip" role="status">
        <span className="terra-eg-active-dot" aria-hidden="true" />
        Active
      </span>
    );
  }
  if (active === false) {
    return <span className="terra-dg-chip terra-dg-chip--neutral">Cleared</span>;
  }
  return <span className="terra-dg-muted">—</span>;
}
