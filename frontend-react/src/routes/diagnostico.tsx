import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/cotasync/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/cotasync/DataTable";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { getDiagnostics, type Diagnostics } from "@/services/api";
import { AlertCircle } from "lucide-react";

export const Route = createFileRoute("/diagnostico")({
  head: () => ({ meta: [{ title: "Diagnóstico técnico — CotaSync" }] }),
  component: DiagPage,
});

type RunRow = Diagnostics["runs"][number] & { id: string };


function DiagPage() {
  const [data, setData] = useState<Diagnostics | null>(null);
  const [jsonOpen, setJsonOpen] = useState<any>(null);

  useEffect(() => { getDiagnostics().then(setData); }, []);

  if (!data) return <AppShell title="Diagnóstico técnico"><p className="text-sm text-muted-foreground">Carregando…</p></AppShell>;

  const runs: RunRow[] = data.runs.map((r) => ({ ...r, id: r.runId }));

  const runCols: Column<RunRow>[] = [
    { key: "id", header: "Run ID", cell: (r) => <span className="font-mono text-xs">{r.runId}</span> },
    { key: "a", header: "Ação", cell: (r) => r.action },
    { key: "s", header: "Status", cell: (r) => (
      <BadgeStatus tone={r.status === "success" ? "success" : r.status === "error" ? "error" : "info"}>
        {r.status}
      </BadgeStatus>
    )},
    { key: "h", header: "Host atual", cell: (r) => <span className="text-xs text-muted-foreground">{r.host}</span> },
    { key: "st", header: "Último passo", cell: (r) => <span className="font-mono text-xs">{r.lastStep}</span> },
    { key: "e", header: "Erro", cell: (r) => r.error ? <span className="text-xs text-destructive">{r.error}</span> : "—" },
    { key: "ac", header: "", cell: (r) => (
      <Button size="sm" variant="ghost" onClick={() => setJsonOpen(r)}>Ver JSON</Button>
    )},
  ];

  const batchCols: Column<Diagnostics["batches"][number]>[] = [
    { key: "id", header: "Batch ID", cell: (r) => <span className="font-mono text-xs">{r.id}</span> },
    { key: "p", header: "Progresso", cell: (r) => `${r.done}/${r.total}` },
    { key: "s", header: "Status", cell: (r) => (
      <BadgeStatus tone={r.status === "done" ? "success" : r.status === "error" ? "error" : "info"}>{r.status}</BadgeStatus>
    )},
    { key: "ac", header: "", cell: (r) => (
      <Button size="sm" variant="ghost" onClick={() => setJsonOpen(r)}>Ver JSON</Button>
    )},
  ];

  return (
    <AppShell title="Diagnóstico técnico" subtitle="Área para suporte técnico">
      <div className="mb-4 flex items-start gap-3 rounded-md border border-warning/40 bg-warning/10 p-3">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-warning-foreground" />
        <p className="text-sm text-foreground">
          Esta tela é destinada ao suporte técnico. Termos como <span className="font-mono">run_id</span>,{" "}
          <span className="font-mono">step_trace</span> e <span className="font-mono">selector</span> aparecem apenas aqui.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-4">
        <Card>
          <CardHeader><CardTitle className="text-sm">Backend</CardTitle></CardHeader>
          <CardContent><BadgeStatus tone={data.backend === "ok" ? "success" : "error"}>{data.backend}</BadgeStatus></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">Navegador desktop</CardTitle></CardHeader>
          <CardContent><BadgeStatus tone={data.browser === "ok" ? "success" : "error"}>{data.browser}</BadgeStatus></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">Healthcheck</CardTitle></CardHeader>
          <CardContent><BadgeStatus tone={data.healthcheck === "ok" ? "success" : "error"}>{data.healthcheck}</BadgeStatus></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">Versão</CardTitle></CardHeader>
          <CardContent>
            <p className="text-sm font-medium text-foreground">{data.version}</p>
            <p className="text-xs font-mono text-muted-foreground">commit {data.commit}</p>
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader><CardTitle className="text-base">Últimos runs</CardTitle></CardHeader>
        <CardContent><DataTable columns={runCols} data={runs} /></CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader><CardTitle className="text-base">Últimos batches</CardTitle></CardHeader>
        <CardContent><DataTable columns={batchCols} data={data.batches} /></CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">Logs recentes</CardTitle>
          <Button size="sm" variant="outline">Baixar logs</Button>
        </CardHeader>
        <CardContent>
          <div className="max-h-96 overflow-auto rounded-md border border-border bg-muted/30 p-3 font-mono text-xs">
            {data.logs.map((l, i) => (
              <div key={i} className="flex gap-2 py-0.5">
                <span className="text-muted-foreground">{l.t}</span>
                <span className={l.level === "ok" ? "text-success" : l.level === "err" ? "text-destructive" : "text-primary"}>
                  [{l.level.toUpperCase()}]
                </span>
                <span className="text-foreground">{l.msg}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Dialog open={!!jsonOpen} onOpenChange={(o) => !o && setJsonOpen(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle>Payload JSON</DialogTitle></DialogHeader>
          <pre className="max-h-[60vh] overflow-auto rounded-md border border-border bg-muted/40 p-3 font-mono text-xs">
{jsonOpen ? JSON.stringify(jsonOpen, null, 2) : ""}
          </pre>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
