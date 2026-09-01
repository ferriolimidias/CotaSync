export function runStatusLabel(status: string) {
  return (
    (
      { success: "Concluído", error: "Erro", running: "Executando", pending: "Na fila", needs_attention: "Aguardando atenção" } as Record<
        string,
        string
      >
    )[status] || status
  );
}

export function batchStatusLabel(status: string) {
  return (
    (
      {
        queued: "Na fila",
        running: "Executando",
        cancel_requested: "Cancelamento solicitado",
        completed: "Concluído",
        completed_with_errors: "Concluído com erros",
        cancelled: "Cancelado",
        interrupted: "Interrompido",
        needs_attention: "Aguardando atenção",
        error: "Erro",
        success: "Concluído",
      } as Record<string, string>
    )[status] || status
  );
}

export function workerStatusLabel(status?: string | null) {
  if (!status) return "Sem status";
  return (
    (
      { idle: "Ocioso", running: "Executando", stopped: "Parado", offline: "Offline" } as Record<
        string,
        string
      >
    )[status] || status
  );
}

export function externalSessionStatusLabel(status?: string | null) {
  if (!status) return "Não verificada";
  return (
    (
      {
        authenticated: "Conectada",
        authenticated_system: "Conectada",
        unauthenticated: "Não conectada",
        expired: "Sessão expirada",
        browser_offline: "Navegador offline",
        not_configured: "Não configurada",
        unknown: "Não verificada",
      } as Record<string, string>
    )[status] || status
  );
}

export function loginModeLabel(mode?: string | null) {
  return (
    (
      { manual: "Autenticação manual", manual_operator: "Autenticação manual" } as Record<
        string,
        string
      >
    )[String(mode || "")] || "Autenticação manual"
  );
}

export function actionIsExecutable(action: {
  steps_count?: number;
  has_url?: boolean;
  legacy_unconfigured?: boolean;
}) {
  return Boolean((action.steps_count ?? 0) > 0 && action.has_url && !action.legacy_unconfigured);
}
