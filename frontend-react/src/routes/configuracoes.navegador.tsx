import { Link, createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { BrowserWorkspace } from "@/components/cotasync/BrowserWorkspace";
import { Button } from "@/components/ui/button";
import { getExternalSessionStatus, validateExternalSession } from "@/services/api";
import { externalSessionStatusLabel } from "@/lib/status-labels";

export const Route = createFileRoute("/configuracoes/navegador")({
  head: () => ({ meta: [{ title: "Navegador — CotaSync" }] }),
  component: BrowserWorkspacePage,
});

function BrowserWorkspacePage() {
  const queryClient = useQueryClient();
  const external = useQuery({
    queryKey: ["external-session"],
    queryFn: getExternalSessionStatus,
    refetchInterval: 5000,
    retry: 1,
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
  const systemName = external.data?.external_system_name || "Navegador externo";

  return (
    <main className="min-h-screen bg-muted/30 p-2">
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
          <BadgeStatus
            tone={
              external.data?.session_status === "authenticated"
                ? "success"
                : external.data?.external_system_configured
                  ? "warning"
                  : "neutral"
            }
          >
            Sessão: {externalSessionStatusLabel(external.data?.session_status)}
          </BadgeStatus>
        }
        actions={
          <Button
            size="sm"
            variant="outline"
            onClick={() => validate.mutate()}
            disabled={validate.isPending}
          >
            <ShieldCheck className="h-4 w-4" /> Validar sessão
          </Button>
        }
      />
    </main>
  );
}
