// CotaSync API — mocked layer.
// All functions return realistic mocked data with the same shape the future
// REST backend will use. Swap the bodies for real `fetch()` calls without
// changing any component. Base URL is read from Vite env when available.

import {
  mockActions, mockClients, mockExecutions, mockSchedules,
  type ActionRow, type ClientRow, type ExecutionRow, type ScheduleRow,
} from "@/lib/mock-data";

const BASE_URL =
  (typeof import.meta !== "undefined" && (import.meta as any).env?.VITE_COTASYNC_API) || "";

const delay = <T,>(data: T, ms = 250): Promise<T> =>
  new Promise((r) => setTimeout(() => r(data), ms));

/** Real HTTP helper for the future — currently unused by mocks. */
async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
  return res.json();
}
void http;

/* ------------------------------ Dashboard ------------------------------ */
export type DashboardData = {
  session: "connected" | "disconnected";
  activeClients: number;
  readyActions: number;
  executionsToday: number;
  lastExecution: { status: "success" | "error"; at: string };
  nextSchedule: { name: string; at: string } | null;
  queue: "idle" | "running";
  recent: ExecutionRow[];
  alerts: { tone: "warning" | "info" | "error"; title: string; desc: string }[];
};

export const getDashboard = (): Promise<DashboardData> =>
  delay({
    session: "connected",
    activeClients: 124,
    readyActions: 3,
    executionsToday: 18,
    lastExecution: { status: "success", at: "2025-07-14 09:15" },
    nextSchedule: { name: "Consulta mensal de parcelas", at: "2025-08-05 08:00" },
    queue: "idle",
    recent: mockExecutions,
    alerts: [
      { tone: "warning", title: "Sessão expira em breve", desc: "Renove em Configurações." },
      { tone: "info", title: "2 clientes com dados incompletos", desc: "Lista Principal." },
      { tone: "error", title: "1 execução com erro pendente", desc: "Reprocesse em Relatórios." },
    ],
  });

/* ------------------------------- Clients ------------------------------- */
export const getClients = (): Promise<ClientRow[]> => delay(mockClients);

export type NewClientInput = {
  name: string; list: string; active: boolean;
  grupo: string; cota: string; versao: string;
  notes?: string; extras?: Record<string, unknown>;
};
export const createClient = (input: NewClientInput): Promise<ClientRow> =>
  delay({
    id: crypto.randomUUID(),
    name: input.name,
    list: input.list,
    active: input.active,
    grupo: input.grupo,
    cota: input.cota,
    versao: input.versao,
    lastQuery: "—",
    lastResult: "—",
  });

export type CsvImportResult = { inserted: number; skipped: number; errors: string[] };
export const importClientsCsv = (_file: File): Promise<CsvImportResult> =>
  delay({ inserted: 42, skipped: 3, errors: [] });

/* ------------------------------- Actions ------------------------------- */
export const getActions = (): Promise<ActionRow[]> => delay(mockActions);

export type LearningSession = { sessionId: string; startedAt: string };
export const startLearning = (input: { name: string; expected: string; vars?: string[] }): Promise<LearningSession> =>
  delay({ sessionId: `learn_${Date.now()}`, startedAt: new Date().toISOString(), ...input });

export const insertOperatorText = (input: {
  sessionId: string; text: string; isVariable?: boolean; variableName?: string;
}): Promise<{ ok: true; step: number }> => delay({ ok: true, step: 8 });

export const finishLearning = (input: { sessionId: string }): Promise<{
  ok: true; pathLearned: boolean; vars: string[]; detectedResult: string;
}> => delay({ ok: true, pathLearned: true, vars: ["grupo", "cota", "versao"], detectedResult: "032" });

export const confirmExtractionResult = (input: {
  sessionId: string; value: string; useAi?: boolean;
}): Promise<{ ok: true; actionId: string }> =>
  delay({ ok: true, actionId: `a_${Date.now()}` });

/* -------------------------------- Batches ------------------------------ */
export type BatchStatus = "queued" | "running" | "done" | "error" | "canceled";
export type BatchResult = {
  clientId: string; clientName: string;
  status: "success" | "error" | "pending";
  result: string; runId: string; startedAt: string; finishedAt: string; error?: string;
};
export type Batch = {
  id: string; actionId: string; listId: string; delaySeconds: number;
  total: number; done: number; status: BatchStatus;
  currentClient?: string; etaSeconds?: number; results: BatchResult[];
};

export const createBatch = (input: {
  actionId: string; listId: string; delaySeconds: number;
}): Promise<Batch> =>
  delay({
    id: `batch_${Date.now()}`,
    actionId: input.actionId, listId: input.listId, delaySeconds: input.delaySeconds,
    total: mockClients.length, done: 0, status: "queued", results: [],
  });

export const getBatch = (id: string): Promise<Batch> =>
  delay({
    id, actionId: "a1", listId: "p", delaySeconds: 3,
    total: 4, done: 2, status: "running", currentClient: "Cliente Gama", etaSeconds: 18,
    results: [
      { clientId: "1", clientName: "Cliente Alfa", status: "success", result: "038", runId: "run_9f2a", startedAt: "09:15:02", finishedAt: "09:15:08" },
      { clientId: "2", clientName: "Cliente Beta", status: "success", result: "042", runId: "run_9f2b", startedAt: "09:15:11", finishedAt: "09:15:17" },
      { clientId: "3", clientName: "Cliente Gama", status: "error",   result: "—",   runId: "run_9f2c", startedAt: "09:15:20", finishedAt: "09:15:26", error: "Campo cota não encontrado" },
      { clientId: "4", clientName: "Cliente Épsilon", status: "pending", result: "—", runId: "run_9f2d", startedAt: "—", finishedAt: "—" },
    ],
  });

/* ------------------------------ Schedules ------------------------------ */
export const getSchedules = (): Promise<ScheduleRow[]> => delay(mockSchedules);

export type NewScheduleInput = {
  name: string; actionId: string; listId: string;
  frequency: "diario" | "semanal" | "mensal";
  dayOfMonth?: number; time: string; delaySeconds: number; active: boolean;
};
export const createSchedule = (input: NewScheduleInput): Promise<ScheduleRow> =>
  delay({
    id: `s_${Date.now()}`,
    name: input.name,
    action: input.actionId,
    list: input.listId,
    frequency: input.frequency,
    next: "2025-08-05 08:00",
    status: input.active ? "Ativo" : "Pausado",
    last: "—",
  });

/* ------------------------------- Reports ------------------------------- */
export type ReportFilters = {
  from?: string; to?: string; actionId?: string; listId?: string;
  clientQuery?: string; status?: "success" | "error";
};
export type ReportRow = {
  id: string; date: string; client: string; action: string;
  result: string; status: "success" | "error"; error?: string;
  variables: Record<string, string>; screenshotUrl?: string;
  diagnostic: { runId: string; steps: number; durationMs: number };
};
export const getReports = (_filters?: ReportFilters): Promise<ReportRow[]> =>
  delay([
    { id: "r1", date: "2025-07-14 09:15", client: "Cliente Alfa", action: "Número de parcelas pagas", result: "038", status: "success",
      variables: { grupo: "935", cota: "110", versao: "00" },
      diagnostic: { runId: "run_9f2a", steps: 7, durationMs: 5820 } },
    { id: "r3", date: "2025-07-14 09:16", client: "Cliente Gama", action: "Número de parcelas pagas", result: "—", status: "error", error: "Campo cota não encontrado",
      variables: { grupo: "935", cota: "112", versao: "00" },
      diagnostic: { runId: "run_9f2c", steps: 4, durationMs: 6120 } },
  ]);

/* ----------------------------- Diagnostics ----------------------------- */
export type Diagnostics = {
  backend: "ok" | "degraded" | "down";
  browser: "ok" | "disconnected";
  version: string; commit: string; healthcheck: "ok" | "fail";
  runs: { runId: string; action: string; status: "success" | "error" | "running"; host: string; lastStep: string; error?: string }[];
  batches: { id: string; total: number; done: number; status: BatchStatus }[];
  logs: { t: string; level: "info" | "ok" | "err"; msg: string }[];
};
export const getDiagnostics = (): Promise<Diagnostics> =>
  delay({
    backend: "ok", browser: "ok",
    version: "0.1.0", commit: "a1b2c3d", healthcheck: "ok",
    runs: [
      { runId: "run_9f2a", action: "Número de parcelas pagas", status: "success", host: "sistema.externo", lastStep: "extract_result" },
      { runId: "run_9f2c", action: "Número de parcelas pagas", status: "error",   host: "sistema.externo", lastStep: "fill_cota", error: "Campo cota não encontrado" },
      { runId: "run_9f2d", action: "Número de parcelas pagas", status: "running", host: "sistema.externo", lastStep: "open_page" },
    ],
    batches: [
      { id: "batch_1042", total: 42, done: 42, status: "done" },
      { id: "batch_1043", total: 4,  done: 2,  status: "running" },
    ],
    logs: [
      { t: "09:15:02", level: "info", msg: "Execução iniciada — Ação: Número de parcelas pagas" },
      { t: "09:15:07", level: "ok",   msg: "Cliente Alfa · resultado 038" },
      { t: "09:15:22", level: "err",  msg: "Cliente Gama · sessão expirada" },
    ],
  });
