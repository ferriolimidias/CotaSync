import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Check, CircleDot, Play, Save, Square } from "lucide-react";

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
  createLearningSession,
  getLearningSession,
  saveLearnedAction,
  startLearningRecording,
  stopLearningRecording,
} from "@/services/api";

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
        variable_names: ["grupo", "cota", "versao"],
      }),
    onSuccess: () => toast.success("Ação publicada."),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível publicar a ação."),
  });

  const eventCount = Number(session.data?.learning_events_count || 0);
  const variableCount = Array.isArray(session.data?.variables) ? session.data.variables.length : 3;

  return (
    <AppShell
      title="Ensinar ação"
      subtitle="Grave um fluxo no navegador sem lidar com seletores ou JSON"
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
                  onClick={() => publish.mutate()}
                >
                  <Save className="h-4 w-4" /> Publicar versão
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        <BrowserWorkspace
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
              <p>
                Ao finalizar o ensino, confirme qual informação a ação deve retornar no campo
                “Resultado esperado”.
              </p>
              <p>Diagnóstico/reparo por IA não está disponível nesta rodada.</p>
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
