import type { SparklineItem } from "../types";

import { datatypeSparklineExpression } from "./datatypeSparkline";

type Props = {
  hasCellular: boolean;
  item: SparklineItem | undefined;
  loading?: boolean;
};

function qualityClass(quality: string): string {
  const q = quality.toLowerCase();
  if (q === "excellent" || q === "good" || q === "fair" || q === "poor") {
    return `terra-dg-dot--${q}`;
  }
  return "terra-dg-dot--unknown";
}

export function CellularSparklineCell({ hasCellular, item, loading }: Props) {
  if (!hasCellular) {
    return <span className="terra-dg-muted">—</span>;
  }
  if (loading && !item) {
    return (
      <span className="terra-dg-muted" aria-busy="true">
        …
      </span>
    );
  }
  const q = item?.quality || "unknown";
  const title =
    item?.latest_rssi != null
      ? `RSSI ${item.latest_rssi} dBm · ${q}`
      : "No RSSI samples (recent history)";
  const expr = datatypeSparklineExpression(item?.points || []);
  const sparkClass = `terra-dg-datatype-spark terra-dg-datatype-spark--${q}`;

  return (
    <span className="terra-dg-cellular">
      <span className={`terra-dg-dot ${qualityClass(q)}`} title={title} aria-label={title} />
      {expr ? (
        <span className={sparkClass} aria-hidden="true">
          {expr}
        </span>
      ) : (
        <span className="terra-dg-muted terra-dg-datatype-empty">no samples</span>
      )}
    </span>
  );
}
