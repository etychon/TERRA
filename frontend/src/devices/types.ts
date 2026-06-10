export type DeviceHomeRow = {
  id: number;
  cluster: string;
  manager: string;
  tenant: string;
  hostname: string;
  serial_number: string;
  model: string;
  software_version: string;
  device_type: string;
  site_name: string;
  site_id: string;
  reachability: string;
  state_changed_at_utc: string;
  synced_at_utc: string;
  has_cellular: boolean;
  owner_email: string;
};

export type DevicesListResponse = {
  items: DeviceHomeRow[];
  total: number;
  limit: number;
  offset: number;
};

export type SparklinePoint = { t: number; v: number };

export type SparklineItem = {
  device_id: number;
  has_cellular: boolean;
  points: SparklinePoint[];
  latest_rssi: number | null;
  quality: string;
};

export type GridPreferences = {
  schemaVersion: 1;
  columnVisibility: Record<string, boolean>;
  pageSize: number;
  hideControl: boolean;
  sortId: string;
  sortDesc: boolean;
};

export const GRID_PREFS_KEY = "terra.devicesGrid.prefs.v1";

export const DEFAULT_COLUMN_VISIBILITY: Record<string, boolean> = {
  cluster: true,
  tenant: true,
  owner_email: false,
  hostname: true,
  serial_number: true,
  model: true,
  software_version: true,
  device_type: false,
  site_name: true,
  cellular: true,
  reachability: true,
  state_changed_at_utc: true,
  synced_at_utc: true,
};
