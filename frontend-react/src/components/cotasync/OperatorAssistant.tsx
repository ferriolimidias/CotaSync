import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ChevronDown,
  CornerDownLeft,
  Eraser,
  Keyboard,
  Send,
  Shield,
  TextCursorInput,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { operatorClearActive, operatorInsertActive, operatorPress } from "@/services/api";

const canonicalVariables = ["grupo", "cota", "versao"];
const canonicalVariableLabels: Record<string, string> = {
  grupo: "Grupo",
  cota: "Cota",
  versao: "Versão",
};

type OperatorAssistantMode = "operation" | "learning";
type OperatorAssistantVariant = "panel" | "dock";

export function OperatorAssistant({
  collapsible = false,
  defaultCollapsed = false,
  mode = "learning",
  sessionId,
  statusText,
  variant = "panel",
}: {
  collapsible?: boolean;
  defaultCollapsed?: boolean;
  mode?: OperatorAssistantMode;
  sessionId: string | null;
  statusText?: string;
  variant?: OperatorAssistantVariant;
}) {
  const [text, setText] = useState("");
  const [sensitive, setSensitive] = useState(false);
  const [markVariable, setMarkVariable] = useState(false);
  const [variable, setVariable] = useState("grupo");
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const showVariables = mode === "learning";

  const insert = useMutation({
    mutationFn: () =>
      operatorInsertActive(
        sessionId as string,
        text,
        sensitive,
        showVariables && markVariable ? variable : undefined,
      ),
    onSuccess: () => {
      toast.success(
        showVariables && markVariable
          ? `Texto inserido e marcado como ${variable}.`
          : "Texto inserido no campo ativo.",
      );
      if (sensitive) setText("");
    },
    onError: (error) =>
      toast.error(operatorErrorMessage(error, "Não foi possível inserir o texto.")),
  });
  const press = useMutation({
    mutationFn: (key: "Tab" | "Enter") => operatorPress(sessionId as string, key),
    onError: (error) =>
      toast.error(operatorErrorMessage(error, "Não foi possível enviar a tecla.")),
  });
  const clear = useMutation({
    mutationFn: () => operatorClearActive(sessionId as string),
    onSuccess: () => {
      setText("");
      toast.message("Campo ativo limpo.");
    },
    onError: (error) =>
      toast.error(operatorErrorMessage(error, "Não foi possível limpar o campo.")),
  });

  const disabled = !sessionId;
  const insertThenTab = async () => {
    try {
      await insert.mutateAsync();
      await press.mutateAsync("Tab");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Não foi possível inserir e avançar.");
    }
  };

  if (variant === "dock" && collapsed) {
    return (
      <div className="border-t border-border bg-background/95 px-3 py-2 backdrop-blur">
        <Button size="sm" variant="outline" onClick={() => setCollapsed(false)}>
          <Keyboard className="h-4 w-4" /> Digitar
        </Button>
      </div>
    );
  }

  if (variant === "dock") {
    return (
      <div className="border-t border-border bg-background/95 px-2 py-2 shadow-[0_-4px_16px_rgba(15,23,42,0.08)] backdrop-blur">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex min-w-[260px] flex-1 items-center gap-2">
            <TextCursorInput className="h-4 w-4 shrink-0 text-primary" />
            <Input
              className="h-9 min-w-0 flex-1"
              type={sensitive ? "password" : "text"}
              value={text}
              onChange={(event) => setText(event.target.value)}
              disabled={disabled}
              placeholder="Digite para enviar ao campo selecionado no navegador..."
            />
          </div>
          <Button
            size="sm"
            disabled={disabled || !text || insert.isPending}
            onClick={() => insert.mutate()}
          >
            <Send className="h-4 w-4" /> Inserir
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={disabled || clear.isPending}
            onClick={() => clear.mutate()}
          >
            <Eraser className="h-4 w-4" /> Limpar
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={disabled || press.isPending}
            onClick={() => press.mutate("Tab")}
          >
            Tab
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={disabled || press.isPending}
            onClick={() => press.mutate("Enter")}
          >
            <CornerDownLeft className="h-4 w-4" /> Enter
          </Button>
          <Label className="flex h-9 items-center gap-2 rounded-md border border-border px-2 text-xs">
            <Checkbox
              checked={sensitive}
              onCheckedChange={(checked) => setSensitive(Boolean(checked))}
            />
            <Shield className="h-4 w-4 text-muted-foreground" />
            Modo sensível
          </Label>
          {statusText && (
            <span className="text-xs text-muted-foreground" aria-live="polite">
              {statusText}
            </span>
          )}
          {collapsible && (
            <Button size="sm" variant="ghost" onClick={() => setCollapsed(true)}>
              <ChevronDown className="h-4 w-4" /> Ocultar controles
            </Button>
          )}
        </div>
        {showVariables && (
          <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-border/70 pt-2">
            <Label className="flex items-center gap-2 text-xs">
              <Checkbox
                checked={markVariable}
                onCheckedChange={(checked) => setMarkVariable(Boolean(checked))}
              />
              Marcar como variável
            </Label>
            <Select
              value={variable}
              onValueChange={setVariable}
              disabled={!markVariable || disabled}
            >
              <SelectTrigger className="h-8 w-[140px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {canonicalVariables.map((item) => (
                  <SelectItem key={item} value={item}>
                    {canonicalVariableLabels[item]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <TextCursorInput className="h-4 w-4 text-primary" />
        <h2 className="text-sm font-semibold text-foreground">Assistente do operador</h2>
      </div>
      <div className="mt-4 space-y-3">
        <div className="grid gap-2">
          <Label>Texto para o campo ativo</Label>
          <Input
            type={sensitive ? "password" : "text"}
            value={text}
            onChange={(event) => setText(event.target.value)}
            disabled={disabled}
          />
        </div>
        <div className="flex items-center justify-between rounded-md border border-border p-2">
          <Label className="flex items-center gap-2 text-xs">
            <Checkbox
              checked={sensitive}
              onCheckedChange={(checked) => setSensitive(Boolean(checked))}
            />{" "}
            Modo sensível
          </Label>
          <Shield className="h-4 w-4 text-muted-foreground" />
        </div>
        {showVariables && (
          <div className="grid gap-2">
            <Label className="flex items-center gap-2 text-xs">
              <Checkbox
                checked={markVariable}
                onCheckedChange={(checked) => setMarkVariable(Boolean(checked))}
              />{" "}
              Marcar como variável
            </Label>
            <Select
              value={variable}
              onValueChange={setVariable}
              disabled={!markVariable || disabled}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {canonicalVariables.map((item) => (
                  <SelectItem key={item} value={item}>
                    {item}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        <div className="grid grid-cols-2 gap-2">
          <Button
            size="sm"
            disabled={disabled || !text || insert.isPending}
            onClick={() => insert.mutate()}
          >
            <Send className="h-4 w-4" /> Inserir
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={disabled || !text || insert.isPending || press.isPending}
            onClick={() => void insertThenTab()}
          >
            <Send className="h-4 w-4" /> Inserir + Tab
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => press.mutate("Tab")}
          >
            Tab
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => press.mutate("Enter")}
          >
            <CornerDownLeft className="h-4 w-4" /> Enter
          </Button>
          <Button
            className="col-span-2"
            size="sm"
            variant="ghost"
            disabled={disabled}
            onClick={() => clear.mutate()}
          >
            <Eraser className="h-4 w-4" /> Limpar campo ativo
          </Button>
        </div>
      </div>
    </div>
  );
}

function operatorErrorMessage(error: unknown, fallback: string) {
  const message = error instanceof Error ? error.message : "";
  if (/Foque um campo editável|campo ativo|active element/i.test(message)) {
    return "Selecione primeiro um campo no sistema externo.";
  }
  return message || fallback;
}
