export type ApiUser = {
  username: string;
  role: "admin" | "operator";
};

export type ApiPage<T> = {
  page: number;
  page_size: number;
  total: number;
  items: T[];
};

export type ApiClient = {
  id: string;
  name: string;
  active: boolean;
  group: string;
  notes: string;
  variables: Record<string, string>;
  display_variables: {
    grupo?: string;
    cota?: string;
    versao?: string;
  };
  created_at?: string;
  updated_at?: string;
};

export type ApiAction = {
  id: string;
  key?: string;
  name: string;
  description?: string;
  variables: Array<{ key: string; label?: string; required?: boolean }>;
  steps_count?: number;
  has_url?: boolean;
  learning_mode?: string | null;
  needs_attention?: boolean;
  legacy_unconfigured?: boolean;
  published_version?: { id: string | null; status: string };
  last_run?: ApiRun | null;
  learning_warnings?: string[];
};

export type ApiActionVersion = {
  id: string;
  version_number: number;
  status: string;
  published: boolean;
  created_at: string | null;
  published_at: string | null;
};

export type ApiRun = {
  id: string;
  action_id: string;
  action_key: string;
  status: "pending" | "running" | "success" | "error";
  mode: "sync" | "async";
  run_origin: string;
  requested_by: string;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  variables: Record<string, unknown>;
  result_summary?: string | null;
  operational_summary?: string | null;
  error_message?: string | null;
};

export type WorkerStatus = {
  online?: boolean;
  status?: string;
  heartbeat_at?: string | null;
  current_batch_id?: string | null;
  browser_lock?: unknown;
};

export type DashboardPayload = {
  session_status: string;
  clients_active: number;
  actions_ready: number;
  runs_today: number;
  last_run: { id: string; status: string; created_at: string } | null;
  worker_status: WorkerStatus;
  queue_status: { queued: number; running: number };
  alerts: Array<{ level: "warning" | "info" | "error"; code: string; message: string }>;
};

export type BatchItem = {
  id?: string;
  client_id?: string;
  client_name?: string;
  status?: "queued" | "running" | "success" | "error" | "interrupted" | "cancelled";
  result_summary?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type ApiBatch = {
  id?: string;
  batch_id?: string;
  status: string;
  action_id: string;
  total_items: number;
  processed_items: number;
  success_items: number;
  error_items: number;
  interrupted_items: number;
  cancelled_items: number;
  current_position?: number | null;
  current_client_id?: string | null;
  current_client_name?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  items?: BatchItem[];
  results?: BatchItem[];
};

export type BrowserStatus = {
  browser_mode: string;
  desktop_browser: Record<string, unknown>;
};

export type ExternalSessionStatus = {
  external_system_name: string;
  login_url_configured: boolean;
  manual_login_required: boolean;
  automation: string;
};

export type LearningSession = {
  id?: string;
  session_id?: string;
  status?: string;
  recording?: boolean;
  learning_events_count?: number;
  variables?: string[];
  [key: string]: unknown;
};

export type DiagnosticsPayload = {
  worker: WorkerStatus;
  browser_mode: string;
  browser: Record<string, unknown>;
};
