import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Server, Stethoscope, Wifi } from "lucide-react";

import { AppShell } from "@/components/cotasync/AppShell";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { StatusCard } from "@/components/cotasync/StatusCard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getBrowserStatus, getDiagnostics, getWorkerStatus } from "@/services/api";

export const Route = createFileRoute("/diagnostico")({
  head: () => ({ meta: [{ title: "Diagnóstico técnico — CotaSync" }] }),
  component: DiagPage,
});

function DiagPage() {
  const diagnostics = useQuery({
    queryKey: ["diagnostics"],
    queryFn: getDiagnostics,
    refetchInterval: 5000,
    retry: false,
  });
  const worker = useQuery({
    queryKey: ["worker"],
    queryFn: getWorkerStatus,
    refetchInterval: 3000,
  });
  const browser = useQuery({
    queryKey: ["browser"],
    queryFn: getBrowserStatus,
    refetchInterval: 5000,
  });

  return (
    <AppShell
      title="Diagnóstico técnico"
      subtitle="Visão administrativa de API, worker e navegador"
    >
      <div className="grid gap-4 md:grid-cols-3">
        <StatusCard
          label="API"
          value="Online"
          hint="Endpoint v1 respondendo"
          icon={Server}
          tone="success"
        />
        <StatusCard
          label="Worker"
          value={worker.data?.online ? "Online" : "Offline"}
          hint={worker.data?.status || "Sem status"}
          icon={Stethoscope}
          tone={worker.data?.online ? "success" : "warning"}
        />
        <StatusCard
          label="Browser"
          value={browser.data ? "Respondendo" : "Indisponível"}
          hint={browser.data?.browser_mode || "Aguardando status"}
          icon={Wifi}
          tone={browser.data ? "success" : "warning"}
        />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Worker</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <Row
              label="Online"
              value={
                <BadgeStatus tone={worker.data?.online ? "success" : "warning"}>
                  {worker.data?.online ? "Sim" : "Não"}
                </BadgeStatus>
              }
            />
            <Row label="Status" value={worker.data?.status || "-"} />
            <Row label="Heartbeat" value={worker.data?.heartbeat_at || "-"} />
            <Row label="Batch atual" value={worker.data?.current_batch_id || "-"} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Browser</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <Row
              label="Modo"
              value={browser.data?.browser_mode || diagnostics.data?.browser_mode || "-"}
            />
            <Row
              label="CDP alcançável"
              value={String(
                Boolean(
                  browser.data?.desktop_browser?.cdp_reachable ??
                  diagnostics.data?.browser?.cdp_reachable,
                ),
              )}
            />
            <Row
              label="noVNC"
              value={String(
                Boolean(
                  browser.data?.desktop_browser?.view_url ?? diagnostics.data?.browser?.view_url,
                ),
              )}
            />
          </CardContent>
        </Card>
      </div>

      {diagnostics.error && (
        <Card className="mt-4 border-destructive/40">
          <CardContent className="p-4 text-sm text-destructive">
            {diagnostics.error instanceof Error
              ? diagnostics.error.message
              : "Diagnóstico restrito a administradores."}
          </CardContent>
        </Card>
      )}
    </AppShell>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-md border border-border bg-muted/20 px-3 py-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right text-foreground">{value}</span>
    </div>
  );
}
