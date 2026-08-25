import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Maximize2, Minimize2, Monitor } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { Button } from "@/components/ui/button";
import { createBrowserViewToken, ensureBrowserReady, getBrowserStatus } from "@/services/api";

export function BrowserWorkspace({
  actions,
  leading,
  resizeMode = "scale",
  sessionStatus,
  variant = "embedded",
}: {
  actions?: React.ReactNode;
  leading?: React.ReactNode;
  resizeMode?: "scale" | "remote";
  sessionStatus?: React.ReactNode;
  variant?: "embedded" | "workspace";
}) {
  const queryClient = useQueryClient();
  const rootRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
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
  const iframeUrl = useMemo(() => withResizeMode(viewUrl, resizeMode), [resizeMode, viewUrl]);
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
  const workspaceMode = variant === "workspace";

  useEffect(() => {
    const updateFullscreen = () => setIsFullscreen(document.fullscreenElement === rootRef.current);
    document.addEventListener("fullscreenchange", updateFullscreen);
    return () => document.removeEventListener("fullscreenchange", updateFullscreen);
  }, []);

  async function toggleFullscreen() {
    if (!rootRef.current) return;
    if (document.fullscreenElement === rootRef.current) {
      await document.exitFullscreen();
      return;
    }
    await rootRef.current.requestFullscreen();
  }

  return (
    <div
      ref={rootRef}
      className={
        workspaceMode
          ? "flex h-[calc(100vh-1rem)] min-h-[720px] flex-col overflow-hidden rounded-lg border border-border bg-card shadow-sm fullscreen:h-screen fullscreen:min-h-screen fullscreen:rounded-none fullscreen:border-0"
          : "flex min-h-[700px] flex-col overflow-hidden rounded-lg border border-border bg-card lg:min-h-[75vh]"
      }
    >
      <div
        className={
          workspaceMode
            ? "flex min-h-12 flex-wrap items-center gap-2 border-b border-border bg-background/95 px-3 py-2 fullscreen:absolute fullscreen:left-3 fullscreen:right-3 fullscreen:top-3 fullscreen:z-10 fullscreen:rounded-md fullscreen:border fullscreen:bg-background/90 fullscreen:shadow-sm fullscreen:backdrop-blur"
            : "flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2"
        }
      >
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          {leading}
          <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
            <Monitor className="h-4 w-4 shrink-0" />
            <span className="truncate">Navegador do sistema externo</span>
          </div>
          {workspaceMode && (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <BadgeStatus tone={browserReady ? "success" : browserRunning ? "warning" : "neutral"}>
                Browser: {browserReady ? "Pronto" : browserRunning ? "Indisponível" : "Offline"}
              </BadgeStatus>
              {sessionStatus}
            </div>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {actions}
          <Button size="sm" variant="outline" onClick={() => void toggleFullscreen()}>
            {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            {isFullscreen ? "Sair da tela cheia" : "Tela cheia"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => ensure.mutate()}
            disabled={ensure.isPending || token.isPending}
          >
            {viewUrl ? "Renovar acesso" : "Abrir navegador"}
          </Button>
        </div>
      </div>
      {iframeUrl ? (
        <iframe
          title="Navegador CotaSync"
          src={iframeUrl}
          className={
            workspaceMode
              ? "h-full min-h-0 w-full flex-1 bg-background"
              : "min-h-[640px] flex-1 bg-background lg:min-h-[calc(75vh-3rem)]"
          }
        />
      ) : (
        <div
          className={
            workspaceMode
              ? "grid min-h-0 flex-1 place-items-center bg-muted/30 p-6 text-center"
              : "grid min-h-[640px] flex-1 place-items-center bg-muted/30 p-6 text-center lg:min-h-[calc(75vh-3rem)]"
          }
        >
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

function withResizeMode(viewUrl: string | undefined, resizeMode: "scale" | "remote") {
  if (!viewUrl) return undefined;
  const parsed = new URL(viewUrl);
  parsed.searchParams.set("resize", resizeMode);
  return parsed.toString();
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
