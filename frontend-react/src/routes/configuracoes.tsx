import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ExternalLink, ShieldCheck } from "lucide-react";

import { AppShell } from "@/components/cotasync/AppShell";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { BrowserWorkspace } from "@/components/cotasync/BrowserWorkspace";
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

export const Route = createFileRoute("/configuracoes")({
  head: () => ({ meta: [{ title: "Configurações — CotaSync" }] }),
  component: ConfigPage,
});

function ConfigPage() {
  const { user } = useAuth();
  const external = useQuery({
    queryKey: ["external-session"],
    queryFn: getExternalSessionStatus,
    refetchInterval: 5000,
  });
  const openLogin = useMutation({
    mutationFn: openExternalLogin,
    onSuccess: (result) => {
      toast.message("URL de login obtida. Use o navegador ao lado para autenticar manualmente.");
      window.open(result.login_url, "_blank", "noopener,noreferrer");
    },
    onError: (error) =>
      toast.error(
        error instanceof Error ? error.message : "Não foi possível abrir a sessão externa.",
      ),
  });
  const validate = useMutation({
    mutationFn: validateExternalSession,
    onSuccess: (result) =>
      toast.success(result.valid ? "Configuração de sessão válida." : "Configuração incompleta."),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível validar a sessão."),
  });

  return (
    <AppShell title="Configurações" subtitle="Conta, sessão do navegador e parâmetros operacionais">
      <div className="grid gap-4 xl:grid-cols-[420px_1fr]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
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
            <CardHeader>
              <CardTitle className="text-base">Sistema externo</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-2">
                <Label>Nome</Label>
                <Input value={external.data?.external_system_name || ""} readOnly />
              </div>
              <div className="flex items-center justify-between rounded-md border border-border p-3">
                <span className="text-sm text-muted-foreground">Login configurado</span>
                <BadgeStatus tone={external.data?.login_url_configured ? "success" : "warning"}>
                  {external.data?.login_url_configured ? "Sim" : "Não"}
                </BadgeStatus>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => openLogin.mutate()} disabled={openLogin.isPending}>
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
              <p className="text-xs text-muted-foreground">
                Login, senha e MFA continuam manuais. O CotaSync não automatiza credenciais.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Configurações operacionais</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-2">
                <Label>Intervalo padrão entre clientes</Label>
                <Input type="number" min={0} defaultValue={3} readOnly />
              </div>
              <div className="grid gap-2">
                <Label>Timeout padrão de ação</Label>
                <Input type="number" min={10} defaultValue={90} readOnly />
              </div>
              <p className="text-xs text-muted-foreground">
                Edição persistente desses parâmetros ficará para uma fachada de configurações v1
                posterior.
              </p>
            </CardContent>
          </Card>
        </div>

        <BrowserWorkspace />
      </div>
    </AppShell>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-border bg-muted/20 px-3 py-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-foreground">{value}</span>
    </div>
  );
}
