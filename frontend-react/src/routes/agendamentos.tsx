import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { AppShell } from "@/components/cotasync/AppShell";
import { DataTable, type Column } from "@/components/cotasync/DataTable";
import { BadgeStatus } from "@/components/cotasync/BadgeStatus";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { mockSchedules, mockActions, type ScheduleRow } from "@/lib/mock-data";
import { Plus, Pencil, PowerOff, Info } from "lucide-react";

export const Route = createFileRoute("/agendamentos")({
  head: () => ({ meta: [{ title: "Agendamentos — CotaSync" }] }),
  component: AgendamentosPage,
});

const columns: Column<ScheduleRow>[] = [
  { key: "n", header: "Nome", cell: (r) => <span className="font-medium text-foreground">{r.name}</span> },
  { key: "a", header: "Ação", cell: (r) => r.action },
  { key: "l", header: "Lista", cell: (r) => r.list },
  { key: "f", header: "Frequência", cell: (r) => r.frequency },
  { key: "p", header: "Próxima execução", cell: (r) => r.next },
  { key: "s", header: "Status", cell: (r) => (
    <BadgeStatus tone={r.status === "Ativo" ? "success" : "neutral"}>{r.status}</BadgeStatus>
  )},
  { key: "u", header: "Última execução", cell: (r) => <span className="text-xs text-muted-foreground">{r.last}</span> },
  { key: "ac", header: "", cell: () => (
    <div className="flex gap-1">
      <Button size="sm" variant="ghost"><Pencil className="h-3.5 w-3.5" /> Editar</Button>
      <Button size="sm" variant="ghost"><PowerOff className="h-3.5 w-3.5" /> Pausar</Button>
    </div>
  )},
];

function NewScheduleDialog() {
  const [open, setOpen] = useState(false);
  const [freq, setFreq] = useState("mensal");
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm"><Plus className="h-4 w-4" /> Novo agendamento</Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>Novo agendamento</DialogTitle></DialogHeader>
        <div className="grid gap-4 py-2">
          <div className="grid gap-2">
            <Label htmlFor="s-name">Nome do agendamento</Label>
            <Input id="s-name" placeholder="Ex.: Consulta mensal de parcelas" />
          </div>
          <div className="grid gap-2">
            <Label>Ação</Label>
            <Select>
              <SelectTrigger><SelectValue placeholder="Selecione a ação" /></SelectTrigger>
              <SelectContent>
                {mockActions.map(a => <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label>Lista/grupo de clientes</Label>
            <Select>
              <SelectTrigger><SelectValue placeholder="Selecione a lista" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="p">Lista Principal</SelectItem>
                <SelectItem value="v">Lista VIP</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-2">
              <Label>Frequência</Label>
              <Select value={freq} onValueChange={setFreq}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="diario">Diário</SelectItem>
                  <SelectItem value="semanal">Semanal</SelectItem>
                  <SelectItem value="mensal">Mensal</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {freq === "mensal" && (
              <div className="grid gap-2">
                <Label htmlFor="s-day">Dia do mês</Label>
                <Input id="s-day" type="number" min={1} max={31} defaultValue={5} />
              </div>
            )}
            <div className="grid gap-2">
              <Label htmlFor="s-hour">Horário</Label>
              <Input id="s-hour" type="time" defaultValue="08:00" />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="s-delay">Delay entre clientes (s)</Label>
              <Input id="s-delay" type="number" min={0} defaultValue={3} />
            </div>
          </div>
          <div className="flex items-center justify-between rounded-md border border-border p-3">
            <div>
              <Label htmlFor="s-active" className="text-sm">Ativo</Label>
              <p className="text-xs text-muted-foreground">O agendamento só é executado quando ativo.</p>
            </div>
            <Switch id="s-active" defaultChecked />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Cancelar</Button>
          <Button onClick={() => setOpen(false)}>Salvar agendamento</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function AgendamentosPage() {
  return (
    <AppShell
      title="Agendamentos"
      subtitle="Execuções recorrentes usando a mesma fila sequencial"
      actions={<NewScheduleDialog />}
    >
      <div className="mb-4 flex items-start gap-3 rounded-md border border-border bg-muted/30 p-3">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <p className="text-sm text-foreground">
          As execuções agendadas usam a mesma fila sequencial da execução manual.
        </p>
      </div>

      <Card>
        <CardContent className="p-0">
          <DataTable columns={columns} data={mockSchedules} />
        </CardContent>
      </Card>
    </AppShell>
  );
}
