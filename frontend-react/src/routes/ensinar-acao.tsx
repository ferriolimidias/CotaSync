import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Check, CircleDot, Crosshair, Play, Save, Square, X } from "lucide-react";

import { AppShell } from "@/components/cotasync/AppShell";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { BrowserWorkspace } from "@/components/cotasync/BrowserWorkspace";
import { OperatorAssistant } from "@/components/cotasync/OperatorAssistant";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  ApiError,
  createLearningSession,
  cancelLearningResultSelection,
  captureLearningResultSelection,
  confirmLearningResultSelection,
  getLearningSession,
  saveLearnedAction,
  startLearningRecording,
  startLearningResultSelection,
  stopLearningRecording,
} from "@/services/api";
import type { ResultSelectionCandidate } from "@/types/api";

export const Route = createFileRoute("/ensinar-acao")({
  head: () => ({ meta: [{ title: "Ensinar ação — CotaSync" }] }),
  component: EnsinarPage,
});

function EnsinarPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [expected, setExpected] = useState("");
  const [stopped, setStopped] = useState(false);
  const [selectionMode, setSelectionMode] = useState<"idle" | "selecting" | "preview">("idle");
  const [selectionCandidate, setSelectionCandidate] = useState<ResultSelectionCandidate | null>(null);
  const [resultConfirmed, setResultConfirmed] = useState(false);
  const [normalization, setNormalization] = useState<"exact_text" | "digits_only">("exact_text");
  const session = useQuery({
    queryKey: ["learning-session", sessionId],
    queryFn: () => getLearningSession(sessionId as string),
    enabled: Boolean(sessionId),
    refetchInterval: stopped ? false : 2500,
  });

  const create = useMutation({
    mutationFn: createLearningSession,
    onSuccess: async (created) => {
      const id = String(created.session_id || created.id || "");
      setSessionId(id);
      await start.mutateAsync(id);
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível iniciar o ensino."),
  });
  const start = useMutation({
    mutationFn: (id: string) =>
      startLearningRecording(id, { name, objective, expected_result: expected }),
    onSuccess: () => toast.success("Gravação iniciada."),
  });
  const stop = useMutation({
    mutationFn: () => stopLearningRecording(sessionId as string),
    onSuccess: () => {
      setStopped(true);
      toast.message("Gravação finalizada. Revise e publique a ação.");
    },
  });
  const publish = useMutation({
    mutationFn: () =>
      saveLearnedAction(sessionId as string, {
        name,
        description: objective,
        objective,
        expected_result: expected,
        variable_names: {
          grupo: "Grupo",
          cota: "Cota",
          versao: "Versão",
        },
      }),
    onSuccess: () => toast.success("Ação publicada."),
    onError: (error) => {
      if (error instanceof ApiError && error.status === 422) {
        toast.error("Não foi possível publicar a versão: resultado da ação incompleto.");
        return;
      }
      toast.error(error instanceof Error ? error.message : "Não foi possível publicar a ação.");
    },
  });
  const targetName = useMemo(
    () => expected.trim() || objective.trim() || name.trim() || "resultado",
    [expected, name, objective],
  );
  const hasConfirmedContract = hasContract(session.data?.extraction_review);
  const screenLabel = useMemo(() => contextText(selectionCandidate), [selectionCandidate]);
  const resultValue = useMemo(() => candidateValue(selectionCandidate), [selectionCandidate]);
  const displayValue =
    normalization === "digits_only" ? digitsOnlyPreview(resultValue) || resultValue : resultValue;
  const startSelection = useMutation({
    mutationFn: () => startLearningResultSelection(sessionId as string),
    onSuccess: () => {
      setSelectionCandidate(null);
      setSelectionMode("selecting");
      setResultConfirmed(false);
      toast.message("Clique no campo que deseja capturar no navegador.");
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível iniciar a seleção."),
  });
  const captureSelection = useMutation({
    mutationFn: () =>
      captureLearningResultSelection(sessionId as string, {
        target_name: targetName,
        screen_label: screenLabel,
      }),
    onSuccess: (result) => {
      if (result.status === "blocked") {
        toast.error(result.message || "Campos de senha não podem ser usados como resultado.");
        setSelectionMode("idle");
        return;
      }
      if (result.status === "cancelled") {
        setSelectionMode("idle");
        return;
      }
      const candidate = Array.isArray(result.candidates) ? result.candidates[0] : null;
      if (candidate) {
        setSelectionCandidate(candidate);
        const value = candidateValue(candidate);
        setNormalization(/^\d+$/.test(value) ? "digits_only" : "exact_text");
        setSelectionMode("preview");
      }
    },
  });
  const confirmSelection = useMutation({
    mutationFn: () =>
      confirmLearningResultSelection(sessionId as string, {
        target_name: targetName,
        screen_label: screenLabel || targetName,
        selection_type: String(selectionCandidate?.type || selectionCandidate?.candidate_type || "field_value"),
        candidate: selectionCandidate as ResultSelectionCandidate,
        normalization,
      }),
    onSuccess: () => {
      setResultConfirmed(true);
      setSelectionMode("idle");
      void session.refetch();
      toast.success("Resultado selecionado.");
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível confirmar o resultado."),
  });
  const cancelSelection = useMutation({
    mutationFn: () => cancelLearningResultSelection(sessionId as string),
    onSuccess: () => {
      setSelectionMode("idle");
      setSelectionCandidate(null);
    },
  });

  useEffect(() => {
    if (selectionMode !== "selecting" || !sessionId) return;
    const timer = window.setInterval(() => {
      if (!captureSelection.isPending) captureSelection.mutate();
    }, 900);
    return () => window.clearInterval(timer);
  }, [captureSelection, selectionMode, sessionId]);

  const eventCount = Number(session.data?.learning_events_count || 0);
  const variableCount = Array.isArray(session.data?.variables) ? session.data.variables.length : 3;

  return (
    <AppShell
      title="Ensinar ação"
      subtitle="Grave um fluxo no navegador remoto"
    >
      <div className="grid gap-4 xl:grid-cols-[360px_1fr_280px]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Dados da ação</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-2">
              <Label>Nome</Label>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Quantidade de parcelas"
              />
            </div>
            <div className="grid gap-2">
              <Label>Objetivo</Label>
              <Textarea
                rows={3}
                value={objective}
                onChange={(event) => setObjective(event.target.value)}
                placeholder="Consultar quantas parcelas o cliente já pagou."
              />
            </div>
            <div className="grid gap-2">
              <Label>Resultado esperado</Label>
              <Textarea
                rows={3}
                value={expected}
                onChange={(event) => setExpected(event.target.value)}
                placeholder="A quantidade de parcelas pagas."
              />
            </div>
            {!sessionId ? (
              <Button
                className="w-full"
                disabled={!name || create.isPending}
                onClick={() => create.mutate()}
              >
                <Play className="h-4 w-4" /> Começar ensino
              </Button>
            ) : (
              <div className="space-y-2">
                <BadgeStatus tone={stopped ? "success" : "error"}>
                  <CircleDot className="h-3 w-3" /> {stopped ? "Gravação finalizada" : "Gravando"}
                </BadgeStatus>
                <p className="text-xs text-muted-foreground">
                  {eventCount} passos · {variableCount} variáveis
                </p>
                <Button
                  className="w-full"
                  variant="outline"
                  disabled={stopped || stop.isPending}
                  onClick={() => stop.mutate()}
                >
                  <Square className="h-4 w-4" /> Finalizar ensino
                </Button>
                <Button
                  className="w-full"
                  disabled={!stopped || publish.isPending}
                  onClick={() => {
                    if (expected.trim() && !resultConfirmed && !hasConfirmedContract) {
                      toast.warning("Selecione no navegador qual informação esta ação deve retornar.");
                      return;
                    }
                    publish.mutate();
                  }}
                >
                  <Save className="h-4 w-4" /> Publicar versão
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        <BrowserWorkspace
          actions={
            selectionMode === "selecting" ? (
              <Button
                size="sm"
                variant="outline"
                disabled={cancelSelection.isPending}
                onClick={() => cancelSelection.mutate()}
              >
                <X className="h-4 w-4" /> Cancelar seleção
              </Button>
            ) : (
              <Button
                size="sm"
                disabled={!sessionId || startSelection.isPending || stopped}
                onClick={() => startSelection.mutate()}
              >
                <Crosshair className="h-4 w-4" /> Selecionar resultado
              </Button>
            )
          }
          footer={
            <OperatorAssistant
              collapsible
              mode="learning"
              sessionId={sessionId}
              statusText={sessionId ? "Controles prontos" : "Inicie o ensino para usar"}
              variant="dock"
            />
          }
        />

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Resultado da ação</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              {selectionMode === "selecting" && (
                <BadgeStatus tone="warning">
                  <Crosshair className="h-3 w-3" /> Clique no campo que deseja capturar
                </BadgeStatus>
              )}
              {selectionCandidate && selectionMode === "preview" && (
                <div className="space-y-3 text-foreground">
                  <div>
                    <p className="text-xs font-medium uppercase text-muted-foreground">
                      Resultado selecionado
                    </p>
                    <p className="mt-1 text-2xl font-semibold">{displayValue || "Sem valor"}</p>
                  </div>
                  <div className="grid gap-1 text-sm">
                    <span className="text-muted-foreground">Contexto</span>
                    <span>{screenLabel || "Campo selecionado"}</span>
                  </div>
                  <div className="space-y-2">
                    <span className="text-sm text-muted-foreground">Formato</span>
                    <label className="flex items-center gap-2">
                      <input
                        type="radio"
                        checked={normalization === "exact_text"}
                        onChange={() => setNormalization("exact_text")}
                      />
                      Texto exato
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="radio"
                        checked={normalization === "digits_only"}
                        onChange={() => setNormalization("digits_only")}
                      />
                      Somente números
                    </label>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" size="sm" onClick={() => cancelSelection.mutate()}>
                      Cancelar
                    </Button>
                    <Button
                      size="sm"
                      disabled={!selectionCandidate || confirmSelection.isPending}
                      onClick={() => confirmSelection.mutate()}
                    >
                      Confirmar resultado
                    </Button>
                  </div>
                </div>
              )}
              {(resultConfirmed || hasConfirmedContract) && selectionMode !== "preview" && (
                <div className="space-y-2 text-foreground">
                  <BadgeStatus tone="success">
                    <Check className="h-3 w-3" /> Resultado selecionado
                  </BadgeStatus>
                  <p className="text-2xl font-semibold">{displayValue || "Confirmado"}</p>
                  <p className="text-sm text-muted-foreground">{screenLabel || targetName}</p>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!sessionId || startSelection.isPending || stopped}
                    onClick={() => startSelection.mutate()}
                  >
                    Alterar resultado
                  </Button>
                </div>
              )}
              {!selectionCandidate && !resultConfirmed && !hasConfirmedContract && (
                <p>Use “Selecionar resultado” quando chegar ao campo que a ação deve retornar.</p>
              )}
              {publish.isSuccess && (
                <Button size="sm" asChild>
                  <Link to="/acoes">
                    <Check className="h-4 w-4" /> Ver ação publicada
                  </Link>
                </Button>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}

function candidateValue(candidate: ResultSelectionCandidate | null) {
  if (!candidate) return "";
  return String(candidate.value || candidate.selected_element?.candidate_value || candidate.selected_element?.selected_text || "").trim();
}

function contextText(candidate: ResultSelectionCandidate | null) {
  if (!candidate) return "";
  const selected = (candidate.selected_element || {}) as Record<string, unknown>;
  const before = Array.isArray(selected.nearby_text_before) ? selected.nearby_text_before : [];
  return String(
    candidate.label ||
      selected.label ||
      selected.candidate_label ||
      selected.column_header ||
      before[0] ||
      "",
  ).trim();
}

function digitsOnlyPreview(value: string) {
  const groups = value.match(/\d+/g) || [];
  return groups.length === 1 ? groups[0] : "";
}

function hasContract(value: unknown) {
  return Boolean(value && typeof value === "object" && Object.keys(value).length > 0);
}
