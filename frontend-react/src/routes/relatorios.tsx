import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { AppShell } from "@/components/cotasync/AppShell";
import { StatusCard } from "@/components/cotasync/StatusCard";
import { DataTable, type Column } from "@/components/cotasync/DataTable";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { mockActions } from "@/lib/mock-data";
import { Activity, CheckCircle2, XCircle, Users, Download, ChevronDown, Image as ImageIcon } from "lucide-react";

export const Route = createFileRoute("/relatorios")({
  head: () => ({ meta: [{ title: "Relatórios — CotaSync" }] }),
  component: RelatoriosPage,
});

type ReportRow = {
  id: string; date: string; client: string; action: string;
  result: string; status: "Sucesso" | "Erro"; error?: string;
};

const rows: ReportRow[] = [
  { id: "r1", date: "2025-07-14 09:15", client: "Cliente Alfa",   action: "Número de parcelas pagas", result: "038", status: "Sucesso" },
  { id: "r2", date: "2025-07-14 09:15", client: "Cliente Beta",   action: "Número de parcelas pagas", result: "042", status: "Sucesso" },
  { id: "r3", date: "2025-07-14 09:16", client: "Cliente Gama",   action: "Número de parcelas pagas", result: "—",   status: "Erro", error: "Campo cota não encontrado" },
  { id: "r4", date: "2025-07-13 08:00", client: "Cliente Épsilon",action: "Número de parcelas pagas", result: "051", status: "Sucesso" },
];

function RelatoriosPage() {
  const [detail, setDetail] = useState<ReportRow | null>(null);
  const [techOpen, setTechOpen] = useState(false);

  const columns: Column<ReportRow>[] = [
    { key: "d", header: "Data", cell: (r) => <span className="text-xs text-muted-foreground">{r.date}</span> },
    { key: "c", header: "Cliente", cell: (r) => <span className="font-medium text-foreground">{r.client}</span> },
    { key: "a", header: "Ação", cell: (r) => r.action },
    { key: "r", header: "Resultado", cell: (r) => r.result },
    { key: "s", header: "Status", cell: (r) => (
      <BadgeStatus tone={r.status === "Sucesso" ? "success" : "error"}>{r.status}</BadgeStatus>
    )},
    { key: "e", header: "Erro", cell: (r) => r.error ? <span className="text-xs text-destructive">{r.error}</span> : "—" },
    { key: "ac", header: "", cell: (r) => (
      <Button size="sm" variant="ghost" onClick={() => setDetail(r)}>Ver detalhes</Button>
    )},
  ];

  return (
    <AppShell
      title="Relatórios"
      subtitle="Histórico de execuções e resultados"
      actions={
        <div className="flex gap-2">
          <Button variant="outline" size="sm"><Download className="h-4 w-4" /> Baixar CSV</Button>
          <Button size="sm"><Download className="h-4 w-4" /> Relatório mensal</Button>
        </div>
      }
    >
      {/* Filtros */}
      <Card className="mb-4">
        <CardContent className="grid gap-3 p-4 md:grid-cols-5">
          <div className="grid gap-1.5">
            <Label className="text-xs">Período</Label>
            <Select defaultValue="7">
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="1">Últimas 24h</SelectItem>
                <SelectItem value="7">Últimos 7 dias</SelectItem>
                <SelectItem value="30">Últimos 30 dias</SelectItem>
                <SelectItem value="custom">Personalizado</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label className="text-xs">Ação</Label>
            <Select>
              <SelectTrigger><SelectValue placeholder="Todas" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Todas</SelectItem>
                {mockActions.map(a => <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label className="text-xs">Lista/grupo</Label>
            <Select>
              <SelectTrigger><SelectValue placeholder="Todas" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Todas</SelectItem>
                <SelectItem value="p">Lista Principal</SelectItem>
                <SelectItem value="v">Lista VIP</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label className="text-xs">Cliente</Label>
            <Input placeholder="Buscar" />
          </div>
          <div className="grid gap-1.5">
            <Label className="text-xs">Status</Label>
            <Select>
              <SelectTrigger><SelectValue placeholder="Todos" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Todos</SelectItem>
                <SelectItem value="ok">Sucesso</SelectItem>
                <SelectItem value="err">Erro</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Cards */}
      <div className="mb-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatusCard label="Total de execuções" value="142" icon={Activity} />
        <StatusCard label="Sucessos" value="134" icon={CheckCircle2} tone="success" />
        <StatusCard label="Erros" value="8" icon={XCircle} tone="error" />
        <StatusCard label="Clientes processados" value="118" icon={Users} />
      </div>

      <Card>
        <CardContent className="p-0">
          <DataTable columns={columns} data={rows} />
        </CardContent>
      </Card>

      {/* Detalhe */}
      <Dialog open={!!detail} onOpenChange={(o) => { if (!o) { setDetail(null); setTechOpen(false); } }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle>Detalhe da execução</DialogTitle></DialogHeader>
          {detail && (
            <div className="grid gap-4 py-2 text-sm">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Cliente</p>
                  <p className="mt-1 text-foreground">{detail.client}</p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Ação</p>
                  <p className="mt-1 text-foreground">{detail.action}</p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Variáveis usadas</p>
                  <p className="mt-1 text-foreground">grupo=935, cota=110, versao=00</p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Resultado extraído</p>
                  <p className="mt-1 text-foreground">{detail.result}</p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Status</p>
                  <p className="mt-1"><BadgeStatus tone={detail.status === "Sucesso" ? "success" : "error"}>{detail.status}</BadgeStatus></p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Data</p>
                  <p className="mt-1 text-foreground">{detail.date}</p>
                </div>
              </div>

              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Evidência</p>
                <div className="mt-2 flex h-40 items-center justify-center rounded-md border border-dashed border-border bg-muted/30 text-muted-foreground">
                  <div className="flex flex-col items-center gap-1">
                    <ImageIcon className="h-6 w-6" />
                    <span className="text-xs">Screenshot da tela do sistema externo</span>
                  </div>
                </div>
              </div>

              <Collapsible open={techOpen} onOpenChange={setTechOpen}>
                <CollapsibleTrigger className="flex w-full items-center justify-between rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40">
                  Diagnóstico técnico
                  <ChevronDown className={`h-4 w-4 transition ${techOpen ? "rotate-180" : ""}`} />
                </CollapsibleTrigger>
                <CollapsibleContent className="mt-2">
                  <pre className="max-h-64 overflow-auto rounded-md border border-border bg-muted/40 p-3 font-mono text-xs text-foreground">
{JSON.stringify({
  run_id: "run_9f2c",
  duration_ms: 6120,
  steps: 7,
  status: detail.status,
  error: detail.error ?? null,
}, null, 2)}
                  </pre>
                </CollapsibleContent>
              </Collapsible>
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDetail(null)}>Fechar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
