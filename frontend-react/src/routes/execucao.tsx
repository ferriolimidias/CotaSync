import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Download, Play, StopCircle } from "lucide-react";

import { AppShell } from "@/components/cotasync/AppShell";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { ClientSearchCombobox } from "@/components/cotasync/ClientSearchCombobox";
import { SearchableSelect } from "@/components/cotasync/SearchableSelect";
import { DataTable, type Column } from "@/components/cotasync/DataTable";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  cancelBatch,
  createBatch,
  exportBatchResultsCsv,
  exportSystemSpreadsheet,
  getActions,
  getBatch,
  getBatches,
  getClients,
  getClientLists,
  getSystemSpreadsheets,
  getRun,
  runAction,
  resumeBatch,
  syncSystemSpreadsheetGoogle,
} from "@/services/api";
import type { ApiBatch, ApiClient, ApiRun, BatchItem } from "@/types/api";
import { actionIsExecutable, batchStatusLabel, runStatusLabel } from "@/lib/status-labels";

export const Route = createFileRoute("/execucao")({
  head: () => ({ meta: [{ title: "Execução — CotaSync" }] }),
  component: ExecucaoPage,
});

function ExecucaoPage() {
  const queryClient = useQueryClient();
  const actions = useQuery({ queryKey: ["actions"], queryFn: () => getActions({ pageSize: 200 }) });
  const clients = useQuery({
    queryKey: ["clients"],
    queryFn: () => getClients({ pageSize: 200, includeInactive: false }),
  });
  const clientLists = useQuery({ queryKey: ["client-lists"], queryFn: getClientLists });
  const spreadsheets = useQuery({ queryKey: ["system-spreadsheets"], queryFn: getSystemSpreadsheets });
  const batches = useQuery({
    queryKey: ["batches"],
    queryFn: () => getBatches({ pageSize: 10 }),
    refetchInterval: 3000,
  });
  const [actionId, setActionId] = useState("");
  const [group, setGroup] = useState("");
  const [spreadsheetId, setSpreadsheetId] = useState("");
  const [delay, setDelay] = useState(3);
  const [currentBatchId, setCurrentBatchId] = useState<string | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());
  const [singleActionId, setSingleActionId] = useState("");
  const [singleClient, setSingleClient] = useState<ApiClient | null>(null);
  const [singleClientSearch, setSingleClientSearch] = useState("");
  const [debouncedClientSearch, setDebouncedClientSearch] = useState("");
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);
  const currentBatch = useQuery({
    queryKey: ["batch", currentBatchId],
    queryFn: () => getBatch(currentBatchId as string),
    enabled: Boolean(currentBatchId),
    refetchInterval: (query) =>
      isFinalBatch(query.state.data as ApiBatch | undefined) ? false : 2500,
  });
  const currentRun = useQuery({
    queryKey: ["run", currentRunId],
    queryFn: () => getRun(currentRunId as string),
    enabled: Boolean(currentRunId),
    refetchInterval: (query) => (isFinalRun(query.state.data as ApiRun | undefined) ? false : 2500),
  });

  const selectedClients = useMemo(
    () => (clients.data?.items ?? []).filter((client) => !group || client.list_id === group),
    [clients.data, group],
  );
  const singleClients = useQuery({
    queryKey: ["clients", "single", debouncedClientSearch],
    queryFn: () => getClients({ pageSize: 50, search: debouncedClientSearch, includeInactive: false }),
  });
  const executableActions = useMemo(
    () => (actions.data?.items ?? []).filter(actionIsExecutable),
    [actions.data],
  );
  const compatibleActions = useMemo(
    () => executableActions.filter((action) => !group || action.scope_mode === "all" || action.allowed_list_ids.length === 0 || action.allowed_list_ids.includes(group)),
    [executableActions, group],
  );
  const compatibleSpreadsheets = useMemo(
    () => (spreadsheets.data ?? []).filter((sheet) => !group || sheet.default_list_id === group),
    [spreadsheets.data, group],
  );
  const selectedAction = useMemo(() => compatibleActions.find((action) => action.id === actionId), [compatibleActions, actionId]);
  const selectedSpreadsheet = useMemo(() => compatibleSpreadsheets.find((sheet) => sheet.id === spreadsheetId), [compatibleSpreadsheets, spreadsheetId]);
  const requiredFieldIds = useMemo(() => (selectedAction?.outputs ?? []).map((output) => output.destination?.field_id).filter(Boolean) as string[], [selectedAction]);
  const requiresSpreadsheet = requiredFieldIds.length > 0;
  const missingFieldIds = useMemo(() => requiredFieldIds.filter((fieldId) => !selectedSpreadsheet?.fields.some((field) => field.field_id === fieldId || field.id === fieldId)), [requiredFieldIds, selectedSpreadsheet]);
  const individualActions = useMemo(
    () => executableActions.filter((action) => !singleClient || action.allowed_list_ids.length === 0 || action.allowed_list_ids.includes(singleClient.list_id || "")),
    [executableActions, singleClient],
  );
  const selectedSingleAction = useMemo(
    () => individualActions.find((action) => action.id === singleActionId),
    [individualActions, singleActionId],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedClientSearch(singleClientSearch), 250);
    return () => window.clearTimeout(timer);
  }, [singleClientSearch]);

  const runSingle = useMutation({
    mutationFn: async () => {
      if (!singleClient) throw new Error("Selecione um cliente.");
      const variables = variablesFromClient(singleClient);
      const missingClientField = (selectedSingleAction?.variables ?? []).find(
        (variable) =>
          ["grupo", "cota", "versao"].includes(variable.key) &&
          !String(variables[variable.key as keyof typeof variables] || "").trim(),
      );
      if (missingClientField) {
        const labels: Record<string, string> = { grupo: "Grupo", cota: "Cota", versao: "Versão" };
        throw new Error(`O cliente ${singleClient.name} não possui ${labels[missingClientField.key] || missingClientField.label} cadastrada.`);
      }
      return runAction(singleActionId, { ...variables, client_id: singleClient.id });
    },
    onSuccess: (run) => {
      setCurrentRunId(run.id);
      toast.success("Execução individual adicionada à fila.");
      void queryClient.invalidateQueries({ queryKey: ["reports"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) =>
      toast.error(
        error instanceof Error ? error.message : "Não foi possível executar a ação individual.",
      ),
  });

  const create = useMutation({
    mutationFn: () =>
      createBatch({
        action_id: actionId,
        list_id: group || undefined,
        spreadsheet_id: spreadsheetId || undefined,
        delay_between_rows_seconds: delay,
        idempotencyKey,
      }),
    onSuccess: (batch) => {
      const id = batch.batch_id || batch.id;
      if (id) setCurrentBatchId(id);
      setIdempotencyKey(crypto.randomUUID());
      toast.success("Execução adicionada à fila.");
      void queryClient.invalidateQueries({ queryKey: ["batches"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível criar a execução."),
  });

  useEffect(() => {
    setActionId("");
    setSpreadsheetId("");
  }, [group]);

  useEffect(() => {
    if (compatibleSpreadsheets.length === 1) setSpreadsheetId(compatibleSpreadsheets[0].id);
    if (!compatibleSpreadsheets.some((sheet) => sheet.id === spreadsheetId)) setSpreadsheetId("");
  }, [compatibleSpreadsheets, spreadsheetId]);

  const cancel = useMutation({
    mutationFn: (id: string) => cancelBatch(id),
    onSuccess: () => {
      toast.message(
        "Cancelamento solicitado. A execução atual será concluída antes de cancelar os próximos clientes.",
      );
      void queryClient.invalidateQueries({ queryKey: ["batch", currentBatchId] });
      void queryClient.invalidateQueries({ queryKey: ["batches"] });
    },
  });

  const resume = useMutation({
    mutationFn: (id: string) => resumeBatch(id),
    onSuccess: (nextBatch) => {
      setCurrentBatchId(nextBatch.batch_id || nextBatch.id || null);
      void queryClient.invalidateQueries({ queryKey: ["batch", currentBatchId] });
      void queryClient.invalidateQueries({ queryKey: ["batches"] });
      toast.success("Execução retomada pelo cliente que aguardava atenção.");
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível retomar a execução."),
  });

  const batch = currentBatch.data;
  const latestBatch = batches.data?.items[0];
  const batchId = batch?.batch_id || batch?.id || "";
  const progress = batch?.total_items
    ? Math.round((batch.processed_items / batch.total_items) * 100)
    : 0;
  const batchRows = batch?.rows || batch?.items || batch?.results || [];
  const attentionItem = batchRows.find((item) => item.status === "needs_attention");
  const batchSheet = spreadsheets.data?.find((sheet) => sheet.id === batch?.spreadsheet_id);
  const googleConnectors = batchSheet?.connectors.filter((connector) => connector.type === "google_sheets") ?? [];
  const googlePending = googleConnectors.filter((connector) => connector.status !== "synced" && connector.status !== "active");
  const batchTableColumns = useMemo<Column<BatchItem>[]>(
    () => (batch?.result_columns || []).map((column) => ({
      key: column.key,
      header: column.label,
      cell: (item) => {
        if (column.key === "client_name") return item.client_name || item.client_id || "-";
        if (column.key === "grupo" || column.key === "cota" || column.key === "versao") {
          return item.client_fields?.[column.key as "grupo" | "cota" | "versao"] || "-";
        }
        if (column.key === "status") {
          return (
            <BadgeStatus
              tone={item.status === "success" ? "success" : item.status === "error" ? "error" : "info"}
            >
              {item.status_label || batchStatusLabel(item.status || "queued")}
            </BadgeStatus>
          );
        }
        if (column.key === "error_message") return item.error_message || "-";
        return item.output_values?.[column.key] || "-";
      },
    })),
    [batch?.result_columns],
  );

  return (
    <AppShell title="Execução" subtitle="Consultas individuais e lotes sequenciais">
      <div className="mb-4 grid gap-4 lg:grid-cols-[360px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Execução individual</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-2">
              <Label>Ação</Label>
              <SearchableSelect
                value={singleActionId}
                options={individualActions.map((action) => ({ value: action.id, label: action.name }))}
                onValueChange={setSingleActionId}
                placeholder="Selecione uma ação"
              />
            </div>
            <div className="grid gap-2">
              <Label>Cliente</Label>
              <ClientSearchCombobox
                value={singleClient}
                clients={singleClients.data?.items ?? []}
                search={singleClientSearch}
                loading={singleClients.isLoading || singleClients.isFetching}
                onSearchChange={setSingleClientSearch}
                onSelect={setSingleClient}
                onClear={() => {
                  setSingleClient(null);
                  setSingleClientSearch("");
                  setDebouncedClientSearch("");
                }}
              />
            </div>
            {singleClient && (
              <div className="rounded-md border border-border bg-muted/20 p-3 text-xs text-muted-foreground">
                Grupo {singleClient.display_variables.grupo || "-"} · Cota {singleClient.display_variables.cota || "-"} · Versão {singleClient.display_variables.versao || "-"}
              </div>
            )}
            <Button
              className="w-full"
              disabled={!singleActionId || !singleClient || runSingle.isPending}
              onClick={() => runSingle.mutate()}
            >
              <Play className="h-4 w-4" />{" "}
              {runSingle.isPending ? "Enfileirando..." : "Executar cliente"}
            </Button>
            {currentRun.data && (
              <RunProgress
                run={currentRun.data}
                loading={currentRun.isFetching && !isFinalRun(currentRun.data)}
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Resultado individual</CardTitle>
          </CardHeader>
          <CardContent>
            {!currentRun.data ? (
              <p className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                Execute um cliente para acompanhar status e resultado aqui.
              </p>
            ) : (
              <div className="space-y-3 text-sm">
                <Info label="Run" value={currentRun.data.id} />
                <Info label="Status" value={runStatusLabel(currentRun.data.status)} />
                <Info
                  label="Resultado"
                  value={
                    currentRun.data.operational_summary ||
                    currentRun.data.result_summary ||
                    currentRun.data.error_message ||
                    "-"
                  }
                />
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Nova execução</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-2">
              <Label>Lista/grupo</Label>
              <SearchableSelect
                value={group}
                options={[{ value: "", label: "Todos os clientes ativos" }, ...(clientLists.data ?? []).map((item) => ({ value: item.id, label: item.name }))]}
                onValueChange={setGroup}
                placeholder="Selecione uma lista"
              />
            </div>
            <div className="grid gap-2">
              <Label>Ação</Label>
              <SearchableSelect
                value={actionId}
                options={compatibleActions.map((action) => ({ value: action.id, label: action.name, description: action.allowed_list_ids.length ? "Disponível para listas selecionadas" : "Disponível para todas as listas" }))}
                onValueChange={setActionId}
                placeholder="Selecione uma ação"
                emptyLabel={group ? "Nenhuma ação disponível para esta lista." : "Nenhuma ação executável encontrada."}
              />
            </div>
            <div className="grid gap-2">
              <Label>Planilha do Sistema</Label>
              <SearchableSelect
                value={spreadsheetId}
                options={compatibleSpreadsheets.map((sheet) => ({ value: sheet.id, label: sheet.name, description: `${sheet.client_count} clientes · ${sheet.fields.length} campos` }))}
                onValueChange={setSpreadsheetId}
                placeholder={group ? "Selecione a planilha da lista" : "Selecione uma planilha"}
                emptyLabel={group ? "Nenhuma planilha associada a esta lista." : "Nenhuma Planilha do Sistema encontrada."}
              />
              {!compatibleSpreadsheets.length && <p className="text-xs text-amber-700">Nenhuma Planilha do Sistema está associada à seleção atual. Para uma ação livre, este destino é opcional.</p>}
              {missingFieldIds.length > 0 && <p className="text-xs text-destructive">A ação usa {missingFieldIds.length} campo(s) que não existem nesta planilha.</p>}
            </div>
            <div className="grid gap-2">
              <Label>Intervalo entre clientes</Label>
              <Input
                type="number"
                min={0}
                value={delay}
                onChange={(event) => setDelay(Number(event.target.value || 0))}
              />
            </div>
            <div className="rounded-md border border-border bg-muted/30 p-3 text-sm">
              <p className="font-medium text-foreground">Resumo da execução</p>
              <div className="mt-2 grid gap-1 text-xs text-muted-foreground">
                <span>Lista: <strong className="text-foreground">{(clientLists.data ?? []).find((item) => item.id === group)?.name || "Todas as listas"}</strong></span>
                <span>Ação: <strong className="text-foreground">{selectedAction?.name || "-"}</strong></span>
                <span>Planilha: <strong className="text-foreground">{selectedSpreadsheet?.name || "-"}</strong></span>
                <span>Clientes ativos: <strong className="text-foreground">{selectedClients.length}</strong></span>
                <span>Processamento: <strong className="text-foreground">1 cliente por vez · {delay}s entre clientes</strong></span>
              </div>
            </div>
            <Button
              className="w-full"
              disabled={!actionId || selectedClients.length === 0 || (requiresSpreadsheet && !spreadsheetId) || missingFieldIds.length > 0 || create.isPending}
              onClick={() => create.mutate()}
            >
              <Play className="h-4 w-4" /> {create.isPending ? "Enfileirando..." : "Executar agora"}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">Progresso</CardTitle>
            {batch && (
              <BadgeStatus
                tone={
                  batch.status === "completed" || batch.status === "success"
                    ? "success"
                    : batch.status.includes("error")
                      ? "error"
                      : "info"
                }
              >
                {batchStatusLabel(batch.status)}
              </BadgeStatus>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            {!batch ? (
              <div className="space-y-3">
                <p className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                  Nenhuma execução em massa ativa nesta configuração.
                </p>
                {latestBatch && <div className="rounded-md border border-border bg-muted/20 p-3 text-sm">
                  <p className="font-medium text-foreground">Última execução</p>
                  <p className="mt-1 text-xs text-muted-foreground">{latestBatch.processed_items} de {latestBatch.total_items} processados · {batchStatusLabel(latestBatch.status)}</p>
                </div>}
              </div>
            ) : (
              <>
                <div className="space-y-2">
                  <Progress value={progress} />
                  {batch.current_client_name && (
                    <p className="text-sm text-muted-foreground">Cliente atual: <strong className="text-foreground">{batch.current_client_name}</strong></p>
                  )}
                  <div className="grid gap-2 text-sm sm:grid-cols-3">
                    <Info label="Total" value={batch.total_items} />
                    <Info label="Processados" value={batch.processed_items} />
                    <Info label="Sucesso" value={batch.success_items} />
                    <Info label="Erros" value={batch.error_items} />
                    <Info label="Interrompidos" value={batch.interrupted_items} />
                    <Info label="Cancelados" value={batch.cancelled_items} />
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                    <span className="rounded-full border px-2 py-1">Planilha: {batchSheet ? "resultados salvos" : "não selecionada"}</span>
                    {googleConnectors.length > 0 && <span className="rounded-full border px-2 py-1">Google Sheets: {googlePending.length ? `${googlePending.length} pendência(s)` : "sincronizado"}</span>}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!batchId || isFinalBatch(batch) || cancel.isPending}
                    onClick={() => cancel.mutate(batchId)}
                  >
                    <StopCircle className="h-4 w-4" /> Cancelar execução
                  </Button>
                  {googlePending.length > 0 && batch.spreadsheet_id && (
                    <Button variant="outline" size="sm" onClick={async () => {
                      try {
                        await syncSystemSpreadsheetGoogle(batch.spreadsheet_id as string, "outbound");
                        await queryClient.invalidateQueries({ queryKey: ["system-spreadsheets"] });
                        toast.success("Sincronização Google repetida sem executar a ação novamente.");
                      } catch (error) {
                        toast.error(error instanceof Error ? error.message : "Não foi possível repetir a sincronização.");
                      }
                    }}>
                      Repetir sincronização
                    </Button>
                  )}
                  {batch.status === "interrupted" && attentionItem && (
                    <>
                      <Button asChild variant="outline" size="sm">
                        <Link to="/configuracoes/navegador">Abrir navegador</Link>
                      </Button>
                      <Button
                        size="sm"
                        disabled={!batchId || resume.isPending}
                        onClick={() => resume.mutate(batchId)}
                      >
                        {resume.isPending ? "Retomando..." : "Retomar execução"}
                      </Button>
                    </>
                  )}
                  <Button
                    size="sm"
                    disabled={!batch.spreadsheet_id}
                    onClick={async () => {
                      try {
                        const blob = await exportSystemSpreadsheet(batch.spreadsheet_id as string);
                        downloadBlob(`planilha_atualizada_${batch.spreadsheet_id}.xlsx`, blob);
                      } catch (error) {
                        toast.error(error instanceof Error ? error.message : "Não foi possível baixar o Excel atualizado.");
                      }
                    }}
                  >
                    <Download className="h-4 w-4" /> Baixar Excel atualizado
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={!batchId}
                    onClick={async () => {
                      try {
                        downloadCsv(`batch_${batchId}_results.csv`, await exportBatchResultsCsv(batchId));
                      } catch (error) {
                        toast.error(error instanceof Error ? error.message : "Não foi possível baixar o CSV.");
                      }
                    }}
                  >
                    CSV (opcional)
                  </Button>
                </div>
                {batch.spreadsheet_id && (
                  <p className="text-xs text-muted-foreground">Os resultados persistidos podem ser baixados na Planilha do Sistema, inclusive em lotes com erros parciais.</p>
                )}
                {batch.status === "interrupted" && attentionItem && (
                  <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                    <p className="font-medium text-foreground">Execução pausada</p>
                    <p className="mt-1 text-muted-foreground">
                      Cliente atual: {attentionItem.client_name || attentionItem.client_id || "-"}
                    </p>
                    <p className="mt-1 text-muted-foreground">
                      Motivo: {attentionItem.error_message || "A sessão do sistema externo precisa de atenção."}
                    </p>
                  </div>
                )}
                <p className="text-xs text-muted-foreground">
                  Cancelar execução conclui o cliente atual e cancela os próximos.
                </p>
                <DataTable
                  columns={batchTableColumns.length ? batchTableColumns : itemColumns}
                  data={batchRows.map((item, index) => ({ id: item.id || `${index}`, ...item }))}
                  empty="Resultados aparecerão conforme o worker processar a fila."
                />
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

function RunProgress({ run, loading }: { run: ApiRun; loading: boolean }) {
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="text-muted-foreground">{loading ? "Atualizando..." : "Status"}</span>
        <BadgeStatus
          tone={run.status === "success" ? "success" : run.status === "error" ? "error" : "info"}
        >
          {runStatusLabel(run.status)}
        </BadgeStatus>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {run.status === "pending" && "A execução entrou na fila."}
        {run.status === "running" && "O sistema está operando no navegador."}
        {run.status === "success" && "Execução concluída."}
        {run.status === "error" && (run.error_message || "Execução finalizada com erro.")}
      </p>
    </div>
  );
}

const itemColumns: Column<{
  id: string;
  client_name?: string;
  client_id?: string;
  status?: string;
  result_summary?: string | null;
  error_message?: string | null;
}>[] = [
  { key: "client", header: "Cliente", cell: (item) => item.client_name || item.client_id || "-" },
  {
    key: "status",
    header: "Status",
    cell: (item) => (
      <BadgeStatus
        tone={item.status === "success" ? "success" : item.status === "error" ? "error" : "info"}
      >
        {batchStatusLabel(item.status || "queued")}
      </BadgeStatus>
    ),
  },
  {
    key: "result",
    header: "Resultado",
    cell: (item) => item.result_summary || item.error_message || "-",
  },
];

function Info({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold text-foreground">{value}</p>
    </div>
  );
}

function isFinalBatch(batch?: ApiBatch) {
  return Boolean(
    batch &&
    ["completed", "completed_with_errors", "cancelled", "interrupted", "error", "success"].includes(
      batch.status,
    ),
  );
}

function isFinalRun(run?: ApiRun) {
  return Boolean(run && ["success", "error"].includes(run.status));
}

function variablesFromClient(client: ApiClient) {
  return {
    grupo: client.display_variables?.grupo || client.variables.grupo || "",
    cota: client.display_variables?.cota || client.variables.cota || "",
    versao: client.display_variables?.versao || client.variables.versao || "",
  };
}

function downloadCsv(filename: string, csvText: string) {
  const blob = new Blob([csvText], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
