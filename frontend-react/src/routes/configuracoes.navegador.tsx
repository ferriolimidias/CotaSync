import { Link, createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { BrowserWorkspace } from "@/components/cotasync/BrowserWorkspace";
import { OperatorAssistant } from "@/components/cotasync/OperatorAssistant";
import { Button } from "@/components/ui/button";
import {
  createLearningSession,
  getExternalSessionStatus,
  openExternalLogin,
  validateExternalSession,
} from "@/services/api";
import { externalSessionStatusLabel } from "@/lib/status-labels";

export const Route = createFileRoute("/configuracoes/navegador")({
  head: () => ({ meta: [{ title: "Navegador — CotaSync" }] }),
  component: BrowserWorkspacePage,
});

function BrowserWorkspacePage() {
  const queryClient = useQueryClient();
  const [operatorSessionId, setOperatorSessionId] = useState<string | null>(null);
  const operatorSessionRequested = useRef(false);
  const external = useQuery({
    queryKey: ["external-session"],
    queryFn: getExternalSessionStatus,
    refetchInterval: 5000,
    retry: 1,
  });
  const operatorSession = useMutation({
    mutationFn: createLearningSession,
    onSuccess: (created) => {
      const id = String(created.session_id || created.id || "");
      setOperatorSessionId(id || null);
      if (id) toast.message("Assistente do operador pronto.");
    },
    onError: (error) =>
      toast.error(
        error instanceof Error ? error.message : "Não foi possível preparar o assistente.",
      ),
  });
  const openLogin = useMutation({
    mutationFn: openExternalLogin,
    onSuccess: (result) => {
      toast.message("URL de login obtida. Use o navegador para autenticar manualmente.");
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
  const prepareOperatorSession = operatorSession.mutate;

  useEffect(() => {
    if (!operatorSessionRequested.current) {
      operatorSessionRequested.current = true;
      prepareOperatorSession();
    }
  }, [prepareOperatorSession]);

  return (
    <main className="min-h-screen bg-muted/30 p-2">
      <BrowserWorkspace
        resizeMode="remote"
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
          <>
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
          </>
        }
        footer={
          <OperatorAssistant
            collapsible
            mode="operation"
            sessionId={operatorSessionId}
            statusText={
              operatorSession.isPending
                ? "Preparando controles..."
                : operatorSessionId
                  ? "Controles prontos"
                  : "Controles indisponíveis"
            }
            variant="dock"
          />
        }
      />
    </main>
  );
}
