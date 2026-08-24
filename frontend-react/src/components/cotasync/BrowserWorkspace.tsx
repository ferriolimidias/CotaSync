import { useMutation, useQuery } from "@tanstack/react-query";
import { Monitor } from "lucide-react";

import { Button } from "@/components/ui/button";
import { createBrowserViewToken, ensureBrowserReady, getBrowserStatus } from "@/services/api";

export function BrowserWorkspace() {
  const status = useQuery({
    queryKey: ["browser"],
    queryFn: getBrowserStatus,
    refetchInterval: 5000,
  });
  const token = useMutation({ mutationFn: createBrowserViewToken });
  const ensure = useMutation({ mutationFn: ensureBrowserReady, onSuccess: () => token.mutate() });
  const viewUrl = token.data?.view_url;

  return (
    <div className="flex min-h-[520px] flex-col overflow-hidden rounded-lg border border-border bg-card">
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
          className="min-h-[520px] flex-1 bg-background"
        />
      ) : (
        <div className="grid min-h-[520px] flex-1 place-items-center bg-muted/30 p-6 text-center">
          <div>
            <p className="text-sm font-medium text-foreground">
              {status.data ? "Navegador pronto para abrir." : "Verificando navegador..."}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              O acesso noVNC é autenticado por token temporário emitido pela API.
            </p>
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
