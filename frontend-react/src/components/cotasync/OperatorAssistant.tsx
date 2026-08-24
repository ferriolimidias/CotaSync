import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { CornerDownLeft, Eraser, Send, Shield, TextCursorInput } from "lucide-react";

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

export function OperatorAssistant({ sessionId }: { sessionId: string | null }) {
  const [text, setText] = useState("");
  const [sensitive, setSensitive] = useState(false);
  const [markVariable, setMarkVariable] = useState(false);
  const [variable, setVariable] = useState("grupo");

  const insert = useMutation({
    mutationFn: () =>
      operatorInsertActive(
        sessionId as string,
        text,
        sensitive,
        markVariable ? variable : undefined,
      ),
    onSuccess: () => {
      toast.success(
        markVariable
          ? `Texto inserido e marcado como ${variable}.`
          : "Texto inserido no campo ativo.",
      );
      if (sensitive) setText("");
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Não foi possível inserir o texto."),
  });
  const press = useMutation({
    mutationFn: (key: "Tab" | "Enter") => operatorPress(sessionId as string, key),
  });
  const clear = useMutation({
    mutationFn: () => operatorClearActive(sessionId as string),
    onSuccess: () => toast.message("Campo ativo limpo."),
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
        <div className="grid gap-2">
          <Label className="flex items-center gap-2 text-xs">
            <Checkbox
              checked={markVariable}
              onCheckedChange={(checked) => setMarkVariable(Boolean(checked))}
            />{" "}
            Marcar como variável
          </Label>
          <Select value={variable} onValueChange={setVariable} disabled={!markVariable || disabled}>
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
