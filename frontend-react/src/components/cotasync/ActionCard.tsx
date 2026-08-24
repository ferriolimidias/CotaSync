import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BadgeStatus } from "./BadgeStatus";
import type { ActionRow } from "@/lib/mock-data";
import { Play, Settings2, Eye, PowerOff, ChevronDown } from "lucide-react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Collapsible, CollapsibleContent, CollapsibleTrigger,
} from "@/components/ui/collapsible";

const statusTone = {
  Pronta: "success",
  "Precisa confirmar": "warning",
  "Em desenvolvimento": "neutral",
} as const;

export function ActionCard({ action }: { action: ActionRow }) {
  const [open, setOpen] = useState(false);
  const [techOpen, setTechOpen] = useState(false);

  const mockJson = {
    run_id: `run_${action.id}_20250714`,
    action_id: action.id,
    vars: action.vars,
    last_result: action.lastResult,
    diagnostic: {
      steps_recorded: 7,
      last_status: action.status,
      elapsed_ms: 1840,
    },
  };

  return (
    <>
      <Card className="border-border/60 shadow-sm transition hover:shadow-md">
        <CardContent className="flex flex-col gap-4 p-5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="truncate text-base font-semibold text-foreground">{action.name}</h3>
              <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{action.purpose}</p>
            </div>
            <BadgeStatus tone={statusTone[action.status]}>{action.status}</BadgeStatus>
          </div>

          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <p className="text-muted-foreground">Variáveis</p>
              <p className="mt-0.5 font-medium text-foreground">{action.vars.join(", ")}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Último resultado</p>
              <p className="mt-0.5 font-medium text-foreground">{action.lastResult}</p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2 pt-1">
            <Button size="sm" disabled={action.status === "Em desenvolvimento"}>
              <Play className="h-3.5 w-3.5" /> Executar teste
            </Button>
            <Button size="sm" variant="outline">
              <Settings2 className="h-3.5 w-3.5" /> Editar
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
              <Eye className="h-3.5 w-3.5" /> Detalhes
            </Button>
            <Button size="sm" variant="ghost">
              <PowerOff className="h-3.5 w-3.5" /> Desativar
            </Button>
          </div>
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {action.name}
              <BadgeStatus tone={statusTone[action.status]}>{action.status}</BadgeStatus>
            </DialogTitle>
          </DialogHeader>

          <div className="grid gap-4 py-2 text-sm">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Objetivo</p>
              <p className="mt-1 text-foreground">{action.purpose}</p>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Variáveis</p>
                <p className="mt-1 text-foreground">{action.vars.join(", ")}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Resultado esperado</p>
                <p className="mt-1 text-foreground">Número inteiro (ex.: 038)</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Última execução</p>
                <p className="mt-1 text-foreground">{action.lastRun}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Último resultado</p>
                <p className="mt-1 text-foreground">{action.lastResult}</p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button size="sm" disabled={action.status === "Em desenvolvimento"}>
                <Play className="h-3.5 w-3.5" /> Executar teste
              </Button>
              <Button size="sm" variant="outline">
                <Settings2 className="h-3.5 w-3.5" /> Configurar resultado
              </Button>
            </div>

            <Collapsible open={techOpen} onOpenChange={setTechOpen}>
              <CollapsibleTrigger className="flex w-full items-center justify-between rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40">
                Área técnica (run_id, diagnóstico, JSON)
                <ChevronDown className={`h-4 w-4 transition ${techOpen ? "rotate-180" : ""}`} />
              </CollapsibleTrigger>
              <CollapsibleContent className="mt-2">
                <pre className="max-h-64 overflow-auto rounded-md border border-border bg-muted/40 p-3 font-mono text-xs text-foreground">
{JSON.stringify(mockJson, null, 2)}
                </pre>
              </CollapsibleContent>
            </Collapsible>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>Fechar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
