// Mock data for CotaSync. Replace with real REST API calls later.

export type ClientRow = {
  id: string;
  name: string;
  list: string;
  active: boolean;
  grupo: string;
  cota: string;
  versao: string;
  lastQuery: string;
  lastResult: string;
};

export const mockClients: ClientRow[] = [
  { id: "1", name: "Cliente Alfa", list: "Lista Principal", active: true, grupo: "935", cota: "110", versao: "00", lastQuery: "2025-07-12 09:14", lastResult: "038" },
  { id: "2", name: "Cliente Beta", list: "Lista Principal", active: true, grupo: "935", cota: "111", versao: "00", lastQuery: "2025-07-12 09:15", lastResult: "042" },
  { id: "3", name: "Cliente Gama", list: "Lista Principal", active: true, grupo: "935", cota: "112", versao: "00", lastQuery: "2025-07-12 09:15", lastResult: "029" },
  { id: "4", name: "Cliente Delta", list: "Lista VIP", active: false, grupo: "941", cota: "203", versao: "01", lastQuery: "2025-06-30 10:02", lastResult: "—" },
  { id: "5", name: "Cliente Épsilon", list: "Lista VIP", active: true, grupo: "941", cota: "204", versao: "01", lastQuery: "2025-07-11 08:44", lastResult: "051" },
];

export type ActionRow = {
  id: string;
  name: string;
  purpose: string;
  status: "Pronta" | "Precisa confirmar" | "Em desenvolvimento";
  vars: string[];
  lastResult: string;
  lastRun: string;
};

export const mockActions: ActionRow[] = [
  { id: "a1", name: "Número de parcelas pagas", purpose: "Consultar quantas parcelas o cliente já pagou", status: "Pronta", vars: ["grupo", "cota", "versao"], lastResult: "038", lastRun: "2025-07-12 09:15" },
  { id: "a2", name: "Porcentagem a pagar", purpose: "Consultar o percentual restante do contrato", status: "Precisa confirmar", vars: ["grupo", "cota", "versao"], lastResult: "pendente", lastRun: "2025-07-10 14:22" },
  { id: "a3", name: "Emitir boleto", purpose: "Gerar boleto da próxima parcela", status: "Em desenvolvimento", vars: ["grupo", "cota", "versao"], lastResult: "—", lastRun: "—" },
];

export type ExecutionRow = {
  id: string;
  datetime: string;
  action: string;
  clients: number;
  status: "Sucesso" | "Erro" | "Em andamento";
  ok: number;
  err: number;
};

export const mockExecutions: ExecutionRow[] = [
  { id: "e1", datetime: "2025-07-14 09:15", action: "Número de parcelas pagas", clients: 42, status: "Sucesso", ok: 40, err: 2 },
  { id: "e2", datetime: "2025-07-13 08:00", action: "Número de parcelas pagas", clients: 38, status: "Sucesso", ok: 38, err: 0 },
  { id: "e3", datetime: "2025-07-12 14:30", action: "Porcentagem a pagar", clients: 12, status: "Erro", ok: 8, err: 4 },
  { id: "e4", datetime: "2025-07-12 09:00", action: "Número de parcelas pagas", clients: 50, status: "Sucesso", ok: 49, err: 1 },
];

export type ScheduleRow = {
  id: string;
  name: string;
  action: string;
  list: string;
  frequency: string;
  next: string;
  status: "Ativo" | "Pausado";
  last: string;
};

export const mockSchedules: ScheduleRow[] = [
  { id: "s1", name: "Consulta mensal de parcelas", action: "Número de parcelas pagas", list: "Lista Principal", frequency: "Mensal — dia 05 às 08:00", next: "2025-08-05 08:00", status: "Ativo", last: "2025-07-05 08:00" },
  { id: "s2", name: "Consulta semanal VIP", action: "Número de parcelas pagas", list: "Lista VIP", frequency: "Semanal — segunda 09:00", next: "2025-07-21 09:00", status: "Ativo", last: "2025-07-14 09:00" },
];
