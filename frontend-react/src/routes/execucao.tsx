import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { AppShell } from "@/components/cotasync/AppShell";
import { StatusCard } from "@/components/cotasync/StatusCard";
import { DataTable, type Column } from "@/components/cotasync/DataTable";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { mockClients, mockActions } from "@/lib/mock-data";
import {
  Users, CheckCircle2, AlertTriangle, PowerOff, Play, Download, RefreshCcw,
  StopCircle, Info, ChevronDown, Upload,
} from "lucide-react";

export const Route = createFileRoute("/execucao")({
  head: () => ({ meta: [{ title: "Execução em massa — CotaSync" }] }),
  component: ExecucaoPage,
});

type PreviewRow = {
  id: string; name: string; grupo: string; cota: string; versao: string;
  status: "Pronto" | "Incompleto" | "Inativo";
};

const previewCols: Column<PreviewRow>[] = [
  { key: "n", header: "Cliente", cell: (r) => <span className="font-medium text-foreground">{r.name}</span> },
  { key: "g", header: "Grupo", cell: (r) => r.grupo },
  { key: "c", header: "Cota", cell: (r) => r.cota },
  { key: "v", header: "Versão", cell: (r) => r.versao },
  { key: "s", header: "Status", cell: (r) => (
    <BadgeStatus tone={r.status === "Pronto" ? "success" : r.status === "Incompleto" ? "warning" : "neutral"}>
      {r.status}
    </BadgeStatus>
  )},
];

type ResultRow = {
  id: string; name: string; status: "Sucesso" | "Erro" | "Pendente";
  result: string; runId: string; start: string; end: string; error?: string;
};

const resultCols: Column<ResultRow>[] = [
  { key: "n", header: "Cliente", cell: (r) => <span className="font-medium text-foreground">{r.name}</span> },
  { key: "s", header: "Status", cell: (r) => (
    <BadgeStatus tone={r.status === "Sucesso" ? "success" : r.status === "Erro" ? "error" : "info"}>{r.status}</BadgeStatus>
  )},
  { key: "r", header: "Resultado", cell: (r) => r.result },
  { key: "id", header: "Run ID", cell: (r) => <span className="font-mono text-xs text-muted-foreground">{r.runId}</span> },
  { key: "ini", header: "Início", cell: (r) => <span className="text-xs text-muted-foreground">{r.start}</span> },
  { key: "fim", header: "Fim", cell: (r) => <span className="text-xs text-muted-foreground">{r.end}</span> },
  { key: "e", header: "Erro", cell: (r) => r.error ? <span className="text-xs text-destructive">{r.error}</span> : "—" },
];

function ExecucaoPage() {
  const [advOpen, setAdvOpen] = useState(false);

  const preview: PreviewRow[] = mockClients.map((c) => ({
    id: c.id, name: c.name, grupo: c.grupo, cota: c.cota, versao: c.versao,
    status: !c.active ? "Inativo" : c.grupo && c.cota ? "Pronto" : "Incompleto",
  }));

  const results: ResultRow[] = [
    { id: "1", name: "Cliente Alfa",    status: "Sucesso", result: "038", runId: "run_9f2a", start: "09:15:02", end: "09:15:08" },
    { id: "2", name: "Cliente Beta",    status: "Sucesso", result: "042", runId: "run_9f2b", start: "09:15:11", end: "09:15:17" },
    { id: "3", name: "Cliente Gama",    status: "Erro",    result: "—",   runId: "run_9f2c", start: "09:15:20", end: "09:15:26", error: "Campo cota não encontrado" },
    { id: "4", name: "Cliente Épsilon", status: "Pendente",result: "—",   runId: "run_9f2d", start: "—",        end: "—" },
  ];

  const total = preview.length;
  const done = 2;
  const progress = Math.round((done / total) * 100);

  return (
    <AppShell title="Execução em massa" subtitle="Execute uma ação para toda uma lista de clientes">
      {/* Aviso de fila sequencial */}
      <div className="mb-4 flex items-start gap-3 rounded-md border border-border bg-muted/30 p-3">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <p className="text-sm text-foreground">
          <span className="font-medium">Fila sequencial:</span> o CotaSync executa um cliente por vez para operar com segurança no sistema externo.
        </p>
      </div>

      {/* Passo 1 + 2 + delay */}
      <Card className="mb-4">
        <CardContent className="grid gap-4 p-4 md:grid-cols-3">
          <div className="grid gap-1.5">
            <Label className="text-xs">1. Ação</Label>
            <Select>
              <SelectTrigger><SelectValue placeholder="Selecione uma ação" /></SelectTrigger>
              <SelectContent>
                {mockActions.map((a) => (
                  <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label className="text-xs">2. Lista/grupo de clientes</Label>
            <Select>
              <SelectTrigger><SelectValue placeholder="Selecione uma lista" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="p">Lista Principal</SelectItem>
                <SelectItem value="v">Lista VIP</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label className="text-xs">Delay entre clientes (segundos)</Label>
            <Input type="number" min={0} defaultValue={3} />
          </div>
        </CardContent>
      </Card>

      {/* Passo 3 — Validação */}
      <div className="mb-4 grid gap-4 md:grid-cols-3">
        <StatusCard label="Clientes prontos" value={preview.filter(p => p.status === "Pronto").length} icon={CheckCircle2} tone="success" />
        <StatusCard label="Clientes incompletos" value={preview.filter(p => p.status === "Incompleto").length} icon={AlertTriangle} tone="warning" />
        <StatusCard label="Clientes inativos" value={preview.filter(p => p.status === "Inativo").length} icon={PowerOff} />
      </div>

      <Card className="mb-4">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">Prévia da fila</CardTitle>
          <Button><Play className="h-4 w-4" /> Executar agora</Button>
        </CardHeader>
        <CardContent>
          <DataTable columns={previewCols} data={preview} />
        </CardContent>
      </Card>

      {/* Passo 4 — Progresso */}
      <Card className="mb-4">
        <CardHeader><CardTitle className="text-base">Execução em andamento</CardTitle></CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
            <div className="lg:col-span-2 rounded-md border border-border bg-muted/30 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Cliente atual</p>
              <p className="mt-1 truncate font-semibold text-foreground">Cliente Gama</p>
              <p className="mt-0.5 text-xs text-muted-foreground">Linha {done + 1} de {total}</p>
            </div>
            <div className="rounded-md border border-border bg-card p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Processados</p>
              <p className="mt-1 text-xl font-semibold text-foreground">{done}</p>
            </div>
            <div className="rounded-md border border-border bg-card p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Faltam</p>
              <p className="mt-1 text-xl font-semibold text-foreground">{total - done}</p>
            </div>
            <div className="rounded-md border border-success/30 bg-success/5 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Sucessos</p>
              <p className="mt-1 text-xl font-semibold text-success">2</p>
            </div>
            <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Erros</p>
              <p className="mt-1 text-xl font-semibold text-destructive">0</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <BadgeStatus tone="info">Em andamento</BadgeStatus>
            <span className="text-xs text-muted-foreground">Tempo estimado ~ 00:00:18</span>
          </div>

          <div>
            <Progress value={progress} />
            <p className="mt-1 text-xs text-muted-foreground">{progress}% concluído</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm"><StopCircle className="h-4 w-4" /> Cancelar depois do cliente atual</Button>
          </div>

        </CardContent>
      </Card>

      {/* Passo 5 — Resultados */}
      <Card className="mb-4">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">Resultados</CardTitle>
          <div className="flex gap-2">
            <Button variant="outline" size="sm"><RefreshCcw className="h-4 w-4" /> Reprocessar erros</Button>
            <Button size="sm"><Download className="h-4 w-4" /> Baixar CSV final</Button>
          </div>
        </CardHeader>
        <CardContent>
          <DataTable columns={resultCols} data={results} />
        </CardContent>
      </Card>

      {/* Avançado */}
      <Collapsible open={advOpen} onOpenChange={setAdvOpen}>
        <CollapsibleTrigger className="flex w-full items-center justify-between rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40">
          Avançado: executar com CSV avulso
          <ChevronDown className={`h-4 w-4 transition ${advOpen ? "rotate-180" : ""}`} />
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2">
          <Card>
            <CardContent className="flex flex-wrap items-center gap-2 p-4">
              <p className="flex-1 text-sm text-muted-foreground">
                Envie um CSV avulso apenas para uma execução pontual. O fluxo recomendado é utilizar a lista de clientes cadastrada.
              </p>
              <Button variant="outline" size="sm"><Upload className="h-4 w-4" /> Selecionar CSV</Button>
            </CardContent>
          </Card>
        </CollapsibleContent>
      </Collapsible>
    </AppShell>
  );
}
