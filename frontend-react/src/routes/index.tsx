import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ChevronRight,
  Clock,
  GraduationCap,
  ListChecks,
  Shield,
  UserPlus,
  Users,
  Wifi,
  Zap,
} from "lucide-react";

import { AppShell } from "@/components/cotasync/AppShell";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { DataTable, type Column } from "@/components/cotasync/DataTable";
import { StatusCard } from "@/components/cotasync/StatusCard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getDashboard, getReportsRuns } from "@/services/api";
import type { ApiRun } from "@/types/api";
import {
  externalSessionStatusLabel,
  loginModeLabel,
  runStatusLabel,
  workerStatusLabel,
} from "@/lib/status-labels";

export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "Dashboard — CotaSync" }] }),
  component: Dashboard,
});

const columns: Column<ApiRun>[] = [
  { key: "dt", header: "Data/hora", cell: (run) => formatDate(run.created_at) },
  { key: "ac", header: "Ação", cell: (run) => run.action_key || run.action_id },
  {
    key: "st",
    header: "Status",
    cell: (run) => (
      <BadgeStatus
        tone={run.status === "success" ? "success" : run.status === "error" ? "error" : "info"}
      >
        {runStatusLabel(run.status)}
      </BadgeStatus>
    ),
  },
  { key: "or", header: "Origem", cell: (run) => run.run_origin || "operacional" },
  {
    key: "rs",
    header: "Resultado",
    cell: (run) => run.operational_summary || run.result_summary || run.error_message || "-",
  },
];

const quickActions = [
  {
    title: "Ensinar nova ação",
    desc: "Grave um novo fluxo automatizado",
    to: "/ensinar-acao",
    icon: GraduationCap,
    tone: "primary" as const,
  },
  {
    title: "Executar em massa",
    desc: "Rode uma ação para vários clientes",
    to: "/execucao",
    icon: ListChecks,
  },
  {
    title: "Cadastrar cliente",
    desc: "Adicione um cliente à base",
    to: "/clientes",
    icon: UserPlus,
  },
  { title: "Verificar sessão", desc: "Teste o acesso externo", to: "/configuracoes", icon: Shield },
];

function Dashboard() {
  const dashboard = useQuery({
    queryKey: ["dashboard"],
    queryFn: getDashboard,
    refetchInterval: 3000,
  });
  const runs = useQuery({
    queryKey: ["reports", "runs", "dashboard"],
    queryFn: () => getReportsRuns({ pageSize: 5, runOrigin: "operational" }),
  });
  const data = dashboard.data;
  const workerOnline = Boolean(data?.worker_status?.online);
  const queueRunning = Number(data?.queue_status.running || 0);
  const externalSession = data?.external_session;

  return (
    <AppShell title="Dashboard" subtitle="Visão geral do CotaSync">
      <div className="mb-6">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Ações rápidas
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {quickActions.map((action) => (
            <Link
              key={action.to}
              to={action.to}
              className={`group flex items-start gap-3 rounded-lg border p-4 transition hover:border-primary hover:bg-primary/5 ${action.tone === "primary" ? "border-primary/40 bg-primary/5" : "border-border bg-card"}`}
            >
              <div
                className={`grid h-10 w-10 shrink-0 place-items-center rounded-md ${action.tone === "primary" ? "bg-primary text-primary-foreground" : "bg-muted text-foreground"}`}
              >
                <action.icon className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-foreground">{action.title}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{action.desc}</p>
              </div>
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition group-hover:translate-x-0.5 group-hover:text-primary" />
            </Link>
          ))}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatusCard
          label="Sessão externa"
          value={externalSessionStatusLabel(
            externalSession?.session_status || data?.session_status,
          )}
          hint={loginModeLabel(externalSession?.login_mode || externalSession?.automation)}
          icon={Wifi}
          tone={
            (externalSession?.session_status || data?.session_status) === "authenticated"
              ? "success"
              : externalSession?.external_system_configured
                ? "warning"
                : "error"
          }
        />
        <StatusCard
          label="Clientes ativos"
          value={dashboard.isLoading ? "..." : (data?.clients_active ?? 0)}
          hint="Base operacional"
          icon={Users}
        />
        <StatusCard
          label="Ações prontas"
          value={dashboard.isLoading ? "..." : (data?.actions_ready ?? 0)}
          hint="Executáveis pelo worker"
          icon={Zap}
        />
        <StatusCard
          label="Execuções hoje"
          value={dashboard.isLoading ? "..." : (data?.runs_today ?? 0)}
          hint="Runs criadas hoje"
          icon={Activity}
        />
        <StatusCard
          label="Última execução"
          value={data?.last_run ? runStatusLabel(data.last_run.status) : "Sem histórico"}
          hint={
            data?.last_run ? formatDate(data.last_run.created_at) : "Nenhuma execução registrada"
          }
          icon={Clock}
          tone={data?.last_run?.status === "success" ? "success" : "default"}
        />
        <StatusCard
          label="Sistema de execução"
          value={workerOnline ? "Online" : "Offline"}
          hint={workerStatusLabel(data?.worker_status?.status)}
          icon={Shield}
          tone={workerOnline ? "success" : "warning"}
        />
        <StatusCard
          label="Fila atual"
          value={queueRunning ? "Executando" : "Ociosa"}
          hint={`${data?.queue_status.queued ?? 0} na fila · ${queueRunning} em execução`}
          icon={ListChecks}
        />
        <StatusCard
          label="Alertas"
          value={data?.alerts.length ?? 0}
          hint="Requerem revisão"
          icon={AlertTriangle}
          tone={(data?.alerts.length ?? 0) > 0 ? "warning" : "success"}
        />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Últimas execuções</CardTitle>
          </CardHeader>
          <CardContent>
            <DataTable
              columns={columns}
              data={runs.data?.items ?? []}
              empty={runs.isLoading ? "Carregando..." : "Nenhuma execução registrada."}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Alertas</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {(data?.alerts ?? []).length === 0 ? (
              <p className="rounded-md border border-border bg-muted/30 p-3 text-sm text-muted-foreground">
                Nenhum alerta ativo.
              </p>
            ) : (
              data?.alerts.map((alert) => (
                <div key={alert.code} className="rounded-md border border-border bg-muted/30 p-3">
                  <BadgeStatus
                    tone={
                      alert.level === "error"
                        ? "error"
                        : alert.level === "warning"
                          ? "warning"
                          : "info"
                    }
                  >
                    {alert.code}
                  </BadgeStatus>
                  <p className="mt-2 text-sm text-foreground">{alert.message}</p>
                </div>
              ))
            )}
            {dashboard.error && (
              <p className="text-sm text-destructive">Não foi possível carregar o dashboard.</p>
            )}
            <Button variant="outline" size="sm" asChild>
              <Link to="/diagnostico">Diagnóstico técnico</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

function formatDate(value?: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString("pt-BR");
}
