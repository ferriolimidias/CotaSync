import { Link, Outlet, createFileRoute, useLocation } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ExternalLink, Monitor, ShieldCheck } from "lucide-react";

import { AppShell } from "@/components/cotasync/AppShell";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  getExternalSessionStatus,
  openExternalLogin,
  validateExternalSession,
} from "@/services/api";
import { useAuth } from "@/services/auth";
import { externalSessionStatusLabel, loginModeLabel } from "@/lib/status-labels";

export const Route = createFileRoute("/configuracoes")({
  head: () => ({ meta: [{ title: "Configurações — CotaSync" }] }),
  component: ConfigPage,
});

function ConfigPage() {
  const { user } = useAuth();
  const location = useLocation();
  const queryClient = useQueryClient();
  const external = useQuery({
    queryKey: ["external-session"],
    queryFn: getExternalSessionStatus,
    refetchInterval: 5000,
    retry: 1,
  });
  const openLogin = useMutation({
    mutationFn: openExternalLogin,
    onSuccess: (result) => {
      toast.message("URL de login obtida. Use o navegador ao lado para autenticar manualmente.");
      void queryClient.invalidateQueries({ queryKey: ["external-session"] });
      void queryClient.invalidateQueries({ queryKey: ["browser"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      window.open(result.login_url, "_blank", "noopener,noreferrer");
    },
    onError: (error) =>
      toast.error(
        error instanceof Error ? error.message : "Não foi possível abrir a sessão externa.",
      ),
  });
  const validate = useMutation({
    mutationFn: validateExternalSession,
    onSuccess: (result) => {
      toast.success(result.valid ? "Configuração externa válida." : "Configuração incompleta.");
      void queryClient.invalidateQueries({ queryKey: ["external-session"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível validar a sessão."),
  });

  if (location.pathname === "/configuracoes/navegador") {
    return <Outlet />;
  }

  return (
    <AppShell title="Configurações" subtitle="Conta, sessão do navegador e parâmetros operacionais">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Monitor className="h-4 w-4" />
              Navegador do sistema externo
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <CompactRow label="Browser">
                <BadgeStatus tone="success">Disponível</BadgeStatus>
              </CompactRow>
              <CompactRow label="Sessão">
                <BadgeStatus
                  tone={
                    external.data?.session_status === "authenticated"
                      ? "success"
                      : external.data?.external_system_configured
                        ? "warning"
                        : "neutral"
                  }
                >
                  {externalSessionStatusLabel(external.data?.session_status)}
                </BadgeStatus>
              </CompactRow>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button asChild>
                <Link to="/configuracoes/navegador">
                  <Monitor className="h-4 w-4" /> Abrir navegador
                </Link>
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => openLogin.mutate()}
                disabled={openLogin.isPending}
              >
                <ExternalLink className="h-4 w-4" /> Abrir sessão para login
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => validate.mutate()}
                disabled={validate.isPending}
              >
                <ShieldCheck className="h-4 w-4" /> Validar sessão
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Conta</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <Row label="Usuário" value={user?.username || "-"} />
            <Row label="Perfil" value={user?.role === "admin" ? "Administrador" : "Operador"} />
            <p className="text-xs text-muted-foreground">
              A sessão CotaSync usa cookie HttpOnly. Tokens de sessão não são armazenados no
              navegador.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Sistema externo</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <CompactRow label="Nome">
              <span className="truncate text-right">
                {external.data?.external_system_name || "Não configurado"}
              </span>
            </CompactRow>
            <CompactRow label="Configuração">
              <BadgeStatus tone={external.data?.external_system_configured ? "success" : "warning"}>
                {external.data?.external_system_configured ? "Configurado" : "Não configurado"}
              </BadgeStatus>
            </CompactRow>
            <CompactRow label="Sessão">
              <BadgeStatus
                tone={
                  external.data?.session_status === "authenticated"
                    ? "success"
                    : external.data?.external_system_configured
                      ? "warning"
                      : "neutral"
                }
              >
                {externalSessionStatusLabel(external.data?.session_status)}
              </BadgeStatus>
            </CompactRow>
            <CompactRow label="Login configurado">
              <BadgeStatus tone={external.data?.login_url_configured ? "success" : "warning"}>
                {external.data?.login_url_configured ? "Sim" : "Não"}
              </BadgeStatus>
            </CompactRow>
            <Row
              label="Login"
              value={loginModeLabel(external.data?.login_mode || external.data?.automation)}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Configurações operacionais</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label>Intervalo padrão entre clientes</Label>
                <Input type="number" min={0} defaultValue={3} readOnly />
              </div>
              <div className="grid gap-2">
                <Label>Timeout padrão de ação</Label>
                <Input type="number" min={10} defaultValue={90} readOnly />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Edição persistente desses parâmetros ficará para uma fachada de configurações v1
              posterior.
            </p>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

function CompactRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-10 items-center justify-between gap-3 rounded-md border border-border bg-muted/20 px-3 py-2 text-sm">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <div className="min-w-0 text-foreground">{children}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex min-h-10 items-center justify-between gap-3 rounded-md border border-border bg-muted/20 px-3 py-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 text-right text-foreground">{value}</span>
    </div>
  );
}
