export type GovernanceEventRow = {
  id: number;
  stream_kind: string;
  entry_time_utc: string;
  severity_raw: string;
  severity_norm: string;
  active: boolean | null;
  cluster: string;
  tenant: string;
  sdwan_instance_id: number;
  device_id: number | null;
  device_hostname: string;
  system_ip: string;
  site_id: string;
  title: string;
  summary: string;
  component: string;
  rule_name: string;
  loguser: string;
  logfeature: string;
  degraded: boolean;
};

export type GovernanceEventsListResponse = {
  items: GovernanceEventRow[];
  total: number;
  limit: number;
  offset: number;
};

export const EVENTS_GRID_PREFS_KEY = "terra_events_grid_prefs_v1";

export const DEFAULT_COLUMN_VISIBILITY: Record<string, boolean> = {
  entry_time_utc: true,
  severity_norm: true,
  stream_kind: true,
  active: true,
  cluster: true,
  tenant: false,
  device_hostname: true,
  system_ip: false,
  site_id: false,
  title: true,
  summary: true,
  loguser: false,
  logfeature: false,
};

export type EventsGridPreferences = {
  schemaVersion: 1;
  columnVisibility: Record<string, boolean>;
  pageSize: number;
  sortId: string;
  sortDesc: boolean;
  rangeHours: number;
  streams: string[];
  severities: string[];
};
