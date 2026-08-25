import type {
  ApiAction,
  ApiActionVersion,
  ApiBatch,
  ApiClient,
  ClientsCsvImportResult,
  ClientsCsvPreview,
  ApiPage,
  ApiRun,
  ApiUser,
  BrowserStatus,
  DashboardPayload,
  DiagnosticsPayload,
  ExternalSessionStatus,
  LearningSession,
  WorkerStatus,
} from "@/types/api";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const DEFAULT_TIMEOUT_MS = 20_000;

let csrfToken: string | null = null;

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

export function getCsrfToken() {
  return csrfToken;
}

export function restoreCsrfTokenFromCookie() {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith("cotasync_csrf="));
  csrfToken = match ? decodeURIComponent(match.split("=").slice(1).join("=")) : csrfToken;
  return csrfToken;
}

function friendlyMessage(status: number, code: string, message: string) {
  if (status === 401) return "Sessão CotaSync encerrada. Faça login novamente.";
  if (status === 403) return "Acesso não permitido para seu perfil.";
  if (status === 409 && code === "BATCH_IDEMPOTENCY_CONFLICT")
    return "Esta execução já foi enviada com dados diferentes.";
  if (code === "BROWSER_UNAVAILABLE") return "Navegador indisponível no momento.";
  if (code === "EXTERNAL_LOGIN_URL_MISSING")
    return "URL de login do sistema externo não configurada.";
  return message || "Não foi possível concluir a operação.";
}

async function parseError(response: Response): Promise<ApiError> {
  let code = `HTTP_${response.status}`;
  let message = response.statusText;
  try {
    const payload = await response.json();
    if (payload?.error) {
      code = String(payload.error.code || code);
      message = String(payload.error.message || message);
    } else if (payload?.detail) {
      if (typeof payload.detail === "string") message = payload.detail;
      if (typeof payload.detail === "object") {
        code = String(payload.detail.code || code);
        message = String(payload.detail.message || payload.detail.message || message);
      }
    }
  } catch {
    // Non-JSON error responses keep the HTTP status text.
  }
  return new ApiError(response.status, code, friendlyMessage(response.status, code, message));
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), init.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const method = (init.method || "GET").toUpperCase();
  const headers = new Headers(init.headers);

  if (!(init.body instanceof FormData) && !headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      method,
      headers,
      credentials: "include",
      signal: init.signal || controller.signal,
    });
    if (!response.ok) throw await parseError(response);
    if (response.status === 204) return undefined as T;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("text/csv")) return (await response.text()) as T;
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(0, "REQUEST_TIMEOUT", "Tempo esgotado ao falar com a API.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function login(username: string, password: string) {
  const payload = await apiFetch<{ user: ApiUser; csrf_token: string }>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  setCsrfToken(payload.csrf_token);
  return payload.user;
}

export async function logout() {
  await apiFetch<{ status: string }>("/api/v1/auth/logout", { method: "POST" });
  setCsrfToken(null);
}

export async function getMe() {
  const payload = await apiFetch<{ user: ApiUser }>("/api/v1/auth/me");
  return payload.user;
}

export async function getDashboard() {
  const payload = await apiFetch<{ dashboard: DashboardPayload }>("/api/v1/dashboard");
  return payload.dashboard;
}

export async function getClients(
  params: { page?: number; pageSize?: number; group?: string; includeInactive?: boolean } = {},
) {
  const query = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 50),
    include_inactive: String(params.includeInactive ?? true),
  });
  if (params.group) query.set("group", params.group);
  const payload = await apiFetch<{ clients: ApiPage<ApiClient> }>(`/api/v1/clients?${query}`);
  return payload.clients;
}

export async function createClient(input: {
  name: string;
  group: string;
  active: boolean;
  notes: string;
  variables: Record<string, string>;
}) {
  const payload = await apiFetch<{ client: ApiClient }>("/api/v1/clients", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return payload.client;
}

export async function updateClient(
  id: string,
  input: {
    name: string;
    group: string;
    active: boolean;
    notes: string;
    variables: Record<string, string>;
  },
) {
  const payload = await apiFetch<{ client: ApiClient }>(`/api/v1/clients/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
  return payload.client;
}

export async function deactivateClient(id: string) {
  const payload = await apiFetch<{ client: ApiClient }>(`/api/v1/clients/${id}`, {
    method: "DELETE",
  });
  return payload.client;
}

export async function previewClientsCsv(input: { filename: string; csvText: string }) {
  const payload = await apiFetch<{ preview: ClientsCsvPreview }>("/api/v1/clients/import/preview", {
    method: "POST",
    body: JSON.stringify({ filename: input.filename, csv_text: input.csvText }),
  });
  return payload.preview;
}

export async function importClientsCsv(input: { filename: string; csvText: string }) {
  const payload = await apiFetch<{ import_result: ClientsCsvImportResult }>(
    "/api/v1/clients/import",
    {
      method: "POST",
      body: JSON.stringify({ filename: input.filename, csv_text: input.csvText }),
    },
  );
  return payload.import_result;
}

export async function exportClientsCsv() {
  return apiFetch<string>("/api/v1/clients/export.csv");
}

export async function getActions(params: { page?: number; pageSize?: number } = {}) {
  const query = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 50),
  });
  const payload = await apiFetch<{ actions: ApiPage<ApiAction> }>(`/api/v1/actions?${query}`);
  return payload.actions;
}

export async function getAction(id: string) {
  const payload = await apiFetch<{ action: ApiAction }>(`/api/v1/actions/${id}`);
  return payload.action;
}

export async function getActionVersions(id: string) {
  const payload = await apiFetch<{ versions: ApiActionVersion[] }>(
    `/api/v1/actions/${id}/versions`,
  );
  return payload.versions;
}

export async function runAction(id: string, variables: Record<string, string>) {
  const payload = await apiFetch<{ run: ApiRun }>(`/api/v1/actions/${id}/run`, {
    method: "POST",
    body: JSON.stringify({
      variables,
      mode: "async",
      requested_by: "react",
      run_origin: "operational",
    }),
  });
  return payload.run;
}

export async function getRun(id: string) {
  const payload = await apiFetch<{ run: ApiRun }>(`/api/v1/runs/${id}`);
  return payload.run;
}

export async function getBatches(params: { page?: number; pageSize?: number } = {}) {
  const query = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 20),
  });
  const payload = await apiFetch<{ batches: ApiPage<ApiBatch> }>(`/api/v1/batches?${query}`);
  return payload.batches;
}

export async function createBatch(input: {
  action_id: string;
  client_group?: string;
  client_ids?: string[];
  delay_between_rows_seconds?: number;
  idempotencyKey: string;
}) {
  const payload = await apiFetch<{ batch: ApiBatch }>("/api/v1/batches", {
    method: "POST",
    headers: { "Idempotency-Key": input.idempotencyKey },
    body: JSON.stringify({
      action_id: input.action_id,
      client_group: input.client_group || null,
      client_ids: input.client_ids || [],
      requested_by: "react",
      delay_between_rows_seconds: input.delay_between_rows_seconds ?? 3,
    }),
  });
  return payload.batch;
}

export async function getBatch(id: string) {
  const payload = await apiFetch<{ batch: ApiBatch }>(`/api/v1/batches/${id}`);
  return payload.batch;
}

export async function cancelBatch(id: string) {
  const payload = await apiFetch<{ batch: ApiBatch }>(`/api/v1/batches/${id}/cancel`, {
    method: "POST",
  });
  return payload.batch;
}

export async function exportBatchResultsCsv(id: string) {
  return apiFetch<string>(`/api/v1/batches/${id}/results.csv`);
}

export async function getReportsRuns(
  params: {
    page?: number;
    pageSize?: number;
    actionId?: string;
    status?: string;
    client?: string;
    dateFrom?: string;
    dateTo?: string;
    runOrigin?: string;
  } = {},
) {
  const query = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 50),
  });
  if (params.actionId) query.set("action_id", params.actionId);
  if (params.status) query.set("status", params.status);
  if (params.client) query.set("client", params.client);
  if (params.dateFrom) query.set("date_from", params.dateFrom);
  if (params.dateTo) query.set("date_to", params.dateTo);
  if (params.runOrigin) query.set("run_origin", params.runOrigin);
  const payload = await apiFetch<{ runs: ApiPage<ApiRun> }>(`/api/v1/reports/runs?${query}`);
  return payload.runs;
}

export async function exportReportsRunsCsv(
  params: {
    actionId?: string;
    status?: string;
    client?: string;
    dateFrom?: string;
    dateTo?: string;
    runOrigin?: string;
  } = {},
) {
  const query = new URLSearchParams();
  if (params.actionId) query.set("action_id", params.actionId);
  if (params.status) query.set("status", params.status);
  if (params.client) query.set("client", params.client);
  if (params.dateFrom) query.set("date_from", params.dateFrom);
  if (params.dateTo) query.set("date_to", params.dateTo);
  if (params.runOrigin) query.set("run_origin", params.runOrigin);
  const suffix = query.toString() ? `?${query}` : "";
  return apiFetch<string>(`/api/v1/reports/runs.csv${suffix}`);
}

export async function getReportsBatches(
  params: { page?: number; pageSize?: number; status?: string } = {},
) {
  const query = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 50),
  });
  if (params.status) query.set("status", params.status);
  const payload = await apiFetch<{ batches: ApiPage<ApiBatch> }>(
    `/api/v1/reports/batches?${query}`,
  );
  return payload.batches;
}

export async function getWorkerStatus() {
  const payload = await apiFetch<{ worker: WorkerStatus }>("/api/v1/worker/status");
  return payload.worker;
}

export async function getBrowserStatus() {
  const payload = await apiFetch<{ browser: BrowserStatus }>("/api/v1/browser/status");
  return payload.browser;
}

export async function createBrowserViewToken() {
  return apiFetch<{ view_url: string; expires_at: string; ttl_seconds: number }>(
    "/api/v1/browser/view-token",
    {
      method: "POST",
    },
  );
}

export async function ensureBrowserReady() {
  const payload = await apiFetch<{ browser: Record<string, unknown> }>(
    "/api/v1/browser/ensure-ready",
    { method: "POST" },
  );
  return payload.browser;
}

export async function getExternalSessionStatus() {
  const payload = await apiFetch<{ external_session: ExternalSessionStatus }>(
    "/api/v1/external-session/status",
  );
  return payload.external_session;
}

export async function openExternalLogin() {
  return apiFetch<{ login_url: string; manual_login_required: boolean }>(
    "/api/v1/external-session/open-login",
    { method: "POST" },
  );
}

export async function validateExternalSession() {
  return apiFetch<{ valid: boolean; manual_login_required: boolean }>(
    "/api/v1/external-session/validate",
    { method: "POST" },
  );
}

export async function createLearningSession() {
  const payload = await apiFetch<{ session: LearningSession }>("/api/v1/learning/sessions", {
    method: "POST",
  });
  return payload.session;
}

export async function getLearningSession(id: string) {
  const payload = await apiFetch<{ session: LearningSession }>(`/api/v1/learning/sessions/${id}`);
  return payload.session;
}

export async function startLearningRecording(
  id: string,
  input: { name: string; objective: string; expected_result: string },
) {
  const payload = await apiFetch<{ session: LearningSession }>(
    `/api/v1/learning/sessions/${id}/recording/start`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
  return payload.session;
}

export async function stopLearningRecording(id: string) {
  return apiFetch<{ learned_action?: unknown; session?: LearningSession }>(
    `/api/v1/learning/sessions/${id}/recording/stop`,
    {
      method: "POST",
    },
  );
}

export async function saveLearnedAction(
  id: string,
  input: {
    name: string;
    description: string;
    objective: string;
    expected_result: string;
    variable_names: string[];
  },
) {
  const payload = await apiFetch<{ action: ApiAction }>(`/api/v1/learning/sessions/${id}/actions`, {
    method: "POST",
    body: JSON.stringify({
      ...input,
      input_description: "Campos informados pelo operador durante o ensino.",
      success_criteria: "Retornar a informação confirmada pelo operador.",
      output_type: "text",
      ai_result_summary_enabled: false,
      ai_recovery_enabled: false,
    }),
  });
  return payload.action;
}

export async function operatorInsertActive(
  id: string,
  value: string,
  sensitive: boolean,
  variableKey?: string,
) {
  return apiFetch<{ operator: unknown }>(`/api/v1/learning/sessions/${id}/operator/insert-active`, {
    method: "POST",
    body: JSON.stringify({ value, sensitive, variable_key: variableKey || null }),
  });
}

export async function operatorPress(id: string, key: "Tab" | "Enter") {
  return apiFetch<{ operator: unknown }>(`/api/v1/learning/sessions/${id}/operator/press`, {
    method: "POST",
    body: JSON.stringify({ key }),
  });
}

export async function operatorClearActive(id: string) {
  return apiFetch<{ operator: unknown }>(`/api/v1/learning/sessions/${id}/operator/clear-active`, {
    method: "POST",
  });
}

export async function getDiagnostics() {
  const payload = await apiFetch<{ diagnostics: DiagnosticsPayload }>("/api/v1/diagnostics/system");
  return payload.diagnostics;
}
