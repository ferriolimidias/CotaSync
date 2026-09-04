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
  list_id?: string | null;
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

export type SystemSpreadsheet = {
  id: string;
  system_spreadsheet_id: string;
  name: string;
  active: boolean;
  client_count: number;
  last_sync?: string | null;
  fields: Array<{ id: string; field_id: string; display_name: string; internal_key: string; position: number; type: string }>;
  connectors: Array<{ id: string; type: string; status: string; last_synced_at?: string | null; last_error?: string | null }>;
};

export type SystemSpreadsheetRows = {
  system_spreadsheet: SystemSpreadsheet;
  rows: Array<{ client_id: string; name: string; active: boolean; values: Record<string, string> }>;
};

export type ClientsCsvPreviewRow = {
  row_number: number;
  operation: "create" | "update";
  valid: boolean;
  name: string;
  group: string;
  active: boolean;
  display_variables: {
    grupo?: string;
    cota?: string;
    versao?: string;
  };
  notes?: string;
  errors: string[];
};

export type ClientsCsvPreview = {
  filename: string;
  limits: {
    max_bytes: number;
    max_rows: number;
    encoding: string;
    supported_headers: string[];
  };
  headers: string[];
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  new_clients: number;
  updates: number;
  conflicts: Array<{
    row_number: number;
    field: string;
    message: string;
    values: Record<string, string>;
  }>;
  warnings: Array<{ code: string; message: string }>;
  rows: ClientsCsvPreviewRow[];
  can_import: boolean;
};

export type ClientsCsvImportResult = {
  created: number;
  updated: number;
  count: number;
  clients: ApiClient[];
};

export type ApiAction = {
  id: string;
  key?: string;
  name: string;
  description?: string;
  allowed_list_ids: string[];
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
  external_session?: ExternalSessionStatus;
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
  index?: number;
  client_id?: string;
  client_name?: string;
  client_fields?: { grupo?: string; cota?: string; versao?: string };
  status?: "queued" | "running" | "success" | "error" | "interrupted" | "cancelled" | "needs_attention";
  status_label?: string;
  output_values?: Record<string, string>;
  dados_extraidos?: Record<string, string>;
  result_summary?: string | null;
  result_payload?: Record<string, unknown>;
  error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type BatchResultColumn = {
  key: string;
  label: string;
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
  rows?: BatchItem[];
  result_columns?: BatchResultColumn[];
  output_definitions?: BatchResultColumn[];
  metadata?: Record<string, unknown>;
};

export type BrowserStatus = {
  browser_mode: string;
  desktop_browser: {
    running?: boolean;
    cdp_reachable?: boolean;
    view_url?: string;
    browser_product?: string;
    error?: string;
    [key: string]: unknown;
  };
};

export type ExternalSessionStatus = {
  external_system_name: string;
  external_system_configured: boolean;
  login_url_configured: boolean;
  login_configured?: boolean;
  manual_login_required: boolean;
  login_mode?: string;
  automation: string;
  validation_mode?: string;
  session_status: string;
  expected_system_host_configured?: boolean;
  updated_at?: string | null;
};

export type ExternalSystemConfig = {
  external_system_name: string;
  external_login_url: string;
  access_profile_email_or_identifier: string;
  expected_system_host: string;
  updated_at?: string | null;
};

export type LearningAISettings = {
  enabled: boolean;
  provider: string;
  model: string;
  base_url: string;
  api_key_configured: boolean;
  api_key_source: "stored" | "environment" | "none" | string;
};

export type LearningSession = {
  id?: string;
  session_id?: string;
  status?: string;
  recording?: boolean;
  learning_events_count?: number;
  variables?: string[];
  result_selection?: Record<string, unknown>;
  extraction_review?: Record<string, unknown>;
  outputs?: Array<Record<string, unknown>>;
  learning_mode?: "free_action" | "spreadsheet";
  data_source_id?: string | null;
  [key: string]: unknown;
};

export type DataSourceField = {
  id: string;
  field_id: string;
  display_name: string;
  source_column_reference: string;
  semantic_role?: string | null;
  data_type: string;
  active: boolean;
};

export type DataSource = {
  id: string;
  name: string;
  type: "excel" | "google_sheets";
  source_type: string;
  status: string;
  schema: Record<string, unknown>;
  fields: DataSourceField[];
};

export type ResultSelectionCandidate = {
  label?: string;
  value?: string;
  type?: string;
  candidate_type?: string;
  selected_element?: Record<string, unknown>;
  [key: string]: unknown;
};

export type LearningResultSelection = {
  status?: string;
  captured?: Record<string, unknown> | null;
  candidates?: ResultSelectionCandidate[];
  reason?: string;
  message?: string;
  extraction_review?: Record<string, unknown>;
};

export type DiagnosticsPayload = {
  worker: WorkerStatus;
  browser_mode: string;
  browser: Record<string, unknown>;
};
