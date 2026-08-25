import { Outlet, createFileRoute, useLocation, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ExternalLink, Save, ShieldCheck } from "lucide-react";

import { AppShell } from "@/components/cotasync/AppShell";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  getExternalSessionStatus,
  getExternalSystemConfig,
  openExternalLogin,
  saveExternalSystemConfig,
  validateExternalSession,
} from "@/services/api";
import { useAuth } from "@/services/auth";
import { externalSessionStatusLabel, loginModeLabel } from "@/lib/status-labels";
import type { ExternalSystemConfig } from "@/types/api";

export const Route = createFileRoute("/configuracoes")({
  head: () => ({ meta: [{ title: "Configurações — CotaSync" }] }),
  component: ConfigPage,
});

function ConfigPage() {
  const { user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<ExternalSystemConfig>({
    external_system_name: "",
    external_login_url: "",
    access_profile_email_or_identifier: "",
    expected_system_host: "",
  });
  const external = useQuery({
    queryKey: ["external-session"],
    queryFn: getExternalSessionStatus,
    refetchInterval: 5000,
    retry: 1,
  });
  const externalConfig = useQuery({
    queryKey: ["external-system-config"],
    queryFn: getExternalSystemConfig,
    retry: 1,
  });
  const saveConfig = useMutation({
    mutationFn: saveExternalSystemConfig,
    onSuccess: (saved) => {
      setForm(saved);
      toast.success("Configuração do sistema externo salva.");
      void queryClient.invalidateQueries({ queryKey: ["external-system-config"] });
      void queryClient.invalidateQueries({ queryKey: ["external-session"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) =>
      toast.error(
        error instanceof Error ? error.message : "Não foi possível salvar a configuração.",
      ),
  });
  const openLogin = useMutation({
    mutationFn: openExternalLogin,
    onSuccess: (result) => {
      toast.message("Navegador aberto na URL de login configurada.");
      void queryClient.invalidateQueries({ queryKey: ["external-session"] });
      void queryClient.invalidateQueries({ queryKey: ["browser"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void navigate({ to: "/configuracoes/navegador" });
      void result;
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

  useEffect(() => {
    if (externalConfig.data) {
      setForm({
        external_system_name: externalConfig.data.external_system_name || "",
        external_login_url: externalConfig.data.external_login_url || "",
        access_profile_email_or_identifier:
          externalConfig.data.access_profile_email_or_identifier || "",
        expected_system_host: externalConfig.data.expected_system_host || "",
      });
    }
  }, [externalConfig.data]);

  function updateForm(key: keyof ExternalSystemConfig, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  const loginConfigured = Boolean(form.external_login_url.trim());

  if (location.pathname === "/configuracoes/navegador") {
    return <Outlet />;
  }

  return (
    <AppShell title="Configurações" subtitle="Conta, sessão do navegador e parâmetros operacionais">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card className="xl:col-start-2 xl:row-start-1">
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

        <Card className="xl:col-start-1 xl:row-span-2 xl:row-start-1">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Sistema externo</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3">
              <div className="grid gap-2">
                <Label htmlFor="external-system-name">Nome do sistema</Label>
                <Input
                  id="external-system-name"
                  value={form.external_system_name}
                  onChange={(event) => updateForm("external_system_name", event.target.value)}
                  placeholder="Sistema Priscila e Jonatan"
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="external-login-url">URL de login</Label>
                <Input
                  id="external-login-url"
                  value={form.external_login_url}
                  onChange={(event) => updateForm("external_login_url", event.target.value)}
                  placeholder="https://..."
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="external-identifier">Usuário / identificador</Label>
                <Input
                  id="external-identifier"
                  value={form.access_profile_email_or_identifier}
                  onChange={(event) =>
                    updateForm("access_profile_email_or_identifier", event.target.value)
                  }
                  placeholder="email, login, matrícula ou identificador"
                />
              </div>
              <details className="rounded-md border border-border bg-muted/20 px-3 py-2">
                <summary className="cursor-pointer text-sm font-medium text-foreground">
                  Configurações avançadas
                </summary>
                <div className="mt-3 grid gap-2">
                  <Label htmlFor="external-expected-host">Host esperado após login</Label>
                  <Input
                    id="external-expected-host"
                    value={form.expected_system_host}
                    onChange={(event) => updateForm("expected_system_host", event.target.value)}
                    placeholder="nwcweb.randonconsorcios.com.br"
                  />
                </div>
              </details>
              <Button
                className="w-full sm:w-fit"
                onClick={() => saveConfig.mutate(form)}
                disabled={saveConfig.isPending}
              >
                <Save className="h-4 w-4" /> Salvar configuração
              </Button>
            </div>

            <div className="space-y-2 border-t border-border pt-4">
              <h3 className="text-xs font-semibold uppercase text-muted-foreground">Status</h3>
              <StatusRow label="Configuração">
                <BadgeStatus
                  tone={external.data?.external_system_configured ? "success" : "warning"}
                >
                  {external.data?.external_system_configured ? "Configurado" : "Não configurado"}
                </BadgeStatus>
              </StatusRow>
              <StatusRow label="Sessão">
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
              </StatusRow>
              <StatusRow label="Login">
                <span className="whitespace-nowrap text-sm text-foreground">
                  {loginModeLabel(external.data?.login_mode || external.data?.automation)}
                </span>
              </StatusRow>
            </div>

            <div className="flex flex-col gap-2 border-t border-border pt-4 sm:flex-row sm:flex-wrap">
              <Button
                className="w-full sm:w-auto"
                onClick={() => openLogin.mutate()}
                disabled={openLogin.isPending || !loginConfigured}
                title={!loginConfigured ? "Salve uma URL de login primeiro." : undefined}
              >
                <ExternalLink className="h-4 w-4" /> Abrir sessão para login
              </Button>
              <Button
                className="w-full sm:w-auto"
                variant="outline"
                onClick={() => validate.mutate()}
                disabled={validate.isPending}
              >
                <ShieldCheck className="h-4 w-4" /> Validar sessão
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-start-2 xl:row-start-2">
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

function StatusRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-10 flex-col gap-1 rounded-md border border-border bg-muted/20 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <div className="min-w-0 sm:text-right">{children}</div>
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
