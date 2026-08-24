import { createFileRoute, Link } from "@tanstack/react-router";
import { AppShell } from "@/components/cotasync/AppShell";
import { StatusCard } from "@/components/cotasync/StatusCard";
import { DataTable, type Column } from "@/components/cotasync/DataTable";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { mockExecutions, type ExecutionRow } from "@/lib/mock-data";
import {
  Wifi, Users, Zap, Activity, Clock, CalendarClock, ListChecks, AlertTriangle,
  GraduationCap, UserPlus, Shield, ChevronRight,
} from "lucide-react";


export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "Dashboard — CotaSync" }] }),
  component: Dashboard,
});

const columns: Column<ExecutionRow>[] = [
  { key: "dt", header: "Data/hora", cell: (r) => r.datetime },
  { key: "ac", header: "Ação", cell: (r) => r.action },
  { key: "cl", header: "Clientes", cell: (r) => r.clients },
  {
    key: "st", header: "Status",
    cell: (r) => (
      <BadgeStatus tone={r.status === "Sucesso" ? "success" : r.status === "Erro" ? "error" : "info"}>
        {r.status}
      </BadgeStatus>
    ),
  },
  { key: "ok", header: "Sucesso", cell: (r) => r.ok },
  { key: "er", header: "Erros", cell: (r) => r.err },
  { key: "ac2", header: "", cell: () => <Button size="sm" variant="ghost">Ver detalhes</Button> },
];

const quickActions = [
  { title: "Ensinar nova ação", desc: "Grave um novo fluxo automatizado", to: "/ensinar-acao", icon: GraduationCap, tone: "primary" as const },
  { title: "Executar em massa", desc: "Rode uma ação para vários clientes", to: "/execucao", icon: ListChecks },
  { title: "Cadastrar cliente", desc: "Adicione um novo cliente à lista", to: "/clientes", icon: UserPlus },
  { title: "Verificar sessão", desc: "Teste o acesso ao sistema externo", to: "/configuracoes", icon: Shield },
];

const alerts = [
  { tone: "warning" as const, label: "Precisa de atenção", title: "Sessão expira em breve", desc: "Renove a sessão do sistema externo.", to: "/configuracoes" },
  { tone: "info" as const, label: "Info", title: "2 clientes com dados incompletos", desc: "Grupo ou cota ausentes na Lista Principal.", to: "/clientes" },
  { tone: "error" as const, label: "Erro", title: "1 execução com erro pendente", desc: "Reprocesse a partir de Relatórios.", to: "/relatorios" },
];

function Dashboard() {
  return (
    <AppShell title="Dashboard" subtitle="Visão geral do CotaSync">
      {/* Ações rápidas */}
      <div className="mb-6">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Ações rápidas
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {quickActions.map((a) => (
            <Link
              key={a.to}
              to={a.to}
              className={`group flex items-start gap-3 rounded-lg border p-4 transition hover:border-primary hover:bg-primary/5 ${
                a.tone === "primary" ? "border-primary/40 bg-primary/5" : "border-border bg-card"
              }`}
            >
              <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-md ${
                a.tone === "primary" ? "bg-primary text-primary-foreground" : "bg-muted text-foreground"
              }`}>
                <a.icon className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-foreground">{a.title}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{a.desc}</p>
              </div>
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition group-hover:translate-x-0.5 group-hover:text-primary" />
            </Link>
          ))}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatusCard label="Sessão externa" value="Sessão conectada" hint="Última verificação: agora" icon={Wifi} tone="success" />
        <StatusCard label="Clientes ativos" value="124" hint="Lista Principal + VIP" icon={Users} />
        <StatusCard label="Ações prontas" value="3" hint="1 em desenvolvimento" icon={Zap} />
        <StatusCard label="Execuções hoje" value="18" hint="17 sucesso · 1 erro" icon={Activity} />
        <StatusCard label="Última execução" value="Concluído" hint="Hoje às 09:15" icon={Clock} tone="success" />
        <StatusCard label="Próximo agendamento" value="05/08 · 08:00" hint="Consulta mensal de parcelas" icon={CalendarClock} />
        <StatusCard label="Fila atual" value="Ociosa" hint="Nenhuma execução em andamento" icon={ListChecks} />
        <StatusCard label="Alertas" value="3" hint="Requerem revisão" icon={AlertTriangle} tone="warning" />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Últimas execuções</CardTitle>
          </CardHeader>
          <CardContent>
            <DataTable columns={columns} data={mockExecutions} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Alertas</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {alerts.map((a, i) => (
              <Link
                key={i}
                to={a.to}
                className="group block rounded-md border border-border bg-muted/30 p-3 transition hover:border-primary/50 hover:bg-muted/60"
              >
                <div className="flex items-center gap-2">
                  <BadgeStatus tone={a.tone}>{a.label}</BadgeStatus>
                  <p className="flex-1 text-sm font-medium text-foreground">{a.title}</p>
                  <ChevronRight className="h-4 w-4 text-muted-foreground transition group-hover:translate-x-0.5 group-hover:text-primary" />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{a.desc}</p>
              </Link>
            ))}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

