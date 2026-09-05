import { Link, Outlet, createFileRoute, useLocation, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Check, Copy, ExternalLink, FileKey2, KeyRound, Save, ShieldCheck, Trash2 } from "lucide-react";

import { AppShell } from "@/components/cotasync/AppShell";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  getExternalSessionStatus,
  getExternalSystemConfig,
  openExternalLogin,
  saveExternalSystemConfig,
  validateExternalSession,
  getLearningAISettings,
  removeLearningAIKey,
  saveLearningAISettings,
  testLearningAI,
  getGoogleSheetsSettings,
  saveGoogleSheetsCredential,
  removeGoogleSheetsCredential,
  testGoogleSheetsCredential,
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
  const [aiForm, setAiForm] = useState({ enabled: false, provider: "openai_compatible", model: "gpt-4o-mini", base_url: "", api_key: "" });
  const [googleCredential, setGoogleCredential] = useState<File | null>(null);
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
  const aiSettings = useQuery({ queryKey: ["learning-ai-settings"], queryFn: getLearningAISettings, retry: 1, enabled: user?.role === "admin" });
  const googleSettings = useQuery({ queryKey: ["google-sheets-settings"], queryFn: getGoogleSheetsSettings, retry: 1, enabled: user?.role === "admin" });
  const saveAI = useMutation({
    mutationFn: saveLearningAISettings,
    onSuccess: (saved) => { setAiForm((current) => ({ ...current, ...saved, api_key: "" })); toast.success("Configuração da IA salva."); void queryClient.invalidateQueries({ queryKey: ["learning-ai-settings"] }); },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Não foi possível salvar a IA."),
  });
  const removeAIKey = useMutation({
    mutationFn: removeLearningAIKey,
    onSuccess: (saved) => { setAiForm((current) => ({ ...current, ...saved, api_key: "" })); toast.success("Chave removida."); void queryClient.invalidateQueries({ queryKey: ["learning-ai-settings"] }); },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Não foi possível remover a chave."),
  });
  const testAI = useMutation({ mutationFn: testLearningAI, onSuccess: () => toast.success("Conexão funcionando"), onError: (error) => toast.error(error instanceof Error ? error.message : "Não foi possível testar a IA.") });
  const saveGoogle = useMutation({
    mutationFn: async () => {
      if (!googleCredential) throw new Error("Selecione um arquivo JSON.");
      if (!googleCredential.name.toLowerCase().endsWith(".json")) throw new Error("Selecione um arquivo .json.");
      return saveGoogleSheetsCredential(await googleCredential.text());
    },
    onSuccess: (saved) => { setGoogleCredential(null); toast.success("Credencial Google configurada."); void queryClient.invalidateQueries({ queryKey: ["google-sheets-settings"] }); void saved; },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Não foi possível configurar o Google Sheets."),
  });
  const removeGoogle = useMutation({ mutationFn: removeGoogleSheetsCredential, onSuccess: () => { toast.success("Credencial Google removida."); void queryClient.invalidateQueries({ queryKey: ["google-sheets-settings"] }); }, onError: (error) => toast.error(error instanceof Error ? error.message : "Não foi possível remover a credencial Google.") });
  const testGoogle = useMutation({ mutationFn: testGoogleSheetsCredential, onSuccess: () => { toast.success("Credencial Google válida."); void queryClient.invalidateQueries({ queryKey: ["google-sheets-settings"] }); }, onError: (error) => toast.error(error instanceof Error ? error.message : "Falha ao autenticar com Google.") });
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
    mutationFn: (force: boolean) => openExternalLogin(force),
    onSuccess: (result) => {
      toast.message(
        result.status === "already_connected"
          ? "A sessão externa já está conectada."
          : "Navegador aberto na URL de login configurada.",
      );
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

  useEffect(() => {
    if (aiSettings.data) setAiForm((current) => ({ ...current, ...aiSettings.data, api_key: "" }));
  }, [aiSettings.data]);

  function updateForm(key: keyof ExternalSystemConfig, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  const loginConfigured = Boolean(form.external_login_url.trim());
  const sessionStatus = external.data?.session_status;

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

        {user?.role === "admin" && (
          <Card className="xl:col-start-2 xl:row-start-2">
            <CardHeader className="pb-3"><CardTitle className="text-base">IA do aprendizado</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between gap-4 rounded-md border border-border bg-muted/20 px-3 py-3">
                <div><Label htmlFor="learning-ai-enabled">Usar IA para aprimorar o aprendizado</Label><p className="mt-1 text-xs text-muted-foreground">A IA analisa ações durante o ensino. Execuções automáticas não utilizam IA.</p></div>
                <Switch id="learning-ai-enabled" checked={aiForm.enabled} onCheckedChange={(enabled) => setAiForm((current) => ({ ...current, enabled }))} />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="grid gap-2"><Label htmlFor="learning-ai-provider">Provider</Label><select id="learning-ai-provider" className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={aiForm.provider} onChange={(event) => setAiForm((current) => ({ ...current, provider: event.target.value }))}><option value="openai_compatible">OpenAI-compatible</option><option value="openai">OpenAI</option></select></div>
                <div className="grid gap-2"><Label htmlFor="learning-ai-model">Modelo</Label><Input id="learning-ai-model" value={aiForm.model} onChange={(event) => setAiForm((current) => ({ ...current, model: event.target.value }))} /></div>
              </div>
              <div className="grid gap-2"><Label htmlFor="learning-ai-key">API Key</Label><div className="flex gap-2"><Input id="learning-ai-key" type="password" autoComplete="new-password" placeholder={aiSettings.data?.api_key_configured ? "Chave configurada; digite para substituir" : "Cole a chave da API"} value={aiForm.api_key} onChange={(event) => setAiForm((current) => ({ ...current, api_key: event.target.value }))} /><Button type="button" variant="outline" title="Remover chave" aria-label="Remover chave" disabled={!aiSettings.data?.api_key_configured || removeAIKey.isPending} onClick={() => removeAIKey.mutate()}><Trash2 className="h-4 w-4" /></Button></div>{aiSettings.data?.api_key_configured && <p className="flex items-center gap-1 text-xs text-emerald-700"><Check className="h-3 w-3" /> Chave configurada ({aiSettings.data.api_key_source === "stored" ? "painel" : "ambiente"})</p>}</div>
              <div className="grid gap-2"><Label htmlFor="learning-ai-base-url">Base URL <span className="font-normal text-muted-foreground">(opcional)</span></Label><Input id="learning-ai-base-url" type="url" placeholder="https://api.openai.com/v1" value={aiForm.base_url} onChange={(event) => setAiForm((current) => ({ ...current, base_url: event.target.value }))} /></div>
              <div className="flex flex-col gap-2 sm:flex-row"><Button type="button" variant="outline" onClick={() => testAI.mutate()} disabled={testAI.isPending || !aiSettings.data?.api_key_configured}><KeyRound className="h-4 w-4" /> Testar IA</Button><Button type="button" onClick={() => saveAI.mutate({ enabled: aiForm.enabled, provider: aiForm.provider, model: aiForm.model, base_url: aiForm.base_url, ...(aiForm.api_key.trim() ? { api_key: aiForm.api_key } : {}) })} disabled={saveAI.isPending}><Save className="h-4 w-4" /> Salvar configurações</Button></div>
            </CardContent>
          </Card>
        )}

        {user?.role === "admin" && (
          <Card className="xl:col-start-2 xl:row-start-3">
            <CardHeader className="pb-3"><CardTitle className="text-base">Google Sheets</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <p className="text-xs text-muted-foreground">Conecte o CotaSync às planilhas compartilhadas com a conta de serviço. A chave fica criptografada somente no backend.</p>
              <StatusRow label="Status">
                <BadgeStatus tone={googleSettings.data?.configured ? "success" : "warning"}>{googleSettings.data?.configured ? "Configurado" : "Não configurado"}</BadgeStatus>
              </StatusRow>
              {googleSettings.data?.configured && <>
                <StatusRow label="Conta de serviço"><span className="break-all text-sm text-foreground">{googleSettings.data.client_email}</span></StatusRow>
                <StatusRow label="Projeto"><span className="text-sm text-foreground">{googleSettings.data.project_id || "-"}</span></StatusRow>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="outline" size="sm" onClick={() => googleSettings.data?.client_email && navigator.clipboard.writeText(googleSettings.data.client_email).then(() => toast.success("E-mail copiado."))}><Copy className="h-4 w-4" /> Copiar e-mail</Button>
                  <Button type="button" variant="outline" size="sm" onClick={() => testGoogle.mutate()} disabled={testGoogle.isPending}><ShieldCheck className="h-4 w-4" /> Testar conexão</Button>
                </div>
              </>}
              <div className="grid gap-2">
                <Label htmlFor="google-service-account-json">{googleSettings.data?.configured ? "Substituir credencial" : "Selecionar arquivo JSON"}</Label>
                <Input id="google-service-account-json" type="file" accept="application/json,.json" onChange={(event) => setGoogleCredential(event.target.files?.[0] || null)} />
                <p className="text-xs text-muted-foreground">Compartilhe depois a planilha como Editor com o e-mail exibido acima.</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" onClick={() => saveGoogle.mutate()} disabled={!googleCredential || saveGoogle.isPending}><FileKey2 className="h-4 w-4" /> {googleSettings.data?.configured ? "Substituir credencial" : "Configurar Google Sheets"}</Button>
                {googleSettings.data?.configured && <Button type="button" variant="outline" onClick={() => { if (window.confirm("Remover a credencial Google? As planilhas e clientes não serão apagados.")) removeGoogle.mutate(); }} disabled={removeGoogle.isPending}><Trash2 className="h-4 w-4" /> Remover credencial</Button>}
              </div>
            </CardContent>
          </Card>
        )}

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
                  placeholder="Nome do sistema externo"
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
                    placeholder="sistema.exemplo.com.br"
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
              <Button className="w-full sm:w-auto" asChild>
                <Link to="/configuracoes/navegador">
                  <ExternalLink className="h-4 w-4" /> Abrir navegador
                </Link>
              </Button>
              <Button
                className="w-full sm:w-auto"
                variant="outline"
                onClick={() => openLogin.mutate(true)}
                disabled={openLogin.isPending || !loginConfigured}
                title={!loginConfigured ? "Salve uma URL de login primeiro." : undefined}
              >
                <ShieldCheck className="h-4 w-4" />
                {sessionStatus === "authenticated" ? "Reiniciar login" : "Iniciar login"}
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

        <Card className="xl:col-start-2 xl:row-start-4">
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
