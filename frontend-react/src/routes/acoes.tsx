import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { History, Play, Plus } from "lucide-react";

import { AppShell } from "@/components/cotasync/AppShell";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { getActions, getActionVersions } from "@/services/api";
import type { ApiAction } from "@/types/api";
import { actionIsExecutable, runStatusLabel } from "@/lib/status-labels";

export const Route = createFileRoute("/acoes")({
  head: () => ({ meta: [{ title: "Ações — CotaSync" }] }),
  component: AcoesPage,
});

function AcoesPage() {
  const actions = useQuery({ queryKey: ["actions"], queryFn: () => getActions({ pageSize: 200 }) });

  return (
    <AppShell
      title="Ações"
      subtitle="Fluxos publicados e disponíveis para execução"
      actions={
        <Button size="sm" asChild>
          <a href="/ensinar-acao">
            <Plus className="h-4 w-4" /> Nova ação
          </a>
        </Button>
      }
    >
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(actions.data?.items ?? []).map((action) => (
          <ActionCard key={action.id} action={action} />
        ))}
      </div>
      {!actions.isLoading && (actions.data?.items ?? []).length === 0 && (
        <div className="rounded-lg border border-dashed border-border bg-card p-8 text-center text-sm text-muted-foreground">
          Nenhuma ação publicada.
        </div>
      )}
      {actions.isLoading && (
        <div className="rounded-lg border border-border bg-card p-8 text-center text-sm text-muted-foreground">
          Carregando ações...
        </div>
      )}
    </AppShell>
  );
}

function ActionCard({ action }: { action: ApiAction }) {
  const [open, setOpen] = useState(false);
  const executable = actionIsExecutable(action);
  const versionLabel = executable ? "Publicada" : "Não executável";
  return (
    <Card className="border-border/70 shadow-sm">
      <CardHeader className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base">{action.name}</CardTitle>
            <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
              {action.description || "Sem descrição operacional."}
            </p>
          </div>
          <BadgeStatus tone={executable ? "success" : "warning"}>
            {executable ? "Pronta" : "Precisa de atenção"}
          </BadgeStatus>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <Info label="Versão" value={versionLabel} />
          <Info label="Passos" value={String(action.steps_count ?? 0)} />
          <Info
            label="Última execução"
            value={action.last_run ? runStatusLabel(action.last_run.status) : "Sem histórico"}
          />
          <Info
            label="Variáveis"
            value={action.variables.map((item) => item.key).join(", ") || "Nenhuma"}
          />
        </div>
        {action.legacy_unconfigured && (
          <div className="rounded-md border border-warning/40 bg-warning/10 p-3 text-xs text-warning-foreground">
            Ação legada sem URL inicial segura. Ela permanece visível, mas deve ser normalizada por
            novo aprendizado.
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          {executable ? (
            <Button size="sm" variant="outline" asChild>
              <a href="/execucao">
                <Play className="h-4 w-4" /> Executar
              </a>
            </Button>
          ) : (
            <Button size="sm" variant="outline" disabled>
              <Play className="h-4 w-4" /> Executar
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
            <History className="h-4 w-4" /> Versões
          </Button>
        </div>
      </CardContent>
      <VersionsDialog action={action} open={open} onOpenChange={setOpen} />
    </Card>
  );
}

function VersionsDialog({
  action,
  open,
  onOpenChange,
}: {
  action: ApiAction;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const versions = useQuery({
    queryKey: ["actions", action.id, "versions"],
    queryFn: () => getActionVersions(action.id),
    enabled: open,
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Versões de {action.name}</DialogTitle>
        </DialogHeader>
        <div className="space-y-2">
          {(versions.data ?? []).map((version) => (
            <div
              key={version.id}
              className="flex items-center justify-between rounded-md border border-border p-3 text-sm"
            >
              <div>
                <p className="font-medium">Versão v{version.version_number}</p>
                <p className="text-xs text-muted-foreground">
                  {version.published_at
                    ? new Date(version.published_at).toLocaleString("pt-BR")
                    : "Não publicada"}
                </p>
              </div>
              <BadgeStatus tone={version.published ? "success" : "neutral"}>
                {version.published ? "Publicada" : version.status}
              </BadgeStatus>
            </div>
          ))}
          {!versions.isLoading && (versions.data ?? []).length === 0 && (
            <p className="text-sm text-muted-foreground">Nenhuma versão registrada.</p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase text-muted-foreground">{label}</p>
      <p className="mt-1 truncate text-foreground">{value}</p>
    </div>
  );
}
