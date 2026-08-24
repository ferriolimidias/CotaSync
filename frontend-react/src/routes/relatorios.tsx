import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Download } from "lucide-react";

import { AppShell } from "@/components/cotasync/AppShell";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { DataTable, type Column } from "@/components/cotasync/DataTable";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getActions, getReportsBatches, getReportsRuns } from "@/services/api";
import type { ApiBatch, ApiRun } from "@/types/api";

export const Route = createFileRoute("/relatorios")({
  head: () => ({ meta: [{ title: "Relatórios — CotaSync" }] }),
  component: RelatoriosPage,
});

function RelatoriosPage() {
  const [actionId, setActionId] = useState("all");
  const [status, setStatus] = useState("all");
  const [detail, setDetail] = useState<ApiRun | null>(null);
  const actions = useQuery({ queryKey: ["actions"], queryFn: () => getActions({ pageSize: 200 }) });
  const runs = useQuery({
    queryKey: ["reports", "runs", actionId, status],
    queryFn: () =>
      getReportsRuns({
        pageSize: 50,
        actionId: actionId === "all" ? undefined : actionId,
        status: status === "all" ? undefined : status,
      }),
  });
  const batches = useQuery({
    queryKey: ["reports", "batches"],
    queryFn: () => getReportsBatches({ pageSize: 10 }),
  });

  const columns: Column<ApiRun>[] = [
    { key: "date", header: "Data", cell: (run) => formatDate(run.created_at) },
    { key: "action", header: "Ação", cell: (run) => run.action_key || run.action_id },
    {
      key: "status",
      header: "Status",
      cell: (run) => (
        <BadgeStatus
          tone={run.status === "success" ? "success" : run.status === "error" ? "error" : "info"}
        >
          {statusLabel(run.status)}
        </BadgeStatus>
      ),
    },
    { key: "origin", header: "Origem", cell: (run) => run.run_origin },
    {
      key: "result",
      header: "Resultado",
      cell: (run) => run.operational_summary || run.result_summary || run.error_message || "-",
    },
    {
      key: "detail",
      header: "",
      cell: (run) => (
        <Button size="sm" variant="ghost" onClick={() => setDetail(run)}>
          Ver detalhes
        </Button>
      ),
    },
  ];

  return (
    <AppShell title="Relatórios" subtitle="Histórico paginado de execuções e batches">
      <Card className="mb-4">
        <CardContent className="flex flex-wrap items-center gap-2 p-4">
          <Select value={actionId} onValueChange={setActionId}>
            <SelectTrigger className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todas as ações</SelectItem>
              {(actions.data?.items ?? []).map((action) => (
                <SelectItem key={action.id} value={action.id}>
                  {action.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todos</SelectItem>
              <SelectItem value="success">Sucesso</SelectItem>
              <SelectItem value="error">Erro</SelectItem>
              <SelectItem value="running">Executando</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" disabled>
            <Download className="h-4 w-4" /> Exportação CSV
          </Button>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <DataTable
          columns={columns}
          data={runs.data?.items ?? []}
          empty={runs.isLoading ? "Carregando histórico..." : "Nenhuma execução encontrada."}
        />
        <Card>
          <CardContent className="space-y-3 p-4">
            <h2 className="text-sm font-semibold text-foreground">Batches recentes</h2>
            {(batches.data?.items ?? []).map((batch) => (
              <BatchSummary key={batch.batch_id || batch.id} batch={batch} />
            ))}
            {!batches.isLoading && (batches.data?.items ?? []).length === 0 && (
              <p className="text-sm text-muted-foreground">Nenhum batch registrado.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog open={Boolean(detail)} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Detalhes da execução</DialogTitle>
          </DialogHeader>
          {detail && (
            <div className="space-y-3 text-sm">
              <Info label="Run" value={detail.id} />
              <Info label="Ação" value={detail.action_key || detail.action_id} />
              <Info label="Status" value={statusLabel(detail.status)} />
              <Info
                label="Resultado"
                value={detail.operational_summary || detail.result_summary || "-"}
              />
              {detail.error_message && <Info label="Erro" value={detail.error_message} />}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}

function BatchSummary({ batch }: { batch: ApiBatch }) {
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <p className="truncate font-medium">{batch.batch_id || batch.id}</p>
        <BadgeStatus
          tone={
            batch.status.includes("error")
              ? "error"
              : batch.status === "completed"
                ? "success"
                : "info"
          }
        >
          {batchStatus(batch.status)}
        </BadgeStatus>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {batch.processed_items}/{batch.total_items} processados · {batch.success_items} sucesso ·{" "}
        {batch.error_items} erro
      </p>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase text-muted-foreground">{label}</p>
      <p className="mt-1 break-words text-foreground">{value}</p>
    </div>
  );
}

function statusLabel(status: string) {
  return (
    (
      { success: "Concluído", error: "Erro", running: "Executando", pending: "Na fila" } as Record<
        string,
        string
      >
    )[status] || status
  );
}

function batchStatus(status: string) {
  return (
    (
      {
        queued: "Na fila",
        running: "Executando",
        cancel_requested: "Cancelando",
        completed: "Concluído",
        completed_with_errors: "Concluído com erros",
        cancelled: "Cancelado",
      } as Record<string, string>
    )[status] || status
  );
}

function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleString("pt-BR") : "-";
}
