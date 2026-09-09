import { Link, createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { BrowserWorkspace } from "@/components/cotasync/BrowserWorkspace";
import { Button } from "@/components/ui/button";
import { getExternalSessionStatus, validateExternalSession } from "@/services/api";

export const Route = createFileRoute("/configuracoes/navegador")({
  head: () => ({ meta: [{ title: "Navegador — CotaSync" }] }),
  component: BrowserWorkspacePage,
});

function BrowserWorkspacePage() {
  const queryClient = useQueryClient();
  const external = useQuery({
    queryKey: ["external-session"],
    queryFn: getExternalSessionStatus,
    refetchInterval: () => (document.visibilityState === "visible" ? 10000 : false),
    refetchOnWindowFocus: true,
    retry: 1,
  });
  const validate = useMutation({
    mutationFn: validateExternalSession,
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["access-profiles"] });
      if (result.external_session) queryClient.setQueryData(["external-session"], result.external_session);
      toast.success(result.external_session?.microsoft_status === "available" ? "Acessos verificados. Microsoft disponível." : result.configuration_valid ? "Configuração verificada; o acesso Microsoft precisa de atenção." : `Configuração incompleta: ${(result.configuration?.missing_fields || []).join(", ") || "verifique os campos técnicos."}.`);
      void queryClient.invalidateQueries({ queryKey: ["external-session"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível validar a sessão."),
  });
  const systemName = external.data?.external_system_name || "Navegador externo";

  return (
    <main className="flex h-dvh flex-col overflow-hidden bg-muted/30">
      <BrowserWorkspace
        accessButtonLabel="Renovar acesso"
        autoOpen
        resizeMode="scale"
        title={systemName}
        variant="workspace"
        leading={
          <Button size="sm" variant="ghost" asChild>
            <Link to="/configuracoes">
              <ArrowLeft className="h-4 w-4" /> Voltar
            </Link>
          </Button>
        }
        sessionStatus={
          <div className="flex flex-wrap items-center gap-2">
            <BadgeStatus tone={external.data?.microsoft_status === "available" ? "success" : external.data?.microsoft_status === "reauth_required" ? "warning" : "neutral"}>
              Microsoft: {external.data?.microsoft_status === "available" ? `${external.data?.available_profile_count ?? external.data?.access_profile_count ?? 0}${external.data?.access_profile_count && (external.data.available_profile_count ?? external.data.access_profile_count) < external.data.access_profile_count ? ` de ${external.data.access_profile_count}` : ""} perfil(is) disponível(is)` : external.data?.microsoft_status === "reauth_required" ? "Reautenticação necessária" : external.data?.microsoft_status === "account_picker" ? "Aguardando seleção" : "Não verificado"}
            </BadgeStatus>
            <BadgeStatus tone={external.data?.external_system_status === "inside" ? "success" : "neutral"}>
              Sistema: {external.data?.external_system_status === "inside" ? "Dentro" : "Fora do sistema"}
            </BadgeStatus>
          </div>
        }
        actions={
          <Button
            size="sm"
            variant="outline"
            onClick={() => validate.mutate()}
            disabled={validate.isPending}
          >
            <ShieldCheck className="h-4 w-4" /> Verificar acessos
          </Button>
        }
      />
    </main>
  );
}
