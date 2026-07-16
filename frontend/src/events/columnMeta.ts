export const COLUMN_META: { id: string; label: string; sortable?: boolean }[] = [
  { id: "entry_time_utc", label: "Time (local)", sortable: true },
  { id: "severity_norm", label: "Severity", sortable: true },
  { id: "stream_kind", label: "Stream", sortable: true },
  { id: "active", label: "Active" },
  { id: "cluster", label: "Cluster", sortable: true },
  { id: "tenant", label: "Tenant", sortable: true },
  { id: "device_hostname", label: "Device" },
  { id: "system_ip", label: "System IP", sortable: true },
  { id: "site_id", label: "Site", sortable: true },
  { id: "title", label: "Title", sortable: true },
  { id: "summary", label: "Summary" },
  { id: "loguser", label: "Audit user", sortable: true },
  { id: "logfeature", label: "Audit feature", sortable: true },
];

export const SORTABLE_COLUMN_IDS = new Set(
  COLUMN_META.filter((c) => c.sortable).map((c) => c.id),
);

export const STREAM_OPTIONS = [
  { id: "alarm", label: "Alarms" },
  { id: "event", label: "Events" },
  { id: "audit", label: "Audit" },
];

export const SEVERITY_OPTIONS = ["critical", "major", "minor", "info", "unknown"];

export const RANGE_PRESETS = [
  { hours: 1, label: "1h" },
  { hours: 6, label: "6h" },
  { hours: 24, label: "24h" },
  { hours: 168, label: "7d" },
];
