/** Stable column ids — bump GRID_PREFS_KEY schema when adding/removing ids. */
export const COLUMN_META: { id: string; label: string; sortable?: boolean }[] = [
  { id: "cluster", label: "Cluster", sortable: true },
  { id: "tenant", label: "Tenant", sortable: true },
  { id: "owner_email", label: "Account", sortable: true },
  { id: "hostname", label: "Hostname", sortable: true },
  { id: "serial_number", label: "Serial", sortable: true },
  { id: "model", label: "Model", sortable: true },
  { id: "software_version", label: "Software", sortable: true },
  { id: "device_type", label: "Type", sortable: true },
  { id: "site_name", label: "Site Name", sortable: true },
  { id: "cellular", label: "Cellular" },
  { id: "reachability", label: "Reachability", sortable: true },
  { id: "state_changed_at_utc", label: "Since status (local)", sortable: true },
  { id: "synced_at_utc", label: "Last inventory (local)", sortable: true },
];

export const SORTABLE_COLUMN_IDS = new Set(
  COLUMN_META.filter((c) => c.sortable).map((c) => c.id),
);
