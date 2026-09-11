import { Link, createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";

import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { BrowserWorkspace } from "@/components/cotasync/BrowserWorkspace";
import { Button } from "@/components/ui/button";
import { getAccessCycle, getExternalSessionStatus, listAccessProfiles, validateAccessCycleManually } from "@/services/api";

export const Route = createFileRoute("/configuracoes/navegador")({
  head: () => ({ meta: [{ title: "Navegador — CotaSync" }] }),
  validateSearch: (search) => ({
    access_profile_id: typeof search.access_profile_id === "string" ? search.access_profile_id : "",
    access_cycle_id: typeof search.access_cycle_id === "string" ? search.access_cycle_id : "",
  }),
  component: BrowserWorkspacePage,
});

function BrowserWorkspacePage() {
  const queryClient = useQueryClient();
  const { access_profile_id: accessProfileId, access_cycle_id: accessCycleId } = Route.useSearch();
  const profiles = useQuery({ queryKey: ["access-profiles"], queryFn: listAccessProfiles, retry: 1 });
  const external = useQuery({
    queryKey: ["external-session"],
    queryFn: getExternalSessionStatus,
    refetchInterval: () => (document.visibilityState === "visible" ? 10000 : false),
    refetchOnWindowFocus: true,
    retry: 1,
  });
  const cycle = useQuery({
    queryKey: ["access-cycle", accessCycleId],
    queryFn: () => getAccessCycle(accessCycleId),
    enabled: Boolean(accessCycleId),
    refetchInterval: () => (document.visibilityState === "visible" ? 2000 : false),
    refetchOnWindowFocus: true,
    retry: 1,
  });
  const profile = profiles.data?.find((item) => item.id === accessProfileId && item.active);
  const systemName = external.data?.external_system_name || "Navegador externo";
  const manualValidation = useMutation({
    mutationFn: () => validateAccessCycleManually(accessCycleId),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["access-cycle", accessCycleId] });
      void queryClient.invalidateQueries({ queryKey: ["access-profiles"] });
      void queryClient.invalidateQueries({ queryKey: ["external-session"] });
      if (result.validated) toast.success("Usuário autenticado e acesso validado.");
      else if (result.status === "validation_requested") toast.info(result.message);
      else toast.warning(result.message || "Finalize a autenticação no navegador antes de validar o acesso.");
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Não foi possível validar o acesso."),
  });
  const canValidateManually = Boolean(
    accessCycleId && cycle.data && cycle.data.access_profile_id === accessProfileId && cycle.data.status !== "ready" &&
      (["starting", "running", "waiting"].includes(cycle.data.status) ||
        ["reauthentication_required", "account_picker_skipped", "access_authentication_not_completed", "access_identity_mismatch"].includes(cycle.data.error_code || "")),
  );
  const boundCycle = cycle.data?.access_profile_id === accessProfileId ? cycle.data : undefined;
  const accessReady = boundCycle?.status === "ready" && boundCycle.stage === "external_system_ready";
  const validating = manualValidation.isPending || Boolean(boundCycle?.manual_validation_pending);

  if (!accessProfileId || profiles.isLoading || !profile) {
    return (
      <main className="grid min-h-dvh place-items-center bg-muted/30 p-6">
        <section className="w-full max-w-md rounded-lg border border-border bg-card p-6 shadow-sm">
          <h1 className="text-base font-semibold">Selecione um perfil de acesso</h1>
          <p className="mt-2 text-sm text-muted-foreground">Abra o navegador pelo botão Autenticar de um perfil ativo em Configurações.</p>
          <Button className="mt-4" asChild><Link to="/configuracoes"><ArrowLeft className="h-4 w-4" /> Voltar para Configurações</Link></Button>
        </section>
      </main>
    );
  }

  return (
    <main className="flex h-dvh flex-col overflow-hidden bg-muted/30">
      <BrowserWorkspace
        accessButtonLabel="Renovar acesso"
        autoOpen
        resizeMode="scale"
        title={`${systemName} · ${profile!.display_name}`}
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
            <BadgeStatus tone={accessReady ? "success" : boundCycle?.error_code ? "warning" : "neutral"}>
              Acesso: {accessReady ? "Validado" : validating ? "Validando" : boundCycle?.status === "waiting" ? "Aguardando autenticação" : "Iniciando"}
            </BadgeStatus>
            <BadgeStatus tone={accessReady ? "success" : "neutral"}>
              Identidade: {accessReady ? "Verificada" : "Não verificada neste ciclo"}
            </BadgeStatus>
          </div>
        }
        actions={canValidateManually ? (
          <Button size="sm" onClick={() => manualValidation.mutate()} disabled={validating}>
            {validating ? "Validando..." : "Validar acesso"}
          </Button>
        ) : undefined}
        footer={<p role="status" className="text-sm">{accessReady ? "Usuário autenticado e acesso validado." : boundCycle?.error_message || "Conclua a autenticação no navegador e depois clique em Validar acesso."}</p>}
      />
    </main>
  );
}
