import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Download, Play, StopCircle } from "lucide-react";

import { AppShell } from "@/components/cotasync/AppShell";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { DataTable, type Column } from "@/components/cotasync/DataTable";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  cancelBatch,
  createBatch,
  getActions,
  getBatch,
  getBatches,
  getClients,
} from "@/services/api";
import type { ApiBatch, ApiClient } from "@/types/api";

export const Route = createFileRoute("/execucao")({
  head: () => ({ meta: [{ title: "Execução em massa — CotaSync" }] }),
  component: ExecucaoPage,
});

function ExecucaoPage() {
  const queryClient = useQueryClient();
  const actions = useQuery({ queryKey: ["actions"], queryFn: () => getActions({ pageSize: 200 }) });
  const clients = useQuery({
    queryKey: ["clients"],
    queryFn: () => getClients({ pageSize: 200, includeInactive: false }),
  });
  const batches = useQuery({
    queryKey: ["batches"],
    queryFn: () => getBatches({ pageSize: 10 }),
    refetchInterval: 3000,
  });
  const [actionId, setActionId] = useState("");
  const [group, setGroup] = useState("");
  const [delay, setDelay] = useState(3);
  const [currentBatchId, setCurrentBatchId] = useState<string | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());
  const currentBatch = useQuery({
    queryKey: ["batch", currentBatchId],
    queryFn: () => getBatch(currentBatchId as string),
    enabled: Boolean(currentBatchId),
    refetchInterval: (query) =>
      isFinalBatch(query.state.data as ApiBatch | undefined) ? false : 2500,
  });

  const groups = useMemo(
    () =>
      Array.from(
        new Set((clients.data?.items ?? []).map((client) => client.group).filter(Boolean)),
      ).sort(),
    [clients.data],
  );
  const selectedClients = useMemo(
    () => (clients.data?.items ?? []).filter((client) => !group || client.group === group),
    [clients.data, group],
  );

  const create = useMutation({
    mutationFn: () =>
      createBatch({
        action_id: actionId,
        client_group: group || undefined,
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

  const batch = currentBatch.data || batches.data?.items[0];
  const batchId = batch?.batch_id || batch?.id || "";
  const progress = batch?.total_items
    ? Math.round((batch.processed_items / batch.total_items) * 100)
    : 0;

  return (
    <AppShell title="Execução em massa" subtitle="Um cliente por vez, na ordem da fila">
      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Nova execução</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-2">
              <Label>Ação</Label>
              <Select value={actionId} onValueChange={setActionId}>
                <SelectTrigger>
                  <SelectValue placeholder="Selecione uma ação" />
                </SelectTrigger>
                <SelectContent>
                  {(actions.data?.items ?? []).map((action) => (
                    <SelectItem key={action.id} value={action.id}>
                      {action.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label>Lista/grupo</Label>
              <Select
                value={group || "all"}
                onValueChange={(value) => setGroup(value === "all" ? "" : value)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos os clientes ativos</SelectItem>
                  {groups.map((item) => (
                    <SelectItem key={item} value={item}>
                      {item}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
              <p className="font-medium text-foreground">
                {selectedClients.length} clientes selecionados
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                O sistema processa 1 cliente por vez.
              </p>
            </div>
            <Button
              className="w-full"
              disabled={!actionId || selectedClients.length === 0 || create.isPending}
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
                {batchStatus(batch.status)}
              </BadgeStatus>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            {!batch ? (
              <p className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                Nenhuma execução em massa recente.
              </p>
            ) : (
              <>
                <div className="space-y-2">
                  <Progress value={progress} />
                  <div className="grid gap-2 text-sm sm:grid-cols-3">
                    <Info label="Total" value={batch.total_items} />
                    <Info label="Processados" value={batch.processed_items} />
                    <Info label="Sucesso" value={batch.success_items} />
                    <Info label="Erros" value={batch.error_items} />
                    <Info label="Interrompidos" value={batch.interrupted_items} />
                    <Info label="Cancelados" value={batch.cancelled_items} />
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
                  <Button variant="outline" size="sm" disabled>
                    <Download className="h-4 w-4" /> Baixar CSV final
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Cancelar execução conclui o cliente atual e cancela os próximos.
                </p>
                <DataTable
                  columns={itemColumns}
                  data={(batch.items || batch.results || []).map((item, index) => ({
                    id: item.id || `${index}`,
                    ...item,
                  }))}
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
        {batchStatus(item.status || "queued")}
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

function batchStatus(status: string) {
  return (
    (
      {
        queued: "Na fila",
        running: "Executando",
        cancel_requested: "Cancelamento solicitado",
        completed: "Concluído",
        completed_with_errors: "Concluído com erros",
        cancelled: "Cancelado",
        interrupted: "Interrompido",
        error: "Erro",
        success: "Concluído",
      } as Record<string, string>
    )[status] || status
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
