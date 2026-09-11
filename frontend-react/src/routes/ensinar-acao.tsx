import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Check, CircleDot, Crosshair, Play, Save, Square, Trash2, X } from "lucide-react";

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
  getAccessCycle,
  getLearningDrafts,
  resumeLearningRecording,
  resolveTeachingContext,
  validateAccessProfile,
  validateAccessCycleManually,
  authenticateAccessProfile,
  getSystemSpreadsheets,
  getClientLists,
  getExternalSystemConfig,
  listAccessProfiles,
  updateClientListAccessProfile,
  removeLearningOutput,
  renameLearningOutput,
  saveLearnedAction,
  startLearningRecording,
  startLearningResultSelection,
  stopLearningRecording,
} from "@/services/api";
import type { ResultSelectionCandidate } from "@/types/api";
import { compatibleTeachingList, restoredTeachingProfile, teachingProfiles, teachingProfileStatus } from "@/lib/teaching-profile";

export const Route = createFileRoute("/ensinar-acao")({
  head: () => ({ meta: [{ title: "Ensinar ação — CotaSync" }] }),
  component: EnsinarPage,
});

function EnsinarPage() {
  const queryClient = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [expected, setExpected] = useState("");
  const [stopped, setStopped] = useState(false);
  const [selectionMode, setSelectionMode] = useState<"idle" | "selecting" | "preview">("idle");
  const [selectionCandidate, setSelectionCandidate] = useState<ResultSelectionCandidate | null>(null);
  const [resultConfirmed, setResultConfirmed] = useState(false);
  const [normalization, setNormalization] = useState<"exact_text" | "digits_only">("exact_text");
  const [learningMode, setLearningMode] = useState<"free_action" | "spreadsheet">("free_action");
  const [dataSourceId, setDataSourceId] = useState<string>("");
  const [dataSourceFieldId, setDataSourceFieldId] = useState<string>("");
  const [scopeAllLists, setScopeAllLists] = useState(true);
  const [scopeListIds, setScopeListIds] = useState<string[]>([]);
  const [accessProfileId, setAccessProfileId] = useState<string>("");
  const [outputLabels, setOutputLabels] = useState<Record<string, string>>({});
  const drafts = useQuery({ queryKey: ["learning-drafts"], queryFn: getLearningDrafts });
  const dataSources = useQuery({ queryKey: ["system-spreadsheets"], queryFn: getSystemSpreadsheets });
  const clientLists = useQuery({ queryKey: ["client-lists"], queryFn: getClientLists });
  const externalConfig = useQuery({ queryKey: ["external-system-config"], queryFn: getExternalSystemConfig });
  const accessProfiles = useQuery({ queryKey: ["access-profiles"], queryFn: listAccessProfiles });
  const availableProfiles = teachingProfiles(accessProfiles.data ?? [], externalConfig.data?.id);
  const selectedSheet = dataSources.data?.find((sheet) => sheet.id === dataSourceId);
  const sheetList = clientLists.data?.find((list) => list.id === selectedSheet?.default_list_id);
  useEffect(() => {
    if (sessionId) return;
    if (learningMode === "spreadsheet" && !dataSourceId && dataSources.data?.length === 1) setDataSourceId(dataSources.data[0].id);
    if (learningMode === "spreadsheet" && sheetList?.access_profile_id) {
      setAccessProfileId(sheetList.access_profile_id);
      setScopeAllLists(false);
      setScopeListIds([sheetList.id]);
    } else if (!accessProfileId && availableProfiles.length === 1) {
      setAccessProfileId(availableProfiles[0].id);
    }
  }, [sessionId, learningMode, dataSourceId, dataSources.data, sheetList, accessProfileId, accessProfiles.data, externalConfig.data]);
  const hydratedSessionId = useRef<string | null>(null);
  const preparedContext = useRef<Awaited<ReturnType<typeof resolveTeachingContext>> | null>(null);
  const [reauthRequired, setReauthRequired] = useState(false);
  const session = useQuery({
    queryKey: ["learning-session", sessionId],
    queryFn: () => getLearningSession(sessionId as string),
    enabled: Boolean(sessionId),
    refetchInterval: () =>
      stopped || document.visibilityState !== "visible" ? false : 2500,
  });
  const learningCycleId = String(session.data?.access_cycle_id || "");
  const accessCycle = useQuery({
    queryKey: ["learning-access-cycle", learningCycleId],
    queryFn: () => getAccessCycle(learningCycleId),
    enabled: Boolean(learningCycleId),
    refetchInterval: () => (document.visibilityState === "visible" ? 2000 : false),
    refetchOnWindowFocus: true,
  });
  const manualAccessValidation = useMutation({
    mutationFn: () => validateAccessCycleManually(learningCycleId),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["learning-access-cycle", learningCycleId] });
      void queryClient.invalidateQueries({ queryKey: ["learning-session", sessionId] });
      if (result.validated) toast.success("Usuário autenticado e acesso validado. O ensino será liberado.");
      else if (result.status === "validation_requested") toast.info(result.message);
      else toast.warning(result.message || "Finalize a autenticação no navegador antes de validar o acesso.");
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Não foi possível validar o acesso."),
  });
  const canValidateLearningAccess = Boolean(
    learningCycleId && accessCycle.data && accessCycle.data.status !== "ready" &&
      (["starting", "running", "waiting"].includes(accessCycle.data.status) ||
        ["reauthentication_required", "account_picker_skipped", "access_authentication_not_completed", "access_identity_mismatch"].includes(accessCycle.data.error_code || "")),
  );

  useEffect(() => {
    if (!sessionId || !session.data || hydratedSessionId.current === sessionId) return;
    hydratedSessionId.current = sessionId;
    setAccessProfileId(restoredTeachingProfile(session.data));
    setName(String(session.data.action_name || ""));
    setObjective(String(session.data.objective || ""));
    setExpected(String(session.data.expected_result || ""));
    setLearningMode(session.data.learning_mode === "spreadsheet" ? "spreadsheet" : "free_action");
    setDataSourceId(String(session.data.data_source_id || ""));
    const lists = Array.isArray(session.data.allowed_list_ids) ? session.data.allowed_list_ids.map(String) : [];
    setScopeListIds(lists);
    setScopeAllLists(lists.length === 0);
  }, [sessionId, session.data]);

  const incompatibleScope = !scopeAllLists && (scopeListIds.length === 0 || scopeListIds.some((id) =>
    !compatibleTeachingList(clientLists.data?.find((list) => list.id === id)?.access_profile_id, accessProfileId),
  ));

  function newTeaching() {
    setSessionId(null);
    hydratedSessionId.current = null;
    setAccessProfileId("");
    setScopeListIds([]);
    setScopeAllLists(true);
    setStopped(false);
    setName("");
    setObjective("");
    setExpected("");
    setSelectionMode("idle");
    setSelectionCandidate(null);
    setResultConfirmed(false);
    setOutputLabels({});
    setDataSourceId("");
    setDataSourceFieldId("");
  }

  const create = useMutation({
    mutationFn: async () => {
      preparedContext.current = await resolveTeachingContext({ required_access_profile_id: accessProfileId || undefined, data_source_id: learningMode === "spreadsheet" ? dataSourceId : undefined, allowed_list_ids: scopeAllLists ? [] : scopeListIds });
      const validation = await validateAccessProfile(preparedContext.current.required_access_profile_id);
      if (validation.profile.validation_status === "reauth_required") {
        setReauthRequired(true);
        throw new Error(`${validation.profile.display_name} precisa ser autenticado novamente.`);
      }
      setReauthRequired(false);
      return createLearningSession();
    },
    onSuccess: async (created) => {
      const id = String(created.session_id || created.id || "");
      hydratedSessionId.current = id;
      setSessionId(id);
      await start.mutateAsync(id);
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível iniciar o ensino."),
  });
  const start = useMutation({
    mutationFn: (id: string) =>
      startLearningRecording(id, {
        name,
        objective,
        expected_result: expected,
        learning_mode: learningMode,
        data_source_id: dataSourceId || null,
        required_access_profile_id: accessProfileId || null,
        run_start_strategy: externalConfig.data?.run_start_strategy,
        allowed_list_ids: scopeAllLists ? [] : scopeListIds,
        ...preparedContext.current,
      }),
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
        allowed_list_ids: scopeAllLists ? [] : scopeListIds,
      }),
    onSuccess: () => {
      void session.refetch();
      toast.success("Ação publicada.");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 422) {
        void session.refetch();
        if (error.code === "ACCESS_PROFILE_REQUIRED") {
          toast.error("Selecione um perfil de acesso antes de publicar a ação.");
          return;
        }
        if (error.code === "ACTION_PROFILE_SCOPE_INVALID") {
          toast.error("As listas escolhidas usam outro perfil de acesso.");
          return;
        }
        if (error.code === "LEARNED_GRAPH_INVALID") {
          toast.error("Não foi possível validar o fluxo aprendido. O ensino foi preservado; tente publicar novamente.");
        } else {
          toast.error("Não foi possível publicar a versão: resultado da ação incompleto.");
        }
        return;
      }
      if (error instanceof ApiError && error.status >= 500) {
        void session.refetch();
        toast.error("Não foi possível publicar a versão. O ensino foi preservado; tente novamente.");
        return;
      }
      void session.refetch();
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
        destination: learningMode === "spreadsheet" && dataSourceId && dataSourceFieldId
          ? { type: "system_sheet_field", system_spreadsheet_id: dataSourceId, field_id: dataSourceFieldId }
          : null,
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
  const renameOutput = useMutation({
    mutationFn: ({ outputId, label }: { outputId: string; label: string }) =>
      renameLearningOutput(sessionId as string, outputId, label),
    onSuccess: () => {
      void session.refetch();
      toast.success("Resultado renomeado.");
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível renomear o resultado."),
  });
  const removeOutput = useMutation({
    mutationFn: (outputId: string) => removeLearningOutput(sessionId as string, outputId),
    onSuccess: (outputs) => {
      setResultConfirmed(outputs.length > 0);
      void session.refetch();
      toast.success("Resultado removido.");
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível remover o resultado."),
  });

  useEffect(() => {
    if (selectionMode !== "selecting" || !sessionId) return;
    const timer = window.setInterval(() => {
      if (!captureSelection.isPending) captureSelection.mutate();
    }, 900);
    return () => window.clearInterval(timer);
  }, [captureSelection, selectionMode, sessionId]);

  const eventCount = Number(
    session.data?.steps_count
      ?? session.data?.recorded_steps_count
      ?? session.data?.learning_events_count
      ?? 0,
  );
  const variableCount = Number(
    session.data?.variables_count
      ?? (Array.isArray(session.data?.variables) ? session.data.variables.length : 0),
  );
  const sessionStopped = stopped || (session.data?.recording === false && eventCount > 0);
  const outputs = Array.isArray(session.data?.outputs) ? session.data.outputs : [];

  return (
    <AppShell
      title="Ensinar ação"
      subtitle="Grave um fluxo no navegador remoto"
    >
      <div className="grid min-h-0 gap-4 xl:grid-cols-[360px_minmax(0,1fr)_280px]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Dados da ação</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {!sessionId && (drafts.data ?? []).length > 0 && <details><summary className="text-sm">Ensinos salvos</summary>{drafts.data?.map((draft) => <Button key={draft.id} variant="ghost" onClick={async () => { try { if (["interrupted", "recording"].includes(draft.recording_status)) await resumeLearningRecording(draft.id); setName(draft.name); setSessionId(draft.id); } catch (error) { toast.error(error instanceof Error ? error.message : "Não foi possível continuar o ensino."); } }}>{draft.recording_status === "interrupted" || draft.recording_status === "recording" ? "Continuar ensino" : "Revisar ensino"}: {draft.name || "Sem nome"}</Button>)}</details>}
            <div className="grid gap-2">
              <Label>O que você quer ensinar?</Label>
              <div className="grid grid-cols-2 gap-2">
                <Button type="button" variant={learningMode === "free_action" ? "default" : "outline"} onClick={() => setLearningMode("free_action")}>
                  Ação livre
                </Button>
                <Button type="button" variant={learningMode === "spreadsheet" ? "default" : "outline"} onClick={() => setLearningMode("spreadsheet")}>
                  Atualizar planilha
                </Button>
              </div>
              {learningMode === "spreadsheet" && <p className="text-xs text-muted-foreground">Escolha a Planilha do Sistema e o campo que receberá o resultado.</p>}
              {learningMode === "spreadsheet" && (
                <>
                  <select className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={dataSourceId} onChange={(event) => { setDataSourceId(event.target.value); setDataSourceFieldId(""); }}>
                    <option value="">Selecione a Planilha do Sistema</option>
                    {(dataSources.data || []).map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}
                  </select>
                  <select className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={dataSourceFieldId} onChange={(event) => setDataSourceFieldId(event.target.value)} disabled={!dataSourceId}>
                    <option value="">Selecione o campo a atualizar</option>
                    {(dataSources.data || []).find((source) => source.id === dataSourceId)?.fields.map((field) => <option key={field.id} value={field.id}>{field.display_name}</option>)}
                  </select>
                </>
              )}
            </div>
            <div className="grid gap-2">
              <Label>Nome</Label>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Quantidade de parcelas"
              />
            </div>
            <div className="grid gap-2">
              <Label>Sistema externo</Label>
              <p className="text-sm">{externalConfig.data?.external_system_name || "Carregando sistema..."}</p>
            </div>
            <div className="grid gap-2">
              <Label>Acesso</Label>
              {availableProfiles.length === 1 || (learningMode === "spreadsheet" && sheetList?.access_profile_id) ? <p className="text-sm">{availableProfiles.find((profile) => profile.id === accessProfileId)?.display_name || "Acesso da lista"}</p> : <select aria-label="Perfil de acesso" className="h-9 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm" value={accessProfileId} onChange={(event) => { setAccessProfileId(event.target.value); setScopeListIds([]); }} disabled={Boolean(sessionId)}>
                <option value="">Selecione o perfil usado nesta ação</option>
                {availableProfiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>{profile.display_name} · {profile.login_identifier}</option>
                ))}
              </select>}
              {accessProfileId && <p className="text-xs text-muted-foreground">{teachingProfileStatus(availableProfiles.find((profile) => profile.id === accessProfileId)?.validation_status)}</p>}
              {reauthRequired && <Button type="button" variant="outline" onClick={() => authenticateAccessProfile(accessProfileId).then(() => toast.message("Conclua a autenticação no navegador abaixo e inicie o ensino novamente. Seus dados continuam preenchidos.")).catch((error) => toast.error(error.message))}>Autenticar</Button>}
              {accessProfiles.isError && <p className="text-xs text-amber-700">Não foi possível carregar os perfis. Atualize a página.</p>}
              {accessProfiles.isSuccess && externalConfig.isSuccess && !availableProfiles.length && <p className="text-xs text-amber-700">{accessProfiles.data.some((profile) => profile.external_system_id === externalConfig.data.id) ? "Nenhum perfil ativo disponível." : "Nenhum perfil de acesso cadastrado para este sistema."}</p>}
              {sessionId && !accessProfileId && <p className="text-xs text-amber-700">O ensino retomado não possui perfil de acesso definido.</p>}
              {sessionId && (session.data?.recording === false || (session.error instanceof ApiError && session.error.status === 404)) && <Button type="button" variant="outline" onClick={newTeaching}><Play className="h-4 w-4" /> Novo ensino</Button>}
              <p className="text-xs text-muted-foreground">Início: {externalConfig.data?.run_start_strategy === "external_entry_each_run" ? "Entrada do sistema" : externalConfig.data?.run_start_strategy === "persistent_graph_reentry" ? "Reentrada pelo grafo" : "Configuração pendente"}</p>
              {externalConfig.data?.run_start_strategy === "external_entry_each_run" && !accessProfileId && !sessionId && (
                <p className="text-xs text-amber-700">Este sistema exige um perfil antes de iniciar o ensino.</p>
              )}
            </div>
            <div className="grid gap-2">
              <Label>Disponível para</Label>
              <select className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={scopeAllLists ? "all" : "specific"} onChange={(event) => setScopeAllLists(event.target.value === "all")}>
                <option value="all">Todas as listas compatíveis com o perfil</option>
                <option value="specific">Listas específicas</option>
              </select>
              {!scopeAllLists && <div className="grid gap-1 rounded-md border border-border p-2">{(clientLists.data ?? []).map((list) => <label className="flex items-center gap-2 text-sm" key={list.id}><input type="checkbox" disabled={!compatibleTeachingList(list.access_profile_id, accessProfileId)} checked={scopeListIds.includes(list.id)} onChange={() => setScopeListIds((current) => current.includes(list.id) ? current.filter((id) => id !== list.id) : [...current, list.id])} /> {list.name}{!list.access_profile_id ? " · Perfil não definido" : !compatibleTeachingList(list.access_profile_id, accessProfileId) ? " · Outro perfil" : ""}</label>)}</div>}
              {(clientLists.data ?? []).filter((list) => !list.access_profile_id).map((list) => <div key={list.id} className="text-xs text-muted-foreground">{list.name}: acesso ainda não definido. <Button type="button" size="sm" variant="outline" disabled={!accessProfileId} onClick={() => updateClientListAccessProfile(list.id, accessProfileId).then(() => clientLists.refetch()).catch((error) => toast.error(error.message))}>Vincular a {availableProfiles.find((profile) => profile.id === accessProfileId)?.display_name || "um acesso"}</Button></div>)}
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
                disabled={!name || create.isPending || !externalConfig.data?.id || !externalConfig.data?.run_start_strategy || !availableProfiles.some((profile) => profile.id === accessProfileId) || incompatibleScope}
                onClick={() => create.mutate()}
              >
                <Play className="h-4 w-4" /> Começar ensino
              </Button>
            ) : (
              <div className="space-y-2">
                <BadgeStatus tone={sessionStopped ? "success" : session.data?.recording ? "error" : "warning"}>
                  <CircleDot className="h-3 w-3" /> {sessionStopped ? "Gravação finalizada" : session.data?.recording ? "Gravando" : "Aguardando acesso"}
                </BadgeStatus>
                <p className="text-xs text-muted-foreground">
                  {eventCount} passos · {variableCount} variáveis
                </p>
                {sessionStopped && <div className="space-y-1 text-sm"><p>Ação: {name || "Ensino salvo"}</p><p>Acesso: {availableProfiles.find((profile) => profile.id === accessProfileId)?.display_name || "Não definido"}</p><p>Listas: {scopeAllLists ? "Compatíveis com o acesso" : (clientLists.data ?? []).filter((list) => scopeListIds.includes(list.id)).map((list) => list.name).join(", ")}</p><p>Resultados: {outputs.length}</p><p>Variáveis: {(session.data?.variables ?? []).map((key) => ({ grupo: "Grupo", cota: "Cota", versao: "Versão" })[key] || key).join(", ") || "Nenhuma"}</p></div>}
                {(() => {
                  const reviewStatus = String((session.data?.ai_review as Record<string, unknown> | undefined)?.status || "");
                  if (reviewStatus === "completed") return <p className="text-xs text-emerald-700">Revisão por IA concluída; validação local preservada.</p>;
                  if (reviewStatus === "fallback" || reviewStatus === "failed") return <p className="text-xs text-amber-700">Revisão por IA indisponível; validação local utilizada.</p>;
                  return null;
                })()}
                <Button
                  className="w-full"
                  variant="outline"
                  disabled={!session.data?.recording || stop.isPending}
                  onClick={() => stop.mutate()}
                >
                  <Square className="h-4 w-4" /> Finalizar ensino
                </Button>
                <Button
                  className="w-full"
                  disabled={!sessionStopped || publish.isPending}
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
            <>
              {canValidateLearningAccess && (
                <Button
                  size="sm"
                  onClick={() => manualAccessValidation.mutate()}
                  disabled={manualAccessValidation.isPending}
                >
                  {manualAccessValidation.isPending ? "Validando..." : "Validar acesso"}
                </Button>
              )}
              {selectionMode === "selecting" ? (
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
                  disabled={!session.data?.recording || startSelection.isPending || stopped}
                  onClick={() => startSelection.mutate()}
                >
                  <Crosshair className="h-4 w-4" /> {outputs.length > 0 ? "+ Selecionar outro resultado" : "Selecionar resultado"}
                </Button>
              )}
            </>
          }
          footer={
            <OperatorAssistant
              collapsible
              mode="learning"
              sessionId={session.data?.recording ? sessionId : null}
              statusText={session.data?.recording ? "Controles prontos" : sessionId ? "Aguardando acesso validado" : "Inicie o ensino para usar"}
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
              {outputs.length > 0 && selectionMode !== "preview" && (
                <div className="space-y-2 text-foreground">
                  <p className="text-xs font-medium uppercase text-muted-foreground">Resultados selecionados</p>
                  {outputs.map((output, index) => {
                    const outputId = String(output.output_id || index);
                    const currentLabel = outputLabels[outputId] ?? String(output.label || `Resultado ${index + 1}`);
                    return (
                    <div className="grid gap-2 rounded-md border border-border p-2" key={outputId}>
                      <div className="flex items-center gap-2">
                        <Check className="h-4 w-4 text-emerald-600" />
                        <Input
                          className="h-8 min-w-0 flex-1"
                          value={currentLabel}
                          onChange={(event) =>
                            setOutputLabels((labels) => ({ ...labels, [outputId]: event.target.value }))
                          }
                          onBlur={() => {
                            const nextLabel = currentLabel.trim();
                            if (nextLabel && nextLabel !== String(output.label || "")) {
                              renameOutput.mutate({ outputId, label: nextLabel });
                            }
                          }}
                          onKeyDown={(event) => {
                            if (event.key !== "Enter") return;
                            event.currentTarget.blur();
                          }}
                        />
                        <Button
                          size="icon"
                          variant="ghost"
                          disabled={removeOutput.isPending}
                          onClick={() => removeOutput.mutate(outputId)}
                          title="Remover resultado"
                          aria-label="Remover resultado"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                      {isOutputDestination(output.destination) && (
                        <p className="text-xs text-muted-foreground">
                          Campo: {String(output.destination.field_id)}
                        </p>
                      )}
                    </div>
                  )})}
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!sessionId || startSelection.isPending || stopped}
                    onClick={() => startSelection.mutate()}
                  >
                    <Crosshair className="h-4 w-4" /> + Selecionar outro resultado
                  </Button>
                </div>
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

function isOutputDestination(value: unknown): value is { field_id: unknown } {
  return Boolean(value && typeof value === "object" && "field_id" in value);
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
