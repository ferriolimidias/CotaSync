import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Monitor } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { createBrowserViewToken, ensureBrowserReady, getBrowserStatus } from "@/services/api";

export function BrowserWorkspace() {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ["browser"],
    queryFn: getBrowserStatus,
    refetchInterval: 5000,
    retry: 1,
  });
  const token = useMutation({
    mutationFn: createBrowserViewToken,
    onSuccess: () => toast.success("Navegador disponível."),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível abrir o navegador."),
  });
  const ensure = useMutation({
    mutationFn: ensureBrowserReady,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["browser"] });
      token.mutate();
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Navegador indisponível."),
  });
  const viewUrl = token.data?.view_url;
  const health = status.data?.desktop_browser;
  const browserReady = Boolean(health?.cdp_reachable);
  const browserRunning = Boolean(health?.running);
  const state = browserState({
    hasViewUrl: Boolean(viewUrl),
    isLoading: status.isLoading,
    isFetching: status.isFetching,
    isOpening: ensure.isPending || token.isPending,
    hasError: Boolean(status.error || ensure.error || token.error),
    browserReady,
    browserRunning,
  });

  return (
    <div className="flex min-h-[min(680px,calc(100vh-9rem))] flex-col overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Monitor className="h-4 w-4" />
          Navegador do sistema externo
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => ensure.mutate()}
          disabled={ensure.isPending || token.isPending}
        >
          {viewUrl ? "Renovar acesso" : "Abrir navegador"}
        </Button>
      </div>
      {viewUrl ? (
        <iframe
          title="Navegador CotaSync"
          src={viewUrl}
          className="min-h-[min(620px,calc(100vh-12rem))] flex-1 bg-background"
        />
      ) : (
        <div className="grid min-h-[min(620px,calc(100vh-12rem))] flex-1 place-items-center bg-muted/30 p-6 text-center">
          <div>
            <p className="text-sm font-medium text-foreground">{state.title}</p>
            <p className="mt-1 text-xs text-muted-foreground">{state.description}</p>
          </div>
        </div>
      )}
      {(status.error || ensure.error || token.error) && (
        <div className="border-t border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {(status.error || ensure.error || token.error) instanceof Error
            ? (status.error || ensure.error || (token.error as Error)).message
            : "Navegador indisponível."}
        </div>
      )}
    </div>
  );
}

function browserState(input: {
  hasViewUrl: boolean;
  isLoading: boolean;
  isFetching: boolean;
  isOpening: boolean;
  hasError: boolean;
  browserReady: boolean;
  browserRunning: boolean;
}) {
  if (input.hasViewUrl) {
    return {
      title: "Navegador aberto.",
      description: "Acesso noVNC autenticado por token temporário.",
    };
  }
  if (input.isOpening) {
    return {
      title: "Abrindo navegador...",
      description: "Validando o processo do browser e emitindo acesso.",
    };
  }
  if (input.hasError) {
    return {
      title: "Erro ao verificar navegador.",
      description: "Tente novamente ou abra o diagnóstico técnico.",
    };
  }
  if (input.isLoading) {
    return {
      title: "Verificando navegador...",
      description: "Consultando o status do browser persistente.",
    };
  }
  if (!input.browserRunning) {
    return {
      title: "Navegador offline.",
      description: "O processo do browser persistente não respondeu.",
    };
  }
  if (!input.browserReady) {
    return {
      title: "Navegador indisponível.",
      description: "O processo existe, mas o canal de controle não respondeu.",
    };
  }
  return {
    title: input.isFetching
      ? "Navegador pronto. Atualizando status..."
      : "Navegador pronto para abrir.",
    description: "O acesso noVNC é autenticado por token temporário emitido pela API.",
  };
}
